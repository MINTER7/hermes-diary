"""Durable delivery snapshots for one configured destination. Called under diary_lock."""
import json
import math
from http.client import HTTPException
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from diary_common import DiaryError, Rejected, Uncertain, atomic_write, write_json
from diary_transports import LIMITS, send_webhook, target_identity, validate_target


def retry_delay(result):
    try:
        return max(0, int(result.get("parameters", {}).get("retry_after", 0)))
    except (ValueError, TypeError, AttributeError):
        return 0


def chunks(text, limit=3900):
    """Use conservative UTF-16 units; keep newlines when possible and never split a code point."""
    if limit < 2:
        raise ValueError("chunk limit must be >= 2")
    result = []
    while text:
        units = end = 0
        for character in text:
            size = 2 if ord(character) > 0xFFFF else 1
            if units + size > limit:
                break
            units += size
            end += 1
        if end < len(text):
            newline = text.rfind("\n", 0, end)
            if newline >= end // 2:
                end = newline + 1
        part, text = text[:end], text[end:]
        if part.strip():
            result.append(part)
    return result


def send(token, channel, text):
    payload = urllib.parse.urlencode({"chat_id": channel, "text": text}).encode()
    request = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage",
                                     data=payload, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        # Only explicit client rejection is safe to retry automatically. Never log the URL/token.
        if 400 <= exc.code < 500 and exc.code != 408:
            try:
                result = json.loads(exc.read())
            except (ValueError, OSError, HTTPException):
                result = {}
            raise Rejected(exc.code, retry_delay(result)) from None
        raise Uncertain("Telegram returned a server error. Verify delivery before retrying.") from None
    except (OSError, ValueError, HTTPException):
        raise Uncertain("Telegram request failed or timed out. Verify delivery before retrying.") from None
    if not isinstance(result, dict):
        raise Uncertain("Unexpected Telegram response. Verify delivery before retrying.")
    if result.get("ok") is False:
        code = result.get("error_code", 0)
        if isinstance(code, int) and 400 <= code < 500 and code != 408:
            raise Rejected(code, retry_delay(result))
        raise Uncertain("Telegram returned an unknown error. Verify delivery before retrying.")
    message = result.get("result")
    if result.get("ok") is not True or not isinstance(message, dict) or "message_id" not in message:
        raise Uncertain("Telegram did not confirm a message ID. Verify delivery before retrying.")
    return message["message_id"]


def state_path(settings, day):
    return settings.diary_dir / "state" / "deliveries" / f"{day}.json"


def load_state(settings, day):
    path = state_path(settings, day)
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        parts, confirmed = state["parts"], state["confirmed"]
        valid = (
            state["version"] in (1, 2) and state["day"] == day
            and ((state["version"] == 1 and isinstance(state["channel"], str) and bool(state["channel"]))
                 or (state["version"] == 2 and state["provider"] in LIMITS
                     and isinstance(state["target"], str) and bool(state["target"])
                     and isinstance(state["delivery_id"], str) and bool(state["delivery_id"])
                     and state["language"] in ("en", "zh") and isinstance(state["timezone"], str)))
            and isinstance(parts, list) and bool(parts)
            and all(isinstance(p, str) and p.strip() for p in parts)
            and type(confirmed) is int and 0 <= confirmed <= len(parts)
            and (state["inflight"] is None or
                 (type(state["inflight"]) is int and state["inflight"] == confirmed < len(parts)))
            and isinstance(state["message_ids"], list) and len(state["message_ids"]) == confirmed
            and type(state["complete"]) is bool
            and (not state["complete"] or (confirmed == len(parts) and state["inflight"] is None))
            and isinstance(state.get("retry_at", 0), (int, float))
            and math.isfinite(state.get("retry_at", 0))
        )
        if not valid:
            raise ValueError("invalid delivery journal")
        return state
    except (ValueError, KeyError, TypeError) as exc:
        raise DiaryError(f"Corrupt delivery state: {path}. Stopped to avoid duplicate delivery.") from exc


def check_destination(settings, state):
    validate_target(settings)
    provider = state.get("provider", "telegram")
    target = state.get("target", state.get("channel"))
    if provider != settings.delivery or target != target_identity(settings):
        raise DiaryError("Delivery destination changed. Restore the original destination or explicitly use resend.")


def already_sent(settings, day, state=None):
    if state is not None:
        check_destination(settings, state)
        return state["complete"]
    legacy = settings.diary_dir / "state" / "last_push.txt"
    return settings.delivery == "telegram" and legacy.exists() and legacy.read_text(encoding="utf-8").strip() == day


def deliver(settings, day, force=False):
    state = load_state(settings, day)
    if not force and already_sent(settings, day, state):
        return "already sent"
    validate_target(settings)
    path = state_path(settings, day)
    if force or state is None:
        composed = settings.diary_dir / "composed" / f"{day}.md"
        if not composed.exists() or not composed.read_text(encoding="utf-8").strip():
            raise DiaryError(f"No composed diary for {day}. Run compose --date {day} first.")
        if state is not None:
            write_json(path.parent / "history" / f"{day}-{uuid.uuid4().hex}.json", state)
        state = {"version": 2, "day": day, "provider": settings.delivery, "target": target_identity(settings),
                 "delivery_id": uuid.uuid4().hex, "language": settings.language, "timezone": settings.timezone,
                 "parts": chunks(composed.read_text(encoding="utf-8").strip(), LIMITS[settings.delivery]),
                 "confirmed": 0, "message_ids": [], "inflight": None, "complete": False, "retry_at": 0}
        write_json(path, state)
    check_destination(settings, state)
    if state["inflight"] is not None:
        raise DiaryError(f"Uncertain delivery of {day}, part {state['inflight'] + 1}. Check the destination, then run resolve --date {day} --delivered or --retry.")
    if state.get("retry_at", 0) > time.time():
        return "waiting for rate limit"
    for index in range(state["confirmed"], len(state["parts"])):
        state["inflight"] = index
        write_json(path, state)
        try:
            if settings.delivery == "telegram":
                message_id = send(settings.token, settings.channel, state["parts"][index])
            elif settings.delivery == "local":
                message_id = "local"
            else:
                from dataclasses import replace
                snapshot_settings = replace(settings, language=state["language"], timezone=state["timezone"])
                message_id = send_webhook(snapshot_settings, state["parts"][index], day,
                                          state["delivery_id"], index, len(state["parts"]))
        except Rejected as exc:
            state["inflight"] = None
            state["retry_at"] = time.time() + max(60, exc.retry_after)
            write_json(path, state)
            raise
        # On timeout, process death, or disk failure, inflight stays set: do not guess delivery.
        state["confirmed"] = index + 1
        state["message_ids"].append(message_id)
        state["inflight"] = None
        state["retry_at"] = 0
        write_json(path, state)
        if settings.delivery != "local" and index + 1 < len(state["parts"]):
            time.sleep(1.1)
    state["complete"] = True
    write_json(path, state)
    atomic_write(settings.diary_dir / "state" / "last_push.txt", day + "\n")
    return "saved locally" if settings.delivery == "local" else "sent"


def resolve(settings, day, delivered):
    state = load_state(settings, day)
    if state is None or state["inflight"] is None:
        raise DiaryError("No uncertain part to resolve for this date.")
    check_destination(settings, state)
    if delivered:
        state["confirmed"] += 1
        state["message_ids"].append("manually-confirmed")
    state["inflight"] = None
    state["retry_at"] = 0
    state["complete"] = state["confirmed"] == len(state["parts"])
    write_json(state_path(settings, day), state)
    if state["complete"]:
        atomic_write(settings.diary_dir / "state" / "last_push.txt", day + "\n")

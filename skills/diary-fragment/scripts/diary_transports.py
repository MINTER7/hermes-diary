"""Explicitly configured delivery adapters. Never use the agent gateway's credentials."""
import hashlib
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from email.utils import parsedate_to_datetime
from http.client import HTTPException

from diary_common import DiaryError, Rejected, Uncertain

LIMITS = {"local": 3900, "telegram": 3900, "discord": 1900, "slack": 2900, "webhook": 3900}


def validate_target(settings):
    provider = settings.delivery
    if provider not in LIMITS:
        raise DiaryError("Unsupported delivery provider.")
    if provider == "local":
        return
    if provider == "telegram":
        if not settings.token or not settings.channel:
            raise DiaryError("Telegram requires a diary Bot Token and chat/channel ID.")
        return
    try:
        url = urllib.parse.urlsplit(settings.webhook_url)
        if (url.scheme != "https" or not url.hostname or url.username or url.password
                or url.fragment or url.port not in (None, 443)
                or any(c.isspace() or ord(c) < 32 for c in settings.webhook_url)):
            raise ValueError
        if provider == "discord":
            if (url.hostname not in ("discord.com", "discordapp.com", "ptb.discord.com", "canary.discord.com")
                    or not re.fullmatch(r"/api(?:/v\d+)?/webhooks/\d+/[A-Za-z0-9_-]+", url.path)):
                raise ValueError
            query = urllib.parse.parse_qs(url.query, keep_blank_values=True)
            if set(query) - {"wait", "thread_id"}:
                raise ValueError
            if "thread_id" in query and (len(query["thread_id"]) != 1 or not query["thread_id"][0].isdigit()):
                raise ValueError
        if provider == "slack" and (url.hostname not in ("hooks.slack.com", "hooks.slack-gov.com")
                                     or not re.fullmatch(r"/services/[^/]+/[^/]+/[^/]+", url.path)
                                     or url.query):
            raise ValueError
    except ValueError:
        # URLs embed access tokens; never include the supplied value in an error.
        raise DiaryError(f"Invalid {provider} webhook URL. Use a direct HTTPS webhook URL without a fragment or userinfo.") from None


def normalized_url(settings):
    url = urllib.parse.urlsplit(settings.webhook_url)
    if settings.delivery == "discord":
        query = [(key, value) for key, value in urllib.parse.parse_qsl(url.query) if key != "wait"]
        query.append(("wait", "true"))
        return urllib.parse.urlunsplit(url._replace(query=urllib.parse.urlencode(sorted(query))))
    return settings.webhook_url


def target_identity(settings):
    if settings.delivery == "local":
        return "local"
    if settings.delivery == "telegram":
        return settings.channel
    return hashlib.sha256(normalized_url(settings).encode("utf-8")).hexdigest()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "Redirect blocked", headers, fp)


def _open(request):
    return urllib.request.build_opener(NoRedirect()).open(request, timeout=20)


def retry_seconds(headers, body):
    values = []
    header = (headers or {}).get("Retry-After", "")
    try:
        values.append(float(header))
    except (TypeError, ValueError):
        try:
            values.append(parsedate_to_datetime(header).timestamp() - time.time())
        except (TypeError, ValueError, OverflowError, AttributeError):
            pass
    try:
        data = json.loads(body)
        values.append(float(data.get("retry_after", data.get("parameters", {}).get("retry_after", 0))))
    except (ValueError, TypeError, AttributeError):
        pass
    return max([0] + [math.ceil(value) for value in values if math.isfinite(value)])


def send_webhook(settings, text, day, delivery_id, index, total):
    validate_target(settings)
    provider = settings.delivery
    headers = {"Content-Type": "application/json; charset=utf-8", "User-Agent": "hermes-diary/2.3"}
    if provider == "discord":
        payload = {"content": text, "allowed_mentions": {"parse": []}, "flags": 4}
    elif provider == "slack":
        escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        payload = {"text": escaped, "mrkdwn": False, "link_names": False,
                   "unfurl_links": False, "unfurl_media": False,
                   "blocks": [{"type": "section", "text": {"type": "plain_text", "text": text, "emoji": False}}]}
    elif provider == "webhook":
        event_id = f"{delivery_id}:{index + 1}"
        payload = {"schema_version": 1, "event": "diary.daily", "id": event_id,
                   "date": day, "timezone": settings.timezone, "language": settings.language,
                   "part": index + 1, "parts": total, "text": text}
        headers["Idempotency-Key"] = event_id
        if settings.webhook_token:
            headers["Authorization"] = "Bearer " + settings.webhook_token
    else:
        raise DiaryError("This provider does not use a webhook.")
    request = urllib.request.Request(normalized_url(settings),
                                     data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                     headers=headers, method="POST")
    try:
        with _open(request) as response:
            body = response.read(1048577)
            code = response.getcode()
        if len(body) > 1048576 or not 200 <= code < 300:
            raise Uncertain(f"{provider} returned an unexpected response. Verify delivery before retrying.")
    except urllib.error.HTTPError as exc:
        if 400 <= exc.code < 500 and exc.code != 408:
            try:
                body = exc.read(65536)
            except (OSError, HTTPException):
                body = b""
            raise Rejected(exc.code, retry_seconds(exc.headers, body), provider) from None
        raise Uncertain(f"{provider} returned an error or redirect. Verify delivery before retrying.") from None
    except (OSError, ValueError, HTTPException):
        raise Uncertain(f"{provider} request failed or timed out. Verify delivery before retrying.") from None
    if provider == "discord":
        try:
            result = json.loads(body)
            if not isinstance(result, dict) or not isinstance(result.get("id"), str) or not result["id"].isdigit():
                raise ValueError
            return result["id"]
        except (ValueError, TypeError):
            raise Uncertain("Discord did not confirm a message ID. Verify delivery before retrying.") from None
    if provider == "slack" and body.strip() != b"ok":
        raise Uncertain("Slack did not return 'ok'. Verify delivery before retrying.")
    # Slack has no message ID here; generic webhooks confirm HTTP acceptance only.
    return f"{provider}-accepted:{delivery_id}:{index + 1}"

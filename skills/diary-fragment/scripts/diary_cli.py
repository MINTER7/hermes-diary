#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
sys.dont_write_bytecode = True  # Keep the Hub-managed skill bundle unchanged at runtime.
from datetime import timedelta

from compose_diary import compose
from diary_common import (BusyError, DiaryError, Settings, atomic_write, current_city,
                          diary_lock, validate_day)
from diary_delivery import already_sent, deliver, load_state, resolve


def parser():
    root = argparse.ArgumentParser(description="Hermes Diary: local Markdown journals and optional daily delivery")
    commands = root.add_subparsers(dest="command")
    for name in ("status", "context", "logs", "scheduled"):
        commands.add_parser(name)
    city = commands.add_parser("city")
    city.add_argument("value", nargs="?")
    for name in ("today", "compose", "send", "resend", "run", "record", "resolve"):
        command = commands.add_parser(name)
        command.add_argument("--date", dest="day", type=validate_day)
        if name == "record":
            command.add_argument("text")
            command.add_argument("--at", help="Explicit HH:MM time; defaults to the configured timezone's current time")
            command.add_argument("--city", help="City where the user has explicitly arrived or is currently located")
        if name == "resolve":
            choice = command.add_mutually_exclusive_group(required=True)
            choice.add_argument("--delivered", action="store_true")
            choice.add_argument("--retry", action="store_true")
    return root


def run_day(settings, day, today):
    state = load_state(settings, day)
    if already_sent(settings, day, state):
        return None
    if state is None:
        output = settings.diary_dir / "composed" / f"{day}.md"
        if not output.exists() or day == today:
            if compose(settings, day, today) is None:
                return None
    return deliver(settings, day)


def one_line(value, label):
    if not value.strip() or any(ord(c) < 32 for c in value):
        raise DiaryError(f"{label} must be nonempty single-line text.")
    return value.strip()


def execute(args, settings, now):
    command = args.command or "status"
    today = now.date().isoformat()
    day = getattr(args, "day", None) or today
    raw = settings.diary_dir / f"{day}.md"
    if command == "context":
        preferences = settings.diary_dir / "notes" / "preferences.md"
        print(json.dumps({"date": today, "time": now.strftime("%H:%M"), "timezone": settings.timezone,
                          "diary_dir": str(settings.diary_dir), "city": current_city(settings),
                          "language": settings.language, "delivery": settings.delivery,
                          "weather_enabled": settings.weather_enabled, "temperature_unit": settings.temperature_unit,
                          "schedule_at": settings.schedule_at,
                          "setup_needed": not ((settings.hermes_home / "diary" / "setup.json").is_file()
                                               and (settings.hermes_home / "diary" / "config.env").is_file()),
                          "preferences": preferences.read_text(encoding="utf-8") if preferences.exists() else ""},
                         ensure_ascii=False, indent=2))
    elif command == "status":
        count = sum(bool(line.strip()) for line in raw.read_text(encoding="utf-8").splitlines()) if raw.exists() else 0
        last = settings.diary_dir / "state" / "last_push.txt"
        receipt = settings.hermes_home / "diary" / "setup.json"
        schedule = "Not configured; run setup_diary.py check"
        if receipt.is_file():
            try:
                enabled = json.loads(receipt.read_text(encoding="utf-8")).get("schedule_enabled") is True
                schedule = f"Configured for {settings.schedule_at} {settings.timezone}" if enabled else "Disabled"
            except (ValueError, AttributeError):
                schedule = "Invalid receipt; run setup_diary.py check"
        print(f"Hermes Diary\nCity       {current_city(settings)}\nDiary      {settings.diary_dir}\n"
              f"Timezone   {settings.timezone}\nFragments  {count}\nSchedule   {schedule}\n"
              f"Delivery   {settings.delivery}\nLanguage   {settings.language}\n"
              f"Last run   {last.read_text(encoding='utf-8').strip() if last.exists() else 'None'}")
        for path in sorted((settings.diary_dir / "state" / "deliveries").glob("????-??-??.json")):
            state = load_state(settings, validate_day(path.stem))
            if not state["complete"]:
                detail = f"Verify part {state['inflight'] + 1}" if state["inflight"] is not None else "Resumable"
                print(f"Pending    {path.stem}: {state['confirmed']}/{len(state['parts'])} {detail}")
    elif command == "today":
        print(raw.read_text(encoding="utf-8") if raw.exists() else "No entries for this date.")
    elif command == "city":
        if args.value is not None:
            atomic_write(settings.diary_dir / "notes" / "location.md", one_line(args.value, "City") + "\n")
        print(current_city(settings))
    elif command == "record":
        text = one_line(args.text, "Diary entry")
        at = args.at or now.strftime("%H:%M")
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", at):
            raise DiaryError("Time must use HH:MM format.")
        city = one_line(args.city, "City") if args.city is not None else None
        raw.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(raw), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8", newline="\n") as stream:
            stream.write(f"[{at}] — {text}\n")
            stream.flush()
            os.fsync(stream.fileno())
        if city is not None:
            atomic_write(settings.diary_dir / "notes" / "location.md", city + "\n")
        print(f"Recorded: {day} [{at}] — {text}")
    elif command == "compose":
        output = compose(settings, day, today)
        print(f"Composed: {output}" if output else f"No entries for {day}; skipped.")
    elif command in ("send", "resend"):
        print(f"{day}: {deliver(settings, day, force=command == 'resend')}")
    elif command == "resolve":
        resolve(settings, day, args.delivered)
        print(f"Updated state for {day}; run send --date {day} to continue.")
    elif command == "run":
        print(f"{day}: {run_day(settings, day, today) or 'skipped'}")
    elif command == "scheduled":
        receipt = settings.hermes_home / "diary" / "setup.json"
        if not receipt.is_file():
            return 0
        try:
            enabled = json.loads(receipt.read_text(encoding="utf-8")).get("schedule_enabled") is True
        except (ValueError, AttributeError) as exc:
            raise DiaryError("Invalid schedule receipt. Run setup_diary.py configure again.") from exc
        if not enabled:
            return 0
        # Cron ticks every minute in any host timezone; application decides eligibility.
        days = [(now.date() - timedelta(days=1)).isoformat()]
        if now.strftime("%H:%M") >= settings.schedule_at:
            days.append(today)
        failed = False
        for target in days:
            try:
                result = run_day(settings, target, today)
                if result and result != "waiting for rate limit":
                    print(f"{now.isoformat()} {target}: {result}")
            except DiaryError as exc:
                print(f"{now.isoformat()} {target}: {exc}", file=sys.stderr)
                failed = True
        return 1 if failed else 0
    elif command == "logs":
        path = settings.diary_dir / "cron.log"
        if path.exists():
            from collections import deque
            with path.open(encoding="utf-8", errors="replace") as stream:
                print("".join(deque(stream, maxlen=100)), end="")
        else:
            print("No logs yet.")
    return 0


def main(argv=None):
    try:
        args = parser().parse_args(argv)
        settings = Settings.load()
        now = settings.now()
        with diary_lock(settings):
            return execute(args, settings, now)
    except BusyError as exc:
        print(str(exc), file=sys.stderr)
        return 75
    except (DiaryError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

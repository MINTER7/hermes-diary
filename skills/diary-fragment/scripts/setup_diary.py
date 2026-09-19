#!/usr/bin/env python3
"""Initialize data/configuration and cron; code remains in the Hub-managed skill directory."""
import argparse
import getpass
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
sys.dont_write_bytecode = True
from pathlib import Path

from diary_common import (CONFIG_KEYS, DiaryError, Settings, atomic_write, diary_lock,
                          defaults, environment_values, hermes_home, process_environment, read_config, write_json)
from diary_transports import validate_target

SKILL_ROOT = Path(__file__).resolve().parent.parent
MARKER = "# hermes-diary managed cron"
VERSION = "2.3.0"


def profile_marker(home):
    return MARKER + " " + hashlib.sha256(str(home.resolve()).encode()).hexdigest()[:12]


def read_cron():
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True,
                            env={**process_environment(), "LC_ALL": "C"})
    if result.returncode == 0:
        return result.stdout
    if result.returncode == 1 and "no crontab for" in result.stderr.lower():
        return ""
    raise DiaryError("Cannot read crontab. Stopped to protect other jobs; check cron installation and permissions.")


def legacy_belongs(line, home):
    if not line.rstrip().endswith(MARKER) or line.startswith("CRON_TZ="):
        return False
    try:
        parts = shlex.split(line)
        configured = next((p.split("=", 1)[1] for p in parts if p.startswith("HERMES_HOME=")), None)
        if configured:
            return Path(configured).expanduser().resolve() == home.resolve()
        return str(home / "scripts" / "diary_compose_and_push.sh") in parts
    except ValueError:
        return False


def strip_managed(cron, home):
    lines = cron.splitlines(keepends=True)
    has_legacy = any(legacy_belongs(line, home) for line in lines)
    return "".join(line for line in lines if not (
        line.rstrip().endswith(profile_marker(home)) or legacy_belongs(line, home)
        or (has_legacy and line.startswith("CRON_TZ=") and line.rstrip().endswith(MARKER))))


def legacy_directory(cron, home):
    for line in cron.splitlines():
        if legacy_belongs(line, home) and "DIARY_DIR=" in line:
            if "$'" in line:
                raise DiaryError("Legacy cron uses a complex path. Set HERMES_DIARY_DIR explicitly before configuring.")
            for item in shlex.split(line):
                if item.startswith("DIARY_DIR="):
                    return item.split("=", 1)[1]
    return None


def cron_text(cron, settings, python, skill_root=None):
    entry = (skill_root or SKILL_ROOT) / "scripts" / "diary_cli.py"
    values = [str(settings.hermes_home), str(settings.diary_dir), python, str(entry)]
    if any("\n" in value or "\r" in value for value in values):
        raise DiaryError("Installation paths cannot contain newlines.")
    command = (f"if test -f {shlex.quote(str(entry))}; then "
               f"HERMES_HOME={shlex.quote(str(settings.hermes_home))} "
               f"{shlex.quote(python)} {shlex.quote(str(entry))} "
               f"scheduled >> {shlex.quote(str(settings.diary_dir / 'cron.log'))} 2>&1; fi")
    command = command.replace("%", "\\%")
    existing = strip_managed(cron, settings.hermes_home)
    if existing and not existing.endswith("\n"):
        existing += "\n"
    return existing + f"* * * * * {command} {profile_marker(settings.hermes_home)}\n"


def write_cron(text):
    result = subprocess.run(["crontab", "-"], input=text, capture_output=True, text=True,
                            env=process_environment())
    if result.returncode:
        raise DiaryError("Cannot write crontab. Configuration and diary files were kept; check permissions and retry.")


def build_settings(args, home, cron):
    path = home / "diary" / "config.env"
    saved = read_config(path)
    env = environment_values()
    values = defaults(home, legacy=bool(saved) and "LANGUAGE" not in saved)
    directory = (saved.get("DIARY_DIR") or args.diary_dir or env.get("DIARY_DIR")
                 or legacy_directory(cron, home) or (str(Path.home() / "diary") if saved else values["DIARY_DIR"]))
    values["DIARY_DIR"] = directory
    values.update(saved)
    if saved and "DELIVERY" not in saved and saved.get("TELEGRAM_BOT_TOKEN"):
        values["DELIVERY"] = "telegram"
    changes = {key: value for key, value in {
        "DIARY_DIR": args.diary_dir, "TIMEZONE": args.timezone,
        "DEFAULT_CITY": args.city, "TELEGRAM_CHANNEL_ID": args.channel,
        "DELIVERY": getattr(args, "delivery", None), "LANGUAGE": getattr(args, "language", None),
        "TEMPERATURE_UNIT": getattr(args, "temperature_unit", None),
        "SCHEDULE_AT": getattr(args, "at", None),
        "WEATHER_ENABLED": (str(args.weather).lower() if getattr(args, "weather", None) is not None else None)
    }.items() if value is not None}
    if saved and not args.reconfigure:
        for key, value in changes.items():
            existing = values[key]
            if key == "DIARY_DIR":
                existing, value = str(Path(existing).expanduser().resolve()), str(Path(value).expanduser().resolve())
            if existing != value:
                raise DiaryError("Existing settings are preserved. Use --reconfigure to change them; migrate data before changing its directory.")
    else:
        values.update(env)
        values.update(changes)
        if not args.non_interactive:
            if getattr(args, "delivery", None) is None:
                values["DELIVERY"] = input(f"Delivery: local/telegram/discord/slack/webhook [{values['DELIVERY']}]: ").strip() or values["DELIVERY"]
            if args.timezone is None:
                values["TIMEZONE"] = input(f"IANA timezone [{values['TIMEZONE']}]: ").strip() or values["TIMEZONE"]
            if getattr(args, "language", None) is None:
                values["LANGUAGE"] = input(f"Diary headings: en/zh [{values['LANGUAGE']}]: ").strip() or values["LANGUAGE"]
            if args.city is None:
                values["DEFAULT_CITY"] = input(f"City (optional) [{values['DEFAULT_CITY']}]: ").strip() or values["DEFAULT_CITY"]
            if values["DELIVERY"] == "telegram":
                if not values["TELEGRAM_BOT_TOKEN"]:
                    if not sys.stdin.isatty():
                        raise DiaryError("Enter the diary Bot Token in a local terminal or via Hermes secure environment input; then use --non-interactive.")
                    values["TELEGRAM_BOT_TOKEN"] = getpass.getpass("Diary Telegram Bot Token: ").strip()
                if not values["TELEGRAM_CHANNEL_ID"]:
                    values["TELEGRAM_CHANNEL_ID"] = input("Telegram chat/channel ID: ").strip()
            elif values["DELIVERY"] in ("discord", "slack", "webhook") and not values["WEBHOOK_URL"]:
                if not sys.stdin.isatty():
                    raise DiaryError("Enter the webhook URL locally or through HERMES_DIARY_WEBHOOK_URL secure input.")
                values["WEBHOOK_URL"] = getpass.getpass("Webhook URL (hidden): ").strip()
    settings = Settings.from_values(home, values)
    validate_target(settings)
    values["DIARY_DIR"] = str(settings.diary_dir)
    values["TELEGRAM_BOT_TOKEN"], values["TELEGRAM_CHANNEL_ID"] = settings.token, settings.channel
    return settings, values, saved


def check(skill_root=None):
    skill_root = (skill_root or SKILL_ROOT).resolve()
    settings = Settings.load()
    receipt = settings.hermes_home / "diary" / "setup.json"
    configured = (settings.hermes_home / "diary" / "config.env").is_file()
    saved = {}
    if receipt.exists():
        try:
            saved = json.loads(receipt.read_text(encoding="utf-8"))
        except ValueError:
            pass
        if not isinstance(saved, dict):
            saved = {}
    cron, cron_error = "", None
    if shutil.which("crontab"):
        try:
            cron = read_cron()
        except DiaryError as exc:
            cron_error = str(exc)
    entry = str(skill_root / "scripts" / "diary_cli.py")
    current_lines = [line for line in cron.splitlines() if line.rstrip().endswith(profile_marker(settings.hermes_home))]
    scheduled = False
    for line in current_lines:
        try:
            scheduled = scheduled or entry in shlex.split(line.replace("\\%", "%"))
        except ValueError:
            pass
    try:
        validate_target(settings)
        ready = True
    except DiaryError:
        ready = False
    return {"version": VERSION, "configured": configured, "skill_dir": str(skill_root),
            "hermes_home": str(settings.hermes_home), "diary_dir": str(settings.diary_dir),
            "timezone": settings.timezone, "city": settings.default_city,
            "language": settings.language, "temperature_unit": settings.temperature_unit,
            "weather_enabled": settings.weather_enabled, "delivery": settings.delivery,
            "delivery_ready": ready, "schedule_at": settings.schedule_at,
            "telegram_ready": bool(settings.token and settings.channel),
            "schedule_enabled": scheduled, "cron_error": cron_error,
            "setup_needed": not configured or not saved or saved.get("entrypoint") != entry
                or (saved.get("schedule_enabled", False) and not scheduled),
            "dependencies": {"bash": bool(shutil.which("bash")), "crontab": bool(shutil.which("crontab"))}}


def main(argv=None, skill_root=None):
    parser = argparse.ArgumentParser(description="Configure local journaling and optional delivery. No test message is sent.")
    parser.add_argument("action", choices=("configure", "check", "disable"), nargs="?", default="check")
    parser.add_argument("--city")
    parser.add_argument("--timezone")
    parser.add_argument("--channel", help="Telegram chat/channel ID (secrets are never CLI arguments)")
    parser.add_argument("--delivery", choices=("local", "telegram", "discord", "slack", "webhook"))
    parser.add_argument("--language", choices=("en", "zh"))
    parser.add_argument("--temperature-unit", choices=("C", "F"))
    weather = parser.add_mutually_exclusive_group()
    weather.add_argument("--weather", action="store_true", default=None, help="Look up weather for the configured city at composition time")
    weather.add_argument("--no-weather", action="store_false", dest="weather")
    parser.add_argument("--at", help="Daily time in the configured timezone (HH:MM; default 23:59)")
    parser.add_argument("--diary-dir")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--reconfigure", action="store_true", help="Update existing settings and back up config.env")
    schedule = parser.add_mutually_exclusive_group()
    schedule.add_argument("--schedule", action="store_false", dest="no_schedule", default=None, help="Enable daily composition/delivery")
    schedule.add_argument("--no-schedule", action="store_true", help="Disable this diary's schedule; keep manual commands")
    args = parser.parse_args(argv)
    skill_root = (skill_root or SKILL_ROOT).resolve()
    try:
        if args.action == "check":
            print(json.dumps(check(skill_root), ensure_ascii=False, indent=2))
            return 0
        home = hermes_home()
        has_cron = bool(shutil.which("crontab"))
        schedule_unspecified = args.no_schedule is None
        if args.no_schedule is None:
            # New installs never enable cron implicitly. Existing receipts keep their choice.
            try:
                receipt = json.loads((home / "diary" / "setup.json").read_text(encoding="utf-8"))
                args.no_schedule = receipt.get("schedule_enabled") is not True
            except (OSError, ValueError, AttributeError):
                args.no_schedule = True
        if not has_cron and args.action != "disable" and not args.no_schedule:
            raise DiaryError("Scheduling requires cron/crontab. Use configure --no-schedule for manual operation.")
        if not shutil.which("bash"):
            raise DiaryError("Bash is required to read local diary configuration.")
        cron = read_cron() if has_cron else ""
        if (schedule_unspecified and not (home / "diary" / "setup.json").exists()
                and any(legacy_belongs(line, home) for line in cron.splitlines())):
            args.no_schedule = False
        if args.action == "disable":
            settings = Settings.load()
            with diary_lock(settings):
                if has_cron:
                    write_cron(strip_managed(cron, home))
                write_json(home / "diary" / "setup.json", {"version": VERSION, "schedule_enabled": False,
                           "entrypoint": str(skill_root / "scripts" / "diary_cli.py")})
            print("Scheduling disabled. Skill, configuration and diary files were kept.")
            if not has_cron:
                print("No crontab command is available; any existing host cron entry must be cleaned up on that host.")
            return 0
        settings, values, saved = build_settings(args, home, cron)
        if skill_root == settings.diary_dir or skill_root in settings.diary_dir.parents:
            raise DiaryError("Store diary data outside the skill directory.")
        preferences_source = skill_root / "assets" / ("preferences.zh.md" if settings.language == "zh" else "preferences.default.md")
        if not preferences_source.is_file() or not (skill_root / "scripts" / "diary_cli.py").is_file():
            raise DiaryError("Incomplete skill package. Reinstall it through Hermes.")
        new_cron = strip_managed(cron, home) if args.no_schedule else cron_text(cron, settings, sys.executable, skill_root)
        with diary_lock(settings):
            config = home / "diary" / "config.env"
            if not config.exists() or args.reconfigure:
                if config.exists():
                    atomic_write(config.with_suffix(".env.bak"), config.read_text(encoding="utf-8"))
                atomic_write(config, "".join(f"{key}={shlex.quote(values[key])}\n" for key in CONFIG_KEYS))
            elif any(key not in saved for key in CONFIG_KEYS):
                atomic_write(config.with_suffix(".env.bak"), config.read_text(encoding="utf-8"))
                atomic_write(config, config.read_text(encoding="utf-8").rstrip("\n") +
                             "\n" + "".join(f"{key}={shlex.quote(values[key])}\n" for key in CONFIG_KEYS if key not in saved))
            config.chmod(0o600)
            preferences = settings.diary_dir / "notes" / "preferences.md"
            if not preferences.exists():
                atomic_write(preferences, preferences_source.read_text(encoding="utf-8"))
            location = settings.diary_dir / "notes" / "location.md"
            if not location.exists() or (args.reconfigure and args.city is not None):
                atomic_write(location, settings.default_city + "\n")
            if has_cron:
                write_cron(new_cron)
            write_json(home / "diary" / "setup.json", {"version": VERSION, "schedule_enabled": not args.no_schedule,
                       "entrypoint": str(skill_root / "scripts" / "diary_cli.py")})
        print(f"Configured. Diary: {settings.diary_dir}\nDelivery: {settings.delivery}\n" +
              ("Scheduling is disabled. Manual commands are available." if args.no_schedule else
               f"Daily at {settings.schedule_at} {settings.timezone}. No test message was sent."))
        return 0
    except (DiaryError, OSError, ValueError, EOFError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

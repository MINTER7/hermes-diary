"""Configuration, atomic files and one process lock shared by every entry point."""
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo


CONFIG_KEYS = ("DIARY_DIR", "TIMEZONE", "DEFAULT_CITY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHANNEL_ID",
               "LANGUAGE", "TEMPERATURE_UNIT", "WEATHER_ENABLED", "DELIVERY", "WEBHOOK_URL",
               "WEBHOOK_TOKEN", "SCHEDULE_AT")
ENV_KEYS = dict(zip(CONFIG_KEYS, ("HERMES_DIARY_DIR", "HERMES_DIARY_TIMEZONE", "HERMES_DIARY_CITY",
                                 "HERMES_DIARY_BOT_TOKEN", "HERMES_DIARY_CHANNEL_ID",
                                 "HERMES_DIARY_LANGUAGE", "HERMES_DIARY_TEMPERATURE_UNIT",
                                 "HERMES_DIARY_WEATHER_ENABLED", "HERMES_DIARY_DELIVERY",
                                 "HERMES_DIARY_WEBHOOK_URL", "HERMES_DIARY_WEBHOOK_TOKEN",
                                 "HERMES_DIARY_SCHEDULE_AT")))


def defaults(home, legacy=False):
    return dict(DIARY_DIR=str(home / "diary" / "data"), TIMEZONE="Asia/Shanghai" if legacy else "UTC",
                DEFAULT_CITY="深圳" if legacy else "", TELEGRAM_BOT_TOKEN="", TELEGRAM_CHANNEL_ID="",
                LANGUAGE="zh" if legacy else "en", TEMPERATURE_UNIT="C",
                WEATHER_ENABLED="true" if legacy else "false", DELIVERY="local",
                WEBHOOK_URL="", WEBHOOK_TOKEN="", SCHEDULE_AT="23:59")


def environment_values():
    # Hermes may use TELEGRAM_BOT_TOKEN for its chat gateway. Never borrow that bot.
    values = {key: os.getenv(key) for key in CONFIG_KEYS[:3] if os.getenv(key) is not None}
    values.update({key: os.getenv(name) for key, name in ENV_KEYS.items() if os.getenv(name) is not None})
    return values


def process_environment():
    # Shell config and crontab need only runtime paths/locale, not any other agent credentials.
    names = ("PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT",
             "TEMP", "TMP", "LANG", "LC_ALL", "HERMES_HOME")
    return {name: os.getenv(name) for name in names if os.getenv(name) is not None}


def hermes_home():
    return Path(os.getenv("HERMES_HOME") or str(Path.home() / ".hermes")).expanduser().resolve()


class DiaryError(Exception):
    pass


class BusyError(DiaryError):
    pass


class Rejected(DiaryError):
    def __init__(self, code, retry_after=0, provider="Telegram"):
        super().__init__(f"{provider} rejected the request (HTTP {code}). Check configuration or retry later.")
        self.retry_after = retry_after


class Uncertain(DiaryError):
    pass


def read_config(path):
    """Read the existing, locally trusted Bash config (including legacy printf %q)."""
    if not path.exists():
        return {}
    bash = shutil.which("bash")
    if not bash:
        raise DiaryError("Bash is required to read config.env.")
    script = 'set -ae; . "$1" >/dev/null; '
    script += "printf '%s\\0' " + " ".join('"${' + key + '+x}" "${' + key + '-}"' for key in CONFIG_KEYS)
    env = process_environment()
    result = subprocess.run([bash, "-c", script, "diary-config", str(path)],
                            env=env, capture_output=True)
    if result.returncode:
        # Never echo shell errors: config lines may contain credentials.
        raise DiaryError("Cannot read config.env. Check its Bash syntax locally.")
    values = result.stdout.decode("utf-8").split("\0")
    if len(values) != 2 * len(CONFIG_KEYS) + 1:
        raise DiaryError("Unexpected config.env output.")
    return {key: values[2 * index + 1] for index, key in enumerate(CONFIG_KEYS) if values[2 * index] == "x"}


@dataclass(frozen=True)
class Settings:
    hermes_home: Path
    diary_dir: Path
    timezone: str = "UTC"
    default_city: str = ""
    token: str = field(default="", repr=False)
    channel: str = ""
    language: str = "en"
    temperature_unit: str = "C"
    weather_enabled: bool = False
    delivery: str = "local"
    webhook_url: str = field(default="", repr=False)
    webhook_token: str = field(default="", repr=False)
    schedule_at: str = "23:59"

    @classmethod
    def load(cls):
        home = hermes_home()
        saved = read_config(home / "diary" / "config.env")
        values = defaults(home, legacy=bool(saved) and "LANGUAGE" not in saved)
        # Older persisted configurations without a directory used ~/diary.
        if saved and "DIARY_DIR" not in saved:
            values["DIARY_DIR"] = str(Path.home() / "diary")
        values.update(saved)
        overrides = environment_values()
        values.update(overrides)
        if saved and "DELIVERY" not in saved and "DELIVERY" not in overrides:
            values["DELIVERY"] = "telegram" if values["TELEGRAM_BOT_TOKEN"] and values["TELEGRAM_CHANNEL_ID"] else "local"
        return cls.from_values(home, values)

    @classmethod
    def from_values(cls, home, values):
        if any(any(ord(c) < 32 for c in value) for value in values.values()):
            raise DiaryError("Configuration values cannot contain control characters.")
        if not values["DIARY_DIR"].strip():
            raise DiaryError("Diary directory cannot be empty.")
        if values["WEATHER_ENABLED"].lower() not in ("true", "false"):
            raise DiaryError("WEATHER_ENABLED must be true or false.")
        settings = cls(home, Path(values["DIARY_DIR"]).expanduser().resolve(), values["TIMEZONE"],
                       values["DEFAULT_CITY"].strip(), values["TELEGRAM_BOT_TOKEN"].strip(),
                       values["TELEGRAM_CHANNEL_ID"].strip(), values["LANGUAGE"], values["TEMPERATURE_UNIT"],
                       values["WEATHER_ENABLED"].lower() == "true", values["DELIVERY"],
                       values["WEBHOOK_URL"].strip(), values["WEBHOOK_TOKEN"].strip(), values["SCHEDULE_AT"])
        if settings.language not in ("en", "zh") or settings.temperature_unit not in ("C", "F"):
            raise DiaryError("Use LANGUAGE=en or zh and TEMPERATURE_UNIT=C or F.")
        if settings.delivery not in ("local", "telegram", "discord", "slack", "webhook"):
            raise DiaryError("DELIVERY must be local, telegram, discord, slack or webhook.")
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", settings.schedule_at):
            raise DiaryError("SCHEDULE_AT must use 24-hour HH:MM format.")
        for code_dir in ((home / "skills").resolve(), Path(__file__).resolve().parent.parent):
            if settings.diary_dir == code_dir or code_dir in settings.diary_dir.parents:
                raise DiaryError("Store diary data outside the skill directory.")
        try:
            ZoneInfo(settings.timezone)
        except (ValueError, KeyError) as exc:
            raise DiaryError("Invalid TIMEZONE or missing system tzdata.") from exc
        return settings

    def now(self):
        return datetime.now(ZoneInfo(self.timezone))


def validate_day(value):
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError
    except ValueError as exc:
        raise DiaryError("Date must use YYYY-MM-DD format.") from exc
    return value


def atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".diary-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(4):
            try:
                os.replace(name, path)
                break
            except PermissionError as exc:
                # Windows indexers/AV can briefly hold an otherwise writable file.
                if os.name != "nt" or getattr(exc, "winerror", None) not in (5, 32) or attempt == 3:
                    raise
                time.sleep(0.05 * (attempt + 1))
        if os.name == "posix":
            directory = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_json(path, value):
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


@contextmanager
def diary_lock(settings):
    """OS releases this lock on exit, SIGKILL and reboot; never unlink the file."""
    path = settings.diary_dir / "state" / ".diary.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if os.name == "nt":
            import msvcrt
            if path.stat().st_size == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise BusyError("Another diary task is running. Try again shortly.") from exc
        else:
            import fcntl
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise BusyError("Another diary task is running. Try again shortly.") from exc
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def current_city(settings):
    path = settings.diary_dir / "notes" / "location.md"
    if path.exists():
        return next((line.strip() for line in path.read_text(encoding="utf-8").splitlines()
                     if line.strip()), settings.default_city)
    return settings.default_city

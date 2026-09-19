"""Offline regression tests. Never install a real cron or contact Telegram/wttr.in."""
import contextlib
import argparse
import io
import json
import os
import shutil
import shlex
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from dataclasses import replace
from datetime import datetime
from http.client import IncompleteRead
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

PROJECT = Path(__file__).resolve().parents[1]
SKILL = PROJECT / "skills" / "diary-fragment"
SCRIPTS = SKILL / "scripts"
sys.path.insert(0, str(SCRIPTS))
import compose_diary
import diary_cli
import diary_common as common
import diary_delivery as delivery
import setup_diary as installer


class DiaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get("HERMES_DIARY_TEST_TMP"))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.settings = common.Settings(self.root / "hermes", self.root / "日记 space", token="test-secret", channel="@test",
                                        language="zh", timezone="Asia/Shanghai", default_city="深圳",
                                        weather_enabled=True, delivery="telegram")
        self.settings.diary_dir.mkdir()
        self.day = "2026-09-19"
        self.now = datetime(2026, 9, 19, 23, 59, 59, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.env = {k: v for k, v in os.environ.items() if k not in common.CONFIG_KEYS and k not in common.ENV_KEYS.values()}
        self.env.update(HERMES_HOME=str(self.settings.hermes_home), DIARY_DIR=str(self.settings.diary_dir),
                        HERMES_DIARY_BOT_TOKEN="test-secret", HERMES_DIARY_CHANNEL_ID="@test", PYTHONIOENCODING="utf-8")
        blocker = patch("urllib.request.urlopen", side_effect=AssertionError("Unexpected network access"))
        blocker.start()
        self.addCleanup(blocker.stop)

    def raw(self, text="[09:00] — 吃面\n", day=None):
        common.atomic_write(self.settings.diary_dir / f"{day or self.day}.md", text)

    def composed(self, text="日记\n" + "记录" * 3000, day=None):
        common.atomic_write(self.settings.diary_dir / "composed" / f"{day or self.day}.md", text)

    def execute(self, argv, now=None):
        with contextlib.redirect_stdout(io.StringIO()):
            return diary_cli.execute(diary_cli.parser().parse_args(argv), self.settings, now or self.now)

    def test_record_same_verified_date_and_city(self):
        self.execute(["record", "到广州", "--date", self.day, "--at", "23:59", "--city", "广州"])
        self.assertEqual((self.settings.diary_dir / f"{self.day}.md").read_text(encoding="utf-8"), "[23:59] — 到广州\n")
        self.assertEqual(common.current_city(self.settings), "广州")
        with self.assertRaises(common.DiaryError):
            self.execute(["record", "invalid\nentry"])

    def test_context_reads_preferences_and_clock(self):
        common.atomic_write(self.settings.diary_dir / "notes" / "preferences.md", "保留具体细节")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            diary_cli.execute(diary_cli.parser().parse_args(["context"]), self.settings, self.now)
        data = json.loads(output.getvalue())
        self.assertEqual(data["preferences"], "保留具体细节")
        self.assertEqual((data["date"], data["time"]), (self.day, "23:59"))
        self.assertNotIn("test-secret", output.getvalue())

    def test_compose_date_stays_fixed(self):
        self.raw()
        with patch.object(compose_diary, "weather", return_value="晴 28°C"):
            output = compose_diary.compose(self.settings, self.day, self.day)
        self.assertIn("周六 · 2026.09.19 · 晴 28°C · 深圳", output.read_text(encoding="utf-8"))

    def test_historical_compose_does_not_claim_current_weather(self):
        self.raw()
        output = compose_diary.compose(self.settings, self.day, "2026-09-20")
        self.assertIn("天气未记录 · 城市未记录", output.read_text(encoding="utf-8"))

    def test_empty_diary_skips_network(self):
        self.raw(" \n\n")
        self.assertIsNone(diary_cli.run_day(self.settings, self.day, self.day))

    def test_weather_failure_still_composes(self):
        self.raw()
        with patch("urllib.request.urlopen", side_effect=TimeoutError), contextlib.redirect_stderr(io.StringIO()):
            output = compose_diary.compose(self.settings, self.day, self.day)
        self.assertIn("天气未知", output.read_text(encoding="utf-8"))

    def test_chunks_preserve_unicode_and_newlines(self):
        text = ("日记😀\n" * 1600) + "末尾"
        parts = delivery.chunks(text)
        self.assertEqual("".join(parts), text)
        self.assertTrue(all(len(part.encode("utf-16-le")) // 2 <= 3900 for part in parts))
        self.assertEqual(delivery.chunks(" \n"), [])

    def test_success_dedupes_per_day_even_after_old_resend(self):
        self.composed("今天")
        self.composed("昨天", "2026-09-18")
        with patch.object(delivery, "send", return_value=1) as send:
            self.assertEqual(delivery.deliver(self.settings, self.day), "sent")
            delivery.deliver(self.settings, "2026-09-18", force=True)
            self.assertEqual(delivery.deliver(self.settings, self.day), "already sent")
        self.assertEqual(send.call_count, 2)

    def test_partial_failure_resumes_frozen_snapshot(self):
        self.composed()
        with patch.object(delivery, "send", side_effect=[1, delivery.Rejected(429, 120)]), patch.object(delivery.time, "sleep"):
            with self.assertRaises(delivery.Rejected):
                delivery.deliver(self.settings, self.day)
        state = delivery.load_state(self.settings, self.day)
        self.assertEqual(state["confirmed"], 1)
        self.assertIsNone(state["inflight"])
        expected = state["parts"][1]
        self.composed("内容已经改变")
        with patch.object(delivery, "send", return_value=2) as send, patch.object(delivery.time, "time", return_value=state["retry_at"] + 1):
            delivery.deliver(self.settings, self.day)
        send.assert_called_once_with("test-secret", "@test", expected)

    def test_rate_limit_is_respected(self):
        self.composed("test")
        with patch.object(delivery, "send", side_effect=delivery.Rejected(429, 3600)):
            with self.assertRaises(delivery.Rejected):
                delivery.deliver(self.settings, self.day)
        with patch.object(delivery, "send") as send:
            self.assertEqual(delivery.deliver(self.settings, self.day), "waiting for rate limit")
            send.assert_not_called()

    def test_transport_response_and_token_redaction(self):
        response = io.BytesIO(b'{"ok":true,"result":{"message_id":42}}')
        with patch("urllib.request.urlopen", return_value=response) as request:
            self.assertEqual(delivery.send("test-secret", "@test", "hello"), 42)
        self.assertEqual(request.call_args.args[0].method, "POST")
        self.assertIn(b"chat_id=%40test", request.call_args.args[0].data)
        for error in (TimeoutError("test-secret"), IncompleteRead(b"partial"),
                      urllib.error.HTTPError("https://example/test-secret", 502, "bad gateway", {}, io.BytesIO(b"error"))):
            with patch("urllib.request.urlopen", side_effect=error):
                with self.assertRaises(delivery.Uncertain) as raised:
                    delivery.send("test-secret", "@test", "hello")
                self.assertNotIn("test-secret", str(raised.exception))

    def test_http_rate_limit_and_malformed_response(self):
        error = urllib.error.HTTPError("https://example/test-secret", 429, "limited", {},
                                       io.BytesIO(b'{"ok":false,"parameters":{"retry_after":120}}'))
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(delivery.Rejected) as raised:
                delivery.send("test-secret", "@test", "hello")
            self.assertEqual(raised.exception.retry_after, 120)
        for body in (b"not json", b"[]", b'{"ok":true}', b'{"ok":false,"error_code":500}'):
            with patch("urllib.request.urlopen", return_value=io.BytesIO(body)):
                with self.assertRaises(delivery.Uncertain):
                    delivery.send("test-secret", "@test", "hello")

    def test_completed_parts_survive_crash_before_final_marker(self):
        self.composed("test")
        with patch.object(delivery, "send", return_value=1):
            delivery.deliver(self.settings, self.day)
        state = delivery.load_state(self.settings, self.day)
        state["complete"] = False
        common.write_json(delivery.state_path(self.settings, self.day), state)
        with patch.object(delivery, "send") as send:
            self.assertEqual(delivery.deliver(self.settings, self.day), "sent")
            send.assert_not_called()

    def test_schema_corruption_fails_closed_even_in_optimized_python(self):
        self.composed("test")
        with patch.object(delivery, "send", return_value=1):
            delivery.deliver(self.settings, self.day)
        state = delivery.load_state(self.settings, self.day)
        state["confirmed"] = 99
        common.write_json(delivery.state_path(self.settings, self.day), state)
        result = subprocess.run([sys.executable, "-O", str(SCRIPTS / "diary_cli.py"), "send", "--date", self.day],
                                env=self.env, capture_output=True, text=True, encoding="utf-8", timeout=15)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Corrupt delivery state", result.stderr)

    def test_uncertain_delivery_requires_resolution(self):
        self.composed("test")
        with patch.object(delivery, "send", side_effect=delivery.Uncertain("timeout")):
            with self.assertRaises(delivery.Uncertain):
                delivery.deliver(self.settings, self.day)
        with patch.object(delivery, "send") as send:
            with self.assertRaises(common.DiaryError):
                delivery.deliver(self.settings, self.day)
            send.assert_not_called()
        delivery.resolve(self.settings, self.day, delivered=True)
        self.assertTrue(delivery.load_state(self.settings, self.day)["complete"])

    def test_resolve_retry_only_updates_state(self):
        self.composed("test")
        with patch.object(delivery, "send", side_effect=delivery.Uncertain("timeout")):
            with self.assertRaises(delivery.Uncertain):
                delivery.deliver(self.settings, self.day)
        delivery.resolve(self.settings, self.day, delivered=False)
        with patch.object(delivery, "send", return_value=1) as send:
            delivery.deliver(self.settings, self.day)
            send.assert_called_once()

    def test_state_corruption_fails_closed(self):
        common.atomic_write(delivery.state_path(self.settings, self.day), "{bad json")
        with self.assertRaises(common.DiaryError):
            delivery.deliver(self.settings, self.day)

    def test_channel_change_requires_explicit_resend(self):
        self.composed("test")
        with patch.object(delivery, "send", side_effect=delivery.Rejected(400)):
            with self.assertRaises(delivery.Rejected):
                delivery.deliver(self.settings, self.day)
        with self.assertRaises(common.DiaryError):
            delivery.deliver(replace(self.settings, channel="@other"), self.day)
        with patch.object(delivery, "send", return_value=1):
            delivery.deliver(replace(self.settings, channel="@other"), self.day, force=True)
        self.assertEqual(len(list((delivery.state_path(self.settings, self.day).parent / "history").glob("*.json"))), 1)

    def test_legacy_last_push_prevents_duplicate(self):
        common.atomic_write(self.settings.diary_dir / "state" / "last_push.txt", self.day + "\n")
        self.assertEqual(delivery.deliver(self.settings, self.day), "already sent")

    def test_scheduler_uses_local_time_and_catches_up_yesterday(self):
        common.write_json(self.settings.hermes_home / "diary" / "setup.json", {"schedule_enabled": True})
        with patch.object(diary_cli, "run_day", return_value=None) as run:
            self.execute(["scheduled"])
        self.assertEqual([call.args[1] for call in run.call_args_list], ["2026-09-18", "2026-09-19"])
        with patch.object(diary_cli, "run_day", return_value=None) as run:
            self.execute(["scheduled"], self.now.replace(hour=10))
        self.assertEqual([call.args[1] for call in run.call_args_list], ["2026-09-18"])

    def test_previous_day_failure_does_not_block_today(self):
        common.write_json(self.settings.hermes_home / "diary" / "setup.json", {"schedule_enabled": True})
        with patch.object(diary_cli, "run_day", side_effect=[common.DiaryError("pending"), None]) as run:
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(self.execute(["scheduled"]), 1)
        self.assertEqual(run.call_count, 2)

    def test_all_python_entrypoints_respect_same_lock(self):
        with common.diary_lock(self.settings):
            for script, args in [("diary_cli.py", ["send"]), ("compose_diary.py", []), ("push_to_telegram.py", [])]:
                result = subprocess.run([sys.executable, str(SCRIPTS / script), *args], env=self.env,
                                        capture_output=True, text=True, encoding="utf-8", timeout=15)
                self.assertEqual(result.returncode, 75, result.stderr)

    def test_lock_released_after_process_kill_and_ignores_old_lockdir(self):
        (self.settings.diary_dir / "state" / "run.lock").mkdir(parents=True)
        code = ("import sys,time; sys.path.insert(0,sys.argv[1]); from diary_common import *; "
                "s=Settings.load(); lock=diary_lock(s); lock.__enter__(); print('ready',flush=True); time.sleep(30)")
        proc = subprocess.Popen([sys.executable, "-c", code, str(SCRIPTS)], env=self.env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(proc.stdout.readline().strip(), "ready")
            with self.assertRaises(common.BusyError):
                with common.diary_lock(self.settings):
                    pass
        finally:
            proc.kill()
            proc.communicate(timeout=10)
        with common.diary_lock(self.settings):
            pass

    def test_atomic_write_preserves_old_file_on_replace_failure(self):
        target = self.root / "file.md"
        target.write_text("old", encoding="utf-8")
        with patch.object(common.os, "replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                common.atomic_write(target, "new")
        self.assertEqual(target.read_text(), "old")

    @unittest.skipUnless(shutil.which("bash"), "Bash required for legacy config")
    def test_legacy_bash_config_and_environment_precedence(self):
        config = self.settings.hermes_home / "diary" / "config.env"
        common.atomic_write(config, "DEFAULT_CITY=$'\\u5e7f\\u5dde'\nTIMEZONE=UTC\nDIARY_DIR='/tmp/space dir'\nTELEGRAM_BOT_TOKEN='secret $x'\n")
        self.assertEqual(common.read_config(config)["DEFAULT_CITY"], "广州")
        with patch.dict(os.environ, self.env, clear=True):
            loaded = common.Settings.load()
        self.assertEqual(loaded.diary_dir, self.settings.diary_dir.resolve())
        self.assertEqual(loaded.timezone, "UTC")
        self.assertEqual(loaded.token, "test-secret")

    def test_cron_update_preserves_other_jobs_and_escapes_percent(self):
        original = ("# unrelated\n0 7 * * * echo hello\nCRON_TZ=Asia/Shanghai " + installer.MARKER +
                    "\n59 23 * * * HERMES_HOME=" + shlex.quote(str(self.settings.hermes_home)) + " old " + installer.MARKER + "\n")
        settings = replace(self.settings, diary_dir=self.root / "100% space")
        cron = installer.cron_text(original, settings, "/usr/bin/python3")
        self.assertTrue(cron.startswith("# unrelated\n0 7 * * * echo hello\n"))
        self.assertEqual(cron.count(installer.MARKER), 1)
        self.assertNotIn("CRON_TZ", cron)
        self.assertIn("100\\% space", cron)
        self.assertEqual(installer.cron_text(cron, settings, "/usr/bin/python3"), cron)

    def test_cron_read_error_does_not_become_empty_crontab(self):
        with patch.object(installer.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "permission denied")):
            with self.assertRaises(common.DiaryError):
                installer.read_cron()

    def test_legacy_custom_directory_recovery(self):
        cron = "59 23 * * * HERMES_HOME=/tmp/hermes DIARY_DIR=/tmp/my\\ diary /tmp/run " + installer.MARKER
        self.assertEqual(installer.legacy_directory(cron, Path("/tmp/hermes")), "/tmp/my diary")

    @unittest.skipUnless(shutil.which("bash"), "Bash required for migration")
    def test_upgrade_recovers_old_directory_without_overwriting_config(self):
        config = self.settings.hermes_home / "diary" / "config.env"
        original = "# keep comment\nTIMEZONE=UTC\nDEFAULT_CITY=深圳\nTELEGRAM_BOT_TOKEN=old-token\nTELEGRAM_CHANNEL_ID=@old\n"
        common.atomic_write(config, original)
        directory = str(self.settings.diary_dir).replace("\\", "/")
        cron = "59 23 * * * HERMES_HOME=" + shlex.quote(str(self.settings.hermes_home)) + " DIARY_DIR='" + directory + "' /tmp/run " + installer.MARKER + "\n"
        env = {key: value for key, value in self.env.items() if key != "DIARY_DIR"}
        original_which = shutil.which
        with patch.dict(os.environ, env, clear=True), \
             patch.object(installer.shutil, "which", side_effect=lambda name: "fake" if name == "crontab" else original_which(name)), \
             patch.object(installer, "read_cron", return_value=cron), patch.object(installer, "write_cron"), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(installer.main(["configure", "--non-interactive"]), 0)
        settings = installer.build_settings(argparse.Namespace(diary_dir=None, timezone=None, city=None, channel=None,
                   reconfigure=False, non_interactive=True, no_schedule=False), self.settings.hermes_home, cron)[0]
        self.assertEqual(settings.diary_dir, self.settings.diary_dir.resolve())
        self.assertEqual((settings.token, settings.channel, settings.timezone), ("old-token", "@old", "UTC"))
        self.assertTrue(config.read_text(encoding="utf-8").startswith(original))

    @unittest.skipUnless(shutil.which("bash"), "Bash required for wrapper smoke test")
    def test_shell_entrypoints(self):
        environment = {**self.env, "PYTHON_BIN": sys.executable.replace("\\", "/")}
        root = PROJECT
        for name in ("install.sh", "update.sh", "uninstall.sh", "scripts/diary_compose_and_push.sh"):
            result = subprocess.run([shutil.which("bash"), str(root / name).replace("\\", "/"), "--help"],
                                    env=environment, capture_output=True, text=True, encoding="utf-8", timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run([shutil.which("bash"), str(root / "bin" / "hermes-diary").replace("\\", "/"),
                                 "record", "shell smoke", "--date", self.day, "--at", "12:34"],
                                env=environment, capture_output=True, text=True, encoding="utf-8", timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[12:34] — shell smoke", (self.settings.diary_dir / f"{self.day}.md").read_text(encoding="utf-8"))

    @unittest.skipUnless(shutil.which("bash"), "Bash required for install integration")
    def test_install_update_uninstall_preserves_user_data(self):
        cron = ["# other task\n0 7 * * * echo hello\n"]
        installed = self.settings.hermes_home / "skills" / "diary-fragment"
        shutil.copytree(SKILL, installed, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        original_which = shutil.which
        def which(name):
            return "mock-crontab" if name == "crontab" else original_which(name)
        with patch.dict(os.environ, self.env, clear=True), patch.object(installer.shutil, "which", side_effect=which), \
             patch.object(installer, "read_cron", side_effect=lambda: cron[0]), \
             patch.object(installer, "write_cron", side_effect=lambda value: cron.__setitem__(0, value)), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(installer.main(["configure", "--non-interactive", "--delivery", "telegram", "--schedule", "--city", "广州"], skill_root=installed), 0)
            config = self.settings.hermes_home / "diary" / "config.env"
            saved = config.read_bytes()
            prefs = self.settings.diary_dir / "notes" / "preferences.md"
            prefs.write_text("my preferences", encoding="utf-8")
            self.raw()
            unrelated = self.settings.hermes_home / "scripts" / "unrelated.py"
            unrelated.parent.mkdir(parents=True)
            unrelated.write_text("untouched", encoding="utf-8")
            shutil.copytree(SKILL, installed, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            self.assertEqual(installer.main(["configure", "--non-interactive"], skill_root=installed), 0)
            self.assertEqual(installer.main(["configure", "--non-interactive"], skill_root=installed), 0)
            self.assertEqual(config.read_bytes(), saved)
            self.assertEqual(prefs.read_text(), "my preferences")
            self.assertEqual(cron[0].count(installer.MARKER), 1)
            self.assertIn(str(installed / "scripts" / "diary_cli.py"), cron[0])
            self.assertFalse((self.settings.hermes_home / "scripts" / "diary_cli.py").exists())
            self.assertEqual(installer.main(["disable"], skill_root=installed), 0)
            self.assertTrue((installed / "SKILL.md").exists())
            # Simulate the Hub removing only its installed code directory.
            shutil.rmtree(installed)
            self.assertEqual(cron[0], "# other task\n0 7 * * * echo hello\n")
            self.assertTrue(config.exists())
            self.assertTrue((self.settings.diary_dir / f"{self.day}.md").exists())
            self.assertEqual(unrelated.read_text(), "untouched")

    def test_native_secret_does_not_borrow_gateway_bot(self):
        env = {key: value for key, value in self.env.items() if key not in common.ENV_KEYS.values()}
        env.update(TELEGRAM_BOT_TOKEN="gateway-secret", TELEGRAM_CHANNEL_ID="@gateway")
        with patch.dict(os.environ, env, clear=True):
            settings = common.Settings.load()
            self.assertEqual((settings.token, settings.channel), ("", ""))
        env.update(HERMES_DIARY_BOT_TOKEN="diary-secret", HERMES_DIARY_CHANNEL_ID="@diary")
        with patch.dict(os.environ, env, clear=True):
            settings = common.Settings.load()
            self.assertEqual((settings.token, settings.channel), ("diary-secret", "@diary"))
            self.assertNotIn("diary-secret", repr(settings))

    def test_subprocess_environment_contains_no_unrelated_credentials(self):
        env = {**self.env, "OPENAI_API_KEY": "unrelated", "TELEGRAM_BOT_TOKEN": "gateway"}
        with patch.dict(os.environ, env, clear=True):
            forwarded = common.process_environment()
        self.assertIn("PATH", forwarded)
        for key in ("OPENAI_API_KEY", "TELEGRAM_BOT_TOKEN", "HERMES_DIARY_BOT_TOKEN"):
            self.assertNotIn(key, forwarded)

    @unittest.skipUnless(shutil.which("bash"), "Bash required for config")
    def test_local_only_setup_works_without_cron_or_token(self):
        env = {key: value for key, value in self.env.items() if key not in ("HERMES_DIARY_BOT_TOKEN", "HERMES_DIARY_CHANNEL_ID")}
        original_which = shutil.which
        with patch.dict(os.environ, env, clear=True), \
             patch.object(installer.shutil, "which", side_effect=lambda name: None if name == "crontab" else original_which(name)), \
             patch.object(installer, "write_cron") as write, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(installer.main(["configure", "--no-schedule", "--non-interactive"]), 0)
            report = installer.check()
        self.assertTrue(report["configured"])
        self.assertFalse(report["setup_needed"])
        self.assertFalse(report["telegram_ready"])
        self.assertFalse(report["schedule_enabled"])
        write.assert_not_called()

    def test_missing_credentials_fails_before_configuration_writes(self):
        env = {key: value for key, value in self.env.items() if key not in ("HERMES_DIARY_BOT_TOKEN", "HERMES_DIARY_CHANNEL_ID")}
        with patch.dict(os.environ, env, clear=True), patch.object(installer.shutil, "which", return_value="available"), \
             patch.object(installer, "read_cron", return_value=""), patch.object(installer, "write_cron") as write, \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(installer.main(["configure", "--non-interactive", "--delivery", "telegram"]), 1)
        self.assertFalse((self.settings.hermes_home / "diary" / "config.env").exists())
        write.assert_not_called()

    def test_check_is_read_only_and_redacts_secrets(self):
        with patch.dict(os.environ, self.env, clear=True), patch.object(installer.shutil, "which", return_value=None):
            report = installer.check()
        self.assertTrue(report["setup_needed"])
        self.assertFalse(self.settings.hermes_home.exists())
        self.assertNotIn("test-secret", json.dumps(report))

    def test_scheduler_does_nothing_without_enabled_setup(self):
        with patch.object(diary_cli, "run_day") as run:
            self.execute(["scheduled"])
            common.write_json(self.settings.hermes_home / "diary" / "setup.json", {"schedule_enabled": False})
            self.execute(["scheduled"])
            run.assert_not_called()

    def test_data_inside_skill_is_rejected_before_writes(self):
        with patch.dict(os.environ, self.env, clear=True), patch.object(installer.shutil, "which", return_value="available"), \
             patch.object(installer, "read_cron", return_value=""), patch.object(installer, "write_cron") as write, \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(installer.main(["configure", "--non-interactive", "--diary-dir",
                             str(self.settings.hermes_home / "skills" / "diary-fragment" / "data")]), 1)
        write.assert_not_called()
        self.assertFalse((self.settings.hermes_home / "diary" / "config.env").exists())

    def test_profiles_keep_each_others_cron_jobs(self):
        other = replace(self.settings, hermes_home=self.root / "other-profile")
        other_cron = installer.cron_text("", other, "/usr/bin/python3", skill_root=other.hermes_home / "skills" / "diary-fragment")
        combined = installer.cron_text(other_cron, self.settings, "/usr/bin/python3")
        self.assertEqual(installer.strip_managed(combined, self.settings.hermes_home), other_cron)
        self.assertEqual(combined.count(installer.MARKER), 2)

    def test_check_handles_quoted_paths_and_broken_receipt(self):
        skill = self.root / "skill O'Brien 50%"
        cron = installer.cron_text("", self.settings, sys.executable, skill_root=skill)
        common.atomic_write(self.settings.hermes_home / "diary" / "setup.json", "[]")
        with patch.dict(os.environ, self.env, clear=True), patch.object(installer.shutil, "which", return_value="available"), \
             patch.object(installer, "read_cron", return_value=cron):
            report = installer.check(skill_root=skill)
        self.assertTrue(report["schedule_enabled"])
        self.assertTrue(report["setup_needed"])

    def test_downloaded_skill_runs_without_repository_files(self):
        installed = self.root / "only-skill" / "diary-fragment"
        shutil.copytree(SKILL, installed, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        before = {p.relative_to(installed): p.read_bytes() for p in installed.rglob("*") if p.is_file()}
        env = {key: value for key, value in self.env.items() if key != "PYTHONDONTWRITEBYTECODE"}
        result = subprocess.run([sys.executable, str(installed / "scripts" / "diary_cli.py"),
                                 "record", "独立技能", "--date", self.day, "--at", "08:00"], env=env,
                                cwd=str(self.root), capture_output=True, text=True, encoding="utf-8", timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[08:00] — 独立技能", (self.settings.diary_dir / f"{self.day}.md").read_text(encoding="utf-8"))
        after = {p.relative_to(installed): p.read_bytes() for p in installed.rglob("*") if p.is_file()}
        self.assertEqual(before, after, "Running the skill must not alter the Hub-managed bundle, even with bytecode caches")


if __name__ == "__main__":
    unittest.main()

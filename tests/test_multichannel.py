"""Offline contract tests for languages, local mode and delivery adapters."""
import contextlib
import io
import json
import os
import shutil
import unittest
import urllib.error
from dataclasses import replace
from unittest.mock import patch

import test_diary as legacy
from test_diary import common, compose_diary, delivery, diary_cli, installer
import diary_transports as transports


class Response(io.BytesIO):
    def __init__(self, body=b"", status=200):
        super().__init__(body)
        self.status = status

    def getcode(self):
        return self.status


class MultichannelTests(unittest.TestCase):
    raw = legacy.DiaryTests.raw
    composed = legacy.DiaryTests.composed

    def setUp(self):
        legacy.DiaryTests.setUp(self)
        blocker = patch.object(transports, "_open", side_effect=AssertionError("Unexpected webhook request"))
        blocker.start()
        self.addCleanup(blocker.stop)

    def target(self, provider="webhook"):
        urls = {"webhook": "https://example.com/diary/secret-url", "discord": "https://discord.com/api/webhooks/123/secret-url",
                "slack": "https://hooks.slack.com/services/T000/B000/secret-url"}
        return replace(self.settings, delivery=provider, language="en", webhook_url=urls[provider], webhook_token="secret-bearer")

    def test_english_headings_keep_original_entries(self):
        self.raw("[12:30] — Lunch with Ana\n[13:00] — 到公司\n")
        settings = replace(self.settings, language="en", default_city="London", weather_enabled=False)
        output = compose_diary.compose(settings, self.day, self.day).read_text(encoding="utf-8")
        self.assertTrue(output.startswith("Saturday · 2026-09-19 · London\n"))
        self.assertIn("[13:00] — 到公司", output)

    def test_weather_unit_and_language(self):
        body = json.dumps({"current_condition": [{"weatherDesc": [{"value": "Sunny"}], "temp_C": "20", "temp_F": "68"}]}).encode()
        with patch("urllib.request.urlopen", return_value=Response(body)):
            self.assertEqual(compose_diary.weather("London", "en", "F"), "Sunny 68°F")
        with patch("urllib.request.urlopen", return_value=Response(body)):
            self.assertEqual(compose_diary.weather("London", "zh", "C"), "晴 20°C")

    def test_weather_disabled_or_city_empty_never_contacts_network(self):
        self.raw()
        for weather, city in [(False, "London"), (True, "")]:
            settings = replace(self.settings, language="en", weather_enabled=weather, default_city=city)
            with patch.object(compose_diary, "weather") as lookup:
                compose_diary.compose(settings, self.day, self.day)
                lookup.assert_not_called()

    def test_local_run_is_offline_and_deduplicated(self):
        self.raw()
        settings = replace(self.settings, delivery="local", token="", channel="", weather_enabled=False)
        with patch.object(delivery, "send") as send:
            self.assertEqual(diary_cli.run_day(settings, self.day, self.day), "saved locally")
            self.assertIsNone(diary_cli.run_day(settings, self.day, self.day))
            send.assert_not_called()
        self.assertTrue((settings.diary_dir / "composed" / f"{self.day}.md").exists())

    def test_custom_schedule_catches_same_day_after_missed_minute(self):
        common.write_json(self.settings.hermes_home / "diary" / "setup.json", {"schedule_enabled": True})
        settings = replace(self.settings, schedule_at="21:30")
        with patch.object(diary_cli, "run_day", return_value=None) as run:
            diary_cli.execute(diary_cli.parser().parse_args(["scheduled"]), settings, self.now.replace(hour=22, minute=0))
        self.assertEqual([call.args[1] for call in run.call_args_list], ["2026-09-18", self.day])

    def test_new_setup_defaults_to_local_without_cron(self):
        env = {k: v for k, v in self.env.items() if k not in ("HERMES_DIARY_BOT_TOKEN", "HERMES_DIARY_CHANNEL_ID")}
        original = shutil.which
        with patch.dict(os.environ, env, clear=True), \
             patch.object(installer.shutil, "which", side_effect=lambda n: None if n == "crontab" else original(n)), \
             patch.object(installer, "write_cron") as cron, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(installer.main(["configure", "--non-interactive"]), 0)
            result = common.Settings.load()
        self.assertEqual((result.delivery, result.language, result.timezone), ("local", "en", "UTC"))
        self.assertFalse(result.weather_enabled)
        cron.assert_not_called()
        preferences = (result.diary_dir / "notes" / "preferences.md").read_text(encoding="utf-8")
        self.assertIn("language", preferences)

    def test_empty_values_stay_present_and_setup_is_idempotent(self):
        path = self.settings.hermes_home / "diary" / "config.env"
        common.atomic_write(path, "WEBHOOK_URL=''\nDEFAULT_CITY=''\n")
        self.assertEqual(common.read_config(path), {"WEBHOOK_URL": "", "DEFAULT_CITY": ""})

    def test_local_user_can_disable_without_crontab(self):
        original = shutil.which
        with patch.dict(os.environ, self.env, clear=True), \
             patch.object(installer.shutil, "which", side_effect=lambda n: None if n == "crontab" else original(n)), \
             patch.object(installer, "write_cron") as cron, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(installer.main(["disable"]), 0)
        receipt = json.loads((self.settings.hermes_home / "diary" / "setup.json").read_text())
        self.assertFalse(receipt["schedule_enabled"])
        cron.assert_not_called()

    def test_credentials_alone_do_not_enable_external_delivery(self):
        with patch.dict(os.environ, self.env, clear=True):
            self.assertEqual(common.Settings.load().delivery, "local")

    @unittest.skipUnless(os.name == "nt", "Windows sharing violation behavior")
    def test_atomic_write_retries_temporary_windows_sharing_failure(self):
        path = self.root / "replace.txt"
        path.write_text("old")
        original = common.os.replace
        calls = []
        def replace_once(source, target):
            calls.append(1)
            if len(calls) == 1:
                failure = PermissionError("temporary sharing violation")
                failure.winerror = 32
                raise failure
            original(source, target)
        with patch.object(common.os, "replace", side_effect=replace_once), patch.object(common.time, "sleep"):
            common.atomic_write(path, "new")
        self.assertEqual(path.read_text(), "new")
        self.assertEqual(len(calls), 2)

    def test_legacy_settings_keep_language_city_weather_and_telegram(self):
        path = self.settings.hermes_home / "diary" / "config.env"
        common.atomic_write(path, "TELEGRAM_BOT_TOKEN=old\nTELEGRAM_CHANNEL_ID=@old\nTIMEZONE=Asia/Shanghai\n")
        env = {k: v for k, v in self.env.items() if k not in ("HERMES_DIARY_BOT_TOKEN", "HERMES_DIARY_CHANNEL_ID")}
        with patch.dict(os.environ, env, clear=True):
            result = common.Settings.load()
        self.assertEqual((result.language, result.default_city, result.delivery), ("zh", "深圳", "telegram"))
        self.assertTrue(result.weather_enabled)

    def test_legacy_journal_continues_after_upgrade(self):
        old = {"version": 1, "day": self.day, "channel": "@test", "parts": ["one", "two"],
               "confirmed": 1, "message_ids": [1], "inflight": None, "complete": False, "retry_at": 0}
        common.write_json(delivery.state_path(self.settings, self.day), old)
        with patch.object(delivery, "send", return_value=2) as send:
            self.assertEqual(delivery.deliver(self.settings, self.day), "sent")
        send.assert_called_once_with("test-secret", "@test", "two")

    def test_discord_payload_and_confirmation(self):
        settings = replace(self.target("discord"), webhook_url=self.target("discord").webhook_url + "?thread_id=456&wait=false")
        with patch.object(transports, "_open", return_value=Response(b'{"id":"789"}')) as opened:
            self.assertEqual(transports.send_webhook(settings, "@everyone diary 😀", self.day, "id", 0, 1), "789")
        request = opened.call_args.args[0]
        self.assertIn("wait=true", request.full_url)
        self.assertNotIn("wait=false", request.full_url)
        self.assertIn("thread_id=456", request.full_url)
        self.assertEqual(json.loads(request.data)["allowed_mentions"], {"parse": []})
        self.assertNotIn("Authorization", request.headers)
        with patch.object(transports, "_open", return_value=Response(b"", 204)):
            with self.assertRaises(common.Uncertain):
                transports.send_webhook(settings, "text", self.day, "id", 0, 1)

    def test_slack_plain_text_and_acknowledgement(self):
        with patch.object(transports, "_open", return_value=Response(b"ok")) as opened:
            transports.send_webhook(self.target("slack"), "<!channel> *text* &", self.day, "id", 0, 1)
        payload = json.loads(opened.call_args.args[0].data)
        self.assertEqual(payload["blocks"][0]["text"]["type"], "plain_text")
        self.assertFalse(payload["mrkdwn"])
        self.assertFalse(payload["link_names"])
        self.assertIn("&lt;!channel&gt;", payload["text"])
        with patch.object(transports, "_open", return_value=Response(b"invalid_payload")):
            with self.assertRaises(common.Uncertain):
                transports.send_webhook(self.target("slack"), "text", self.day, "id", 0, 1)

    def test_generic_payload_bearer_and_stable_id(self):
        settings = self.target()
        with patch.object(transports, "_open", return_value=Response(b"", 202)) as opened:
            transports.send_webhook(settings, "hello", self.day, "stable", 1, 3)
        request = opened.call_args.args[0]
        data = json.loads(request.data)
        self.assertEqual((data["event"], data["id"], data["part"], data["parts"]), ("diary.daily", "stable:2", 2, 3))
        self.assertEqual(request.get_header("Idempotency-key"), data["id"])
        self.assertEqual(request.get_header("Authorization"), "Bearer secret-bearer")

    def test_provider_limits_and_no_credentials_in_journal(self):
        for provider in ("discord", "slack", "webhook"):
            settings = self.target(provider)
            self.composed("😀" * 4200)
            with patch.object(delivery, "send_webhook", return_value="confirmed") as send, patch.object(delivery.time, "sleep"):
                delivery.deliver(settings, self.day, force=True)
            state = delivery.load_state(settings, self.day)
            self.assertEqual("".join(state["parts"]), "😀" * 4200)
            self.assertTrue(all(len(p.encode("utf-16-le")) // 2 <= transports.LIMITS[provider] for p in state["parts"]))
            self.assertEqual(send.call_count, len(state["parts"]))
            for secret in (settings.webhook_url, "secret-bearer", "test-secret"):
                self.assertNotIn(secret, json.dumps(state))
                self.assertNotIn(secret, repr(settings))

    def test_destination_change_even_after_completion_requires_resend(self):
        self.composed("text")
        with patch.object(delivery, "send_webhook", return_value="ok"):
            delivery.deliver(self.target(), self.day)
            with self.assertRaises(common.DiaryError):
                delivery.deliver(self.target("slack"), self.day)
            delivery.deliver(self.target("slack"), self.day, force=True)

    def test_webhook_retry_keeps_id_and_snapshot_metadata(self):
        settings = self.target()
        self.composed("text")
        with patch.object(delivery, "send_webhook", side_effect=common.Rejected(429, 120)):
            with self.assertRaises(common.Rejected):
                delivery.deliver(settings, self.day)
        before = delivery.load_state(settings, self.day)
        with patch.object(delivery, "send_webhook", return_value="ok") as send, \
             patch.object(delivery.time, "time", return_value=before["retry_at"] + 1):
            delivery.deliver(replace(settings, timezone="UTC", language="zh"), self.day)
        self.assertEqual(send.call_args.args[3], before["delivery_id"])
        self.assertEqual(send.call_args.args[0].language, "en")
        self.assertEqual(send.call_args.args[0].timezone, settings.timezone)

    def test_rate_limit_headers_and_discord_fractional_delay(self):
        error = urllib.error.HTTPError("https://secret", 429, "secret", {"Retry-After": "90"}, io.BytesIO(b'{"retry_after":120.2}'))
        with patch.object(transports, "_open", side_effect=error):
            with self.assertRaises(common.Rejected) as raised:
                transports.send_webhook(self.target(), "text", self.day, "id", 0, 1)
        self.assertEqual(raised.exception.retry_after, 121)
        self.assertNotIn("secret", str(raised.exception))

    def test_uncertain_failures_are_sanitized_and_pause(self):
        for code in (302, 408, 500):
            error = urllib.error.HTTPError("https://secret", code, "secret-bearer", {}, io.BytesIO(b"secret-url"))
            with patch.object(transports, "_open", side_effect=error):
                with self.assertRaises(common.Uncertain) as raised:
                    transports.send_webhook(self.target(), "text", self.day, "id", 0, 1)
            self.assertNotIn("secret", str(raised.exception))
        self.composed("text")
        with patch.object(delivery, "send_webhook", side_effect=common.Uncertain("timeout")):
            with self.assertRaises(common.Uncertain):
                delivery.deliver(self.target(), self.day)
        with patch.object(delivery, "send_webhook") as send:
            with self.assertRaises(common.DiaryError):
                delivery.deliver(self.target(), self.day)
            send.assert_not_called()

    def test_redirect_handler_does_not_forward_credentials(self):
        import urllib.request
        request = urllib.request.Request("https://example.com/secret", data=b"diary", headers={"Authorization": "Bearer secret"})
        with self.assertRaises(urllib.error.HTTPError):
            transports.NoRedirect().redirect_request(request, None, 307, "redirect", {}, "https://other.example/")

    def test_invalid_destinations_are_rejected_without_echoing_url(self):
        for provider, url in [("webhook", "http://example.com/secret"), ("webhook", "https://user:secret@example.com"),
                              ("webhook", "https://example.com/secret#fragment"), ("discord", "https://example.com/secret"),
                              ("slack", "https://hooks.slack.com.evil.example/services/T/B/secret")]:
            with self.assertRaises(common.DiaryError) as raised:
                transports.validate_target(replace(self.target(provider), webhook_url=url))
            self.assertNotIn("secret", str(raised.exception))

    def test_webhook_configuration_and_check_redact_secrets(self):
        env = {**self.env, "HERMES_DIARY_WEBHOOK_URL": self.target().webhook_url,
               "HERMES_DIARY_WEBHOOK_TOKEN": "secret-bearer"}
        original = shutil.which
        with patch.dict(os.environ, env, clear=True), \
             patch.object(installer.shutil, "which", side_effect=lambda n: None if n == "crontab" else original(n)), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(installer.main(["configure", "--delivery", "webhook", "--non-interactive", "--no-schedule",
                                             "--language", "en", "--timezone", "America/New_York", "--temperature-unit", "F",
                                             "--at", "22:15", "--no-weather"]), 0)
            settings = common.Settings.load()
            report = installer.check()
        self.assertEqual((settings.delivery, settings.temperature_unit, settings.schedule_at), ("webhook", "F", "22:15"))
        self.assertFalse(settings.weather_enabled)
        self.assertTrue(report["delivery_ready"])
        self.assertNotIn("secret", output.getvalue() + json.dumps(report))


if __name__ == "__main__":
    unittest.main()

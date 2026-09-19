---
name: diary-fragment
description: Keep a local diary and optionally deliver daily entries.
version: 2.3.0
license: MIT
platforms: [linux]
required_environment_variables:
  - name: HERMES_DIARY_BOT_TOKEN
    prompt: Diary Telegram bot token (skip unless using Telegram)
    help: Obtain from BotFather. Local-only users and users with saved credentials can skip.
    required_for: Telegram delivery only
  - name: HERMES_DIARY_WEBHOOK_URL
    prompt: Diary webhook URL (skip for local or Telegram mode)
    help: Use your Discord/Slack incoming webhook or HTTPS receiver. Treat the entire URL as a secret.
    required_for: Discord, Slack or generic webhook delivery only
  - name: HERMES_DIARY_WEBHOOK_TOKEN
    prompt: Optional bearer token for a generic diary webhook (usually skip)
    help: Only for a receiver requiring bearer authentication; unused for Discord and Slack.
    required_for: Generic webhook receivers requiring bearer authentication
metadata:
  hermes:
    tags: [diary, journaling, markdown, telegram, discord, slack, webhook]
---

# Hermes Diary

## When to use

Use for journaling requests, factual daily-life notes, explicit city arrivals, diary previews, and diary setup/delivery. Examples: “remember this”, “log my lunch”, “记一下”, “生活碎片”, “看看今天的日记”. A question, hypothetical event, or discussion of diary software is not itself a diary entry.

Use the user's language for replies and notes. Keep their names, details, and meaning; do not translate existing entries unless asked. English/Chinese heading selection is a separate configuration choice.

## Procedure

For initialization, migration, or configuration changes, read [setup.md](references/setup.md). For choosing or troubleshooting an external destination, also read [delivery.md](references/delivery.md).

Start with the read-only check:

```bash
python3 "${HERMES_SKILL_DIR}/scripts/setup_diary.py" check
```

`${HERMES_SKILL_DIR}` is supplied by Hermes. If the current version does not substitute it, use the absolute Skill directory shown by `skill_view`. Run on the persistent machine/profile that owns the diary.

New users default to local-only storage, no schedule and no weather. Set language from the user's preference; ask for their timezone when needed rather than inferring a city from language. Configure a destination, weather lookup or schedule only when requested. Keep credentials out of model-visible output; the setup program reuses saved values internally. Users can skip every secure credential prompt for local use.

Before recording, read the actual clock and saved preferences once:

```bash
python3 "${HERMES_SKILL_DIR}/scripts/diary_cli.py" context
```

Use the returned date/time together for the new note; retain a user-supplied explicit event time. Do not estimate when “just now” happened. Follow `preferences` for writing style. Pass a concise factual sentence as one correctly shell-quoted argument:

```bash
# Dates/times below are examples, not the current clock.
python3 "${HERMES_SKILL_DIR}/scripts/diary_cli.py" record 'Had lunch with Ana' --date 2026-09-19 --at 12:30
python3 "${HERMES_SKILL_DIR}/scripts/diary_cli.py" record '到广州' --date 2026-09-19 --at 18:20 --city 广州
```

Only set `--city` for a stated arrival or present location; future travel plans do not change the current city. Do not invent emotions, reflections, locations or times. Keep append order and allow several entries in the same minute. Do not automatically deduplicate or delete notes.

For previews, run `compose` and read the resulting Markdown file; this never delivers it. For `send`, `run`, `resend`, historical dates and interrupted delivery, read [commands.md](references/commands.md). Send immediately only when requested; an enabled schedule follows its saved authorization. Each profile has one destination, not simultaneous fan-out.

## Pitfalls

- Webhook URLs and bot tokens are secrets. Use Hermes secure local setup or the user's own terminal, never chat text or literal command-line secret arguments.
- Runtime settings override saved configuration; cron reads persisted settings. Use `configure --reconfigure` to persist an authorized change.
- Do not reuse Hermes gateway credentials or assume this diary sends back to the current chat.
- Unknown delivery outcomes need a human check before `resolve`; do not clear journals or automatically force a resend.
- Weather is optional and current at lookup time. Historical entries must not be assigned today's weather or city.
- Store all data outside the skill directory. An update may replace the entire package.

## Verification

Report a note as saved only after a successful command. Exit 75 means the shared diary lock is busy; retry with the same verified date/time. `check` verifies configuration and matching cron entries, not service health or live delivery. A configured webhook is not a verified destination; do not send an unsolicited test message.

## Bundled resources

All support files are explicitly linked for Hermes versions that download referenced resources:

- [CLI](scripts/diary_cli.py)
- [Setup and scheduling](scripts/setup_diary.py)
- [Configuration, files and locks](scripts/diary_common.py)
- [Composition and weather](scripts/compose_diary.py)
- [Delivery journal and Telegram adapter](scripts/diary_delivery.py)
- [Discord, Slack and HTTPS webhook adapters](scripts/diary_transports.py)
- [Legacy send entry point](scripts/push_to_telegram.py)
- [English default preferences](assets/preferences.default.md)
- [Chinese default preferences](assets/preferences.zh.md)
- [License](assets/LICENSE)
- [Setup reference](references/setup.md)
- [Commands and recovery](references/commands.md)
- [Delivery reference](references/delivery.md)

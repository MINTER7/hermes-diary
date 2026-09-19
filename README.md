# Hermes Diary

**Capture small moments. Keep a diary you own. Read it wherever you prefer.**

English · [简体中文](README.zh-CN.md)

A native skill for [Hermes Agent](https://github.com/NousResearch/hermes-agent) that turns short, factual notes into a daily Markdown journal. Keep everything on your machine, or deliver a daily entry to **Telegram, Discord, Slack, or an HTTPS webhook**.

```text
Saturday · 2026-09-19 · London

[08:10] — Walked to the bakery before work.
[12:30] — Had lunch with Ana.
[18:45] — Finished the first draft of the presentation.
```

Write in the language you use every day. Entries retain their wording; the daily composer adds a heading and joins your notes without an additional AI rewrite.

## What you get

- **Plain Markdown files.** Your entries stay readable and portable without Hermes.
- **Native skill installation.** Install and update through the Hermes skill manager.
- **Your language and clock.** English or Chinese headings, any IANA timezone, Celsius or Fahrenheit, and an optional daily schedule.
- **A choice of destinations.** Local files, Telegram, Discord, Slack, or your own webhook receiver.
- **Optional weather.** Off for new users; enable a city-based lookup when useful.
- **Delivery recovery.** Long entries are split, confirmed parts are remembered, and uncertain sends pause for review.

This is a community skill, not an official Hermes or messaging-platform product. The supported deployment target is **Linux**, including a persistent Linux server or WSL environment.

## Get started

You need Hermes Agent, Python **3.9+**, Bash, and system timezone data (`tzdata`). The runtime uses the Python standard library. Scheduling additionally needs an installed, running **cron** service; manual journaling does not.

### 1. Install the skill

```bash
hermes skills install MINTER7/hermes-diary/skills/diary-fragment
```

Installation downloads and scans the skill. It does **not** create a schedule or send a message.

### 2. Start a new Hermes session

```text
/diary-fragment Set up a local diary in English. Use Europe/London time. Keep weather and automatic delivery off.
```

Hermes may offer secure credential prompts when loading this skill. **Skip all of them for local use.** For a messaging destination, fill only the applicable credentials; existing saved credentials can be reused. Do not paste bot tokens or webhook URLs into a chat.

### 3. Record and preview

```text
/diary-fragment Remember this: I had lunch with Ana at 12:30.
/diary-fragment Show me today's diary without sending it.
```

You can also say “记一下，中午和朋友吃了饭。” Mixed-language entries are supported. Changing the heading language does not translate existing notes.

## Choose where your diary goes

Every mode keeps the original and composed Markdown locally. A profile uses **one delivery destination at a time**; this version does not broadcast to several services simultaneously.

| Mode | What it does | What you provide |
| --- | --- | --- |
| `local` — default | Saves the daily entry locally | No delivery credentials |
| `telegram` | Sends text through the Telegram Bot API | A diary bot token and chat/channel ID |
| `discord` | Posts to a Discord channel or existing thread | An incoming webhook URL |
| `slack` | Posts to the conversation attached to a Slack webhook | An incoming webhook URL |
| `webhook` | POSTs versioned JSON to your own HTTPS endpoint | A URL; optional bearer token |

The generic webhook can connect to an automation service or a custom receiver that accepts the [documented payload](skills/diary-fragment/references/delivery.md). It is not a claim of native support for every chat app or email service. Delivery is configured independently from Hermes's chat gateway.

For example, ask Hermes:

```text
/diary-fragment Send my diary to Discord every day at 23:30 America/New_York. Use English headings and Fahrenheit. Keep weather off for now.
```

Hermes will guide the local configuration. Discord and Slack need a webhook; they do not need a Telegram bot.

## Configure from a terminal

Use the actual skill directory shown by Hermes. The following is the default location; adjust it for a category or custom profile, and run commands on the machine that stores your diary:

```bash
DIARY_SKILL="${HERMES_HOME:-$HOME/.hermes}/skills/diary-fragment"
python3 "$DIARY_SKILL/scripts/setup_diary.py" check
python3 "$DIARY_SKILL/scripts/setup_diary.py" configure \
  --delivery local --language en --timezone Europe/London \
  --no-schedule --non-interactive
```

For interactive setup, omit `--non-interactive`. Secret inputs are hidden. New installations default to local files, English headings, UTC, no weather, and no schedule. An unset city stays unset; it is never guessed from your IP address.

To enable a **local daily summary** at 23:59 without sending anything externally:

```bash
python3 "$DIARY_SKILL/scripts/setup_diary.py" configure \
  --reconfigure --delivery local --schedule --at 23:59 --non-interactive
```

To enable **Discord delivery**, run this in your own Bash terminal. `read -s` hides the URL and keeps its literal value out of shell history:

```bash
read -r -s -p "Discord webhook URL: " HERMES_DIARY_WEBHOOK_URL; printf '\n'
export HERMES_DIARY_WEBHOOK_URL
python3 "$DIARY_SKILL/scripts/setup_diary.py" configure \
  --reconfigure --delivery discord --schedule --at 23:30 --non-interactive
unset HERMES_DIARY_WEBHOOK_URL
```

Use `--delivery slack` with a Slack incoming webhook, or `--delivery webhook` with your own HTTPS receiver. See [delivery setup](skills/diary-fragment/references/delivery.md) for Telegram, optional webhook authentication, acknowledgement rules, and troubleshooting.

Useful options:

| Option | Example / behavior |
| --- | --- |
| `--language` | `en` or `zh`; controls generated headings and the initial preferences template |
| `--timezone` | `Europe/London`, `America/New_York`, `Asia/Shanghai`, `UTC` |
| `--city` | `London`; explicit city for the heading and optional weather lookup |
| `--weather` / `--no-weather` | Enable / disable the external weather lookup |
| `--temperature-unit` | `C` or `F` |
| `--schedule --at HH:MM` | Enable a daily run at the chosen local time |
| `--no-schedule` | Remove this profile's schedule; retain manual commands |
| `--diary-dir` | Store data in another directory outside the skill package |
| `--reconfigure` | Save changes to existing settings and back up the old configuration |

For Chinese headings, for example:

```bash
python3 "$DIARY_SKILL/scripts/setup_diary.py" configure \
  --reconfigure --language zh --timezone Asia/Shanghai --city 深圳 \
  --weather --temperature-unit C --non-interactive
```

Reconfiguration preserves an existing schedule unless you explicitly enable or disable it. Changing `--city` with `--reconfigure` also updates the current city. Existing preferences are never replaced; edit `notes/preferences.md` to change their wording guidance. CLI help and operational diagnostics use English.

## Everyday commands

Run `python3 "$DIARY_SKILL/scripts/diary_cli.py"` followed by:

| Command | Result |
| --- | --- |
| `context` | Clock, non-secret settings, city, and writing preferences |
| `record 'Had lunch with Ana' --at 12:30` | Append a timestamped note |
| `today` | Read today's raw entries |
| `city London` | Set the current city explicitly |
| `compose` | Generate a daily Markdown file without delivery |
| `run` | Compose and deliver using the selected mode |
| `send` | Deliver an already composed entry, or resume its saved snapshot |
| `status` | View the configured schedule and unfinished deliveries |
| `logs` | Read the last 100 lines of the scheduler log |

Date-based commands also accept `--date YYYY-MM-DD`. [Full command and recovery guide →](skills/diary-fragment/references/commands.md)

## Scheduling and reliability

Cron checks once per minute; the program uses the configured timezone and schedule time, including daylight-saving changes. It processes today's diary at or after that time and retries the previous day's unfinished entry. Older dates require an explicit `run --date`.

No entries means no message. Confirmed parts are not resent on ordinary retries. HTTP rejections use a delay of at least 60 seconds and respect supported rate-limit hints. A timeout, server error, interrupted process, or ambiguous response leaves a pending part for manual review: an HTTP client cannot always know whether a remote service accepted a message before a connection failed.

This is **not an exactly-once delivery guarantee**. Generic webhook receivers should use the stable event ID or `Idempotency-Key` to deduplicate retries. A successful webhook response means HTTP acceptance, not confirmation of any downstream email or chat delivery.

A completed daily delivery is a snapshot. Entries added later remain in the raw diary; explicitly `compose` and `resend` to send a revised version. Changing destination also requires an explicit `resend` for dates already tracked, to avoid accidental redistribution. Prefer a late-evening schedule if you want most of the day included.

Weather, when enabled, reflects lookup time, not a historical daily forecast. Freshly composed historical entries label unsaved weather and city as unrecorded; existing composed files can retain their earlier heading.

## Your files and privacy

New profiles store data under `${HERMES_HOME:-~/.hermes}/diary/data/`. Existing installations keep their original directory, including `~/diary` where applicable.

```text
<HERMES_HOME>/diary/
├── config.env              # Saved settings and selected credentials; mode 600
├── config.env.bak          # Previous configuration, when reconfigured
├── setup.json              # Setup receipt; no credentials
└── data/                   # Default for new profiles; configurable
    ├── 2026-09-19.md        # Original notes
    ├── composed/           # Complete daily Markdown entries
    ├── notes/              # Current city and editable preferences
    ├── state/              # Locks and delivery snapshots
    └── cron.log            # Scheduler output
```

Delivery is off for new users. With weather off and `local` selected, the diary scripts make no network requests. Your conversations with Hermes still follow your Hermes/model-provider configuration. Enabling weather sends the configured city to [wttr.in](https://github.com/chubin/wttr.in); enabling delivery sends diary text to your selected destination.

Credentials stay in the local configuration with restricted permissions; this is **not encrypted storage**. Keep the configuration, its backup, diary files, and delivery snapshots out of public repositories. A webhook URL is itself a credential. Status output and journals do not store raw webhook URLs or bot tokens. Webhook redirects are not followed.

Use dedicated `HERMES_DIARY_*` variables when providing overrides. In particular, the skill does not borrow Hermes's `TELEGRAM_BOT_TOKEN`. Runtime overrides must be persisted with `configure --reconfigure` if cron should use them too. See the [configuration reference](skills/diary-fragment/references/setup.md) and [example configuration](config/config.example.env).

## Update, migrate, or uninstall

```bash
hermes skills check
hermes skills update diary-fragment
```

Code stays inside the native skill package; settings and data stay outside it. Normal updates at the same path do not require copying scripts or rebuilding cron.

For v2.2 and earlier, use the same `HERMES_HOME`, install/update the native skill, then run `setup_diary.py configure --non-interactive`. Saved Telegram settings, Chinese headings, timezone, data directory, preferences, and version-1 delivery journals remain compatible. A v2.2 schedule receipt preserves its enabled state; recognizable older managed cron jobs are migrated. To deliberately change settings, use `--reconfigure`.

Before uninstalling, stop the schedule:

```bash
python3 "$DIARY_SKILL/scripts/setup_diary.py" disable
hermes skills uninstall diary-fragment
```

Your diary and configuration are retained. There is no automatic uninstall hook: if you remove the skill first, its cron line becomes dormant and still needs cleanup. [Setup and migration details →](skills/diary-fragment/references/setup.md)

## Development and verification

```bash
python3 -m unittest discover -s tests -v
```

Tests use temporary directories and mocked services. They cover configuration migration, language and temperature settings, local operation, payloads for each adapter, Unicode limits, retries, uncertain outcomes, destination changes, locks, scheduling, and installation isolation. They do not send real messages or edit your crontab. CI is configured for Linux with Python 3.9 and 3.12.

Real credentials, a running cron daemon, and a remote Hermes installation must be checked in the deployment environment. Passing offline tests does not prove that a particular webhook, bot, or server is configured correctly.

The root `install.sh`, `update.sh`, and `uninstall.sh` are compatibility tools for local source checkouts; public distribution should use the native install command above. [Publishing guide →](PUBLISHING.md)

## License

[MIT](LICENSE). Contributions and additional translations are welcome. Please keep issue reports free of diary contents, bot tokens, and webhook URLs.

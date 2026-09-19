# Setup and maintenance

Requires Linux, Python 3.9+, Bash and tzdata. Scheduling requires a running cron service. Use the same persistent machine and `HERMES_HOME` as the diary; a temporary agent sandbox's crontab is not the host's scheduler.

Commands below use the Hermes-provided `${HERMES_SKILL_DIR}`. In a user's terminal, substitute the actual installed path. Install only downloads the package; configuration is a separate step.

## Check before configuring

```bash
python3 "${HERMES_SKILL_DIR}/scripts/setup_diary.py" check
```

Read-only JSON includes `configured`, `setup_needed`, `delivery`, `delivery_ready`, `language`, `timezone`, `weather_enabled`, `schedule_at` and `schedule_enabled`, without credentials. Readiness checks configuration, not a real API request. Schedule detection checks the matching cron entry, not the daemon's health. The CLI `status` displays the saved receipt; use `check` to inspect cron.

## Local first

```bash
python3 "${HERMES_SKILL_DIR}/scripts/setup_diary.py" configure --delivery local --language en --timezone Europe/London --no-schedule --non-interactive
```

Use the user's timezone. For Chinese headings select `--language zh`. New configurations default to local storage, English, UTC, no weather and no schedule. No city is guessed. New data defaults to `<HERMES_HOME>/diary/data`; `--diary-dir` can choose another directory outside the skill tree. Existing profiles retain their previous directory.

For interactive setup, omit `--non-interactive` in a local terminal. This prompts for mode, timezone, heading language, optional city, and missing required credentials. Ask the user to do hidden secret entry locally; do not pass secrets as CLI arguments. New schedules always require `--schedule`.

## External destinations

Read [delivery.md](delivery.md) for credentials and endpoint rules. Example after a Discord URL has been securely supplied in `HERMES_DIARY_WEBHOOK_URL`:

```bash
python3 "${HERMES_SKILL_DIR}/scripts/setup_diary.py" configure --reconfigure --delivery discord --schedule --at 23:30 --timezone America/New_York --non-interactive
```

Omit `--reconfigure` on a fresh install if desired. Do not request a Telegram token for Discord/Slack/webhook. Enabling a schedule is appropriate only when the user requests it. Setup does not send test messages.

`--no-schedule` disables scheduling, not the selected adapter; manual `send`/`run` can still send through that adapter. Select `--delivery local --reconfigure --no-weather` to use the diary entirely offline. Weather requests go to wttr.in and can be enabled independently with `--weather --city London --temperature-unit F`.

## Saved configuration and overrides

`<HERMES_HOME>/diary/config.env` contains Bash assignments and is mode 600. It is locally trusted executable Bash configuration, not a file to import from an untrusted repository. Never display it in a chat. `config.env.bak` may contain previous credentials. Neither file is encrypted.

| Saved field | Runtime environment variable |
| --- | --- |
| `DIARY_DIR` | `HERMES_DIARY_DIR` |
| `TIMEZONE` | `HERMES_DIARY_TIMEZONE` |
| `DEFAULT_CITY` | `HERMES_DIARY_CITY` |
| `LANGUAGE` | `HERMES_DIARY_LANGUAGE` |
| `TEMPERATURE_UNIT` | `HERMES_DIARY_TEMPERATURE_UNIT` |
| `WEATHER_ENABLED` | `HERMES_DIARY_WEATHER_ENABLED` (`true` / `false`) |
| `DELIVERY` | `HERMES_DIARY_DELIVERY` |
| `SCHEDULE_AT` | `HERMES_DIARY_SCHEDULE_AT` |
| `TELEGRAM_BOT_TOKEN` | `HERMES_DIARY_BOT_TOKEN` |
| `TELEGRAM_CHANNEL_ID` | `HERMES_DIARY_CHANNEL_ID` |
| `WEBHOOK_URL` | `HERMES_DIARY_WEBHOOK_URL` |
| `WEBHOOK_TOKEN` | `HERMES_DIARY_WEBHOOK_TOKEN` |

Runtime values override the saved file. Setup preserves saved settings unless `--reconfigure` is used; with it, environment values and explicit CLI options are persisted for cron (CLI options win). Secrets have no CLI flags. Credential environment variables are declared by the skill for Hermes's secure local setup and sandbox passthrough; unrelated gateway secrets are not reused.

Changing secrets in the agent environment alone does not update cron's saved settings. Reconfigure to persist them. After changing the delivery destination, existing daily delivery records require an explicit `resend` or restoring the original target. Journals retain content and confirmation progress; do not erase them to bypass duplicate prevention.

Existing `notes/preferences.md` is preserved. Changing heading language does not replace the preferences file or translate old entries. `--reconfigure --city` also changes the current city. Move data before changing `--diary-dir`; setup does not move it for you. Use a distinct data directory for independent profiles.

## Schedule behavior

`--schedule --at HH:MM` enables daily local composition or external delivery in the selected timezone. Cron ticks every minute. The program handles today at or after that time and the previous day's unfinished entry. This catches a missed minute while limiting automatic historical sends. Empty dates and completed entries are skipped.

Existing schedule receipts preserve the enabled state unless `--schedule` or `--no-schedule` is supplied. Configuration can confirm a cron entry but cannot start or prove the health of a daemon. Check the service in the actual Linux deployment. Daylight-saving time follows IANA timezone rules; a missing local minute is caught after the clock jumps, and repeated minutes share the same daily journal.

## Updates and migration

Use `hermes skills check` and `hermes skills update diary-fragment`, then start a new session. Code executes directly inside the skill package. Normal same-path updates do not need a second script copy or a rewritten cron entry.

For v2/v2.1/v2.2, keep the same `HERMES_HOME` and data directory, stop any active old delivery process, install/update this skill, then run `configure --non-interactive`. Old configs infer Chinese headings, Celsius, enabled weather and Telegram when credentials exist. Saved timezone/city and preferences are preserved. Version-1 Telegram delivery state remains readable. A v2.2 setup receipt retains its schedule; recognizable older managed cron entries are migrated. If a legacy custom data directory is absent from both config and cron, supply its original `--diary-dir` explicitly.

An existing same-name unmanaged skill may need to be backed up/moved according to the Hub's conflict prompt. Legacy copied scripts are not deleted; use the native entry point going forward. Setup backs up a config before migration adds missing fields.

## Disable and uninstall

```bash
python3 "${HERMES_SKILL_DIR}/scripts/setup_diary.py" disable
hermes skills uninstall diary-fragment
```

Disabling removes only this profile's managed cron and retains code/data/settings. Removing the skill first leaves a dormant cron entry guarded by a file-existence check. There is no automatic uninstall hook. Never delete diary or configuration files as part of ordinary uninstall.

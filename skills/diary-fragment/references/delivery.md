# Delivery destinations

Choose one mode per profile: `local`, `telegram`, `discord`, `slack`, or `webhook`. All modes retain local Markdown. External delivery requires an explicitly configured destination; no adapter borrows the current Hermes chat gateway.

## Credential entry

Never include actual tokens or webhook URLs in chat, issue reports, screenshots, or literal CLI arguments. Hermes's local secure setup can supply the declared `HERMES_DIARY_*` secrets. Skip prompts for modes you are not using. Alternatively, run `setup_diary.py configure --delivery <mode>` in your own interactive terminal for hidden secret entry.

For non-interactive configuration from your own Bash terminal:

```bash
read -r -s -p "Webhook URL: " HERMES_DIARY_WEBHOOK_URL; printf '\n'
export HERMES_DIARY_WEBHOOK_URL
python3 "$DIARY_SKILL/scripts/setup_diary.py" configure --reconfigure --delivery discord --schedule --non-interactive
unset HERMES_DIARY_WEBHOOK_URL
```

Set `DIARY_SKILL` to the actual installed directory first. Change the mode to `slack` or `webhook` as appropriate. A webhook URL already contains access information. The saved config is local, mode 600, and not encrypted. HTTPS is required; userinfo, fragments and redirects are rejected. Discord/Slack adapters validate their platform host and URL shape; generic webhooks accept a direct HTTPS endpoint on port 443.

## Local

No delivery credentials or external connection. `run` composes the day and marks it handled. Add `--schedule` only to request automatic daily composition. Disable weather to keep diary-script operation fully offline; Hermes conversations still use the user's configured model service.

## Telegram

Create a bot with Telegram's BotFather, give it access to the intended conversation, and supply its token as `HERMES_DIARY_BOT_TOKEN`. The recipient is a Telegram chat/channel ID, supplied with `--channel`; a bot posting to a channel needs the appropriate channel permissions.

```bash
read -r -s -p "Diary bot token: " HERMES_DIARY_BOT_TOKEN; printf '\n'
export HERMES_DIARY_BOT_TOKEN
# Replace the example channel ID with your real destination.
python3 "$DIARY_SKILL/scripts/setup_diary.py" configure --reconfigure \
  --delivery telegram --channel=-1001234567890 --schedule --non-interactive
unset HERMES_DIARY_BOT_TOKEN
```

The adapter uses plain text and records Telegram message IDs. It splits at a conservative 3,900 UTF-16 units. Existing persisted `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHANNEL_ID` fields remain supported; similarly named generic environment variables are not borrowed from the agent gateway.

## Discord

Create an incoming webhook for the intended channel and use its generated `https://discord.com/api/webhooks/...` URL. For an existing thread, include its `thread_id` query parameter; creating new forum threads is not supported by this adapter.

Requests use `wait=true` and require a returned message ID. Content is split at 1,900 UTF-16 units, below Discord's 2,000-character limit. Automatic mentions are disabled and link embeds suppressed. A webhook can be moved to another channel in Discord without changing its URL; verify the platform-side configuration when changing where entries should go.

Reference: [Discord Execute Webhook](https://docs.discord.com/developers/resources/webhook#execute-webhook).

## Slack

Create a Slack app with Incoming Webhooks enabled, install it into the workspace, and choose the destination conversation. Use its generated `https://hooks.slack.com/services/...` URL (`hooks.slack-gov.com` is also accepted). The conversation is bound to the webhook; this adapter does not override it or post thread replies.

Messages use a plain-text Block Kit section and a fallback text field; automatic mentions/link parsing are disabled. Text is split at 2,900 UTF-16 units to stay below the section text limit. Only an `ok` response confirms acceptance. Incoming webhooks do not return a message ID, so the journal records an acceptance marker.

Reference: [Slack incoming webhooks](https://docs.slack.dev/messaging/sending-messages-using-incoming-webhooks/).

## Generic HTTPS webhook

Select `--delivery webhook` and set `HERMES_DIARY_WEBHOOK_URL`. If your receiver requires bearer authentication, securely set `HERMES_DIARY_WEBHOOK_TOKEN` as well before `configure --reconfigure`:

```bash
read -r -s -p "Optional receiver bearer token: " HERMES_DIARY_WEBHOOK_TOKEN; printf '\n'
export HERMES_DIARY_WEBHOOK_TOKEN
```

Unset secret environment variables after saving the configuration. There is no arbitrary-header template or provider-specific signing algorithm in this version; a receiver needing another protocol needs an adapter.

Each part is a JSON POST with `Content-Type: application/json; charset=utf-8`:

```json
{
  "schema_version": 1,
  "event": "diary.daily",
  "id": "opaque-delivery-id:1",
  "date": "2026-09-19",
  "timezone": "Europe/London",
  "language": "en",
  "part": 1,
  "parts": 2,
  "text": "Saturday · 2026-09-19 · London\n\n[12:30] — Had lunch with Ana."
}
```

`Idempotency-Key` equals `id`; `Authorization: Bearer ...` is added only when a bearer token is configured. Parts are one-based and contain up to 3,900 UTF-16 units. Retries keep the same ID, text and metadata. An explicit `resend` starts a new delivery ID.

The receiver should durably store/deduplicate the ID before returning a 2xx response. Any 2xx confirms HTTP acceptance; the response body is not interpreted as a downstream delivery receipt. Do not return 2xx merely to report a failed downstream action unless you intend the diary to regard the request as accepted.

## Failures and limits

Explicit 4xx responses, except ambiguous HTTP 408, allow a delayed retry. Numeric or HTTP-date `Retry-After` headers and supported JSON retry delays are respected by the webhook adapters; the minimum retry interval is 60 seconds. Redirects, 5xx responses, timeouts and malformed platform acknowledgements pause for manual verification. Error messages omit raw URLs, credentials and remote response bodies.

`check` verifies configuration shape and presence, not endpoint ownership, permissions, availability or successful delivery. Only send a real test when the user requests it. See [commands.md](commands.md) for uncertain-outcome recovery.

# Commands and delivery recovery

Use `python3 "${HERMES_SKILL_DIR}/scripts/diary_cli.py"` followed by a command. In a user's terminal, replace the Hermes placeholder with the actual installed skill directory.

| Command | Behavior |
| --- | --- |
| `context` | Actual configured-timezone clock, city, non-secret settings, preferences and setup status |
| `status` | Raw entry count, saved schedule, selected mode and unfinished deliveries |
| `today` | Read the raw diary |
| `city [value]` | Read or explicitly set the current city |
| `record 'text'` | Append one entry; options: `--at HH:MM`, `--date YYYY-MM-DD`, `--city value` |
| `compose` | Generate `<data>/composed/YYYY-MM-DD.md`; never deliver |
| `send` | Deliver an existing composition or resume a frozen pending snapshot |
| `run` | Compose as needed and deliver; local mode only saves files |
| `resend` | Start a new delivery of the current composed file, archiving the previous journal; can create duplicates |
| `resolve --delivered` / `resolve --retry` | Resolve one uncertain part after checking the destination |
| `logs` | Last 100 lines of the scheduler log |

`record`, `today`, `compose`, `send`, `run`, `resend` and `resolve` support `--date YYYY-MM-DD`. Date defaults to the configured timezone's current date. Use the `context` date and time together when acting on a new note. Command diagnostics are in English; headings support `en` and `zh`.

## Snapshots and historical entries

On the first external send, the full composed text is split to the platform limit and saved in a delivery journal. Subsequent retries use that content even if the Markdown file changes. For generic webhooks, event IDs and metadata also remain stable across retries. Successful parts are not resent on normal retries.

`resend` intentionally starts from the first part with new event IDs. To include edits or late notes, run `compose --date ...` before `resend --date ...`. `resend` alone sends the existing composed file. Changing destination also requires explicit `resend` for dates already tracked.

The scheduler catches unfinished entries from today after the selected time and from yesterday. For older days use `run --date`. If a historical composed file already exists, `run` can reuse it. If a historical heading must be built from raw notes, current weather/city is not presented as historical fact.

## Unknown outcome

A request may have reached the destination before timing out. Server errors, interrupted writes/processes, and unexpected response bodies can also leave an uncertain part. Stop and ask the user to check the destination; do not assume receipt or automatically retry.

```bash
# Only after confirming that the uncertain part arrived:
python3 "${HERMES_SKILL_DIR}/scripts/diary_cli.py" resolve --date 2026-09-18 --delivered
# Or, after deciding to retry the part:
python3 "${HERMES_SKILL_DIR}/scripts/diary_cli.py" resolve --date 2026-09-18 --retry
# Continue the remaining parts:
python3 "${HERMES_SKILL_DIR}/scripts/diary_cli.py" send --date 2026-09-18
```

`resolve` updates only the journal; it does not immediately send. An enabled scheduler may continue on its next eligible tick. Keep the original destination configured while resolving. For a generic receiver, inspect its logs/event ID and downstream service before confirming.

Exit code 75 means the shared file lock is busy. Corrupt journals fail closed; do not delete them just to trigger another send. No client-side workflow guarantees exactly-once delivery across network or machine failures.

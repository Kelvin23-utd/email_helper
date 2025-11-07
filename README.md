# Email Summary Bot

Local-first automation for summarizing unread UTD Outlook messages through Apple Mail, Gemini, and Discord. The repo scaffolds the macOS components needed to run an hourly digest with no cloud infrastructure.

## Layout

```
email_summary_bot/
├── .env.example          # copy to .env and fill with secrets
├── export_unread.scpt    # AppleScript exporter (unread inbox mail only)
├── run_once.py           # orchestrator (Gemini + Discord)
├── launchd/
│   └── edu.utd.emailbot.plist.example
├── logs/                 # runtime logs land here
└── tmp/                  # transient TSV exports
```

## Setup

1. Ensure your UTD Exchange inbox is synced to Apple Mail and messages are cached locally.
2. Install/confirm Python 3.9+ is available at `/usr/bin/python3` (macOS Ventura or newer ships with it).
3. Copy `.env.example` to `.env` and populate:

```
GEMINI_API_KEY=sk-...
DISCORD_WEBHOOK=https://discord.com/api/webhooks/.../...
LOOKBACK_MINUTES=60
MAX_EMAILS=15
GEMINI_MODEL=gemini-1.5-flash
```

4. On the first run macOS will request Automation consent for Terminal/Python to control Mail; approve it under **System Settings > Privacy & Security > Automation** if prompted.

## Manual test run

```
cd email_summary_bot
python3 run_once.py --dry-run
```

Dry-run skips Gemini/Discord and just logs which emails would be summarized. Drop the `--dry-run` flag to perform the live flow.

## Scheduling options

### launchd (recommended)

1. Copy `launchd/edu.utd.emailbot.plist.example` to `~/Library/LaunchAgents/edu.utd.emailbot.plist`.
2. Replace every `REPLACE_ME` with your username or the absolute path to `email_summary_bot`.
3. Load it with:

```
launchctl load ~/Library/LaunchAgents/edu.utd.emailbot.plist
```

By default it fires at the top of every hour. To run twice per hour, duplicate the `StartCalendarInterval` dict and set another `Minute` (for example 30).

### cron (simpler alternative)

Add the following line via `crontab -e` for an hourly run:

```
0 * * * * /usr/bin/python3 /Users/you/email_summary_bot/run_once.py --env /Users/you/email_summary_bot/.env >> /Users/you/email_summary_bot/logs/cron.log 2>&1
```

Adjust the schedule (e.g., `*/30 * * * *`) for higher frequency.

## Logs and troubleshooting

* `email_summary_bot/logs/run_YYYYMMDD.log` stores each Python run.
* Launchd/cron stdout + stderr can be directed to `logs/launchd.log` or `logs/cron.log`.
* If the AppleScript exporter fails, re-open Apple Mail to ensure the inbox is ready and re-run manually to re-trigger consent prompts.

## Future enhancements

* Detect and skip marketing/newsletter senders before hitting Gemini.
* Group digests by sender or topic clusters.
* Swap the Discord webhook for Slack, Teams, Telegram, or Notion integrations.
# email_helper

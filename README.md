# Apple SG Refurb Checker

Monitors the [Apple Singapore Refurbished Store](https://www.apple.com/sg/shop/refurbished/mac) for specific Mac listings and sends Telegram notifications when new ones appear.

## Monitored Products

- **Mac mini** — all listings
- **MacBook Pro 14"** — M4 Pro with 64GB+ RAM
- **Mac Studio** — all listings

## How It Works

1. Scrapes the Apple refurb page and extracts product data from the embedded `REFURB_GRID_BOOTSTRAP` JSON
2. Filters listings against the monitored product criteria
3. Compares with previously seen part numbers (`seen.json`)
4. If new listings are found, sends a Telegram message with the **full list** of matching products, with new ones marked 🆕

Only sends a notification when there's at least one new listing.

## Setup

### Requirements

- Python 3.10+
- `requests` library (`pip install requests`)

### Configuration

Create a `.env` file:

```
TELEGRAM_BOT_TOKEN=your-bot-token
TELEGRAM_CHAT_ID=your-chat-id
```

### Run manually

```bash
python3 checker.py
```

### Run as a systemd timer (every 10 minutes)

```ini
# ~/.config/systemd/user/apple-checker.service
[Unit]
Description=Apple SG Refurbished Mac Checker
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/path/to/apple-checker
ExecStart=/usr/bin/python3 checker.py
EnvironmentFile=/path/to/apple-checker/.env
```

```ini
# ~/.config/systemd/user/apple-checker.timer
[Unit]
Description=Run Apple Refurb Checker every 10 minutes

[Timer]
OnBootSec=1min
OnUnitActiveSec=10min
AccuracySec=1min

[Install]
WantedBy=timers.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now apple-checker.timer
loginctl enable-linger $USER  # keep running after logout
```

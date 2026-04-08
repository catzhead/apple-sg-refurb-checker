# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Single-script Python tool that monitors the Apple Singapore refurbished Mac store and sends Telegram notifications when new listings appear. It scrapes the refurb page, extracts product data from the embedded `REFURB_GRID_BOOTSTRAP` JSON, filters by product criteria, and compares against previously seen part numbers in `seen.json`.

## Running

```bash
python3 checker.py
```

No build step. Single dependency: `requests` (`pip install requests`). Python 3.10+ required.

Typically runs on a 10-minute systemd timer (see README for timer setup).

## Configuration

Environment variables loaded from `.env` in the project root:
- `TELEGRAM_BOT_TOKEN` — Telegram bot API token
- `TELEGRAM_CHAT_ID` — Target chat ID for notifications

## Architecture

Single file `checker.py` with this flow:
1. `load_env()` → reads `.env` into `os.environ`
2. `load_seen()` → reads `seen.json` (set of part numbers already notified about)
3. `fetch_listings()` → HTTP GET to Apple SG refurb page, regex-extracts the `REFURB_GRID_BOOTSTRAP` JSON, filters tiles via `matches_filters()`
4. Compares current part numbers against seen set; if new ones exist, formats and sends via `send_telegram()`
5. `save_seen()` → persists union of old + current part numbers

## Product filters (in `matches_filters()`)

- **Mac mini** — all listings
- **Mac Studio** — all listings
- **MacBook Pro 14"** — only M4 Pro with 64GB+ RAM (parsed from `filters.dimensions.tsMemorySize`)

To add/change monitored products, edit `matches_filters()` and update the module docstring.

## State

`seen.json` — JSON array of previously seen part numbers. Accumulates over time so removed items can re-trigger alerts if they reappear. This file is gitignored.

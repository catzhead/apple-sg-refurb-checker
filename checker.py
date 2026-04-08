#!/usr/bin/env python3
"""Apple Store SG Refurbished Mac Checker.

Scrapes the Apple Singapore refurbished store for specific Mac listings,
compares against previously seen listings, and sends new ones via Telegram.

Monitored products:
- Mac mini (all)
- MacBook Pro 14" M4 Pro with 64GB+ RAM
- Mac Studio (all)
"""

import json
import os
import re
import sys
import requests
from pathlib import Path

DIR = Path(__file__).parent
STATE_FILE = DIR / "seen.json"
ENV_FILE = DIR / ".env"

URL = "https://www.apple.com/sg/shop/refurbished/mac"
APPLE_BASE = "https://www.apple.com"

# Memory sizes in GB, parsed from filter values like "64gb"
MIN_MBP_RAM_GB = 64

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}


def load_env():
    """Load .env file into environment."""
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())


def load_seen() -> set:
    """Load previously seen part numbers."""
    if STATE_FILE.exists():
        return set(json.loads(STATE_FILE.read_text()))
    return set()


def save_seen(part_numbers: set):
    """Persist seen part numbers."""
    STATE_FILE.write_text(json.dumps(sorted(part_numbers), indent=2))


def parse_ram_gb(mem_str: str) -> int:
    """Parse memory string like '64gb' into integer GB."""
    m = re.match(r"(\d+)", mem_str)
    return int(m.group(1)) if m else 0


def matches_filters(title: str, filters: dict) -> bool:
    """Check if a listing matches our monitored products."""
    t = title.lower()

    # Mac mini — all
    if "mac mini" in t:
        return True

    # Mac Studio — all
    if "mac studio" in t:
        return True

    # MacBook Pro 14" M4 Pro with 64GB+ RAM
    if "macbook pro" in t and "14-inch" in t and "m4 pro" in t:
        dims = filters.get("dimensions", {})
        ram = parse_ram_gb(dims.get("tsMemorySize", "0"))
        if ram >= MIN_MBP_RAM_GB:
            return True

    return False


def fetch_listings() -> list[dict]:
    """Fetch matching Mac listings from Apple SG refurb store."""
    resp = requests.get(URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    # Extract the REFURB_GRID_BOOTSTRAP JSON from the page
    match = re.search(
        r"window\.REFURB_GRID_BOOTSTRAP\s*=\s*(\{.+?\});\s*</script>",
        resp.text,
        re.DOTALL,
    )
    if not match:
        return []

    data = json.loads(match.group(1))
    tiles = data.get("tiles", [])

    listings = []
    for tile in tiles:
        title = tile.get("title", "")
        filters = tile.get("filters", {})

        if not matches_filters(title, filters):
            continue

        price = tile.get("price", {})
        current = price.get("currentPrice", {})
        previous = price.get("previousPrice", {})
        dims = filters.get("dimensions", {})
        listings.append({
            "part": tile.get("partNumber", ""),
            "title": title,
            "price": current.get("amount", "N/A"),
            "price_raw": float(current.get("raw_amount", 0)),
            "previous_price": previous.get("amount", ""),
            "url": APPLE_BASE + tile.get("productDetailsUrl", ""),
            "commit": tile.get("omnitureModel", {}).get(
                "customerCommitString", ""
            ),
            "memory": dims.get("tsMemorySize", "").upper(),
            "storage": dims.get("dimensionCapacity", "").upper(),
        })

    return listings


def send_telegram(text: str):
    """Send a message via Telegram Bot API."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("ERROR: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set", file=sys.stderr)
        sys.exit(1)

    # Telegram has a 4096 char limit per message
    MAX_LEN = 4000
    chunks = []
    if len(text) <= MAX_LEN:
        chunks = [text]
    else:
        # Split on double newlines (between listings)
        parts = text.split("\n\n")
        chunk = ""
        for part in parts:
            if chunk and len(chunk) + len(part) + 2 > MAX_LEN:
                chunks.append(chunk)
                chunk = part
            else:
                chunk = chunk + "\n\n" + part if chunk else part
        if chunk:
            chunks.append(chunk)

    for chunk in chunks:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": chunk, "parse_mode": "HTML"},
            timeout=15,
        )
        if not resp.ok:
            print(f"Telegram API error: {resp.text}", file=sys.stderr)
        resp.raise_for_status()


def format_listing(item: dict, is_new: bool) -> str:
    """Format a single listing for Telegram."""
    tag = "🆕 " if is_new else ""
    saving = ""
    if item["previous_price"]:
        saving = f"  (was {item['previous_price']})"
    specs = ""
    if item.get("memory") or item.get("storage"):
        parts = []
        if item.get("memory"):
            parts.append(f"{item['memory']} RAM")
        if item.get("storage"):
            parts.append(f"{item['storage']} Storage")
        specs = " · ".join(parts) + "\n"
    return (
        f"{tag}<b>{item['title']}</b>\n"
        f"{specs}"
        f"Price: {item['price']}{saving}\n"
        f"Delivery: {item['commit']}\n"
        f"<a href=\"{item['url']}\">View on Apple Store</a>"
    )


def main():
    load_env()
    seen = load_seen()

    try:
        listings = fetch_listings()
    except Exception as e:
        print(f"ERROR fetching listings: {e}", file=sys.stderr)
        sys.exit(1)

    current_parts = {item["part"] for item in listings}

    if not listings:
        print("No matching listings found.")
        return

    new_parts = {item["part"] for item in listings if item["part"] not in seen}

    if new_parts:
        # New items detected — send full list with new ones marked
        listings.sort(key=lambda x: x["price_raw"])

        new_count = len(new_parts)
        total = len(listings)
        header = (
            f"🍎 {new_count} new refurb Mac listing(s) on Apple SG!\n"
            f"Showing all {total} matching listing(s):\n\n"
        )
        body = "\n\n".join(
            format_listing(item, item["part"] in new_parts)
            for item in listings
        )
        send_telegram(header + body)
        print(f"Sent notification: {new_count} new, {total} total.")
    else:
        print("No new listings.")

    # Update seen: keep current + previously seen (so removed items can re-alert)
    save_seen(seen | current_parts)


if __name__ == "__main__":
    main()

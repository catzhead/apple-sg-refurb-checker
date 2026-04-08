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
APPLE_SHOP = "https://www.apple.com/sg/shop/buy-mac"

# Memory sizes in GB, parsed from filter values like "64gb"
MIN_MBP_RAM_GB = 64

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

# Map older chip tiers to their current-gen equivalents for new price comparison.
# Format: (chip, cpu_cores, gpu_cores) -> (chip, cpu_cores, gpu_cores, min_memory_gb)
# min_memory_gb: current gen may have higher base memory than the old chip.
CHIP_EQUIVALENTS = {
    # Mac mini (M1, M2, M2 Pro existed; no M1 Pro Mac mini)
    ("macmini", "m1"): ("m4", "10", "10", 16),
    ("macmini", "m2"): ("m4", "10", "10", 16),
    ("macmini", "m2 pro"): ("m4 pro", "12", "16", 24),
    # Mac Studio
    ("macstudio", "m1 max"): ("m4 max", "14", "32", 36),
    ("macstudio", "m1 ultra"): ("m3 ultra", "28", "60", 96),
    ("macstudio", "m2 max"): ("m4 max", "14", "32", 36),
    ("macstudio", "m2 ultra"): ("m3 ultra", "28", "60", 96),
    # MacBook Pro
    ("macbookpro", "m1"): ("m5", "10", "10", 16),
    ("macbookpro", "m1 pro"): ("m5 pro", "15", "16", 24),
    ("macbookpro", "m1 max"): ("m5 max", "18", "32", 36),
    ("macbookpro", "m2"): ("m5", "10", "10", 16),
    ("macbookpro", "m2 pro"): ("m5 pro", "15", "16", 24),
    ("macbookpro", "m2 max"): ("m5 max", "18", "32", 36),
    ("macbookpro", "m3"): ("m5", "10", "10", 16),
    ("macbookpro", "m3 pro"): ("m5 pro", "15", "16", 24),
    ("macbookpro", "m3 max"): ("m5 max", "18", "32", 36),
    ("macbookpro", "m4"): ("m5", "10", "10", 16),
    ("macbookpro", "m4 pro"): ("m5 pro", "15", "16", 24),
    ("macbookpro", "m4 max"): ("m5 max", "18", "32", 36),
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


def _parse_chip_info(title: str) -> tuple[str, str, str]:
    """Extract chip name and core counts from a refurb title.

    Returns (chip, cpu_cores, gpu_cores), e.g. ("m4 pro", "12", "16").
    """
    t = title.lower()
    # Match patterns like "M4 Pro Chip with 12-Core CPU and 16-Core GPU"
    # or "M5 chip with 10‑Core CPU and 10‑Core GPU"
    m = re.search(
        r"(m\d+(?:\s+(?:pro|max|ultra))?)\s+chip\s+with\s+(\d+)[‑-]core\s+cpu\s+and\s+(\d+)[‑-]core\s+gpu",
        t,
    )
    if m:
        return m.group(1), m.group(2), m.group(3)
    return "", "", ""


def _format_storage(storage_upper: str) -> str:
    """Convert storage like '512GB' or '2TB' to URL format like '512gb' or '2tb'."""
    return storage_upper.lower()


def _build_new_product_url(item: dict) -> str | None:
    """Build the Apple SG store URL for the current-gen equivalent of a refurb listing."""
    title = item["title"]
    t = title.lower()
    memory_gb = parse_ram_gb(item.get("memory", "0"))
    storage = _format_storage(item.get("storage", ""))

    chip, cpu, gpu = _parse_chip_info(title)
    if not chip:
        return None

    # Determine product family
    if "mac mini" in t:
        family = "macmini"
        product = "mac-mini"
    elif "mac studio" in t:
        family = "macstudio"
        product = "mac-studio"
    elif "macbook pro" in t:
        family = "macbookpro"
        product = "macbook-pro"
    else:
        return None

    # Map to current-gen equivalent if needed
    equiv = CHIP_EQUIVALENTS.get((family, chip))
    if equiv:
        chip, cpu, gpu, min_mem = equiv
        if memory_gb < min_mem:
            memory_gb = min_mem

    chip_slug = chip.replace(" ", "-")
    mem_str = f"{memory_gb}gb"

    if family == "macmini":
        return (
            f"{APPLE_SHOP}/{product}/"
            f"{chip_slug}-chip-{cpu}-core-cpu-{gpu}-core-gpu-"
            f"{mem_str}-memory-{storage}-storage"
        )
    elif family == "macstudio":
        return (
            f"{APPLE_SHOP}/{product}/"
            f"apple-{chip_slug}-chip-{cpu}-core-cpu-{gpu}-core-gpu-"
            f"{mem_str}-memory-{storage}-storage"
        )
    elif family == "macbookpro":
        # MacBook Pro URLs include screen size, color, and display type
        screen = "14-inch" if "14-inch" in t or "14‑inch" in t else "16-inch"
        color = "space-black" if "space black" in t or "spaceblack" in t else "silver"
        display = "nano-texture" if "nano-texture" in t or "nano‑texture" in t else "standard"
        return (
            f"{APPLE_SHOP}/{product}/"
            f"{screen}-{color}-{display}-display-apple-"
            f"{chip_slug}-chip-{cpu}-core-cpu-{gpu}-core-gpu-"
            f"{mem_str}-memory-{storage}-storage"
        )

    return None


def fetch_new_price(item: dict, cache: dict) -> float | None:
    """Fetch the new price for the current-gen equivalent from the Apple SG store.

    Uses a cache dict keyed by URL to avoid duplicate requests.
    """
    url = _build_new_product_url(item)
    if not url:
        return None

    if url in cache:
        return cache[url]

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            cache[url] = None
            return None
        # Price appears in JSON-LD or as "price":XXXX in the page
        m = re.search(r'"price":([\d.]+)', resp.text)
        if m:
            price = float(m.group(1))
            cache[url] = price
            return price
    except Exception:
        pass

    cache[url] = None
    return None


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
    new_price_line = ""
    if item.get("new_price"):
        new_price = item["new_price"]
        discount = new_price - item["price_raw"]
        pct = discount / new_price * 100
        new_price_line = f"New: S${new_price:,.2f} (save S${discount:,.0f} / {pct:.0f}%)\n"
    return (
        f"{tag}<b>{item['title']}</b>\n"
        f"{specs}"
        f"Price: {item['price']}{saving}\n"
        f"{new_price_line}"
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
        # Fetch new-equivalent prices for all listings
        price_cache = {}
        for item in listings:
            new_price = fetch_new_price(item, price_cache)
            if new_price:
                item["new_price"] = new_price

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

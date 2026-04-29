import html
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import feedparser
import requests
from dateutil import parser as dateparser

NOTION_VERSION = "2022-06-28"

TIMEZONE_NAME = os.getenv("TIMEZONE", "Asia/Tokyo")
LOOKBACK_HOURS = int(os.getenv("LOOKBACK_HOURS", "30"))
MAX_PER_TOPIC = int(os.getenv("MAX_PER_TOPIC", "6"))
MAX_PER_SOURCE_PER_TOPIC = int(os.getenv("MAX_PER_SOURCE_PER_TOPIC", "3"))

TOPICS = ["Physics", "Astronomy", "Mathematics", "AI"]

# You can add/remove RSS feeds here.
# topic = the report section where this feed will appear.
FEEDS = [
    # Physics
    {"topic": "Physics", "source": "Quanta Physics", "url": "https://www.quantamagazine.org/physics/feed/"},
    {"topic": "Physics", "source": "arXiv Physics", "url": "https://rss.arxiv.org/rss/physics"},
    {"topic": "Physics", "source": "Phys.org Physics", "url": "https://phys.org/rss-feed/physics-news/"},
    {"topic": "Physics", "source": "ScienceDaily Physics", "url": "https://www.sciencedaily.com/rss/matter_energy/physics.xml"},

    # Astronomy
    {"topic": "Astronomy", "source": "arXiv Astrophysics", "url": "https://rss.arxiv.org/rss/astro-ph"},
    {"topic": "Astronomy", "source": "NASA", "url": "https://www.nasa.gov/feed/"},
    {"topic": "Astronomy", "source": "Phys.org Space", "url": "https://phys.org/rss-feed/space-news/"},
    {"topic": "Astronomy", "source": "ScienceDaily Astronomy", "url": "https://www.sciencedaily.com/rss/space_time/astronomy.xml"},

    # Mathematics
    {"topic": "Mathematics", "source": "Quanta Mathematics", "url": "https://www.quantamagazine.org/mathematics/feed/"},
    {"topic": "Mathematics", "source": "arXiv Mathematics", "url": "https://rss.arxiv.org/rss/math"},
    {"topic": "Mathematics", "source": "Phys.org Mathematics", "url": "https://phys.org/rss-feed/science-news/mathematics/"},
    {"topic": "Mathematics", "source": "ScienceDaily Mathematics", "url": "https://www.sciencedaily.com/rss/computers_math/mathematics.xml"},

    # AI / computer science
    {"topic": "AI", "source": "Quanta Computer Science", "url": "https://www.quantamagazine.org/computer-science/feed/"},
    {"topic": "AI", "source": "arXiv AI/ML", "url": "https://rss.arxiv.org/rss/cs.AI+cs.LG+stat.ML"},
    {"topic": "AI", "source": "TechXplore AI", "url": "https://techxplore.com/rss-feed/machine-learning-ai-news/"},
    {"topic": "AI", "source": "ScienceDaily AI", "url": "https://www.sciencedaily.com/rss/computers_math/artificial_intelligence.xml"},
]


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def normalize_notion_page_id(value: str) -> str:
    """Accept either a Notion page ID or a full Notion page URL."""
    value = value.strip()

    uuid_match = re.search(
        r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})",
        value,
    )
    if uuid_match:
        return uuid_match.group(1)

    plain_match = re.search(r"([0-9a-fA-F]{32})(?:[?#/]|$)", value)
    if plain_match:
        raw = plain_match.group(1)
        return f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"

    # Last resort: return as-is. Notion will return an error if it is invalid.
    return value


def strip_html(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def truncate(text: str, limit: int) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def parse_entry_date(entry) -> datetime:
    for key in ("published", "updated", "created"):
        value = entry.get(key)
        if value:
            try:
                dt = dateparser.parse(value)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except Exception:
                pass

    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = entry.get(key)
        if value:
            return datetime(*value[:6], tzinfo=timezone.utc)

    return datetime.now(timezone.utc)


def fetch_feed(feed_info: dict, cutoff: datetime):
    items = []
    errors = []

    url = feed_info["url"]
    try:
        response = requests.get(
            url,
            timeout=25,
            headers={"User-Agent": "personal-notion-science-news-bot/1.0"},
        )
        response.raise_for_status()
        parsed = feedparser.parse(response.content)
    except Exception as exc:
        errors.append(f"{feed_info['source']}: {exc}")
        return items, errors

    if getattr(parsed, "bozo", False):
        # Keep going, because many feeds still parse successfully even with a bozo flag.
        errors.append(f"{feed_info['source']}: feed parsed with warning: {parsed.bozo_exception}")

    for entry in parsed.entries:
        title = strip_html(entry.get("title", "Untitled"))
        link = entry.get("link", "")
        summary = strip_html(entry.get("summary", "") or entry.get("description", ""))
        published_utc = parse_entry_date(entry)

        if published_utc < cutoff:
            continue

        items.append(
            {
                "topic": feed_info["topic"],
                "source": feed_info["source"],
                "title": title,
                "link": link,
                "summary": summary,
                "published_utc": published_utc,
            }
        )

    return items, errors


def choose_items(items_by_topic: dict) -> dict:
    selected = {}

    for topic, items in items_by_topic.items():
        sorted_items = sorted(items, key=lambda x: x["published_utc"], reverse=True)
        chosen = []
        source_counts = defaultdict(int)

        for item in sorted_items:
            if source_counts[item["source"]] >= MAX_PER_SOURCE_PER_TOPIC:
                continue
            chosen.append(item)
            source_counts[item["source"]] += 1
            if len(chosen) >= MAX_PER_TOPIC:
                break

        selected[topic] = chosen

    return selected


def rt(text: str, link: str | None = None) -> dict:
    text_obj = {"content": truncate(text, 1900)}
    if link:
        text_obj["link"] = {"url": link}
    return {"type": "text", "text": text_obj}


def paragraph(text: str) -> dict:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [rt(text)] if text else []},
    }


def heading(text: str) -> dict:
    return {
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": [rt(text)]},
    }


def bullet(title: str, link: str, rest: str = "") -> dict:
    rich_text = [rt(truncate(title, 500), link if link else None)]
    if rest:
        rich_text.append(rt(truncate(rest, 1400)))
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": rich_text},
    }


def divider() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def build_blocks(selected: dict, errors: list, now_local: datetime) -> list:
    blocks = [
        paragraph(
            f"Generated automatically on {now_local.strftime('%Y-%m-%d %H:%M')} "
            f"{TIMEZONE_NAME}. Lookback window: {LOOKBACK_HOURS} hours."
        ),
        paragraph(
            "Note: arXiv items are preprints, so treat them as early research leads rather than confirmed results."
        ),
        divider(),
    ]

    for topic in TOPICS:
        blocks.append(heading(topic))
        items = selected.get(topic, [])
        if not items:
            blocks.append(paragraph("No fresh items found in the current lookback window."))
            continue

        for item in items:
            local_date = item["published_utc"].astimezone(now_local.tzinfo).strftime("%Y-%m-%d")
            rest = f" — {item['source']} — {local_date}"
            blocks.append(bullet(item["title"], item["link"], rest))
            if item["summary"]:
                blocks.append(paragraph(truncate(item["summary"], 450)))

    if errors:
        blocks.extend([divider(), heading("Feed warnings")])
        for error in errors[:10]:
            blocks.append(bullet(truncate(error, 700), "", ""))

    return blocks[:95]  # Notion allows up to 100 children in a single create-page request.


def create_notion_page(title: str, blocks: list) -> str:
    notion_token = required_env("NOTION_TOKEN")
    parent_page = normalize_notion_page_id(required_env("NOTION_PARENT_PAGE_ID"))

    payload = {
        "parent": {"page_id": parent_page},
        "properties": {
            "title": [{"type": "text", "text": {"content": title}}],
        },
        "children": blocks,
    }

    response = requests.post(
        "https://api.notion.com/v1/pages",
        headers={
            "Authorization": f"Bearer {notion_token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=25,
    )

    if response.status_code >= 400:
        raise RuntimeError(f"Notion API error {response.status_code}: {response.text}")

    return response.json().get("url", "(URL not returned)")


def main():
    local_tz = ZoneInfo(TIMEZONE_NAME)
    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone(local_tz)
    cutoff = now_utc - timedelta(hours=LOOKBACK_HOURS)

    items_by_topic = defaultdict(list)
    errors = []
    seen = set()

    for feed_info in FEEDS:
        items, feed_errors = fetch_feed(feed_info, cutoff)
        errors.extend(feed_errors)

        for item in items:
            key = (item["link"] or item["title"]).split("?")[0].strip().lower()
            if key in seen:
                continue
            seen.add(key)
            items_by_topic[item["topic"]].append(item)

    selected = choose_items(items_by_topic)
    title = f"Science News Digest — {now_local.strftime('%Y-%m-%d')}"
    blocks = build_blocks(selected, errors, now_local)
    page_url = create_notion_page(title, blocks)
    print(f"Created Notion page: {page_url}")


if __name__ == "__main__":
    main()

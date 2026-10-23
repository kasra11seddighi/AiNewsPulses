
"""Automatic news discovery through Google News RSS."""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from collector import (
    CollectionResult,
    SourceResult,
    _entry_link,
    parse_feed,
)
from deduplicator import normalize_url
from logger import get_logger
from models import Source
from netutils import safe_get

log = get_logger("discovery")

# Google News RSS search queries; when:1d targets recent coverage.
TOPIC_QUERIES = [
    (
        "AI",
        '("artificial intelligence" OR "generative AI" OR "AI model") when:1d',
        "ai",
    ),
    (
        "Data Science",
        '("data science" OR "machine learning" OR "deep learning") when:1d',
        "data_science",
    ),
    (
        "Python",
        '(Python OR "Python library" OR "Python programming") when:1d',
        "programming",
    ),
    (
        "Cybersecurity",
        '("cybersecurity" OR "security vulnerability" OR "zero-day") when:1d',
        "tech",
    ),
]

RSS_BASE = "https://news.google.com/rss/search"


def _feed_url(query: str) -> str:
    """Build a Google News RSS search URL."""
    params = {
        "q": query,
        "hl": "en-US",
        "gl": "US",
        "ceid": "US:en",
    }
    return f"{RSS_BASE}?{urlencode(params)}"


def _publisher_names(content: bytes) -> dict[str, str]:
    """Map Google News article links to publisher names when available."""
    soup = BeautifulSoup(content, "xml")
    names = {}

    for entry in soup.find_all(["item", "entry"]):
        link = _entry_link(entry)
        source = entry.find("source")

        if link and source:
            name = source.get_text(" ", strip=True)
            if name:
                names[normalize_url(link)] = name

    return names


def discover_news(
    fetcher=safe_get,
    now: datetime | None = None,
    max_items: int = 15,
) -> CollectionResult:
    """Collect recent articles from four topic-based RSS searches."""
    now = now or datetime.now(timezone.utc)
    result = CollectionResult()
    seen_urls: set[str] = set()

    for topic, query, category in TOPIC_QUERIES:
        source = Source(
            name=f"Google News — {topic}",
            url=_feed_url(query),
            kind="media",
            category=category,
            trust=0.70,
            enabled=True,
        )

        try:
            page = fetcher(
                source.url,
                timeout=20,
                max_bytes=3_000_000,
            )
            articles = parse_feed(
                page.content,
                source,
                now=now,
                max_items=max_items,
            )
            publisher_names = _publisher_names(page.content)

            added = 0
            for article in articles:
                article.source_name = publisher_names.get(
                    normalize_url(article.url),
                    source.name,
                )

                if article.canonical_url in seen_urls:
                    continue

                seen_urls.add(article.canonical_url)
                result.articles.append(article)
                added += 1

            result.results.append(
                SourceResult(source.name, True, added)
            )
            log.info(
                "discovery succeeded: topic=%s articles=%d",
                topic,
                added,
            )

        except Exception as exc:
            # A failed search must not stop the other topics.
            error = type(exc).__name__
            result.results.append(
                SourceResult(source.name, False, 0, error)
            )
            log.warning(
                "discovery failed: topic=%s error=%s",
                topic,
                error,
            )

    return result

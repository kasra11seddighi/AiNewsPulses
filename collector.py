"""دریافت RSS/Atom و تبدیل به Article. خرابی یک منبع بقیه را متوقف نمی‌کند."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable, List, Optional, Sequence

from bs4 import BeautifulSoup

from deduplicator import normalize_url
from logger import get_logger
from models import Article, Source
from netutils import FetchError, safe_get

log = get_logger("collector")
MAX_SUMMARY_CHARS = 2000


class CollectorError(Exception):
    pass


@dataclass
class SourceResult:
    source: str
    ok: bool
    count: int = 0
    error: str = ""


@dataclass
class CollectionResult:
    articles: List[Article] = field(default_factory=list)
    results: List[SourceResult] = field(default_factory=list)


def _clean_html(raw: str) -> str:
    text = BeautifulSoup(raw or "", "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def parse_date(value: str) -> Optional[datetime]:
    value = (value or "").strip()
    if not value:
        return None
    dt = None
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _first_text(entry, names: Sequence[str]) -> str:
    for name in names:
        tag = entry.find(name)
        if tag is not None and tag.get_text(strip=True):
            return tag.get_text(strip=True) if name in ("title", "pubDate", "published", "updated", "date", "dc:date") \
                else tag.get_text(" ", strip=True)
    return ""


def _entry_link(entry) -> str:
    links = entry.find_all("link")
    for link in links:
        href = (link.get("href") or "").strip()
        rel = link.get("rel") or "alternate"
        rel = " ".join(rel) if isinstance(rel, list) else rel
        if href and rel == "alternate":
            return href
    for link in links:
        href = (link.get("href") or "").strip()
        if href:
            return href
        text = link.get_text(strip=True)
        if text:
            return text
    guid = entry.find("guid")
    if guid is not None and guid.get_text(strip=True).startswith("http"):
        return guid.get_text(strip=True)
    return ""


def _entry_image(entry) -> Optional[str]:
    for name in ("media:content", "media:thumbnail"):
        tag = entry.find(name)
        if tag is not None and tag.get("url"):
            return tag["url"].strip()
    enc = entry.find("enclosure")
    if enc is not None and (enc.get("type") or "").startswith("image") and enc.get("url"):
        return enc["url"].strip()
    return None


def parse_feed(content: bytes, source: Source, now: Optional[datetime] = None, max_items: int = 15) -> List[Article]:
    now = now or datetime.now(timezone.utc)
    soup = BeautifulSoup(content, "xml")
    entries = soup.find_all(["item", "entry"])
    if not entries:
        raise CollectorError("no feed entries found")
    articles: List[Article] = []
    for entry in entries[:max_items]:
        title = _clean_html(_first_text(entry, ["title"]))
        link = _entry_link(entry)
        if not title or not link.startswith(("http://", "https://")):
            continue
        raw_summary = _first_text(entry, ["description", "summary", "content:encoded", "content"])
        articles.append(Article(
            url=link,
            canonical_url=normalize_url(link),
            title=title,
            source_name=source.name,
            source_kind=source.kind,
            source_trust=source.trust,
            category_hint=source.category,
            published_at=parse_date(_first_text(entry, ["pubDate", "published", "updated", "dc:date", "date"])),
            summary=_clean_html(raw_summary)[:MAX_SUMMARY_CHARS],
            image_url=_entry_image(entry),
            fetched_at=now,
        ))
    if not articles:
        raise CollectorError("feed entries had no usable title/link")
    return articles


def collect_all(
    sources: Sequence[Source],
    fetcher: Callable = safe_get,
    now: Optional[datetime] = None,
    max_items: int = 15,
) -> CollectionResult:
    result = CollectionResult()
    for source in sources:
        if not source.enabled or not source.url:
            continue
        try:
            page = fetcher(source.url, timeout=20, max_bytes=3_000_000)
            items = parse_feed(page.content, source, now, max_items)
        except (FetchError, CollectorError) as exc:
            log.warning("source failed: %s (%s)", source.name, exc)
            result.results.append(SourceResult(source.name, False, 0, str(exc)))
            continue
        except Exception as exc:  # هیچ خطای غیرمنتظره‌ای نباید کل اجرا را متوقف کند
            log.warning("source crashed: %s (%s)", source.name, type(exc).__name__)
            result.results.append(SourceResult(source.name, False, 0, type(exc).__name__))
            continue
        result.articles.extend(items)
        result.results.append(SourceResult(source.name, True, len(items)))
    return result

"""مدل‌های داده مشترک."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

# وضعیت‌های خبر
DISCOVERED = "discovered"
EXTRACTED = "extracted"
REJECTED = "rejected"
DRAFTED = "drafted"
PUBLISHING = "publishing"
PUBLISHED = "published"
FAILED = "failed"


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    kind: str = "official"      # official | media | tutorial
    category: str = "ai"        # ai | tech | programming | data_science | tutorial
    trust: float = 0.8          # ۰ تا ۱
    enabled: bool = True
    feed_type: str = "rss"
    verified: bool = False      # آدرس فید با اجرای scripts/check_feeds.py تأیید شده؟
    notes: str = ""


@dataclass
class Article:
    url: str                    # لینک اصلی، عیناً مطابق فید (در پست همین لینک می‌آید)
    canonical_url: str          # نسخه نرمال‌شده؛ شناسه یکتا در SQLite
    title: str
    source_name: str
    source_kind: str = "media"
    source_trust: float = 0.5
    category_hint: str = "tech"
    published_at: Optional[datetime] = None
    summary: str = ""
    text: str = ""
    extraction_ok: bool = False
    image_url: Optional[str] = None
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    score: float = 0.0
    status: str = DISCOVERED

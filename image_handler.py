"""مدیریت تصویر. پیش‌فرض خاموش است.

وجود og:image به معنی مجوز بازنشر نیست؛ بنابراین حتی با ALLOW_ARTICLE_IMAGES=true فقط
تصویر صفحه‌هایی استفاده می‌شود که دامنه‌شان صراحتاً در IMAGE_ALLOWED_DOMAINS آمده باشد
(یعنی خودتان مجوز آن منبع را بررسی و تأیید کرده‌اید).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import urlparse

from config import Settings
from logger import get_logger
from models import Article
from netutils import FetchError, safe_get

log = get_logger("image")
MAX_IMAGE_BYTES = 5_000_000
IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp")
_MAGIC = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"RIFF")


@dataclass
class ImageDecision:
    usable: bool
    reason: str
    data: Optional[bytes] = None


def _domain_allowed(url: str, allowed: tuple) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in allowed)


def evaluate_image(article: Article, settings: Settings, fetcher: Callable = safe_get) -> ImageDecision:
    if not settings.allow_article_images:
        return ImageDecision(False, "images disabled")
    if not article.image_url:
        return ImageDecision(False, "no image")
    if not _domain_allowed(article.url, settings.image_allowed_domains):
        return ImageDecision(False, "source domain not in IMAGE_ALLOWED_DOMAINS (license not confirmed)")
    try:
        page = fetcher(article.image_url, timeout=15, max_bytes=MAX_IMAGE_BYTES, allowed_types=IMAGE_TYPES)
    except FetchError as exc:
        return ImageDecision(False, f"image fetch failed: {exc}")
    if not page.content.startswith(_MAGIC):
        return ImageDecision(False, "file content is not a valid image")
    return ImageDecision(True, "ok", page.content)

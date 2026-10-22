"""استخراج متن واقعی مقاله و تصویر شاخص از صفحه‌ی عمومی (بدون دور زدن paywall)."""
from __future__ import annotations

import re
from typing import Callable, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from logger import get_logger
from models import Article
from netutils import FetchError, safe_get

log = get_logger("extractor")
MIN_USEFUL_CHARS = 300      # کمتر از این: استخراج ناموفق
MAX_TEXT_CHARS = 20000
HTML_TYPES = ("text/html", "application/xhtml+xml")

try:  # اختیاری؛ در نبود آن از BeautifulSoup استفاده می‌شود
    import trafilatura  # type: ignore
except Exception:  # pragma: no cover
    trafilatura = None


def _normalize(text: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _bs4_extract(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "noscript", "svg"]):
        tag.decompose()
    root = soup.find("article") or soup.find("main") or soup.body or soup
    paragraphs = [p.get_text(" ", strip=True) for p in root.find_all(["p", "li"])]
    return "\n\n".join(p for p in paragraphs if len(p) >= 40)


def extract_text(html: str, url: str = "") -> str:
    text = ""
    if trafilatura is not None:
        try:
            text = trafilatura.extract(html, url=url or None, include_comments=False,
                                       include_tables=False, favor_precision=True) or ""
        except Exception:
            text = ""
    if len(text) < MIN_USEFUL_CHARS:
        fallback = _bs4_extract(html)
        if len(fallback) > len(text):
            text = fallback
    return _normalize(text)[:MAX_TEXT_CHARS]


def extract_image_url(html: str, base_url: str) -> Optional[str]:
    soup = BeautifulSoup(html, "html.parser")
    for attrs in ({"property": "og:image"}, {"name": "twitter:image"}, {"property": "twitter:image"}):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            return urljoin(base_url, tag["content"].strip())
    return None


def extract_article(article: Article, fetcher: Callable = safe_get) -> Article:
    """متن را در خود article قرار می‌دهد. در صورت خطا extraction_ok=False می‌ماند."""
    try:
        page = fetcher(article.url, timeout=20, max_bytes=2_500_000, allowed_types=HTML_TYPES)
        html = page.text()
    except FetchError as exc:
        log.info("extraction fetch failed: %s", exc)
        return article
    except Exception as exc:
        log.info("extraction crashed: %s", type(exc).__name__)
        return article
    article.text = extract_text(html, article.url)
    article.extraction_ok = len(article.text) >= MIN_USEFUL_CHARS
    if not article.image_url:
        article.image_url = extract_image_url(html, page.url or article.url)
    return article

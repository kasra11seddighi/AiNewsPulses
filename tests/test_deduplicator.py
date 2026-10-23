"""جلوگیری از خبر تکراری: نرمال‌سازی URL و تشخیص عنوان‌های مشابه."""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Iterable, List, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from database import NewsDB
from models import Article

# فقط پارامترهای رهگیری حذف می‌شوند؛ بقیه (مثل id یا p) حفظ می‌شوند.
TRACKING_PARAMS = {
    "fbclid", "gclid", "yclid", "igshid", "mc_cid", "mc_eid", "mkt_tok", "_hsenc", "_hsmi",
    "cmpid", "ocid", "ncid", "ref_src", "spm",
}
TITLE_SIMILARITY_THRESHOLD = 0.85


def normalize_url(url: str) -> str:
    try:
        p = urlparse(url.strip())
    except ValueError:
        return url.strip()
    host = (p.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if p.port and p.port not in (80, 443):
        host = f"{host}:{p.port}"
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS]
    query.sort()
    path = p.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return urlunparse(("https", host, path, "", urlencode(query), ""))


def _title_key(title: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", title.lower())).strip()


# کلمه‌های عمومی عنوان خبر که درباره‌ی «موضوع» اطلاعاتی نمی‌دهند.
STOPWORDS = {
    "a", "an", "the", "of", "for", "to", "in", "on", "at", "by", "with", "and", "or", "is", "are", "was",
    "s", "new", "here", "now", "how", "why", "what", "its", "your", "our", "more", "most", "yet", "just",
    "launch", "launches", "launched", "release", "releases", "released", "introducing", "introduces",
    "announces", "announced", "announcing", "unveils", "unveiled", "arrives", "arrive", "available",
    "today", "update", "updates", "latest", "capable", "improved",
}
_TOKEN_RE = re.compile(r"[\w]+(?:[.\-][\w]+)*")


def _topic_tokens(title: str) -> set:
    """توکن‌های مهم عنوان؛ نسخه‌ها (gpt-5.5، 3.14.1) به‌صورت یک توکن می‌مانند."""
    low = title.lower().replace("\u2019s", "").replace("'s", "")
    return {t for t in _TOKEN_RE.findall(low) if t not in STOPWORDS}


def _has_version(token: str) -> bool:
    return len(token) >= 4 and any(c.isdigit() for c in token)


def same_topic(a: str, b: str) -> bool:
    """دو عنوان با کلمات متفاوت ولی درباره‌ی یک رویداد (مثلاً دو رسانه درباره‌ی یک مدل)."""
    ta, tb = _topic_tokens(a), _topic_tokens(b)
    shared = ta & tb
    if not shared:
        return False
    overlap = len(shared) / min(len(ta), len(tb))
    if overlap < 0.7:
        return False
    return len(shared) >= 3 or any(_has_version(t) for t in shared)


def titles_similar(a: str, b: str, threshold: float = TITLE_SIMILARITY_THRESHOLD) -> bool:
    ka, kb = _title_key(a), _title_key(b)
    if not ka or not kb:
        return False
    if ka == kb:
        return True
    ta, tb = set(ka.split()), set(kb.split())
    jaccard = len(ta & tb) / len(ta | tb) if ta | tb else 0
    if max(SequenceMatcher(None, ka, kb).ratio(), jaccard) >= threshold:
        return True
    return same_topic(a, b)


def filter_duplicates(
    articles: Iterable[Article], db: NewsDB, recent_titles: Iterable[str] = ()
) -> Tuple[List[Article], List[Tuple[Article, str]]]:
    """خروجی: (خبرهای یکتا، [(خبر حذف‌شده، دلیل)]). از منبع معتبرتر در تکرارها نگه داشته می‌شود."""
    kept: List[Article] = []
    dropped: List[Tuple[Article, str]] = []
    seen_urls = set()
    recent = list(recent_titles)
    ordered = sorted(articles, key=lambda a: (-a.source_trust, -(a.published_at.timestamp() if a.published_at else 0)))
    for art in ordered:
        if art.canonical_url in seen_urls:
            dropped.append((art, "duplicate url in batch"))
        elif db.should_skip(art.canonical_url):
            dropped.append((art, "already processed"))
        elif any(titles_similar(art.title, t) for t in recent):
            dropped.append((art, "similar to recently published title"))
        elif any(titles_similar(art.title, k.title) for k in kept):
            dropped.append((art, "similar title in batch"))
        else:
            seen_urls.add(art.canonical_url)
            kept.append(art)
    return kept, dropped

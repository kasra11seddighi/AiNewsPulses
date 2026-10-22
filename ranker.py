"""امتیازدهی قابل‌توضیح (۰ تا ۱۰۰) و رتبه‌بندی. هیچ بخشی از رتبه‌بندی به مدل زبانی سپرده نشده است."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Tuple

from config import Settings
from models import Article

CATEGORY_KEYWORDS = {
    "ai": ["ai", "artificial intelligence", "llm", "language model", "gpt", "gemini", "claude", "llama",
           "openai", "anthropic", "deepmind", "agent", "agents", "machine learning", "neural", "diffusion",
           "chatbot", "copilot", "transformer", "mistral", "hugging face"],
    "tech": ["chip", "gpu", "cpu", "semiconductor", "cloud", "cybersecurity", "security", "vulnerability",
             "ransomware", "windows", "linux", "android", "ios", "apple", "microsoft", "google", "nvidia",
             "amazon", "aws", "azure", "processor", "smartphone", "startup", "data center", "quantum"],
    "programming": ["python", "javascript", "typescript", "rust", "golang", "java", "framework", "library",
                    "github", "open-source", "open source", "compiler", "api", "sdk", "developer",
                    "developers", "debug", "npm", "react", "node", "cli", "kubernetes", "docker"],
    "data_science": ["data science", "pandas", "numpy", "scikit-learn", "sklearn", "dataset", "data engineering",
                     "sql", "visualization", "jupyter", "notebook", "statistics", "analytics", "pytorch",
                     "tensorflow", "kaggle", "database", "postgres"],
}
IMPORTANCE_POSITIVE = ["launch", "launches", "launched", "release", "released", "releases", "introduces",
                       "introducing", "announces", "announced", "unveils", "open-source", "open source",
                       "new model", "benchmark", "breakthrough", "vulnerability", "partnership", "acquires",
                       "acquisition", "funding", "available", "api", "version", "preview", "agent"]
PROMO_NEGATIVE = ["sponsored", "webinar", "discount", "coupon", "giveaway", "deal", "deals", "sale",
                  "promo", "register now", "we're hiring", "job opening", "newsletter", "best deals",
                  "podcast episode", "event recap", "limited time"]


def _hits(text: str, keywords: Iterable[str]) -> int:
    low = text.lower()
    return sum(1 for kw in set(keywords) if re.search(rf"(?<![\w-]){re.escape(kw)}(?![\w-])", low))


def classify(article: Article) -> str:
    """تعیین دسته (و در نتیجه هشتگ) برای پست."""
    if article.source_kind == "tutorial" or article.category_hint == "tutorial":
        return "tutorial"
    title, body = article.title, f"{article.summary} {article.text[:1500]}"
    scores = {cat: 3 * _hits(title, kws) + _hits(body, kws) for cat, kws in CATEGORY_KEYWORDS.items()}
    if article.category_hint in scores:
        scores[article.category_hint] += 5  # حوزه‌ی اعلام‌شده‌ی منبع، پیش‌فرض قوی است
    best = max(scores, key=lambda c: (scores[c], c == article.category_hint))
    if scores[best] == 0:
        return article.category_hint if article.category_hint in CATEGORY_KEYWORDS else "tech"
    return best


@dataclass
class ScoreResult:
    total: float
    breakdown: Dict[str, float]
    reject_reason: Optional[str] = None
    notes: List[str] = field(default_factory=list)


def _freshness(article: Article, weight: float, max_age_days: int, now: datetime) -> Tuple[float, Optional[str]]:
    if article.published_at is None:
        return weight * 0.25, None  # تاریخ نامعلوم: امتیاز اندک ولی نه رد قطعی
    age_h = max((now - article.published_at).total_seconds() / 3600, 0)
    limit_h = max_age_days * 24
    if age_h > limit_h:
        return 0.0, f"too old ({age_h / 24:.1f} days)"
    if age_h <= 24:
        return weight, None
    return weight * (1 - (age_h - 24) / max(limit_h - 24, 1)), None


def _evidence(article: Article, weight: float, min_chars: int) -> float:
    n = len(article.text)
    if article.extraction_ok and n >= min_chars:
        return weight * (0.5 + 0.5 * min(1.0, n / (min_chars * 3)))
    if article.extraction_ok:
        return weight * 0.4
    s = len(article.summary)
    if s >= 300:
        return weight * 0.4
    if s >= 120:
        return weight * 0.2
    return 0.0


def score_article(article: Article, settings: Settings, now: Optional[datetime] = None) -> ScoreResult:
    now = now or datetime.now(timezone.utc)
    w = settings.weights
    notes: List[str] = []

    source = w["source"] * max(0.0, min(1.0, article.source_trust))

    fresh, reject = _freshness(article, w["freshness"], settings.max_article_age_days, now)

    title_hits = _hits(article.title, IMPORTANCE_POSITIVE)
    body_hits = _hits(f"{article.summary} {article.text[:1500]}", IMPORTANCE_POSITIVE)
    promo = _hits(f"{article.title} {article.summary}", PROMO_NEGATIVE)
    importance = 6 + 4 * title_hits + 1.5 * body_hits + (2 if article.source_kind == "official" else 0)
    importance = max(0.0, min(float(w["importance"]), importance - 10 * promo))
    if promo:
        notes.append(f"promotional keywords: {promo}")

    all_kws = [kw for kws in CATEGORY_KEYWORDS.values() for kw in kws]
    rel_hits = _hits(f"{article.title} {article.summary} {article.text[:2000]}", all_kws)
    relevance = w["relevance"] * min(1.0, rel_hits / 4)
    if article.category_hint:
        relevance = max(relevance, w["relevance"] * 0.5)

    evidence = _evidence(article, w["evidence"], settings.min_article_text_chars)
    image = w["image"] if (settings.allow_article_images and article.image_url) else 0.0

    breakdown = {"source": source, "freshness": fresh, "importance": importance,
                 "relevance": relevance, "evidence": evidence, "image": image}
    breakdown = {k: round(v, 1) for k, v in breakdown.items()}
    return ScoreResult(round(sum(breakdown.values()), 1), breakdown, reject, notes)


def rank_articles(articles: Iterable[Article], settings: Settings, now: Optional[datetime] = None,
                  threshold: Optional[float] = None):
    """خروجی: (پذیرفته‌شده‌ها به ترتیب امتیاز، [(خبر, دلیل رد, ScoreResult)])."""
    limit = settings.min_quality_score if threshold is None else threshold
    accepted: List[Article] = []
    rejected = []
    for art in articles:
        result = score_article(art, settings, now)
        art.score = result.total
        if result.reject_reason:
            rejected.append((art, result.reject_reason, result))
        elif result.total < limit:
            rejected.append((art, f"score {result.total} below {limit}", result))
        else:
            accepted.append(art)
    accepted.sort(key=lambda a: a.score, reverse=True)
    return accepted, rejected

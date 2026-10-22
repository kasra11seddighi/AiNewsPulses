"""بررسی کفایت شواهد، پاک‌سازی ورودی مقاله (ضد prompt-injection) و اعتبارسنجی پست نهایی."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from config import CATEGORY_HASHTAGS, TELEGRAM_MESSAGE_LIMIT, Settings
from models import Article

SUMMARY_MIN_CHARS = 250
MAX_EVIDENCE_CHARS = 12000
MIN_BODY_CHARS = 120
SOURCE_MARKER = "🔗 منبع اصلی:"
URL_RE = re.compile(r"https?://\S+")

_INJECTION_PATTERNS = [
    r"ignore (all |any |the )?(previous|prior|above|earlier) (instructions|prompts?|rules)",
    r"disregard (all |any |the )?(previous|prior|above|earlier)",
    r"forget (all |any |the )?(previous|prior|above|earlier)",
    r"(reveal|print|show|leak|output).{0,40}(system prompt|api key|secret|token|password)",
    r"you are now\b",
    r"(act|behave) as (if you are |an? )",
    r"new instructions\s*:",
    r"دستور(ها|های)? (قبلی|پیشین).{0,20}(نادیده|فراموش)",
    r"پرامپت سیستم",
    r"(کلید|توکن).{0,15}(را )?(فاش|نمایش)",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.I)

_DIGIT_TABLE = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩٫٬", "01234567890123456789.,")
FORBIDDEN_PHRASES = ["چرا مهم است", "example.com", "به عنوان یک مدل زبانی", "as an ai"]


@dataclass
class EvidenceDecision:
    ok: bool
    mode: str       # full | summary | none
    reason: str
    text: str = ""


@dataclass
class ValidationResult:
    ok: bool
    errors: List[str] = field(default_factory=list)


def sanitize_evidence(text: str) -> Tuple[str, int]:
    """خطوطی که شبیه دستور به مدل هستند حذف می‌شوند. خروجی: (متن پاک، تعداد خط حذف‌شده)."""
    kept, removed = [], 0
    for line in text.splitlines():
        if _INJECTION_RE.search(line):
            removed += 1
        else:
            kept.append(line)
    return "\n".join(kept)[:MAX_EVIDENCE_CHARS], removed


def assess_evidence(article: Article, min_chars: int) -> EvidenceDecision:
    text = article.text or ""
    if article.extraction_ok and len(text) >= min_chars:
        clean, _ = sanitize_evidence(text)
        return EvidenceDecision(True, "full", "full article text", clean)
    combined = f"{text}\n\n{article.summary}".strip() if text else article.summary
    if len(combined) >= SUMMARY_MIN_CHARS:
        clean, _ = sanitize_evidence(combined)
        return EvidenceDecision(True, "summary", "summary only", clean)
    return EvidenceDecision(False, "none", "insufficient evidence", "")


def normalize_digits(text: str) -> str:
    out = text.translate(_DIGIT_TABLE)
    return re.sub(r"(?<=\d),(?=\d{3})", "", out)


def _numbers(text: str) -> List[str]:
    return [n for n in re.findall(r"\d+(?:\.\d+)*", normalize_digits(text)) if len(n.replace(".", "")) >= 2]


def _evidence_blob(article: Article, evidence_text: str) -> str:
    date = article.published_at.isoformat() if article.published_at else ""
    return normalize_digits(f"{article.title}\n{article.summary}\n{evidence_text}\n{date}")


def validate_post(post: str, article: Article, settings: Settings, evidence_text: str = "") -> ValidationResult:
    errors: List[str] = []
    text = (post or "").strip()
    if not text:
        return ValidationResult(False, ["empty post"])
    lines = [ln.rstrip() for ln in text.split("\n")]
    nonempty = [ln.strip() for ln in lines if ln.strip()]

    # هشتگ: خط اول دقیقاً یک هشتگ مجاز و هیچ هشتگ دیگری در پست نباشد
    if nonempty[0] not in CATEGORY_HASHTAGS.values():
        errors.append("first line must be exactly one allowed hashtag")
    if len(re.findall(r"#[\w\u200c]+", URL_RE.sub("", text))) != 1:
        errors.append("post must contain exactly one hashtag")

    # عنوان
    if len(nonempty) < 2 or not nonempty[1].startswith("📰") or len(nonempty[1]) < 10:
        errors.append("missing or too short title line (📰)")

    # لینک منبع: بعد از «🔗 منبع اصلی:» دقیقاً لینک اصلی بیاید
    if SOURCE_MARKER not in nonempty:
        errors.append("missing source marker")
    else:
        idx = nonempty.index(SOURCE_MARKER)
        if idx + 1 >= len(nonempty) or nonempty[idx + 1] != article.url:
            errors.append("source link missing or altered")
    if any(u != article.url for u in URL_RE.findall(text)):
        errors.append("unexpected URL in post")

    # آیدی کانال
    handle = settings.channel_handle
    if nonempty[-1] != handle:
        errors.append("channel handle must be the last line")
    if text.count(handle) != 1:
        errors.append("channel handle must appear exactly once")

    # طول
    if len(text) > TELEGRAM_MESSAGE_LIMIT:
        errors.append(f"post too long ({len(text)} > {TELEGRAM_MESSAGE_LIMIT})")

    # بدنه
    body_lines: List[str] = []
    if len(nonempty) >= 2 and SOURCE_MARKER in nonempty:
        body_lines = nonempty[2:nonempty.index(SOURCE_MARKER)]
    body = "\n".join(body_lines)
    if len(body) < MIN_BODY_CHARS:
        errors.append("body too short")
    persian = len(re.findall(r"[\u0600-\u06FF]", body))
    latin = len(re.findall(r"[A-Za-z]", body))
    if persian + latin and persian / (persian + latin) < 0.5:
        errors.append("body is not predominantly Persian")

    # قالب‌بندی و عبارت‌های ممنوع
    no_urls = URL_RE.sub("", text)
    if "```" in no_urls or "**" in no_urls or "__" in no_urls or "`" in no_urls:
        errors.append("markdown formatting is not allowed")
    low = text.lower()
    for phrase in FORBIDDEN_PHRASES:
        if phrase in low:
            errors.append(f"forbidden phrase: {phrase}")
    if re.search(r"«[^»]{20,}»|\"[^\"]{20,}\"|“[^”]{20,}”", body):
        errors.append("direct quotations are not allowed")

    # عددهای ساخته‌شده: هر عدد ≥۲ رقمی باید در شواهد باشد
    blob = _evidence_blob(article, evidence_text)
    content_for_numbers = "\n".join(nonempty[1:2] + body_lines)
    missing = sorted({n for n in _numbers(content_for_numbers) if n not in blob})
    if missing:
        errors.append(f"numbers not found in source evidence: {', '.join(missing[:5])}")

    return ValidationResult(not errors, errors)

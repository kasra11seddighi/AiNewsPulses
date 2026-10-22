"""نقطه‌ی ورود: هماهنگ‌کردن کل جریان اجرا.

    python main.py --dry-run     # همه‌چیز به‌جز ارسال (و بدون تغییر پایگاه داده)
    python main.py               # انتشار فقط اگر ENABLE_PUBLISHING=true باشد
"""
from __future__ import annotations

import argparse
import logging
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, List, Optional, Sequence

from collector import collect_all
from config import Settings
from database import DatabaseError, NewsDB
from deduplicator import filter_duplicates
from extractor import extract_article
from image_handler import evaluate_image
from logger import get_logger, log_event, register_secrets, setup_logging
from models import DRAFTED, EXTRACTED, FAILED, REJECTED, Article, Source
from netutils import safe_get
from publisher import DryRunPublisher, TelegramPublisher
from ranker import classify, rank_articles, score_article
from scheduler import allowed_this_run, posts_remaining
from sources import enabled_sources
from validator import assess_evidence, validate_post
from writer import (GeminiWriter, QuotaExceededError, WriterError, build_post, choose_depth)

log = get_logger("main")

EXTRACT_LIMIT = 10          # حداکثر تعداد مقاله‌ای که در هر اجرا متنش دریافت می‌شود
MAX_CANDIDATES = 6          # حداکثر تعداد خبری که در هر اجرا به Gemini داده می‌شود
WRITE_ATTEMPTS = 2          # تولید + یک تلاش مجدد با بازخورد اعتبارسنج
PRE_SCORE_MARGIN = 15       # شواهد بعد از استخراج می‌تواند امتیاز را بالا ببرد


class ConfigError(Exception):
    pass


@dataclass
class Deps:
    fetcher: Callable = safe_get
    writer: Any = None
    publisher: Any = None
    sleep: Callable[[float], None] = time.sleep


@dataclass
class RunSummary:
    collected: int = 0
    candidates: int = 0
    rejected: int = 0
    drafted: int = 0
    published: int = 0
    failed: int = 0
    unknown: int = 0
    drafts: List[str] = field(default_factory=list)
    message: str = ""


def _reject(db: NewsDB, art: Article, reason: str, summary: RunSummary) -> None:
    summary.rejected += 1
    db.set_status(art.canonical_url, REJECTED, score=art.score, error=reason)
    log_event(log, logging.INFO, "rejected", title=art.title[:80], reason=reason, score=art.score)


def _write_and_validate(art, evidence, mode, category, writer, settings, ev_text):
    """خروجی: (متن پست یا None، دلیل رد). خطای سهمیه به بالا پرتاب می‌شود."""
    feedback: Optional[str] = None
    depth = choose_depth(art, mode)
    last_errors = ""
    for _ in range(WRITE_ATTEMPTS):
        draft = writer.generate(art, evidence, mode, category, depth, feedback)
        if draft.insufficient:
            return None, "model reported insufficient evidence"
        post = build_post(draft, art, category, settings)
        result = validate_post(post, art, settings, ev_text)
        if result.ok:
            return post, ""
        last_errors = "; ".join(result.errors)
        feedback = last_errors
    return None, f"validation failed: {last_errors}"


def run(settings: Settings, *, dry_run: bool = False, deps: Optional[Deps] = None,
        sources: Optional[Sequence[Source]] = None, now: Optional[datetime] = None) -> RunSummary:
    deps = deps or Deps()
    now = now or datetime.now(timezone.utc)
    summary = RunSummary()
    publish_active = settings.publishing_active(dry_run)

    # ناشر: اگر انتشار فعال نباشد، ناشر واقعی اصلاً ساخته/استفاده نمی‌شود.
    if publish_active:
        publisher = deps.publisher or TelegramPublisher(settings.telegram_bot_token, settings.telegram_channel_id)
    else:
        publisher = DryRunPublisher()

    writer = deps.writer
    if writer is None:
        if not settings.gemini_api_key:
            raise ConfigError("GEMINI_API_KEY is not set")
        writer = GeminiWriter(settings.gemini_api_key, settings.gemini_model)

    mode_label = "LIVE" if publish_active else ("DRY-RUN" if dry_run else "PUBLISHING-DISABLED")
    log_event(log, logging.INFO, "run started", mode=mode_label)

    tmp_dir = None
    db_path = settings.database_path
    if dry_run and db_path != ":memory:":
        # dry-run هیچ‌وقت پایگاه داده‌ی واقعی را تغییر نمی‌دهد: روی یک کپی موقت کار می‌کنیم.
        tmp_dir = tempfile.TemporaryDirectory()
        copy = Path(tmp_dir.name) / "dryrun.db"
        if Path(db_path).exists():
            shutil.copyfile(db_path, copy)
        db_path = str(copy)

    try:
        with NewsDB(db_path) as db:
            for rec in db.ambiguous():
                log.warning("ambiguous delivery needs manual check: %r (%s)", rec["title"][:60], rec["last_error"])

            quota = allowed_this_run(db, settings, now)
            if quota <= 0:
                if not dry_run and publish_active:
                    summary.message = "daily limit reached; nothing to do"
                    log.info(summary.message)
                    return summary
                quota = settings.max_posts_per_run  # در حالت بدون انتشار فقط پیش‌نمایش می‌سازیم
                log.info("daily limit reached, but nothing will be published in this mode; previewing only")

            # ۱) جمع‌آوری
            collection = collect_all(sources if sources is not None else enabled_sources(), deps.fetcher, now)
            summary.collected = len(collection.articles)
            failed_sources = [r.source for r in collection.results if not r.ok]
            log_event(log, logging.INFO, "collected", articles=summary.collected,
                      failed_sources=",".join(failed_sources) or "-")

            # ۲) حذف تکراری و خبرهای قدیمی/ضعیف قبل از دریافت متن
            unique, dropped = filter_duplicates(collection.articles, db, db.recent_titles(7, now))
            log.info("deduplicated: kept=%d dropped=%d", len(unique), len(dropped))
            pre_accepted, _ = rank_articles(unique, settings, now,
                                            threshold=settings.min_quality_score - PRE_SCORE_MARGIN)
            shortlist = pre_accepted[:EXTRACT_LIMIT]

            # ۳) استخراج متن واقعی
            for art in shortlist:
                db.upsert_discovered(art)
                extract_article(art, deps.fetcher)
                db.set_status(art.canonical_url, EXTRACTED, score=art.score)
                deps.sleep(0.5)  # فاصله‌ی مؤدبانه بین درخواست‌ها

            # ۴) امتیاز نهایی
            accepted, rejected_list = rank_articles(shortlist, settings, now)
            for art, reason, result in rejected_list:
                _reject(db, art, f"{reason} {result.breakdown}", summary)
            summary.candidates = len(accepted)
            for art in accepted:
                log_event(log, logging.INFO, "candidate", title=art.title[:80], score=art.score,
                          breakdown=score_article(art, settings, now).breakdown)

            # ۵) تولید، اعتبارسنجی و انتشار
            writer_errors = 0
            for art in accepted[:MAX_CANDIDATES]:
                if summary.drafted + summary.published >= quota:
                    break
                decision = assess_evidence(art, settings.min_article_text_chars)
                if not decision.ok:
                    _reject(db, art, decision.reason, summary)
                    continue
                category = classify(art)
                evidence_text = f"{art.title}\n{art.summary}\n{decision.text}"
                try:
                    post, reason = _write_and_validate(art, decision.text, decision.mode, category,
                                                       writer, settings, evidence_text)
                except QuotaExceededError:
                    summary.message = "Gemini quota exhausted; stopping run"
                    log.warning(summary.message)
                    break
                except WriterError as exc:
                    writer_errors += 1
                    summary.failed += 1
                    db.set_status(art.canonical_url, FAILED, error=str(exc))
                    log.warning("writer error: %s", exc)
                    if exc.permanent or writer_errors >= 2:
                        summary.message = "stopping run after writer errors"
                        break
                    continue
                if post is None:
                    _reject(db, art, reason, summary)
                    continue

                db.set_status(art.canonical_url, DRAFTED, score=art.score, draft=post)
                if not publish_active:
                    summary.drafted += 1
                    summary.drafts.append(post)
                    log.info("DRAFT (not published, mode=%s):\n%s", mode_label, post)
                    continue

                # انتشار واقعی: سقف روزانه را دوباره از SQLite کنترل کن
                if posts_remaining(db, settings, datetime.now(timezone.utc)) <= 0:
                    summary.message = "daily limit reached"
                    break
                image = None
                decision_img = evaluate_image(art, settings, deps.fetcher)
                if decision_img.usable:
                    image = decision_img.data
                if not db.begin_publishing(art.canonical_url, post, datetime.now(timezone.utc)):
                    log.info("article already published/publishing; skipped")
                    continue
                result = publisher.send(post, image)
                if result.status == "sent":
                    db.mark_published(art.canonical_url, result.message_id, datetime.now(timezone.utc))
                    summary.published += 1
                    log_event(log, logging.INFO, "published", title=art.title[:80], message_id=result.message_id)
                elif result.status == "failed":
                    db.mark_failed(art.canonical_url, result.error)
                    summary.failed += 1
                    summary.message = "publish failed; stopping run"
                    log.warning("publish failed: %s", result.error)
                    break  # خطای Telegram معمولاً مربوط به تنظیمات/سهمیه است؛ تلاش برای خبر بعدی بی‌فایده است
                else:  # unknown → هرگز دوباره ارسال نکن
                    db.mark_unknown(art.canonical_url, result.error)
                    summary.unknown += 1
                    summary.message = "delivery status unknown; stopping run (manual check required)"
                    log.error(summary.message)
                    break

            if not (summary.published or summary.drafted) and not summary.message:
                summary.message = "no suitable news found"
                log.info(summary.message)
    finally:
        if tmp_dir is not None:
            tmp_dir.cleanup()

    log_event(log, logging.INFO, "run finished", published=summary.published, drafted=summary.drafted,
              rejected=summary.rejected, failed=summary.failed, unknown=summary.unknown)
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="AiNewsPulses news agent")
    parser.add_argument("--dry-run", action="store_true",
                        help="هیچ پیامی ارسال نمی‌شود و پایگاه داده تغییر نمی‌کند")
    parser.add_argument("--log-level", default=None)
    args = parser.parse_args(argv)

    try:
        from dotenv import load_dotenv  # اختیاری برای اجرای محلی
        load_dotenv(override=False)
    except ImportError:
        pass

    settings = Settings.from_env()
    register_secrets(settings.secrets())
    setup_logging(args.log_level or settings.log_level)
    try:
        run(settings, dry_run=args.dry_run)
    except ConfigError as exc:
        log.error("configuration error: %s", exc)
        return 2
    except DatabaseError as exc:
        log.error("database error: %s", exc)
        return 1
    except Exception as exc:
        log.error("fatal error: %s", type(exc).__name__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

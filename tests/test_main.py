import io
import logging
from datetime import timedelta

import logger
from database import NewsDB
from helpers import (GEMINI_KEY, GOOD_BODY, NOW, TOKEN, FakeFetcher, FakePublisher, FakeWriter,
                     make_html, make_rss, make_settings)
from main import Deps, run
from models import Source
from publisher import PublishResult
from writer import Draft, QuotaExceededError, WriterError

FEED = "https://feed.test/rss"
A1 = "https://news.test/openai-model"
A2 = "https://news.test/nvidia-gpu"
SOURCES = [Source("TestFeed", FEED, "official", "ai", 0.95)]


def world(items=None):
    items = items if items is not None else [
        ("OpenAI releases a new open-source model for developers", A1, NOW - timedelta(hours=2), "d" * 150),
        ("NVIDIA announces new GPU architecture for data centers", A2, NOW - timedelta(hours=3), "d" * 150),
    ]
    pages = {FEED: make_rss(items)}
    for _, link, _, _ in items:
        pages[link] = make_html()
    return FakeFetcher(pages)


def deps(fetcher=None, writer=None, publisher=None):
    return Deps(fetcher=fetcher or world(), writer=writer or FakeWriter(), publisher=publisher or FakePublisher(),
                sleep=lambda s: None)


def live(tmp_path, **kw):
    return make_settings(enable_publishing=True, database_path=str(tmp_path / "db.sqlite"), **kw)


def test_dry_run_never_publishes_and_never_touches_database(tmp_path):
    pub = FakePublisher()
    s = live(tmp_path)                                        # حتی با انتشار روشن
    summary = run(s, dry_run=True, deps=deps(publisher=pub), sources=SOURCES, now=NOW)
    assert pub.sent == [] and summary.published == 0 and summary.drafted == 1
    assert summary.drafts[0].startswith("#هوش_مصنوعی") and not (tmp_path / "db.sqlite").exists()


def test_publishing_disabled_by_default_never_publishes(tmp_path):
    pub = FakePublisher()
    s = make_settings(enable_publishing=False, database_path=str(tmp_path / "db.sqlite"))
    summary = run(s, deps=deps(publisher=pub), sources=SOURCES, now=NOW)
    assert pub.sent == [] and summary.published == 0 and summary.drafted == 1
    with NewsDB(s.database_path) as db:
        assert all(r["status"] != "published" for r in db.conn.execute("SELECT status FROM articles"))


def test_live_run_publishes_exactly_one_post_per_run(tmp_path):
    pub = FakePublisher()
    summary = run(live(tmp_path), deps=deps(publisher=pub), sources=SOURCES, now=NOW)
    assert summary.published == 1 and len(pub.sent) == 1
    post = pub.sent[0]
    assert post.endswith("@AiNewsPulses") and "🔗 منبع اصلی:" in post


def test_rerun_never_republishes_same_article(tmp_path):
    items = [("OpenAI releases a new open-source model for developers", A1, NOW - timedelta(hours=2), "d" * 150)]
    pub = FakePublisher()
    s = live(tmp_path)
    run(s, deps=deps(world(items), publisher=pub), sources=SOURCES, now=NOW)
    again = run(s, deps=deps(world(items), publisher=pub), sources=SOURCES, now=NOW)
    assert len(pub.sent) == 1 and again.published == 0 and again.message == "no suitable news found"


def test_daily_limit_is_enforced_by_database_not_by_run_count(tmp_path):
    pub = FakePublisher()
    s = live(tmp_path, daily_post_limit=1)
    run(s, deps=deps(publisher=pub), sources=SOURCES, now=NOW)
    second = run(s, deps=deps(publisher=pub), sources=SOURCES, now=NOW)
    assert len(pub.sent) == 1 and "daily limit" in second.message


def test_manual_run_cannot_bypass_daily_limit(tmp_path):
    # «اجرای دستی» همان run() است؛ سقف از SQLite کنترل می‌شود نه نوع اجرا
    pub = FakePublisher()
    s = live(tmp_path, daily_post_limit=1, max_posts_per_run=5)
    run(s, deps=deps(publisher=pub), sources=SOURCES, now=NOW)
    run(s, deps=deps(publisher=pub), sources=SOURCES, now=NOW)
    assert len(pub.sent) == 1


def test_no_eligible_news_publishes_nothing(tmp_path):
    old = [("Old announcement of a model", A1, NOW - timedelta(days=30), "d" * 150)]
    pub = FakePublisher()
    summary = run(live(tmp_path), deps=deps(world(old), publisher=pub), sources=SOURCES, now=NOW)
    assert pub.sent == [] and summary.message == "no suitable news found"


def test_article_with_insufficient_text_is_rejected_not_published(tmp_path):
    items = [("OpenAI releases a new open-source model for developers", A1, NOW - timedelta(hours=2), "tiny")]
    fetcher = FakeFetcher({FEED: make_rss(items), A1: b"<html><body><p>tiny</p></body></html>"})
    pub, writer = FakePublisher(), FakeWriter()
    summary = run(live(tmp_path), deps=deps(fetcher, writer, pub), sources=SOURCES, now=NOW)
    assert pub.sent == [] and writer.calls == 0 and summary.published == 0


def test_gemini_quota_error_stops_run_without_publishing(tmp_path):
    pub, writer = FakePublisher(), FakeWriter(error=QuotaExceededError())
    summary = run(live(tmp_path), deps=deps(writer=writer, publisher=pub), sources=SOURCES, now=NOW)
    assert pub.sent == [] and "quota" in summary.message and writer.calls == 1


def test_gemini_failure_does_not_publish_low_quality_filler(tmp_path):
    pub, writer = FakePublisher(), FakeWriter(error=WriterError("Gemini server error 500"))
    summary = run(live(tmp_path), deps=deps(writer=writer, publisher=pub), sources=SOURCES, now=NOW)
    assert pub.sent == [] and summary.failed >= 1


def test_model_output_that_fails_validation_is_not_published(tmp_path):
    bad = Draft(False, "عنوان", GOOD_BODY + " ۹۹۹۹ درصد رشد داشته است.")     # عدد ساختگی
    pub, writer = FakePublisher(), FakeWriter(draft=bad)
    summary = run(live(tmp_path), deps=deps(writer=writer, publisher=pub), sources=SOURCES, now=NOW)
    assert pub.sent == [] and writer.calls >= 2                              # یک تلاش مجدد با بازخورد


def test_telegram_permanent_error_marks_failed_and_publishes_nothing(tmp_path):
    pub = FakePublisher(PublishResult("failed", error="chat not found"))
    s = live(tmp_path)
    summary = run(s, deps=deps(publisher=pub), sources=SOURCES, now=NOW)
    assert summary.published == 0 and summary.failed == 1
    with NewsDB(s.database_path) as db:
        assert db.count_consumed_since(NOW - timedelta(days=1)) == 0


def test_unknown_delivery_is_not_resent_and_counts_toward_limit(tmp_path):
    pub = FakePublisher(PublishResult("unknown", error="timeout"))
    s = live(tmp_path)
    first = run(s, deps=deps(publisher=pub), sources=SOURCES, now=NOW)
    assert first.unknown == 1 and len(pub.sent) == 1                         # بعد از وضعیت مبهم، توقف
    pub2 = FakePublisher()
    run(s, deps=deps(publisher=pub2), sources=SOURCES, now=NOW)
    assert all("openai-model" not in p for p in pub2.sent)                   # همان خبر دوباره ارسال نمی‌شود


def test_failed_source_does_not_stop_the_run(tmp_path):
    sources = [Source("Dead", "https://dead.test/rss", "official", "ai", 0.9)] + SOURCES
    pub = FakePublisher()
    summary = run(live(tmp_path), deps=deps(publisher=pub), sources=sources, now=NOW)
    assert summary.published == 1


def test_secrets_never_reach_logs_or_database(tmp_path):
    logger.register_secrets([TOKEN, GEMINI_KEY])
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logger.RedactingFormatter("%(message)s"))
    root = logging.getLogger(logger.ROOT_NAME)
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        pub = FakePublisher(PublishResult("failed", error=f"boom {TOKEN}"))
        s = live(tmp_path)
        run(s, deps=deps(publisher=pub), sources=SOURCES, now=NOW)
        logging.getLogger("ainewspulses.test").warning("leak attempt %s %s", TOKEN, GEMINI_KEY)
    finally:
        root.removeHandler(handler)
    assert TOKEN not in stream.getvalue() and GEMINI_KEY not in stream.getvalue()
    with NewsDB(s.database_path) as db:
        dump = " ".join(str(dict(r)) for r in db.conn.execute("SELECT * FROM articles"))
    assert TOKEN not in dump and GEMINI_KEY not in dump

from datetime import datetime, timedelta, timezone

from database import NewsDB
from helpers import NOW, TOKEN, make_article
from logger import register_secrets
from models import DRAFTED, EXTRACTED, FAILED, PUBLISHED, PUBLISHING, REJECTED


def test_article_is_recorded_and_not_duplicated():
    db = NewsDB(":memory:")
    a = make_article()
    db.upsert_discovered(a)
    db.upsert_discovered(a)
    row = db.get(a.canonical_url)
    assert row["status"] == "discovered" and row["title"] == a.title
    assert db.conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 1


def test_publish_flow_and_published_detection():
    db = NewsDB(":memory:")
    a = make_article()
    db.upsert_discovered(a)
    db.set_status(a.canonical_url, DRAFTED, score=80, draft="متن")
    assert db.begin_publishing(a.canonical_url, "متن", NOW) is True
    assert db.begin_publishing(a.canonical_url, "متن", NOW) is False      # اتمیک: دوبار شروع نمی‌شود
    db.mark_published(a.canonical_url, 42, NOW)
    row = db.get(a.canonical_url)
    assert row["status"] == PUBLISHED and row["telegram_message_id"] == 42
    assert db.should_skip(a.canonical_url)
    db.set_status(a.canonical_url, REJECTED)                              # وضعیت منتشرشده قابل پس‌گرفتن نیست
    assert db.get(a.canonical_url)["status"] == PUBLISHED


def test_daily_count_only_includes_today_and_ambiguous_counts_too():
    db = NewsDB(":memory:")
    day_start = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)
    for i, when in enumerate([day_start - timedelta(hours=1), day_start + timedelta(hours=2)]):
        a = make_article(url=f"https://x.test/{i}")
        db.upsert_discovered(a)
        db.begin_publishing(a.canonical_url, "d", when)
        db.mark_published(a.canonical_url, i, when)
    amb = make_article(url="https://x.test/amb")
    db.upsert_discovered(amb)
    db.begin_publishing(amb.canonical_url, "d", day_start + timedelta(hours=3))
    db.mark_unknown(amb.canonical_url, "timeout")
    assert db.count_consumed_since(day_start) == 2        # ۱ منتشرشده‌ی امروز + ۱ مبهم؛ دیروزی شمرده نمی‌شود
    assert db.get(amb.canonical_url)["status"] == PUBLISHING
    assert len(db.ambiguous()) == 1


def test_failed_articles_are_retried_only_a_few_times():
    db = NewsDB(":memory:")
    a = make_article()
    db.upsert_discovered(a)
    for _ in range(3):
        assert not db.should_skip(a.canonical_url)
        db.begin_publishing(a.canonical_url, "d", NOW)
        db.mark_failed(a.canonical_url, "boom")
    assert db.get(a.canonical_url)["status"] == FAILED and db.should_skip(a.canonical_url)


def test_secrets_are_never_stored_in_database():
    register_secrets([TOKEN])
    db = NewsDB(":memory:")
    a = make_article()
    db.upsert_discovered(a)
    db.set_status(a.canonical_url, FAILED, error=f"request to https://api.telegram.org/bot{TOKEN}/send failed {TOKEN}")
    dump = " ".join(str(v) for v in db.get(a.canonical_url).values())
    assert TOKEN not in dump and "***" in dump


def test_database_persists_to_single_file(tmp_path):
    path = tmp_path / "sub" / "news.db"
    with NewsDB(path) as db:
        db.upsert_discovered(make_article())
    with NewsDB(path) as db:
        assert db.get(make_article().canonical_url) is not None
    assert sorted(p.name for p in path.parent.iterdir()) == ["news.db"]      # بدون فایل wal/journal جانبی

import sqlite3
from datetime import datetime, timedelta, timezone

from database import NewsDB
from helpers import NOW, TOKEN, make_article
from logger import register_secrets
from models import DRAFTED, FAILED, PUBLISHED, PUBLISHING, REJECTED


def test_article_is_recorded_and_not_duplicated():
    db = NewsDB(":memory:")
    a = make_article()
    db.upsert_discovered(a)
    db.upsert_discovered(a)

    row = db.get(a.canonical_url)

    assert row["status"] == "discovered"
    assert row["title"] == a.title
    assert db.conn.execute(
        "SELECT COUNT(*) FROM articles"
    ).fetchone()[0] == 1


def test_publish_flow_and_published_detection():
    db = NewsDB(":memory:")
    a = make_article()
    db.upsert_discovered(a)
    db.set_status(a.canonical_url, DRAFTED, score=80, draft="متن")

    assert db.begin_publishing(a.canonical_url, "متن", NOW) is True
    assert db.begin_publishing(a.canonical_url, "متن", NOW) is False

    db.mark_published(a.canonical_url, 42, NOW)

    row = db.get(a.canonical_url)

    assert row["status"] == PUBLISHED
    assert row["telegram_message_id"] == 42
    assert db.should_skip(a.canonical_url)

    db.set_status(a.canonical_url, REJECTED)

    assert db.get(a.canonical_url)["status"] == PUBLISHED


def test_daily_count_only_includes_today_and_ambiguous_counts_too():
    db = NewsDB(":memory:")
    day_start = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)

    for i, when in enumerate([
        day_start - timedelta(hours=1),
        day_start + timedelta(hours=2),
    ]):
        a = make_article(url=f"https://x.test/{i}")
        db.upsert_discovered(a)
        db.begin_publishing(a.canonical_url, "d", when)
        db.mark_published(a.canonical_url, i, when)

    amb = make_article(url="https://x.test/amb")
    db.upsert_discovered(amb)
    db.begin_publishing(
        amb.canonical_url,
        "d",
        day_start + timedelta(hours=3),
    )
    db.mark_unknown(amb.canonical_url, "timeout")

    assert db.count_consumed_since(day_start) == 2
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

    assert db.get(a.canonical_url)["status"] == FAILED
    assert db.should_skip(a.canonical_url)


def test_secrets_are_never_stored_in_database():
    register_secrets([TOKEN])
    db = NewsDB(":memory:")
    a = make_article()
    db.upsert_discovered(a)

    db.set_status(
        a.canonical_url,
        FAILED,
        error=(
            f"request to https://api.telegram.org/bot{TOKEN}/send "
            f"failed {TOKEN}"
        ),
    )

    dump = " ".join(str(v) for v in db.get(a.canonical_url).values())

    assert TOKEN not in dump
    assert "***" in dump


def test_database_persists_to_single_file(tmp_path):
    path = tmp_path / "sub" / "news.db"

    with NewsDB(path) as db:
        db.upsert_discovered(make_article())

    with NewsDB(path) as db:
        assert db.get(make_article().canonical_url) is not None

    assert sorted(p.name for p in path.parent.iterdir()) == ["news.db"]


# ---------- Bale tests ----------

def create_published_article(db, url="https://x.test/bale"):
    a = make_article(url=url)
    db.upsert_discovered(a)
    db.begin_publishing(a.canonical_url, "متن خبر", NOW)
    db.mark_published(
        a.canonical_url,
        123,
        NOW,
        bale_enabled=True,
    )
    return a


def test_bale_is_pending_only_when_enabled():
    db = NewsDB(":memory:")

    enabled = create_published_article(
        db,
        "https://x.test/enabled",
    )

    disabled = make_article(url="https://x.test/disabled")
    db.upsert_discovered(disabled)
    db.begin_publishing(disabled.canonical_url, "متن", NOW)
    db.mark_published(disabled.canonical_url, 456, NOW)

    assert db.get(enabled.canonical_url)["bale_status"] == "pending"
    assert db.get(disabled.canonical_url)["bale_status"] is None


def test_bale_pending_returns_only_eligible_articles():
    db = NewsDB(":memory:")

    a = create_published_article(db)

    pending = db.bale_pending(now=NOW)

    assert len(pending) == 1
    assert pending[0]["canonical_url"] == a.canonical_url


def test_bale_claim_is_atomic_and_cannot_start_twice():
    db = NewsDB(":memory:")
    a = create_published_article(db)

    assert db.begin_bale_publishing(a.canonical_url, NOW) is True
    assert db.begin_bale_publishing(a.canonical_url, NOW) is False

    row = db.get(a.canonical_url)

    assert row["bale_status"] == "sending"
    assert row["bale_attempts"] == 1


def test_bale_success_records_message_id_and_time():
    db = NewsDB(":memory:")
    a = create_published_article(db)

    db.begin_bale_publishing(a.canonical_url, NOW)
    db.mark_bale_sent(a.canonical_url, 789, NOW)

    row = db.get(a.canonical_url)

    assert row["status"] == PUBLISHED
    assert row["bale_status"] == "sent"
    assert row["bale_message_id"] == 789
    assert row["bale_published_at"] == NOW.isoformat(timespec="seconds")


def test_bale_failed_article_can_be_retried():
    db = NewsDB(":memory:")
    a = create_published_article(db)

    assert db.begin_bale_publishing(a.canonical_url, NOW)
    db.mark_bale_failed(a.canonical_url, "connection failed")

    row = db.get(a.canonical_url)

    assert row["bale_status"] == "failed"
    assert len(db.bale_pending(now=NOW)) == 1

    assert db.begin_bale_publishing(a.canonical_url, NOW)
    assert db.get(a.canonical_url)["bale_attempts"] == 2


def test_bale_failed_article_stops_after_three_attempts():
    db = NewsDB(":memory:")
    a = create_published_article(db)

    for _ in range(3):
        assert db.begin_bale_publishing(a.canonical_url, NOW)
        db.mark_bale_failed(a.canonical_url, "temporary failure")

    assert db.get(a.canonical_url)["bale_attempts"] == 3
    assert db.get(a.canonical_url)["bale_status"] == "failed"
    assert db.bale_pending(now=NOW) == []
    assert db.begin_bale_publishing(a.canonical_url, NOW) is False


def test_bale_unknown_is_never_retried():
    db = NewsDB(":memory:")
    a = create_published_article(db)

    assert db.begin_bale_publishing(a.canonical_url, NOW)
    db.mark_bale_unknown(a.canonical_url, "read timeout")

    row = db.get(a.canonical_url)

    assert row["bale_status"] == "unknown"
    assert db.bale_pending(now=NOW) == []
    assert db.begin_bale_publishing(a.canonical_url, NOW) is False


def test_bale_sending_is_not_retried():
    db = NewsDB(":memory:")
    a = create_published_article(db)

    assert db.begin_bale_publishing(a.canonical_url, NOW)

    assert db.bale_pending(now=NOW) == []
    assert db.begin_bale_publishing(a.canonical_url, NOW) is False


def test_old_bale_articles_are_not_retried():
    db = NewsDB(":memory:")
    a = create_published_article(db)

    future_now = NOW + timedelta(hours=49)

    assert db.bale_pending(now=future_now) == []
    assert db.begin_bale_publishing(
        a.canonical_url,
        future_now,
    ) is False


def test_bale_errors_are_redacted():
    register_secrets([TOKEN])

    db = NewsDB(":memory:")
    a = create_published_article(db)

    db.begin_bale_publishing(a.canonical_url, NOW)
    db.mark_bale_failed(
        a.canonical_url,
        f"request failed with token {TOKEN}",
    )

    row = db.get(a.canonical_url)

    assert TOKEN not in row["bale_last_error"]
    assert "***" in row["bale_last_error"]


def test_old_database_gets_bale_columns_without_losing_data(tmp_path):
    path = tmp_path / "old.db"

    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE articles (
            canonical_url TEXT PRIMARY KEY,
            url TEXT NOT NULL,
            title TEXT NOT NULL,
            source TEXT,
            published_at TEXT,
            fetched_at TEXT NOT NULL,
            score REAL,
            draft TEXT,
            status TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            publishing_started_at TEXT,
            telegram_published_at TEXT,
            telegram_message_id INTEGER,
            last_error TEXT
        );

        INSERT INTO articles (
            canonical_url,
            url,
            title,
            fetched_at,
            status
        )
        VALUES (
            'https://old.test/article',
            'https://old.test/article',
            'خبر قدیمی',
            '2026-11-01T10:00:00+00:00',
            'published'
        );
    """)
    conn.commit()
    conn.close()

    with NewsDB(path) as db:
        row = db.get("https://old.test/article")

        assert row["title"] == "خبر قدیمی"
        assert row["status"] == "published"
        assert row["bale_status"] is None
        assert row["bale_attempts"] == 0

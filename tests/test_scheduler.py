from datetime import datetime, timedelta, timezone

from database import NewsDB
from helpers import make_article, make_settings
from scheduler import allowed_this_run, day_start_utc, posts_remaining

S = make_settings()


def publish_n(db, n, when):
    for i in range(n):
        a = make_article(url=f"https://x.test/{when.isoformat()}/{i}")
        db.upsert_discovered(a)
        db.begin_publishing(a.canonical_url, "d", when)
        db.mark_published(a.canonical_url, i, when)


def test_tehran_day_starts_at_2030_utc_previous_day():
    now = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)
    assert day_start_utc(now, "Asia/Tehran") == datetime(
        2026, 10, 21, 20, 30, tzinfo=timezone.utc
    )


def test_tehran_day_boundary_is_respected():
    db = NewsDB(":memory:")
    before = datetime(2026, 10, 21, 20, 0, tzinfo=timezone.utc)
    publish_n(db, 4, before)

    now = datetime(2026, 10, 22, 5, 30, tzinfo=timezone.utc)
    assert posts_remaining(db, S, now) == 10


def test_daily_cap_of_ten_is_enforced_from_database():
    db = NewsDB(":memory:")
    now = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)

    publish_n(db, 9, now - timedelta(hours=1))
    assert allowed_this_run(db, S, now) == 1

    publish_n(db, 1, now - timedelta(minutes=30))
    assert allowed_this_run(db, S, now) == 0


def test_hard_cap_cannot_be_exceeded_by_settings():
    db = NewsDB(":memory:")
    now = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)

    big = make_settings(daily_post_limit=50, max_posts_per_run=50)
    assert allowed_this_run(db, big, now) == 10

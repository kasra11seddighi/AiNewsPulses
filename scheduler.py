"""منطق سقف روزانه (به وقت تهران) بر پایه‌ی SQLite؛ مستقل از تعداد اجراهای Workflow.

زمان‌بندی GitHub Actions در فایل .github/workflows/news-agent.yml است (cron بر پایه‌ی UTC).
تهران UTC+03:30 است (از ۱۴۰۱ ساعت تابستانی ندارد):
    09:00 → 05:30 UTC | 13:00 → 09:30 UTC | 17:00 → 13:30 UTC | 21:00 → 17:30 UTC
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo
from typing import Tuple

from config import HARD_MAX_DAILY_POSTS, Settings
from database import NewsDB

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None


def get_tz(name: str) -> tzinfo:
    if ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except Exception:
            pass
    if name == "Asia/Tehran":  # جایگزین وقتی tzdata نصب نیست
        return timezone(timedelta(hours=3, minutes=30))
    return timezone.utc


def day_start_utc(now: datetime, tz_name: str) -> datetime:
    tz = get_tz(tz_name)
    local = now.astimezone(tz)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(timezone.utc)


def posts_remaining(db: NewsDB, settings: Settings, now: datetime) -> int:
    limit = min(settings.daily_post_limit, HARD_MAX_DAILY_POSTS)
    used = db.count_consumed_since(day_start_utc(now, settings.timezone))
    return max(0, limit - used)


def allowed_this_run(db: NewsDB, settings: Settings, now: datetime) -> int:
    return min(posts_remaining(db, settings, now), settings.max_posts_per_run)

"""مدیریت SQLite: سابقه خبرها، وضعیت انتشار و سقف روزانه.

نکته: journal_mode=DELETE است تا پایگاه داده همیشه یک فایل واحد بماند (برای commit در Git).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

from logger import redact
from models import (DISCOVERED, DRAFTED, FAILED, PUBLISHED, PUBLISHING, REJECTED, Article)

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
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
CREATE INDEX IF NOT EXISTS idx_articles_status ON articles(status);
"""

MAX_FAILED_ATTEMPTS = 3


class DatabaseError(Exception):
    pass


def iso(dt: Optional[datetime] = None) -> str:
    dt = dt or datetime.now(timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


class NewsDB:
    def __init__(self, path):
        self.path = str(path)
        try:
            if self.path != ":memory:":
                Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(self.path, timeout=30)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA journal_mode=DELETE")
            self.conn.executescript(SCHEMA)
        except (sqlite3.Error, OSError) as exc:
            raise DatabaseError(f"cannot open database: {type(exc).__name__}") from None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        try:
            self.conn.close()
        except sqlite3.Error:
            pass

    def _run(self, sql: str, params: Iterable = ()) -> sqlite3.Cursor:
        try:
            with self.conn:  # commit/rollback اتمیک
                return self.conn.execute(sql, tuple(params))
        except sqlite3.Error as exc:
            raise DatabaseError(f"database error: {type(exc).__name__}: {exc}") from None

    @staticmethod
    def _err(error: Optional[str]) -> Optional[str]:
        return redact(error)[:500] if error else None

    # ---------- خواندن ----------
    def get(self, canonical_url: str) -> Optional[dict]:
        row = self._run("SELECT * FROM articles WHERE canonical_url=?", (canonical_url,)).fetchone()
        return dict(row) if row else None

    def should_skip(self, canonical_url: str) -> bool:
        """خبری که منتشر شده، در حال انتشار، رد شده یا بارها شکست خورده دوباره پردازش نمی‌شود."""
        row = self.get(canonical_url)
        if not row:
            return False
        if row["status"] in (PUBLISHED, PUBLISHING, REJECTED):
            return True
        return row["status"] == FAILED and row["attempts"] >= MAX_FAILED_ATTEMPTS

    def recent_titles(self, days: int = 7, now: Optional[datetime] = None) -> list:
        since = iso((now or datetime.now(timezone.utc)) - timedelta(days=days))
        rows = self._run(
            "SELECT title FROM articles WHERE status IN (?,?) AND "
            "COALESCE(telegram_published_at, publishing_started_at, fetched_at) >= ?",
            (PUBLISHED, PUBLISHING, since),
        ).fetchall()
        return [r["title"] for r in rows]

    def count_consumed_since(self, since: datetime) -> int:
        """تعداد پست‌های امروز؛ وضعیت مبهم (publishing) محتاطانه شمرده می‌شود."""
        s = iso(since)
        row = self._run(
            "SELECT COUNT(*) AS n FROM articles WHERE "
            "(status=? AND telegram_published_at>=?) OR (status=? AND publishing_started_at>=?)",
            (PUBLISHED, s, PUBLISHING, s),
        ).fetchone()
        return int(row["n"])

    def ambiguous(self) -> list:
        rows = self._run("SELECT canonical_url, title, publishing_started_at, last_error "
                         "FROM articles WHERE status=?", (PUBLISHING,)).fetchall()
        return [dict(r) for r in rows]

    # ---------- نوشتن ----------
    def upsert_discovered(self, art: Article) -> None:
        self._run(
            "INSERT INTO articles (canonical_url,url,title,source,published_at,fetched_at,status) "
            "VALUES (?,?,?,?,?,?,?) ON CONFLICT(canonical_url) DO NOTHING",
            (art.canonical_url, art.url, art.title[:500], art.source_name,
             iso(art.published_at) if art.published_at else None, iso(art.fetched_at), DISCOVERED),
        )

    def set_status(self, canonical_url: str, status: str, *, score: Optional[float] = None,
                   draft: Optional[str] = None, error: Optional[str] = None) -> None:
        """تغییر وضعیت؛ هرگز خبرِ published/publishing را تغییر نمی‌دهد."""
        self._run(
            "UPDATE articles SET status=?, score=COALESCE(?,score), draft=COALESCE(?,draft), "
            "last_error=? WHERE canonical_url=? AND status NOT IN (?,?)",
            (status, score, draft, self._err(error), canonical_url, PUBLISHED, PUBLISHING),
        )

    def begin_publishing(self, canonical_url: str, draft: str, now: Optional[datetime] = None) -> bool:
        cur = self._run(
            "UPDATE articles SET status=?, draft=?, publishing_started_at=?, attempts=attempts+1, "
            "last_error=NULL WHERE canonical_url=? AND status NOT IN (?,?)",
            (PUBLISHING, draft, iso(now), canonical_url, PUBLISHED, PUBLISHING),
        )
        return cur.rowcount == 1

    def mark_published(self, canonical_url: str, message_id: Optional[int], now: Optional[datetime] = None) -> None:
        self._run(
            "UPDATE articles SET status=?, telegram_published_at=?, telegram_message_id=?, last_error=NULL "
            "WHERE canonical_url=? AND status=?",
            (PUBLISHED, iso(now), message_id, canonical_url, PUBLISHING),
        )

    def mark_failed(self, canonical_url: str, error: str) -> None:
        """ارسال قطعاً انجام نشده است."""
        self._run("UPDATE articles SET status=?, last_error=? WHERE canonical_url=? AND status=?",
                  (FAILED, self._err(error), canonical_url, PUBLISHING))

    def mark_unknown(self, canonical_url: str, error: str) -> None:
        """نامعلوم ماندن ارسال: وضعیت publishing می‌ماند و هرگز خودکار دوباره ارسال نمی‌شود."""
        self._run("UPDATE articles SET last_error=? WHERE canonical_url=? AND status=?",
                  (self._err("UNKNOWN_DELIVERY: " + error), canonical_url, PUBLISHING))

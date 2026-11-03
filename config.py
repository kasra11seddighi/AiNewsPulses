"""تنظیمات برنامه: همه‌چیز از متغیرهای محیطی خوانده می‌شود و پیش‌فرض‌ها امن هستند."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Mapping, Optional

CHANNEL_HANDLE = "@AiNewsPulses"
BALE_CHANNEL_HANDLE = "@AINewsD1"

HARD_MAX_DAILY_POSTS = 10
TELEGRAM_MESSAGE_LIMIT = 4096

CATEGORY_HASHTAGS = {
    "ai": "#هوش_مصنوعی",
    "tech": "#فناوری",
    "programming": "#برنامه_نویسی",
    "data_science": "#علم_داده",
    "tutorial": "#آموزش",
}

DEFAULT_WEIGHTS = {
    "source": 25,
    "freshness": 20,
    "importance": 20,
    "relevance": 15,
    "evidence": 15,
    "image": 5,
}

_TRUE = {"1", "true", "yes", "on"}


def _get_bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in _TRUE


def _get_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def _get_str(env: Mapping[str, str], name: str, default: str) -> str:
    raw = env.get(name)
    return default if raw is None or raw.strip() == "" else raw.strip()


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str = field(default="", repr=False)
    telegram_channel_id: str = CHANNEL_HANDLE

    bale_bot_token: str = field(default="", repr=False)
    bale_channel_id: str = BALE_CHANNEL_HANDLE

    gemini_api_key: str = field(default="", repr=False)
    gemini_model: str = "gemini-2.5-flash"

    enable_publishing: bool = False
    enable_bale_publishing: bool = False

    daily_post_limit: int = HARD_MAX_DAILY_POSTS
    max_posts_per_run: int = 1
    min_quality_score: int = 65
    min_article_text_chars: int = 800

    allow_article_images: bool = False
    image_allowed_domains: tuple = ()
    max_article_age_days: int = 7

    database_path: str = "data/ainewspulses.db"
    log_level: str = "INFO"
    timezone: str = "Asia/Tehran"

    channel_handle: str = CHANNEL_HANDLE
    weights: Mapping[str, float] = field(
        default_factory=lambda: dict(DEFAULT_WEIGHTS)
    )

    @classmethod
    def from_env(
        cls,
        env: Optional[Mapping[str, str]] = None
    ) -> "Settings":

        env = os.environ if env is None else env

        weights = dict(DEFAULT_WEIGHTS)
        raw_weights = env.get("SCORE_WEIGHTS", "").strip()

        if raw_weights:
            try:
                parsed = json.loads(raw_weights)

                for key, value in parsed.items():
                    if (
                        key in weights
                        and isinstance(value, (int, float))
                        and value >= 0
                    ):
                        weights[key] = float(value)

            except (ValueError, AttributeError):
                pass

        domains = tuple(
            d.strip().lower()
            for d in env.get("IMAGE_ALLOWED_DOMAINS", "").split(",")
            if d.strip()
        )

        daily = _get_int(
            env,
            "DAILY_POST_LIMIT",
            HARD_MAX_DAILY_POSTS
        )

        daily = max(0, min(daily, HARD_MAX_DAILY_POSTS))

        return cls(
            telegram_bot_token=_get_str(
                env,
                "TELEGRAM_BOT_TOKEN",
                ""
            ),

            telegram_channel_id=_get_str(
                env,
                "TELEGRAM_CHANNEL_ID",
                CHANNEL_HANDLE
            ),

            bale_bot_token=_get_str(
                env,
                "BALE_BOT_TOKEN",
                ""
            ),

            bale_channel_id=_get_str(
                env,
                "BALE_CHANNEL_ID",
                BALE_CHANNEL_HANDLE
            ),

            gemini_api_key=_get_str(
                env,
                "GEMINI_API_KEY",
                ""
            ),

            gemini_model=_get_str(
                env,
                "GEMINI_MODEL",
                "gemini-2.5-flash"
            ),

            enable_publishing=_get_bool(
                env,
                "ENABLE_PUBLISHING",
                False
            ),

            enable_bale_publishing=_get_bool(
                env,
                "ENABLE_BALE_PUBLISHING",
                False
            ),

            daily_post_limit=daily,

            max_posts_per_run=max(
                1,
                _get_int(env, "MAX_POSTS_PER_RUN", 1)
            ),

            min_quality_score=_get_int(
                env,
                "MIN_QUALITY_SCORE",
                65
            ),

            min_article_text_chars=_get_int(
                env,
                "MIN_ARTICLE_TEXT_CHARS",
                800
            ),

            allow_article_images=_get_bool(
                env,
                "ALLOW_ARTICLE_IMAGES",
                False
            ),

            image_allowed_domains=domains,

            max_article_age_days=max(
                1,
                _get_int(env, "MAX_ARTICLE_AGE_DAYS", 7)
            ),

            database_path=_get_str(
                env,
                "DATABASE_PATH",
                "data/ainewspulses.db"
            ),

            log_level=_get_str(
                env,
                "LOG_LEVEL",
                "INFO"
            ).upper(),

            timezone=_get_str(
                env,
                "TIMEZONE",
                "Asia/Tehran"
            ),

            weights=weights,
        )

    def publishing_active(self, dry_run: bool = False) -> bool:
        """بررسی امکان انتشار در تلگرام."""

        if dry_run or not self.enable_publishing:
            return False

        return bool(
            self.telegram_bot_token
            and self.telegram_channel_id
        )

    def bale_active(self, dry_run: bool = False) -> bool:
        """بررسی امکان انتشار در بله."""

        if dry_run or not self.enable_bale_publishing:
            return False

        return bool(
            self.bale_bot_token
            and self.bale_channel_id
        )

    def secrets(self) -> list:
        """مقادیر محرمانه برای مخفی‌سازی در لاگ‌ها."""

        return [
            secret
            for secret in (
                self.telegram_bot_token,
                self.bale_bot_token,
                self.gemini_api_key,
            )
            if secret
        ]

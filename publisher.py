"""ارسال امن به Telegram و Bale Bot API.

نتیجه ارسال:
  sent    – API موفقیت را تأیید کرد.
  failed  – مطمئنیم پیام ارسال نشده است.
  unknown – ممکن است پیام ارسال شده باشد؛ ارسال مجدد خودکار ممنوع است.
  skipped – انتشار غیرفعال است.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

import requests
import urllib3

from config import TELEGRAM_MESSAGE_LIMIT
from logger import get_logger, redact

log = get_logger("publisher")

CAPTION_LIMIT = 1024
MAX_RETRY_AFTER = 60
BALE_MESSAGE_LIMIT = 4096


@dataclass
class PublishResult:
    status: str
    message_id: Optional[int] = None
    error: str = ""


class DryRunPublisher:
    """جایگزین امن: هیچ‌وقت به شبکه یا توکن دسترسی ندارد."""

    def send(
        self,
        text: str,
        image: Optional[bytes] = None,
    ) -> PublishResult:
        return PublishResult(
            "skipped",
            error="publishing disabled or dry-run",
        )


def _never_sent(exc: requests.RequestException) -> bool:
    """فقط وقتی مطمئنیم درخواست به سرور نرسیده، retry امن است."""

    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return True

    if isinstance(exc, requests.exceptions.ConnectionError):
        reason = (
            getattr(exc.args[0], "reason", None)
            if exc.args
            else None
        )

        return isinstance(
            reason,
            urllib3.exceptions.NewConnectionError,
        )

    return False


class TelegramPublisher:
    """ناشر Telegram Bot API."""

    def __init__(
        self,
        token: str,
        chat_id: str,
        *,
        session: Optional[requests.Session] = None,
        timeout: float = 20,
        max_retries: int = 2,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if not token or not chat_id:
            raise ValueError(
                "Telegram token and channel id are required"
            )

        self._token = token
        self.chat_id = chat_id
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_retries = max_retries
        self.sleep = sleep

    def _url(self, method: str) -> str:
        return (
            f"https://api.telegram.org/"
            f"bot{self._token}/{method}"
        )

    def send(
        self,
        text: str,
        image: Optional[bytes] = None,
    ) -> PublishResult:

        if len(text) > TELEGRAM_MESSAGE_LIMIT:
            return PublishResult(
                "failed",
                error="message exceeds Telegram limit",
            )

        use_photo = (
            image is not None
            and len(text) <= CAPTION_LIMIT
        )

        method = "sendPhoto" if use_photo else "sendMessage"

        for attempt in range(self.max_retries + 1):
            try:
                if use_photo:
                    resp = self.session.post(
                        self._url(method),
                        timeout=self.timeout,
                        data={
                            "chat_id": self.chat_id,
                            "caption": text,
                        },
                        files={
                            "photo": ("image.jpg", image),
                        },
                    )

                else:
                    resp = self.session.post(
                        self._url(method),
                        timeout=self.timeout,
                        data={
                            "chat_id": self.chat_id,
                            "text": text,
                        },
                    )

            except requests.RequestException as exc:

                if _never_sent(exc):
                    if attempt < self.max_retries:
                        self.sleep(2 ** attempt)
                        continue

                    return PublishResult(
                        "failed",
                        error=(
                            f"connection failed: "
                            f"{type(exc).__name__}"
                        ),
                    )

                return PublishResult(
                    "unknown",
                    error=(
                        f"no response: "
                        f"{type(exc).__name__}"
                    ),
                )

            try:
                body = resp.json()

            except ValueError:
                return PublishResult(
                    "unknown",
                    error=(
                        f"non-JSON response "
                        f"(HTTP {resp.status_code})"
                    ),
                )

            if resp.status_code == 200 and body.get("ok") is True:
                msg_id = (
                    body.get("result") or {}
                ).get("message_id")

                return PublishResult(
                    "sent",
                    message_id=(
                        msg_id
                        if isinstance(msg_id, int)
                        else None
                    ),
                )

            if resp.status_code == 429:
                wait = (
                    body.get("parameters") or {}
                ).get("retry_after", 5)

                wait = min(
                    int(wait)
                    if isinstance(wait, (int, float))
                    else 5,
                    MAX_RETRY_AFTER,
                )

                if attempt < self.max_retries:
                    self.sleep(wait)
                    continue

                return PublishResult(
                    "failed",
                    error="rate limited by Telegram",
                )

            if resp.status_code >= 500:
                return PublishResult(
                    "unknown",
                    error=(
                        f"Telegram server error "
                        f"{resp.status_code}"
                    ),
                )

            desc = redact(
                str(body.get("description", ""))
            )[:200]

            return PublishResult(
                "failed",
                error=(
                    f"Telegram rejected message "
                    f"({resp.status_code}): {desc}"
                ),
            )

        return PublishResult(
            "failed",
            error="exhausted retries",
        )


class BalePublisher:
    """ناشر مستقل برای Bale Bot API."""

    def __init__(
        self,
        token: str,
        chat_id: str,
        *,
        session: Optional[requests.Session] = None,
        timeout: float = 20,
        max_retries: int = 2,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if not token or not chat_id:
            raise ValueError(
                "Bale token and channel id are required"
            )

        self._token = token
        self.chat_id = chat_id
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_retries = max_retries
        self.sleep = sleep

    def _url(self) -> str:
        return (
            f"https://tapi.bale.ai/"
            f"bot{self._token}/sendMessage"
        )

    def send(
        self,
        text: str,
        image: Optional[bytes] = None,
    ) -> PublishResult:

        # فعلاً فقط ارسال متن پشتیبانی می‌شود.
        if len(text) > BALE_MESSAGE_LIMIT:
            return PublishResult(
                "failed",
                error="message exceeds Bale limit",
            )

        payload = {
            "chat_id": self.chat_id,
            "text": text,
        }

        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.post(
                    self._url(),
                    json=payload,
                    timeout=self.timeout,
                )

            except requests.RequestException as exc:

                if _never_sent(exc):
                    if attempt < self.max_retries:
                        self.sleep(2 ** attempt)
                        continue

                    return PublishResult(
                        "failed",
                        error=(
                            f"Bale connection failed: "
                            f"{type(exc).__name__}"
                        ),
                    )

                return PublishResult(
                    "unknown",
                    error=(
                        f"Bale response unknown: "
                        f"{type(exc).__name__}"
                    ),
                )

            try:
                body = response.json()

            except ValueError:
                return PublishResult(
                    "unknown",
                    error=(
                        f"Bale non-JSON response "
                        f"(HTTP {response.status_code})"
                    ),
                )

            if (
                response.status_code == 200
                and body.get("ok") is True
            ):
                message_id = (
                    body.get("result") or {}
                ).get("message_id")

                return PublishResult(
                    "sent",
                    message_id=(
                        message_id
                        if isinstance(message_id, int)
                        else None
                    ),
                )

            if response.status_code == 429:
                wait = (
                    body.get("parameters") or {}
                ).get("retry_after", 5)

                wait = min(
                    int(wait)
                    if isinstance(wait, (int, float))
                    else 5,
                    MAX_RETRY_AFTER,
                )

                if attempt < self.max_retries:
                    self.sleep(wait)
                    continue

                return PublishResult(
                    "failed",
                    error="rate limited by Bale",
                )

            if response.status_code >= 500:
                return PublishResult(
                    "unknown",
                    error=(
                        f"Bale server error "
                        f"{response.status_code}"
                    ),
                )

            description = redact(
                str(body.get("description", ""))
            )[:200]

            return PublishResult(
                "failed",
                error=(
                    f"Bale rejected message "
                    f"({response.status_code}): "
                    f"{description}"
                ),
            )

        return PublishResult(
            "failed",
            error="Bale exhausted retries",
        )


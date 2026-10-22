"""لاگ ساختاریافته (key=value) با پاک‌سازی خودکار Secrets."""
from __future__ import annotations

import logging
import re
import sys
from typing import Iterable

_SECRETS: set = set()
_PATTERNS = [
    re.compile(r"bot\d{6,}:[A-Za-z0-9_-]{20,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
]
ROOT_NAME = "ainewspulses"


def register_secrets(values: Iterable[str]) -> None:
    for value in values:
        if value and len(value) >= 6:
            _SECRETS.add(value)


def clear_secrets() -> None:
    _SECRETS.clear()


def redact(text) -> str:
    out = str(text)
    for secret in sorted(_SECRETS, key=len, reverse=True):
        out = out.replace(secret, "***")
    for pattern in _PATTERNS:
        out = pattern.sub("***", out)
    return out


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def setup_logging(level: str = "INFO") -> logging.Logger:
    root = logging.getLogger(ROOT_NAME)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        RedactingFormatter("%(asctime)s %(levelname)s %(name)s | %(message)s")
    )
    root.addHandler(handler)
    root.propagate = False
    return root


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"{ROOT_NAME}.{name}")


def log_event(logger: logging.Logger, level: int, event: str, **fields) -> None:
    parts = [event] + [f"{k}={v!r}" if isinstance(v, str) else f"{k}={v}" for k, v in fields.items()]
    logger.log(level, " ".join(parts))

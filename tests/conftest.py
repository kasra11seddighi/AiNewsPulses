import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import logger  # noqa: E402


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """هیچ تستی نباید به شبکه (و در نتیجه Telegram یا Gemini واقعی) دسترسی داشته باشد."""
    def blocked(*args, **kwargs):
        raise RuntimeError("Network access is forbidden in tests")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    yield
    logger.clear_secrets()

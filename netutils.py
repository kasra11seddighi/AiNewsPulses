"""دریافت امن از وب: محدودیت حجم، بررسی redirect، و بلاک آدرس‌های داخلی/خصوصی."""
from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from typing import Callable, Optional, Sequence
from urllib.parse import urljoin, urlparse

import requests

USER_AGENT = "AiNewsPulsesBot/1.0 (+https://t.me/AiNewsPulses)"


class FetchError(Exception):
    """خطای دریافت؛ پیام آن هرگز شامل URL یا Secret نیست."""


@dataclass
class Page:
    url: str
    content_type: str
    content: bytes
    charset: Optional[str] = None

    def text(self) -> str:
        for enc in (self.charset, "utf-8"):
            if not enc:
                continue
            try:
                return self.content.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return self.content.decode("utf-8", errors="replace")


def is_public_http_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    if host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        pass  # نام دامنه است
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return False
    return all(ipaddress.ip_address(i[4][0]).is_global for i in infos)


def safe_get(
    url: str,
    *,
    timeout: float = 15,
    max_bytes: int = 2_500_000,
    allowed_types: Optional[Sequence[str]] = None,
    session: Optional[requests.Session] = None,
    max_redirects: int = 5,
    url_checker: Optional[Callable[[str], bool]] = None,
) -> Page:
    checker = url_checker or is_public_http_url
    sess = session or requests.Session()
    current = url
    for _ in range(max_redirects + 1):
        if not checker(current):
            raise FetchError("blocked or invalid URL")
        try:
            resp = sess.get(
                current,
                timeout=timeout,
                stream=True,
                allow_redirects=False,
                headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
            )
        except requests.RequestException as exc:
            raise FetchError(f"request failed: {type(exc).__name__}") from None
        try:
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("Location")
                if not location:
                    raise FetchError("redirect without location")
                current = urljoin(current, location)
                continue
            if resp.status_code >= 400:
                raise FetchError(f"HTTP {resp.status_code}")
            header = resp.headers.get("Content-Type", "")
            ctype = header.split(";")[0].strip().lower()
            if allowed_types and ctype not in allowed_types:
                raise FetchError(f"unexpected content-type: {ctype or 'unknown'}")
            declared = resp.headers.get("Content-Length", "")
            if declared.isdigit() and int(declared) > max_bytes:
                raise FetchError("response too large")
            chunks, size = [], 0
            for chunk in resp.iter_content(16384):
                size += len(chunk)
                if size > max_bytes:
                    raise FetchError("response too large")
                chunks.append(chunk)
            match = re.search(r"charset=([\w-]+)", header, re.I)
            return Page(current, ctype, b"".join(chunks), match.group(1) if match else None)
        finally:
            resp.close()
    raise FetchError("too many redirects")

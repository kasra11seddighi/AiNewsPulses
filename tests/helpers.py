from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from typing import List, Optional

from config import Settings
from deduplicator import normalize_url
from models import Article
from netutils import FetchError, Page
from publisher import PublishResult
from writer import Draft

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)
TOKEN = "123456789:AAFakeTelegramTokenForTestsOnly_1234567"
GEMINI_KEY = "AIzaFakeGeminiKeyForTestsOnly_123456789"

LONG_TEXT = " ".join(
    ["The company released a new open-source language model for developers and researchers."
     " The model supports a context window of 128000 tokens and is designed for coding assistants."
     " Engineers can download the weights and run the model on their own infrastructure today."
     " The announcement also describes tooling for evaluation and fine tuning workflows."] * 4
)

GOOD_TITLE = "معرفی مدل متن‌باز جدید برای توسعه‌دهندگان"
GOOD_BODY = (
    "شرکت یک مدل زبانی متن‌باز جدید را برای توسعه‌دهندگان و پژوهشگران معرفی کرده است. "
    "این مدل از پنجره‌ی زمینه‌ی ۱۲۸۰۰۰ توکن پشتیبانی می‌کند و برای دستیارهای برنامه‌نویسی طراحی شده است.\n\n"
    "به گفته‌ی منبع، مهندسان می‌توانند وزن‌های مدل را دریافت کنند و آن را روی زیرساخت خودشان اجرا کنند."
)


def make_settings(**over) -> Settings:
    base = dict(telegram_bot_token=TOKEN, telegram_channel_id="@AiNewsPulses", gemini_api_key=GEMINI_KEY,
                enable_publishing=False, database_path=":memory:")
    base.update(over)
    return Settings(**base)


def make_article(url="https://example.org/post-1", title="OpenAI releases a new open-source model for developers",
                 hours_old=2, text=LONG_TEXT, ok=True, trust=0.95, kind="official", hint="ai",
                 summary="A new open-source language model was released for developers. " * 4) -> Article:
    return Article(url=url, canonical_url=normalize_url(url), title=title, source_name="TestSource",
                   source_kind=kind, source_trust=trust, category_hint=hint,
                   published_at=NOW - timedelta(hours=hours_old) if hours_old is not None else None,
                   summary=summary, text=text, extraction_ok=ok, fetched_at=NOW)


def good_post(article: Article, settings=None, title=GOOD_TITLE, body=GOOD_BODY, tag="#هوش_مصنوعی") -> str:
    handle = (settings.channel_handle if settings else "@AiNewsPulses")
    return f"{tag}\n\n📰 {title}\n\n{body}\n\n🔗 منبع اصلی:\n{article.url}\n\n{handle}"


def make_rss(items) -> bytes:
    body = ""
    for title, link, when, desc in items:
        body += (f"<item><title>{title}</title><link>{link}</link>"
                 f"<pubDate>{format_datetime(when)}</pubDate><description>{desc}</description></item>")
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>{body}</channel></rss>'.encode()


def make_html(text=LONG_TEXT, image=None) -> bytes:
    paras = "".join(f"<p>{s.strip()}.</p>" for s in text.split(".") if len(s.strip()) > 40)
    meta = f'<meta property="og:image" content="{image}">' if image else ""
    return f"<html><head>{meta}</head><body><nav>menu</nav><article>{paras}</article></body></html>".encode()


class FakeFetcher:
    def __init__(self, pages: dict):
        self.pages, self.calls = pages, []

    def __call__(self, url, **kwargs):
        self.calls.append(url)
        if url not in self.pages:
            raise FetchError("HTTP 404")
        return Page(url, "text/html", self.pages[url], "utf-8")


class FakeWriter:
    def __init__(self, draft: Optional[Draft] = None, error: Optional[Exception] = None):
        self.draft = draft or Draft(False, GOOD_TITLE, GOOD_BODY)
        self.error, self.calls = error, 0

    def generate(self, article, evidence, mode, category, depth, feedback=None):
        self.calls += 1
        if self.error:
            raise self.error
        return self.draft


class FakePublisher:
    def __init__(self, result: Optional[PublishResult] = None):
        self.result = result or PublishResult("sent", message_id=77)
        self.sent: List[str] = []

    def send(self, text, image=None):
        self.sent.append(text)
        return self.result


class FakeResp:
    def __init__(self, status=200, data=None):
        self.status_code, self._data = status, data

    def json(self):
        if self._data is None:
            raise ValueError("no json")
        return self._data


class FakeSession:
    """session ساختگی؛ هر عنصر صف یا FakeResp است یا یک Exception که پرتاب می‌شود."""
    def __init__(self, queue):
        self.queue, self.calls = list(queue), []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

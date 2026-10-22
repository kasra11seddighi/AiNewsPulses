from datetime import timedelta

from collector import collect_all, parse_feed
from helpers import NOW, FakeFetcher, make_rss
from models import Source

SRC = Source("Feed A", "https://a.test/rss", "official", "ai", 0.9)
ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>x</title>
<entry><title>Atom post</title><link rel="alternate" href="https://b.test/p1?utm_source=x"/>
<published>2026-10-22T10:00:00Z</published><summary>&lt;p&gt;Hello &lt;b&gt;world&lt;/b&gt;&lt;/p&gt;</summary></entry></feed>"""


def test_valid_rss_is_parsed():
    xml = make_rss([("Hello AI", "https://a.test/1", NOW - timedelta(hours=1), "<p>Desc <b>bold</b></p>")])
    arts = parse_feed(xml, SRC, NOW)
    assert len(arts) == 1
    a = arts[0]
    assert a.title == "Hello AI" and a.url == "https://a.test/1"
    assert a.summary == "Desc bold"
    assert a.source_name == "Feed A" and a.source_trust == 0.9
    assert a.published_at == NOW - timedelta(hours=1)


def test_atom_feed_is_parsed_and_url_kept_verbatim():
    arts = parse_feed(ATOM, SRC, NOW)
    assert arts[0].url == "https://b.test/p1?utm_source=x"          # لینک اصلی دست‌نخورده
    assert arts[0].canonical_url == "https://b.test/p1"             # نسخه‌ی نرمال بدون UTM
    assert arts[0].summary == "Hello world"


def test_broken_feed_does_not_stop_other_sources():
    good = make_rss([("Good", "https://ok.test/1", NOW, "d" * 50)])
    fetcher = FakeFetcher({"https://bad.test/rss": b"<html>not a feed</html>",
                           "https://ok.test/rss": good})
    sources = [Source("Bad", "https://bad.test/rss"), Source("Missing", "https://gone.test/rss"),
               Source("Ok", "https://ok.test/rss")]
    res = collect_all(sources, fetcher, NOW)
    assert [a.title for a in res.articles] == ["Good"]
    assert [(r.source, r.ok) for r in res.results] == [("Bad", False), ("Missing", False), ("Ok", True)]


def test_disabled_and_empty_url_sources_are_skipped():
    fetcher = FakeFetcher({})
    res = collect_all([Source("Off", "https://x.test/rss", enabled=False), Source("NoUrl", "")], fetcher, NOW)
    assert res.articles == [] and fetcher.calls == []


def test_entries_without_link_are_ignored():
    xml = b'<rss><channel><item><title>No link</title></item><item><title>Ok</title><link>https://a.test/2</link></item></channel></rss>'
    assert [a.title for a in parse_feed(xml, SRC, NOW)] == ["Ok"]

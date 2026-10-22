from database import NewsDB
from deduplicator import filter_duplicates, normalize_url, titles_similar
from helpers import make_article


def test_normalize_removes_tracking_but_keeps_meaningful_params():
    assert normalize_url("http://www.Example.com/a/?utm_source=x&id=5&fbclid=abc#frag") == "https://example.com/a?id=5"
    assert normalize_url("https://example.com/a/") == normalize_url("https://example.com/a")


def test_similar_titles():
    assert titles_similar("OpenAI releases GPT-5 today!", "OpenAI releases GPT-5 today")
    assert not titles_similar("OpenAI releases a model", "NVIDIA ships a new GPU")


def test_duplicate_urls_in_batch_are_dropped():
    db = NewsDB(":memory:")
    a = make_article(url="https://x.test/p?utm_source=a", title="First unique title about models")
    b = make_article(url="https://x.test/p?utm_medium=b", title="Second different headline entirely here")
    kept, dropped = filter_duplicates([a, b], db)
    assert len(kept) == 1 and len(dropped) == 1


def test_already_published_link_is_never_selected_again():
    db = NewsDB(":memory:")
    a = make_article()
    db.upsert_discovered(a)
    assert db.begin_publishing(a.canonical_url, "draft")
    db.mark_published(a.canonical_url, 5)
    kept, dropped = filter_duplicates([make_article()], db)
    assert kept == [] and dropped[0][1] == "already processed"


def test_title_similar_to_recent_published_is_dropped():
    db = NewsDB(":memory:")
    kept, dropped = filter_duplicates([make_article(title="OpenAI releases new model")], db,
                                      ["OpenAI releases new model!"])
    assert kept == [] and "similar" in dropped[0][1]


def test_higher_trust_source_wins_among_similar_titles():
    db = NewsDB(":memory:")
    low = make_article(url="https://m.test/1", title="Google launches Gemini update", trust=0.7)
    high = make_article(url="https://g.test/1", title="Google launches Gemini update", trust=0.95)
    kept, _ = filter_duplicates([low, high], db)
    assert kept[0].url == "https://g.test/1"

from extractor import extract_article, extract_text, MIN_USEFUL_CHARS
from helpers import FakeFetcher, make_article, make_html, LONG_TEXT


def test_extracts_main_text_and_ignores_navigation():
    text = extract_text(make_html().decode())
    assert "128000 tokens" in text and "menu" not in text


def test_extract_article_sets_text_and_image():
    art = make_article(text="", ok=False)
    art.image_url = None
    fetcher = FakeFetcher({art.url: make_html(image="/img/cover.png")})
    extract_article(art, fetcher)
    assert art.extraction_ok and len(art.text) >= MIN_USEFUL_CHARS
    assert art.image_url == "https://example.org/img/cover.png"


def test_fetch_failure_leaves_article_unextracted():
    art = make_article(text="", ok=False)
    extract_article(art, FakeFetcher({}))
    assert art.extraction_ok is False and art.text == ""


def test_short_page_is_not_marked_ok():
    art = make_article(text="", ok=False)
    extract_article(art, FakeFetcher({art.url: b"<html><body><article><p>Tiny page text that is short but long enough to keep.</p></article></body></html>"}))
    assert art.extraction_ok is False

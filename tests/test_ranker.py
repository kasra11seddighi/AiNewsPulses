from dataclasses import replace

from helpers import NOW, make_article, make_settings
from ranker import classify, rank_articles, score_article

S = make_settings()


def test_fresh_official_article_scores_high_and_is_accepted():
    r = score_article(make_article(), S, NOW)
    assert r.total >= 65 and r.reject_reason is None
    assert set(r.breakdown) == {"source", "freshness", "importance", "relevance", "evidence", "image"}


def test_old_article_is_rejected_with_reason():
    acc, rej = rank_articles([make_article(hours_old=24 * 20)], S, NOW)
    assert acc == [] and "too old" in rej[0][1]


def test_weak_media_article_is_rejected_below_threshold():
    weak = make_article(trust=0.5, kind="media", hint="tech", title="Local gadget roundup",
                        summary="short", text="", ok=False, hours_old=24 * 5)
    acc, rej = rank_articles([weak], S, NOW)
    assert acc == [] and "below" in rej[0][1]


def test_promotional_content_is_penalized():
    normal = score_article(make_article(), S, NOW).breakdown["importance"]
    promo = score_article(make_article(title="Sponsored webinar: register now for our new model"), S, NOW).breakdown["importance"]
    assert promo < normal


def test_missing_image_does_not_reject_important_news():
    art = make_article()
    art.image_url = None
    acc, _ = rank_articles([art], S, NOW)
    assert acc == [art]


def test_weights_are_configurable():
    heavy = replace(S, weights={**S.weights, "source": 0})
    assert score_article(make_article(), heavy, NOW).breakdown["source"] == 0


def test_results_sorted_by_score():
    a = make_article(url="https://a.test/1", hours_old=1)
    b = make_article(url="https://a.test/2", hours_old=24 * 5)
    acc, _ = rank_articles([b, a], S, NOW)
    assert acc[0] is a


def test_classification_and_tutorial_separation():
    assert classify(make_article(title="New Python 3.14 release for developers", hint="programming")) == "programming"
    tut = make_article(kind="tutorial", hint="tutorial", title="How to use pandas groupby")
    assert classify(tut) == "tutorial"

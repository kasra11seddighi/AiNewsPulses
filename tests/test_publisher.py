import requests
import urllib3

from helpers import TOKEN, FakeResp, FakeSession
from publisher import (
    BalePublisher,
    DryRunPublisher,
    TelegramPublisher,
)


# ==========================================
# Telegram Tests
# ==========================================

def make(queue, **kw):
    sleeps = []

    pub = TelegramPublisher(
        TOKEN,
        "@AiNewsPulses",
        session=FakeSession(queue),
        sleep=sleeps.append,
        **kw,
    )

    return pub, sleeps


def test_success_requires_api_confirmation():
    pub, _ = make([
        FakeResp(200, {"ok": True, "result": {"message_id": 9}})
    ])

    res = pub.send("سلام")

    assert res.status == "sent"
    assert res.message_id == 9
    assert pub.session.calls[0][1]["timeout"] > 0


def test_http_200_with_ok_false_is_failure():
    pub, _ = make([
        FakeResp(200, {"ok": False, "description": "bad"})
    ])

    assert pub.send("x").status == "failed"


def test_permanent_error_is_failed_and_not_retried():
    pub, _ = make([
        FakeResp(400, {
            "ok": False,
            "description": "chat not found",
        })
    ])

    res = pub.send("x")

    assert res.status == "failed"
    assert "chat not found" in res.error
    assert len(pub.session.calls) == 1


def test_read_timeout_is_unknown_and_never_resent():
    pub, _ = make([
        requests.exceptions.ReadTimeout("slow")
    ])

    res = pub.send("x")

    assert res.status == "unknown"
    assert len(pub.session.calls) == 1


def test_server_error_is_unknown_not_blindly_retried():
    pub, _ = make([
        FakeResp(502, {"ok": False})
    ])

    res = pub.send("x")

    assert res.status == "unknown"
    assert len(pub.session.calls) == 1


def test_rate_limit_is_retried_with_retry_after_then_gives_up():
    pub, sleeps = make(
        [FakeResp(429, {"parameters": {"retry_after": 3}})] * 3,
        max_retries=2,
    )

    res = pub.send("x")

    assert res.status == "failed"
    assert sleeps == [3, 3]
    assert len(pub.session.calls) == 3


def test_connection_that_never_reached_server_is_retried_safely():
    refused = requests.exceptions.ConnectionError(
        urllib3.exceptions.MaxRetryError(
            None,
            "u",
            reason=urllib3.exceptions.NewConnectionError(
                None,
                "refused",
            ),
        )
    )

    pub, _ = make([
        refused,
        FakeResp(200, {"ok": True, "result": {"message_id": 1}}),
    ])

    res = pub.send("x")

    assert res.status == "sent"
    assert len(pub.session.calls) == 2


def test_too_long_message_is_rejected_before_any_request():
    pub, _ = make([])

    res = pub.send("ا" * 5000)

    assert res.status == "failed"
    assert pub.session.calls == []


def test_token_never_appears_in_error_text():
    pub, _ = make([
        requests.exceptions.ReadTimeout(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        )
    ])

    res = pub.send("x")

    assert TOKEN not in res.error


def test_photo_used_only_when_caption_fits():
    pub, _ = make([
        FakeResp(200, {"ok": True, "result": {"message_id": 1}})
    ])

    pub.send("کوتاه", image=b"\xff\xd8\xffdata")

    assert pub.session.calls[0][0].endswith("/sendPhoto")


def test_dry_run_publisher_never_sends():
    assert DryRunPublisher().send("x").status == "skipped"


# ==========================================
# Bale Tests
# ==========================================

def make_bale(queue, **kw):
    sleeps = []

    pub = BalePublisher(
        TOKEN,
        "@AINewsD1",
        session=FakeSession(queue),
        sleep=sleeps.append,
        **kw,
    )

    return pub, sleeps


def test_bale_success_requires_api_confirmation():
    pub, _ = make_bale([
        FakeResp(200, {"ok": True, "result": {"message_id": 15}})
    ])

    res = pub.send("سلام از بله")

    assert res.status == "sent"
    assert res.message_id == 15

    url, kwargs = pub.session.calls[0]

    assert url.endswith("/sendMessage")
    assert kwargs["json"] == {
        "chat_id": "@AINewsD1",
        "text": "سلام از بله",
    }
    assert kwargs["timeout"] > 0


def test_bale_http_200_with_ok_false_is_failure():
    pub, _ = make_bale([
        FakeResp(200, {"ok": False, "description": "bad"})
    ])

    assert pub.send("x").status == "failed"


def test_bale_permanent_error_is_not_retried():
    pub, _ = make_bale([
        FakeResp(400, {
            "ok": False,
            "description": "chat not found",
        })
    ])

    res = pub.send("x")

    assert res.status == "failed"
    assert "chat not found" in res.error
    assert len(pub.session.calls) == 1


def test_bale_read_timeout_is_unknown_and_never_resent():
    pub, _ = make_bale([
        requests.exceptions.ReadTimeout("slow")
    ])

    res = pub.send("x")

    assert res.status == "unknown"
    assert len(pub.session.calls) == 1


def test_bale_server_error_is_unknown_not_retried():
    pub, _ = make_bale([
        FakeResp(502, {"ok": False})
    ])

    res = pub.send("x")

    assert res.status == "unknown"
    assert len(pub.session.calls) == 1


def test_bale_rate_limit_is_retried():
    pub, sleeps = make_bale(
        [FakeResp(429, {"parameters": {"retry_after": 4}})] * 3,
        max_retries=2,
    )

    res = pub.send("x")

    assert res.status == "failed"
    assert sleeps == [4, 4]
    assert len(pub.session.calls) == 3


def test_bale_connection_failure_is_retried_safely():
    refused = requests.exceptions.ConnectionError(
        urllib3.exceptions.MaxRetryError(
            None,
            "u",
            reason=urllib3.exceptions.NewConnectionError(
                None,
                "refused",
            ),
        )
    )

    pub, _ = make_bale([
        refused,
        FakeResp(200, {"ok": True, "result": {"message_id": 2}}),
    ])

    res = pub.send("x")

    assert res.status == "sent"
    assert len(pub.session.calls) == 2


def test_bale_too_long_message_is_rejected_before_request():
    pub, _ = make_bale([])

    res = pub.send("ا" * 5000)

    assert res.status == "failed"
    assert pub.session.calls == []


def test_bale_token_never_appears_in_error_text():
    pub, _ = make_bale([
        requests.exceptions.ReadTimeout(
            f"https://tapi.bale.ai/bot{TOKEN}/sendMessage"
        )
    ])

    res = pub.send("x")

    assert TOKEN not in res.error


def test_bale_image_is_not_sent_as_photo():
    pub, _ = make_bale([
        FakeResp(200, {"ok": True, "result": {"message_id": 3}})
    ])

    pub.send("متن", image=b"\xff\xd8\xffdata")

    url, kwargs = pub.session.calls[0]

    assert url.endswith("/sendMessage")
    assert "files" not in kwargs
    assert kwargs["json"]["text"] == "متن"

import requests
import urllib3

from helpers import TOKEN, FakeResp, FakeSession
from publisher import DryRunPublisher, TelegramPublisher


def make(queue, **kw):
    sleeps = []
    pub = TelegramPublisher(TOKEN, "@AiNewsPulses", session=FakeSession(queue), sleep=sleeps.append, **kw)
    return pub, sleeps


def test_success_requires_api_confirmation():
    pub, _ = make([FakeResp(200, {"ok": True, "result": {"message_id": 9}})])
    res = pub.send("سلام")
    assert res.status == "sent" and res.message_id == 9
    assert pub.session.calls[0][1]["timeout"] > 0


def test_http_200_with_ok_false_is_failure():
    pub, _ = make([FakeResp(200, {"ok": False, "description": "bad"})])
    assert pub.send("x").status == "failed"


def test_permanent_error_is_failed_and_not_retried():
    pub, _ = make([FakeResp(400, {"ok": False, "description": "chat not found"})])
    res = pub.send("x")
    assert res.status == "failed" and "chat not found" in res.error and len(pub.session.calls) == 1


def test_read_timeout_is_unknown_and_never_resent():
    pub, _ = make([requests.exceptions.ReadTimeout("slow")])
    res = pub.send("x")
    assert res.status == "unknown" and len(pub.session.calls) == 1


def test_server_error_is_unknown_not_blindly_retried():
    pub, _ = make([FakeResp(502, {"ok": False})])
    assert pub.send("x").status == "unknown" and len(pub.session.calls) == 1


def test_rate_limit_is_retried_with_retry_after_then_gives_up():
    pub, sleeps = make([FakeResp(429, {"parameters": {"retry_after": 3}})] * 3, max_retries=2)
    assert pub.send("x").status == "failed"
    assert sleeps == [3, 3] and len(pub.session.calls) == 3


def test_connection_that_never_reached_server_is_retried_safely():
    refused = requests.exceptions.ConnectionError(
        urllib3.exceptions.MaxRetryError(None, "u", reason=urllib3.exceptions.NewConnectionError(None, "refused")))
    pub, _ = make([refused, FakeResp(200, {"ok": True, "result": {"message_id": 1}})])
    assert pub.send("x").status == "sent" and len(pub.session.calls) == 2


def test_too_long_message_is_rejected_before_any_request():
    pub, _ = make([])
    assert pub.send("ا" * 5000).status == "failed" and pub.session.calls == []


def test_token_never_appears_in_error_text():
    pub, _ = make([requests.exceptions.ReadTimeout(f"https://api.telegram.org/bot{TOKEN}/sendMessage")])
    assert TOKEN not in pub.send("x").error


def test_photo_used_only_when_caption_fits():
    pub, _ = make([FakeResp(200, {"ok": True, "result": {"message_id": 1}})])
    pub.send("کوتاه", image=b"\xff\xd8\xffdata")
    assert pub.session.calls[0][0].endswith("/sendPhoto")


def test_dry_run_publisher_never_sends():
    assert DryRunPublisher().send("x").status == "skipped"

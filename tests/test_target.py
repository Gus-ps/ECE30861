"""TargetClient bounds: wall-clock timeouts, retry policy, size cap, redirects."""

import json
import time

import httpx
import pytest

from tester.config import FIXTURES
from tester.models import PodProfile
from tester.target import CommunicationError, Deadline, DeadlineExceeded, ResponseTooLarge, TargetClient

from .conftest import TARGET, TOKENS


def profile(**timing):
    data = json.loads((FIXTURES / "pod_profile.json").read_text(encoding="utf-8"))
    data["timing"].update(timing)
    return PodProfile.model_validate(data)


def client(handler, **timing):
    from pydantic import SecretStr
    return TargetClient(TARGET, {k: SecretStr(v) for k, v in TOKENS.items()}, profile(**timing),
                        transport=httpx.MockTransport(handler))


def test_hung_call_is_abandoned_at_its_wall_clock_budget():
    def hang(request):
        time.sleep(3)
        return httpx.Response(200)

    started = time.monotonic()
    with pytest.raises(CommunicationError, match="timed out after 0.3s"):
        client(hang).request("GET", "/api/v1/health", budget=0.3, deadline=Deadline(60))
    assert time.monotonic() - started < 1.5


def test_abandoned_post_warns_outcome_is_uncertain():
    def hang(request):
        time.sleep(3)
        return httpx.Response(202)

    with pytest.raises(CommunicationError, match="may still have processed"):
        client(hang).request("POST", "/api/v1/workbooks", budget=0.3, deadline=Deadline(60))


def test_suite_deadline_wins_over_call_budget():
    def hang(request):
        time.sleep(3)
        return httpx.Response(200)

    with pytest.raises(DeadlineExceeded):
        client(hang).request("GET", "/api/v1/health", budget=10, deadline=Deadline(0.3))


def test_get_retries_transport_errors_within_one_budget():
    calls = []

    def flaky(request):
        calls.append(request)
        if len(calls) < 3:
            raise httpx.ConnectError("refused")
        return httpx.Response(200, json={"ok": True})

    response = client(flaky, get_retries=3).request("GET", "/x", budget=5, deadline=Deadline(60))
    assert response.status == 200 and len(calls) == 3


def test_get_gives_up_after_configured_retries():
    calls = []

    def down(request):
        calls.append(request)
        raise httpx.ConnectError("refused")

    with pytest.raises(CommunicationError, match="failed before a response"):
        client(down, get_retries=2).request("GET", "/x", budget=5, deadline=Deadline(60))
    assert len(calls) == 3


def test_post_is_never_retried():
    calls = []

    def down(request):
        calls.append(request)
        raise httpx.ConnectError("refused")

    with pytest.raises(CommunicationError):
        client(down).request("POST", "/api/v1/workbooks", budget=5, deadline=Deadline(60))
    assert len(calls) == 1


def test_oversized_response_is_refused():
    big = b"x" * (2 * 1024 * 1024 + 1)
    with pytest.raises(ResponseTooLarge):
        client(lambda request: httpx.Response(200, content=big)).request(
            "GET", "/x", budget=5, deadline=Deadline(60))


def test_binary_downloads_use_their_own_cap():
    from pydantic import SecretStr
    data = json.loads((FIXTURES / "pod_profile.json").read_text(encoding="utf-8"))
    data["response_limits"] = {"json_bytes": 10, "binary_bytes": 100}
    body = b"x" * 50
    capped = TargetClient(TARGET, {k: SecretStr(v) for k, v in TOKENS.items()}, PodProfile.model_validate(data),
                          transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body)))
    with pytest.raises(ResponseTooLarge, match="more than 10 bytes"):
        capped.request("GET", "/x", budget=5, deadline=Deadline(60))
    assert capped.request("GET", "/x", budget=5, deadline=Deadline(60), binary=True).body == body


def test_redirects_are_not_followed_and_headers_are_set():
    seen = []

    def redirect(request):
        seen.append(request)
        return httpx.Response(302, headers={"Location": "https://elsewhere.example/steal"})

    response = client(redirect).request("GET", "/api/v1/workbooks/w/versions/v", budget=5, deadline=Deadline(60),
                                        role="userB", session_id="sess-1")
    assert response.status == 302 and len(seen) == 1
    assert seen[0].headers["authorization"] == "Bearer tok-b"
    assert seen[0].headers["x-test-session"] == "sess-1"
    assert str(seen[0].url) == TARGET + "/api/v1/workbooks/w/versions/v"

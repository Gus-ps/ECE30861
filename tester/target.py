"""Bounded HTTP client for an approved target system.

Only this module talks to the network. It never follows redirects, ignores
proxy environment variables, keeps TLS verification on, caps response size,
and retries only GETs on transport failures.

Each attempt runs in a worker thread that the caller abandons at its
wall-clock budget. Python cannot kill a blocked socket, so a late worker may
still finish; its result is discarded. A POST abandoned this way has an
uncertain outcome on the target and is never retried.
"""

import json
import threading
import time
from dataclasses import dataclass, field

import httpx


class CommunicationError(Exception):
    """No usable response: connection failure or timeout."""


class ResponseTooLarge(Exception):
    """The target answered with more bytes than the tester accepts."""


class DeadlineExceeded(Exception):
    """The overall budget ran out before the call could be made or finished."""


class Deadline:
    def __init__(self, seconds):
        self.expires = time.monotonic() + seconds

    def remaining(self):
        return self.expires - time.monotonic()

    def check(self):
        if self.remaining() <= 0:
            raise DeadlineExceeded("The time budget was exhausted.")


@dataclass(frozen=True)
class TargetResponse:
    status: int
    body: bytes
    headers: httpx.Headers = field(default_factory=httpx.Headers)

    def json(self):
        ##  Parsed JSON body, or None when the body is not JSON.
        try:
            return json.loads(self.body)
        except ValueError:
            return None


class TargetClient:
    def __init__(self, base_url, tokens, profile, transport=None):
        self.base_url = base_url.rstrip("/")
        self._tokens = tokens
        self._profile = profile
        self._client = httpx.Client(transport=transport, follow_redirects=False, trust_env=False, verify=True)

    def close(self):
        self._client.close()

    def request(self, method, path, *, budget, deadline, role=None, session_id=None, bearer=None,
                json_body=None, params=None, files=None, data=None, binary=False, idempotency_key=None):
        ##  binary=True marks a workbook or report download, capped separately from JSON.
        ##  bearer sends that literal token instead of a role's (negative authentication cases).
        headers = {}
        if bearer is not None:
            headers["Authorization"] = f"Bearer {bearer}"
        elif role is not None:
            headers["Authorization"] = f"Bearer {self._tokens[role].get_secret_value()}"
        if session_id is not None:
            headers[self._profile.session_transport.header] = session_id
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        if binary:
            ##  Downloads are compared byte for byte against Content-Length, so ask for no transfer coding.
            headers["Accept-Encoding"] = "identity"
        limits = self._profile.response_limits
        limit = limits.binary_bytes if binary else limits.json_bytes
        ##  Retries share one budget for the whole call, and only GETs retry.
        call = Deadline(budget)
        attempts = 1 + (self._profile.timing.get_retries if method == "GET" else 0)
        last_error = None
        for _ in range(attempts):
            deadline.check()
            timeout = min(call.remaining(), deadline.remaining())
            if timeout <= 0:
                break
            try:
                return self._bounded(method, path, timeout, limit, headers, json_body, params, files, data)
            except httpx.TimeoutException as error:
                last_error = self._timed_out(method, path, budget, error)
            except httpx.TransportError as error:
                last_error = CommunicationError(f"{method} {path} failed before a response: {type(error).__name__}.")
                last_error.__cause__ = error
            if method != "GET":
                break
        deadline.check()
        raise last_error or self._timed_out(method, path, budget)

    @staticmethod
    def _timed_out(method, path, budget, cause=None):
        note = " The target may still have processed it." if method != "GET" else ""
        error = CommunicationError(f"{method} {path} timed out after {budget:g}s with no response.{note}")
        error.__cause__ = cause
        return error

    def _bounded(self, method, path, timeout, *args):
        outcome = {}

        def attempt():
            try:
                outcome["response"] = self._send(method, path, timeout, *args)
            except BaseException as error:
                outcome["error"] = error

        worker = threading.Thread(target=attempt, name=f"target {method} {path}", daemon=True)
        worker.start()
        worker.join(timeout)
        if worker.is_alive():
            raise httpx.TimeoutException("wall-clock budget exhausted")
        if "error" in outcome:
            raise outcome["error"]
        return outcome["response"]

    def _send(self, method, path, timeout, limit, headers, json_body, params, files, data):
        with self._client.stream(method, self.base_url + path, headers=headers, timeout=timeout,
                                 json=json_body, params=params, files=files, data=data) as response:
            body = bytearray()
            for chunk in response.iter_bytes():
                body += chunk
                if len(body) > limit:
                    raise ResponseTooLarge(f"{method} {path} returned more than {limit} bytes.")
            return TargetResponse(response.status_code, bytes(body), response.headers)

    ##  ---- System test endpoints (test-admin credential, no session header) ----

    def system_setup(self, session_id, setup, deadline, role="test-admin", bearer=None):
        ##  role/bearer other than test-admin only for the fault cases' credential checks.
        return self.request("POST", "/test/setup", role=role, bearer=bearer, deadline=deadline,
                            budget=self._profile.timing.system_setup_seconds,
                            json_body={"session_id": session_id, "setup": setup})

    def system_report(self, session_id, deadline):
        return self.request("GET", "/test/report", role="test-admin", deadline=deadline,
                            budget=self._profile.timing.get_seconds, params={"session_id": session_id})

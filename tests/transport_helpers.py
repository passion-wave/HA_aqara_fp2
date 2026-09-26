"""Deterministic transport doubles; never open sockets."""

import json
from datetime import UTC, datetime

from custom_components.aqara_presence_lab.api.auth import SessionAuthProvider, SessionCredentials
from custom_components.aqara_presence_lab.api.client import AsyncAqaraClient
from custom_components.aqara_presence_lab.api.importers import ImportedCapture
from custom_components.aqara_presence_lab.api.profiles import PROFILE
from custom_components.aqara_presence_lab.api.rate_limit import AccountRateLimiter
from custom_components.aqara_presence_lab.api.signing import CandidateSigner


class Clock:
    tick = 1000.0

    def monotonic(self):
        return self.tick

    def now(self):
        return datetime.fromtimestamp(1700000000 + self.tick, UTC)


class Content:
    def __init__(self, data):
        self.data = data

    async def iter_chunked(self, size):
        for offset in range(0, len(self.data), size):
            yield self.data[offset : offset + size]


class Response:
    def __init__(self, body=b'{"code":0,"result":[]}', status=200, headers=None):
        self.status, self.headers = status, headers or {}
        self.content = Content(body)
        self.exited = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        self.exited = True


class Session:
    trust_env = False

    def __init__(self, response=None, error=None):
        self.response = response or Response()
        self.error, self.calls, self.closed = error, [], False

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return self.response

    async def close(self):
        self.closed = True


def capture():
    signer = CandidateSigner("demo-key")
    body = json.dumps(
        {
            "devices": [
                {
                    "deviceId": "private-device",
                    "traits": [{"path": "4.154.32989", "needSubscribe": True}],
                }
            ],
            "needParam": True,
        },
        ensure_ascii=False,
    ).encode()
    headers = {
        "appid": PROFILE.app_id,
        "area": "EU",
        "token": "private-token",
        "userid": "private-user",
        "nonce": "test-nonce",
        "time": "1700000000000",
    }
    headers["sign"] = signer.sign(
        body, nonce=headers["nonce"], time_ms=headers["time"], token=headers["token"]
    )
    return ImportedCapture(headers, body, True), signer


def client(session=None, *, own=False):
    imported, signer = capture()
    clock = Clock()
    return AsyncAqaraClient(
        session or Session(),
        SessionAuthProvider(SessionCredentials("private-token", "private-user")),
        signer,
        clock=clock,
        limiter=AccountRateLimiter(clock=clock, jitter=lambda: 0),
        own_session=own,
    )

import asyncio
import base64
import gzip
import hashlib
import json
import ssl
from dataclasses import replace
from unittest.mock import patch

import aiohttp
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from custom_components.aqara_presence_lab.api.errors import (
    AccessDenied,
    ApplicationError,
    InvalidResponse,
    ProtocolUnsupported,
    RateLimited,
    RequestRejected,
    ResponseTooLarge,
    TransportError,
)
from custom_components.aqara_presence_lab.api.profiles import PROFILE, ProtocolProfile
from tests.transport_helpers import Response, Session, capture, client


async def test_probe_exact_bytes_tls_fresh_headers_no_json_reserialize():
    item, signer = capture()
    session = Session(
        Response(
            json.dumps(
                {
                    "code": 0,
                    "result": [
                        {
                            "deviceId": "private-device",
                            "traits": [{"path": "4.154.32989", "value": "9"}],
                        }
                    ],
                }
            ).encode()
        )
    )
    api = client(session)
    result = await api.async_probe_capture(item, consent=True)
    assert result.devices["private-device"].traits["4.154.32989"].normalized_value == 9
    url, kwargs = session.calls[0]
    assert url == "https://rpc-ger.aqara.com/app/v1.0/lumi/app/qlink/trait/read"
    assert kwargs["data"] is item.body
    assert "json" not in kwargs
    assert kwargs["ssl"] is True and kwargs["allow_redirects"] is False
    assert kwargs["auto_decompress"] is False
    assert kwargs["timeout"].total == 20 and kwargs["timeout"].connect == 10
    headers = kwargs["headers"]
    assert headers["Nonce"] != item.headers["nonce"]
    assert signer.matches(
        headers["Sign"],
        item.body,
        nonce=headers["Nonce"],
        time_ms=headers["Time"],
        token=item.headers["token"],
    )
    assert session.response.exited


async def test_production_identity_login_and_consent_are_closed_without_network():
    api = client()
    for coroutine in (
        api.async_read_traits(["x"]),
        api.async_validate_credentials(),
        api.async_login("user", "secret", consent=True),
        api.async_probe_capture(capture()[0], consent=False),
    ):
        with pytest.raises(ProtocolUnsupported):
            await coroutine
    assert not api._session.calls


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (301, RequestRejected),
        (307, RequestRejected),
        (400, RequestRejected),
        (401, AccessDenied),
        (403, AccessDenied),
        (429, RateLimited),
        (500, TransportError),
        (503, TransportError),
    ],
)
async def test_http_status_takes_precedence_over_success_body(status, error):
    api = client(Session(Response(status=status, headers={"Retry-After": "120"})))
    with pytest.raises(error) as caught:
        await api.async_probe_capture(capture()[0], consent=True)
    assert "private" not in str(caught.value) + repr(caught.value)
    if status == 429:
        assert caught.value.retry_after == 120
    assert len(api._session.calls) == 1


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("private-token"),
        aiohttp.ClientConnectionError("private-token"),
        ssl.SSLError("private-token"),
    ],
)
async def test_transport_errors_sanitized_without_retries(error):
    api = client(Session(error=error))
    with pytest.raises(TransportError) as caught:
        await api.async_probe_capture(capture()[0], consent=True)
    assert "private-token" not in repr(caught.value)
    assert caught.value.__suppress_context__
    assert api.limiter.retry_after == 60
    assert len(api._session.calls) == 1


@pytest.mark.parametrize(
    "body",
    [
        b"<html>secret</html>",
        b'{"code":false}',
        b'{"code":0,"code":1}',
        b'{"code":NaN}',
        b'{"code":0}{}',
    ],
)
async def test_bad_json(body):
    with pytest.raises(InvalidResponse):
        await client(Session(Response(body))).async_probe_capture(capture()[0], consent=True)


async def test_unknown_application_code_not_auth_expiry():
    with pytest.raises(ApplicationError) as error:
        await client(
            Session(Response(b'{"code":123456,"message":"private-token"}'))
        ).async_probe_capture(capture()[0], consent=True)
    assert error.value.code == 123456
    assert "private-token" not in repr(error.value)


async def test_gzip_valid_and_decompression_bomb_limit():
    good = gzip.compress(b'{"code":0,"result":[]}')
    api = client(Session(Response(good, headers={"Content-Encoding": "gzip"})))
    await api.async_probe_capture(capture()[0], consent=True)
    bomb = gzip.compress(b" " * (2 * 1024 * 1024 + 1))
    assert len(bomb) < 3000
    with pytest.raises(ResponseTooLarge):
        await client(
            Session(Response(bomb, headers={"Content-Encoding": "gzip", "Content-Length": "12"}))
        ).async_probe_capture(capture()[0], consent=True)
    with pytest.raises(ResponseTooLarge):
        await client(Session(Response(b" " * (2 * 1024 * 1024 + 1)))).async_probe_capture(
            capture()[0], consent=True
        )


@pytest.mark.parametrize("encoding", ["br", "gzip", "deflate"])
async def test_unsupported_corrupt_compression(encoding):
    with pytest.raises(InvalidResponse):
        await client(
            Session(Response(b"invalid", headers={"Content-Encoding": encoding}))
        ).async_probe_capture(capture()[0], consent=True)


async def test_redirect_host_and_proxy_protection():
    api = client()
    api.profile = replace(PROFILE, allowed_host="evil.invalid")
    with pytest.raises(ProtocolUnsupported):
        await api.async_probe_capture(capture()[0], consent=True)
    assert not api._session.calls
    api = client()
    api._session.trust_env = True
    with pytest.raises(ProtocolUnsupported):
        await api.async_probe_capture(capture()[0], consent=True)
    assert not api._session.calls


async def test_cancel_propagates_closes_response_no_retry():
    event = asyncio.Event()

    class Slow:
        async def iter_chunked(self, size):
            event.set()
            await asyncio.Event().wait()
            yield b""

    session = Session()
    session.response.content = Slow()
    api = client(session)
    task = asyncio.create_task(api.async_probe_capture(capture()[0], consent=True))
    await event.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert session.response.exited and len(session.calls) == 1
    assert api.limiter.retry_after == 30


async def test_close_only_owned_session():
    external = client()
    await external.async_close()
    assert not external._session.closed
    owned = client(own=True)
    await owned.async_close()
    assert owned._session.closed


async def test_same_batch_coalesces_into_one_request():
    entered, release = asyncio.Event(), asyncio.Event()

    class Slow:
        async def iter_chunked(self, size):
            entered.set()
            await release.wait()
            yield b'{"code":0,"result":[]}'

    api = client()
    api._session.response.content = Slow()
    with patch.object(ProtocolProfile, "require_production_ready"):
        first = asyncio.create_task(api.async_read_traits(["d"]))
        await entered.wait()
        second = asyncio.create_task(api.async_read_traits(["d"]))
        await asyncio.sleep(0)
        release.set()
        assert (await first) is (await second)
    assert len(api._session.calls) == 1
    payload = json.loads(api._session.calls[0][1]["data"])
    assert len(payload["devices"][0]["traits"]) == 31


async def test_login_transport_without_token_uses_verified_candidate_and_explicit_consent():
    session = Session(
        Response(b'{"code":0,"result":{"token":"new-token","userId":"private-user"}}')
    )
    api = client(session)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    api.profile = replace(PROFILE, public_rsa_key=public)
    with patch.object(ProtocolProfile, "require_production_ready"):
        with pytest.raises(ProtocolUnsupported):
            await api.async_login("account", "test-password", consent=False)
        credentials = await api.async_login("account", "test-password", consent=True)
    assert credentials.token == "new-token"
    url, kwargs = session.calls[0]
    assert url.endswith("/app/v1.0/lumi/user/login")
    body = json.loads(kwargs["data"])
    assert body["encryptType"] == 2 and body["password"] != "test-password"
    decrypted = key.decrypt(base64.b64decode(body["password"]), padding.PKCS1v15())
    assert decrypted.decode() == hashlib.md5(b"test-password", usedforsecurity=False).hexdigest()
    assert "Token" not in kwargs["headers"] and "Userid" not in kwargs["headers"]
    assert "test-password" not in repr(kwargs)
    headers = kwargs["headers"]
    assert api._signer.matches(
        headers["Sign"], kwargs["data"], nonce=headers["Nonce"], time_ms=headers["Time"], token=None
    )
    # Login results are not installed until SessionAuthProvider's verified commit.
    assert (await api._auth.async_credentials()).token == "private-token"


async def test_invalid_read_path_and_mismatched_capture_credentials_never_send():
    api = client()
    api.profile = replace(PROFILE, trait_read_path="/app/v1.0/lumi/user/login")
    with pytest.raises(ProtocolUnsupported):
        await api.async_probe_capture(capture()[0], consent=True)
    assert not api._session.calls
    api = client()
    from custom_components.aqara_presence_lab.api.auth import (
        SessionAuthProvider,
        SessionCredentials,
    )

    api._auth = SessionAuthProvider(SessionCredentials("different-token", "private-user"))
    with pytest.raises(ProtocolUnsupported):
        await api.async_probe_capture(capture()[0], consent=True)
    assert not api._session.calls


async def test_unload_cancels_owned_read_and_releases_response():
    entered = asyncio.Event()

    class Slow:
        async def iter_chunked(self, size):
            entered.set()
            await asyncio.Event().wait()
            yield b""

    api = client(own=True)
    api._session.response.content = Slow()
    with patch.object(ProtocolProfile, "require_production_ready"):
        task = asyncio.create_task(api.async_read_traits(["d"]))
        await entered.wait()
        await api.async_close()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert api._session.closed and api._session.response.exited


@pytest.mark.parametrize(
    ("body", "error"),
    [
        (b'{"code":654321,"message":"private-token"}', ApplicationError),
        (b'{"code":0,"result":"private-token"}', InvalidResponse),
        (b'{"code":0,"result":{"token":null,"userId":"private-user"}}', None),
    ],
)
async def test_login_unknown_or_malformed_response_sanitized_no_retry(body, error):
    from custom_components.aqara_presence_lab.api.errors import AuthenticationRequired

    api = client(Session(Response(body)))
    with patch.object(ProtocolProfile, "require_production_ready"):
        with pytest.raises(error or AuthenticationRequired) as caught:
            await api.async_login("private-account", "private-password", consent=True)
    for secret in ("private-token", "private-user", "private-account", "private-password"):
        assert secret not in str(caught.value) + repr(caught.value)
    assert len(api._session.calls) == 1
    assert (await api._auth.async_credentials()).token == "private-token"


async def test_application_failure_records_observed_status_and_code_without_retry():
    from custom_components.aqara_presence_lab.api.validation import failure_report

    api = client(
        Session(
            Response(
                b'{"code":765432,"message":"SECRET-token","requestId":"SECRET-id"}', status=202
            )
        )
    )
    with pytest.raises(ApplicationError) as caught:
        await api.async_probe_capture(capture()[0], consent=True)
    assert caught.value.code == 765432 and caught.value.http_status == 202
    assert len(api._session.calls) == 1
    report = failure_report(caught.value)
    assert report["http_status"] == 202 and report["application_code"] == 765432
    assert "SECRET" not in json.dumps(report) + str(caught.value) + repr(caught.value)


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (301, RequestRejected),
        (401, AccessDenied),
        (403, AccessDenied),
        (429, RateLimited),
        (500, TransportError),
    ],
)
async def test_non_success_http_status_never_becomes_application_error_metadata(status, error_type):
    from custom_components.aqara_presence_lab.api.validation import failure_report

    api = client(Session(Response(b'{"code":123,"message":"SECRET-token"}', status=status)))
    with pytest.raises(error_type) as caught:
        await api.async_probe_capture(capture()[0], consent=True)
    report = failure_report(caught.value)
    assert "application_code" not in report
    assert "http_status" not in report  # This minimal extension handles ApplicationError only.
    assert len(api._session.calls) == 1


@pytest.mark.parametrize("code", ['"SECRET"', '"123"', "true", "false", "null", "1.5"])
async def test_non_integer_application_code_not_coerced_into_failure_report(code):
    from custom_components.aqara_presence_lab.api.validation import failure_report

    api = client(Session(Response(('{"code":' + code + ',"message":"SECRET"}').encode())))
    with pytest.raises(InvalidResponse) as caught:
        await api.async_probe_capture(capture()[0], consent=True)
    report = failure_report(caught.value)
    assert "application_code" not in report and "http_status" not in report
    assert "SECRET" not in json.dumps(report)
    assert len(api._session.calls) == 1

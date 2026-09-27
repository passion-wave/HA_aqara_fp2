"""Authenticated lifecycle entirely in memory, with a clock and HTTP doubles."""

import asyncio
import json
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from custom_components.aqara_presence_lab.api.account import ManagedAqaraClient
from custom_components.aqara_presence_lab.api.auth import SessionCredentials
from custom_components.aqara_presence_lab.api.client import AsyncAqaraClient
from custom_components.aqara_presence_lab.api.errors import (
    AccessDenied,
    AccountMismatch,
    ApplicationError,
    AuthenticationRequired,
    InvalidResponse,
    ProtocolUnsupported,
    RateLimited,
    RequestRejected,
    SessionExpired,
    SessionPersistenceError,
    TransportError,
)
from custom_components.aqara_presence_lab.api.profiles import PROFILE
from custom_components.aqara_presence_lab.api.rate_limit import AccountRateLimiter
from custom_components.aqara_presence_lab.api.signing import CandidateSigner
from tests.transport_helpers import Clock, Response

OLD = SessionCredentials("token-old-SECRET", "user-SECRET", sys_type="1")
NEW = SessionCredentials("token-new-SECRET", "user-SECRET", sys_type="1")


def login_reply(token=NEW.token, user_id=NEW.user_id):
    return Response(json.dumps({"code": 0, "result": {"token": token, "userId": user_id}}).encode())


def read_reply(ids=("d1", "d2")):
    return Response(
        json.dumps(
            {
                "code": 0,
                "result": [
                    {"deviceId": item, "traits": [{"path": "4.154.32989", "value": "9"}]}
                    for item in ids
                ],
            }
        ).encode()
    )


def expiry_reply():
    return Response(b'{"code":108,"msgDetails":"NEVER-LOG-SECRET"}')


class QueueSession:
    trust_env = False

    def __init__(self, clock, responses):
        self.clock, self.responses, self.calls = clock, list(responses), []
        self.closed = False

    def post(self, url, **kwargs):
        self.calls.append((self.clock.monotonic(), url, kwargs))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    async def close(self):
        self.closed = True


def managed(
    responses, *, initial=None, expected=None, consent=True, live=True, sleep=None, writer=None
):
    clock = Clock()
    http = QueueSession(clock, responses)
    low = AsyncAqaraClient(
        http,
        None,
        CandidateSigner("demo-key"),
        clock=clock,
        limiter=AccountRateLimiter(clock=clock, jitter=lambda: 0),
        live_consent=live,
    )
    delays = []

    async def fake_sleep(delay):
        delays.append(delay)
        clock.tick += delay
        await asyncio.sleep(0)

    loader = AsyncMock(return_value=("account-SECRET", "password-SECRET"))
    writer = writer or AsyncMock()
    api = ManagedAqaraClient(
        low,
        loader,
        writer,
        initial_session=initial,
        expected_user_id=expected,
        consent=consent,
        sleep=sleep or fake_sleep,
    )
    return api, low, http, loader, writer, delays


@pytest.mark.parametrize(("consent", "live"), [(False, True), (True, False), (False, False)])
async def test_both_explicit_consent_layers_required(consent, live):
    api, _, http, _, writer, _ = managed([], consent=consent, live=live)
    with pytest.raises((AuthenticationRequired, ProtocolUnsupported)):
        await api.async_read_traits(["d1"])
    assert not http.calls
    writer.assert_not_called()
    assert PROFILE.production_allowed is False


async def test_initial_login_stages_identity_until_full_read_and_persistence():
    api, low, http, loader, writer, waits = managed([login_reply(), read_reply()])
    identity = await api.async_validate_credentials()
    assert identity.user_id == NEW.user_id and identity.area == "EU"
    assert api.session is None and len(http.calls) == 1
    writer.assert_not_called()
    result = await api.async_read_traits(["d1", "d2"])
    assert set(result.devices) == {"d1", "d2"}
    assert api.session == NEW and waits == [30]
    loader.assert_awaited_once()
    writer.assert_awaited_once_with(NEW)
    assert api.limiter is low.limiter
    for _, _, kwargs in http.calls:
        assert kwargs["headers"]["Sys-Type"] == "1"
        assert kwargs["headers"]["Lang"] == "en"
        assert kwargs["headers"]["User-Agent"] == "pyAqara/1.0.0"
        assert len(kwargs["headers"]["PhoneId"]) == 36
        assert low._signer.matches(
            kwargs["headers"]["Sign"],
            kwargs["data"],
            nonce=kwargs["headers"]["Nonce"],
            time_ms=kwargs["headers"]["Time"],
            token=kwargs["headers"].get("Token"),
        )
    assert http.calls[0][2]["headers"]["App-Version"] == "3.0.0"
    assert http.calls[1][2]["headers"]["App-Version"] == PROFILE.tested_app_version
    assert "Token" not in http.calls[0][2]["headers"]
    assert "Userid" not in http.calls[0][2]["headers"]


async def test_first_read_can_login_without_separate_validate():
    api, _, http, _, _, waits = managed([login_reply(), read_reply()])
    await api.async_read_traits(["d1", "d2"])
    assert api.session == NEW and len(http.calls) == 2 and waits == [30]


async def test_valid_persisted_session_survives_restart_without_login():
    api, _, http, loader, writer, waits = managed([read_reply()], initial=OLD)
    assert (await api.async_validate_credentials()).user_id == OLD.user_id
    assert not http.calls
    await api.async_read_traits(["d1", "d2"])
    assert api.session == OLD and len(http.calls) == 1 and not waits
    loader.assert_not_called()
    writer.assert_not_called()


async def test_expired_stored_session_one_login_then_verified_atomic_install():
    api, _, http, loader, writer, waits = managed(
        [expiry_reply(), login_reply(), read_reply()], initial=OLD
    )

    async def persist(candidate):
        assert api.session == OLD
        assert len(http.calls) == 3
        assert candidate == NEW

    writer.side_effect = persist
    await api.async_read_traits(["d1", "d2"])
    assert api.session == NEW
    assert [entry[0] for entry in http.calls] == [1000, 1030, 1060]
    assert waits == [30, 30]
    loader.assert_awaited_once()
    writer.assert_awaited_once()


async def test_parallel_refreshes_join_one_expiry_login_read_sequence():
    api, _, http, loader, writer, _ = managed(
        [expiry_reply(), login_reply(), read_reply()], initial=OLD
    )
    snapshots = await asyncio.gather(*(api.async_read_traits(["d1", "d2"]) for _ in range(12)))
    assert all(item is snapshots[0] for item in snapshots)
    assert len(http.calls) == 3
    loader.assert_awaited_once()
    writer.assert_awaited_once()


async def test_parallel_validate_and_reads_do_not_duplicate_login_or_read():
    api, _, http, loader, writer, _ = managed([login_reply(), read_reply()])
    identity, first, second = await asyncio.gather(
        api.async_validate_credentials(),
        api.async_read_traits(["d1", "d2"]),
        api.async_read_traits(["d1", "d2"]),
    )
    assert identity == api.identity and first is second
    assert len(http.calls) == 2
    loader.assert_awaited_once()
    writer.assert_awaited_once()


@pytest.mark.parametrize("failure", [Response(b'{"code":1234}'), Response(status=403)])
async def test_failed_login_latched_per_expired_generation(failure):
    api, _, http, loader, writer, _ = managed([expiry_reply(), failure], initial=OLD)
    with pytest.raises((AuthenticationRequired, TransportError)):
        await api.async_read_traits(["d1", "d2"])
    for _ in range(3):
        with pytest.raises(AuthenticationRequired):
            await api.async_read_traits(["d1", "d2"])
    assert len(http.calls) == 2 and api.session == OLD
    loader.assert_awaited_once()
    writer.assert_not_called()


@pytest.mark.parametrize(
    ("reply", "error"),
    [
        (Response(b'{"code":9876,"message":"SECRET"}'), ApplicationError),
        (Response(status=401), AccessDenied),
        (Response(status=403), AccessDenied),
        (Response(status=429), RateLimited),
        (Response(status=503), TransportError),
        (Response(b'{"code":"108"}'), InvalidResponse),
        (TimeoutError("SECRET"), TransportError),
    ],
)
async def test_no_automatic_login_for_unknown_or_transport_failures(reply, error):
    api, _, http, loader, writer, _ = managed([reply], initial=OLD)
    with pytest.raises(error):
        await api.async_read_traits(["d1", "d2"])
    assert len(http.calls) == 1 and api.session == OLD
    loader.assert_not_called()
    writer.assert_not_called()


async def test_server_account_mismatch_retains_old_session_and_blocks_next_attempt():
    api, _, http, _, writer, _ = managed(
        [expiry_reply(), login_reply(user_id="different-user-SECRET")], initial=OLD
    )
    with pytest.raises(AccountMismatch):
        await api.async_read_traits(["d1", "d2"])
    with pytest.raises(AuthenticationRequired):
        await api.async_read_traits(["d1", "d2"])
    assert api.session == OLD and len(http.calls) == 2
    writer.assert_not_called()


def test_initial_expected_account_mismatch_rejected_without_network():
    with pytest.raises(AccountMismatch):
        managed([], initial=OLD, expected="different-user-SECRET")


async def test_partial_candidate_read_kept_uncommitted_and_resumes_without_login():
    api, _, http, loader, writer, waits = managed(
        [login_reply(), read_reply(("d1",)), read_reply()]
    )
    with pytest.raises(InvalidResponse):
        await api.async_read_traits(["d1", "d2"])
    assert api.session is None
    writer.assert_not_called()
    await api.async_read_traits(["d1", "d2"])
    assert api.session == NEW and len(http.calls) == 3 and waits == [30, 30]
    loader.assert_awaited_once()
    writer.assert_awaited_once_with(NEW)


async def test_persistence_failure_preserves_candidate_proof_for_storage_retry():
    writer = AsyncMock(side_effect=[OSError("path-password-SECRET"), None])
    api, _, http, loader, _, _ = managed(
        [expiry_reply(), login_reply(), read_reply()], initial=OLD, writer=writer
    )
    with pytest.raises(SessionPersistenceError) as caught:
        await api.async_read_traits(["d1", "d2"])
    assert "SECRET" not in str(caught.value) + repr(caught.value)
    assert api.session == OLD and len(http.calls) == 3
    result = await api.async_read_traits(["d1", "d2"])
    assert set(result.devices) == {"d1", "d2"}
    assert api.session == NEW and len(http.calls) == 3
    loader.assert_awaited_once()
    assert writer.await_count == 2


async def test_renewed_session_expired_again_is_manual_auth_without_loop():
    api, _, http, loader, writer, _ = managed(
        [expiry_reply(), login_reply(), expiry_reply()], initial=OLD
    )
    with pytest.raises(AuthenticationRequired):
        await api.async_read_traits(["d1", "d2"])
    with pytest.raises(AuthenticationRequired):
        await api.async_read_traits(["d1", "d2"])
    assert api.session == OLD and len(http.calls) == 3
    loader.assert_awaited_once()
    writer.assert_not_called()


async def test_candidate_server_backoff_preserved_and_no_long_hidden_wait():
    api, low, http, loader, writer, waits = managed(
        [
            login_reply(),
            Response(status=429, headers={"Retry-After": "600"}),
            read_reply(),
        ]
    )
    with pytest.raises(RateLimited):
        await api.async_read_traits(["d1", "d2"])
    with pytest.raises(RateLimited) as caught:
        await api.async_read_traits(["d1", "d2"])
    assert caught.value.retry_after == 600 and waits == [30]
    assert api.session is None and len(http.calls) == 2
    low.clock.tick += 600
    await api.async_read_traits(["d1", "d2"])
    assert api.session == NEW and len(http.calls) == 3
    loader.assert_awaited_once()
    writer.assert_awaited_once()


async def test_cancellation_during_candidate_cooldown_resumes_same_login():
    entered = asyncio.Event()

    async def blocked_sleep(delay):
        entered.set()
        await asyncio.Event().wait()

    api, low, http, loader, writer, _ = managed([login_reply(), read_reply()], sleep=blocked_sleep)
    task = asyncio.create_task(api.async_read_traits(["d1", "d2"]))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert api.session is None and len(http.calls) == 1
    low.clock.tick += 30
    await api.async_read_traits(["d1", "d2"])
    assert api.session == NEW and len(http.calls) == 2
    loader.assert_awaited_once()
    writer.assert_awaited_once()


async def test_unload_cancels_bounded_wait_and_closes_no_future_requests():
    entered = asyncio.Event()

    async def blocked_sleep(delay):
        entered.set()
        await asyncio.Event().wait()

    api, _, http, _, writer, _ = managed([login_reply()], sleep=blocked_sleep)
    task = asyncio.create_task(api.async_read_traits(["d1", "d2"]))
    await entered.wait()
    await api.async_close()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(ProtocolUnsupported):
        await api.async_read_traits(["d1", "d2"])
    assert len(http.calls) == 1 and api.session is None
    writer.assert_not_called()


async def test_cancelled_login_allows_later_explicit_call_after_cooldown():
    entered = asyncio.Event()

    class SlowContent:
        async def iter_chunked(self, size):
            entered.set()
            await asyncio.Event().wait()
            yield b""

    slow = Response()
    slow.content = SlowContent()
    api, low, http, loader, writer, _ = managed([slow, login_reply(), read_reply()])
    task = asyncio.create_task(api.async_read_traits(["d1", "d2"]))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    low.clock.tick += 30
    await api.async_read_traits(["d1", "d2"])
    assert api.session == NEW and len(http.calls) == 3 and loader.await_count == 2
    writer.assert_awaited_once()


async def test_manual_new_flow_resolves_rotated_password_after_failed_generation():
    first, _, _, _, _, _ = managed([Response(b'{"code":999}')])
    with pytest.raises(AuthenticationRequired):
        await first.async_validate_credentials()
    await first.async_close()
    second, _, _, loader, _, _ = managed([login_reply(), read_reply()], expected=NEW.user_id)
    loader.return_value = ("account-SECRET", "rotated-password-SECRET")
    await second.async_read_traits(["d1", "d2"])
    assert second.session == NEW
    loader.assert_awaited_once()


async def test_loader_exception_is_sanitized_and_latched():
    api, _, http, loader, _, _ = managed([])
    loader.side_effect = ValueError("account-password-SECRET")
    for _ in range(2):
        with pytest.raises(AuthenticationRequired) as caught:
            await api.async_validate_credentials()
        assert "SECRET" not in repr(caught.value)
    assert not http.calls
    loader.assert_awaited_once()


@pytest.mark.parametrize(
    "profile",
    [
        replace(PROFILE, id="other"),
        replace(PROFILE, version=2),
        replace(PROFILE, area="US"),
        replace(PROFILE, source_reference="unreviewed"),
        replace(PROFILE, allowed_host="attacker.invalid"),
        replace(PROFILE, signing_strategy="unknown"),
        replace(PROFILE, login_strategy="unknown"),
        replace(PROFILE, tested_app_version="secret\r\nInjected: token"),
        replace(PROFILE, read_paths=("unknown",)),
    ],
)
async def test_experimental_consent_cannot_enable_other_protocols(profile):
    api, low, http, _, _, _ = managed([])
    low.profile = profile
    with pytest.raises(ProtocolUnsupported):
        await api.async_read_traits(["d1"])
    assert not http.calls


async def test_expiry_is_profile_and_path_specific_and_retains_safe_metadata():
    api, low, _, _, _, _ = managed([])
    assert PROFILE.is_confirmed_expiry(PROFILE.trait_read_path, 108)
    assert not PROFILE.is_confirmed_expiry(PROFILE.login_path, 108)
    assert not replace(PROFILE, id="different").is_confirmed_expiry(PROFILE.trait_read_path, 108)
    assert not PROFILE.is_confirmed_expiry(PROFILE.trait_read_path, True)
    low._session.responses = [expiry_reply()]
    low.set_session(OLD)
    with pytest.raises(SessionExpired) as caught:
        await low.async_read_traits(["d1"])
    assert isinstance(caught.value, AuthenticationRequired)
    assert isinstance(caught.value, ApplicationError)
    assert caught.value.code == 108 and caught.value.http_status == 200
    assert "SECRET" not in str(caught.value) + repr(caught.value)


async def test_saved_session_setup_waits_shared_flow_cooldown_without_new_login():
    api, low, http, loader, writer, waits = managed([read_reply()], initial=OLD)
    await low.limiter.async_claim()
    await api.async_read_traits(["d1", "d2"])
    assert waits == [30] and len(http.calls) == 1 and http.calls[0][0] == 1030
    loader.assert_not_called()
    writer.assert_not_called()


async def test_stale_persistence_proof_requires_new_read_but_same_candidate():
    writer = AsyncMock(side_effect=[OSError("SECRET"), None])
    api, low, http, loader, _, _ = managed(
        [login_reply(), read_reply(), read_reply()], writer=writer
    )
    with pytest.raises(SessionPersistenceError):
        await api.async_read_traits(["d1", "d2"])
    low.clock.tick += 31
    result = await api.async_read_traits(["d1", "d2"])
    assert len(http.calls) == 3 and result.received_at_utc == low.clock.now()
    assert api.session == NEW
    loader.assert_awaited_once()
    assert writer.await_count == 2


async def test_cancellation_during_storage_preserves_verified_candidate_for_retry():
    entered = asyncio.Event()

    async def slow_write(candidate):
        entered.set()
        await asyncio.Event().wait()

    writer = AsyncMock(side_effect=slow_write)
    api, _, http, loader, _, _ = managed([login_reply(), read_reply()], writer=writer)
    task = asyncio.create_task(api.async_read_traits(["d1", "d2"]))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert api.session is None
    writer.side_effect = None
    await api.async_read_traits(["d1", "d2"])
    assert len(http.calls) == 2 and api.session == NEW
    loader.assert_awaited_once()
    assert writer.await_count == 2


async def test_different_simultaneous_batches_do_not_send_second_request():
    entered, release = asyncio.Event(), asyncio.Event()

    class SlowContent:
        async def iter_chunked(self, size):
            entered.set()
            await release.wait()
            yield read_reply().content.data

    response = Response()
    response.content = SlowContent()
    api, _, http, _, _, _ = managed([response], initial=OLD)
    first = asyncio.create_task(api.async_read_traits(["d1", "d2"]))
    await entered.wait()
    with pytest.raises(RateLimited):
        await api.async_read_traits(["different-device-SECRET"])
    validation = asyncio.create_task(api.async_validate_credentials())
    release.set()
    await first
    assert (await validation).user_id == OLD.user_id
    assert len(http.calls) == 1


@pytest.mark.parametrize(
    "body",
    [
        b'{"code":0,"result":{"token":true,"userId":"SECRET"}}',
        b'{"code":0,"result":{"token":"SECRET","userId":null}}',
        b'{"code":0,"result":{"token":"SECRET\\ud800","userId":"SECRET"}}',
        b'{"code":0,"result":{"mfa":"SECRET"}}',
        b'{"code":108,"msgDetails":"SECRET"}',
        b'{"code":"108","msgDetails":"SECRET"}',
        b'{"code":0,"result":[]}',
    ],
)
async def test_unknown_login_and_malformed_credentials_require_manual_action(body):
    api, _, http, _, writer, _ = managed([Response(body)])
    with pytest.raises(AuthenticationRequired) as caught:
        await api.async_validate_credentials()
    assert "SECRET" not in str(caught.value) + repr(caught.value)
    assert len(http.calls) == 1 and api.session is None
    writer.assert_not_called()


@pytest.mark.parametrize("status", [401, 403, 429, 500, 302])
async def test_http_status_precedes_private_expiry_code(status):
    api, _, http, loader, _, _ = managed([Response(b'{"code":108}', status=status)], initial=OLD)
    with pytest.raises(
        (AccessDenied, TransportError, RequestRejected, ProtocolUnsupported)
    ) as caught:
        await api.async_read_traits(["d1", "d2"])
    assert not isinstance(caught.value, SessionExpired)
    assert len(http.calls) == 1
    loader.assert_not_called()


@pytest.mark.parametrize("sys_type", [False, 1, "", "2", "SECRET", [], {}])
def test_session_platform_is_conservative_and_never_raw_in_errors(sys_type):
    with pytest.raises(AuthenticationRequired) as caught:
        SessionCredentials("token-SECRET", "user-SECRET", sys_type=sys_type)
    assert "SECRET" not in str(caught.value) + repr(caught.value)


@pytest.mark.parametrize(
    "failure", [TimeoutError("SECRET"), Response(status=503), Response(status=429)]
)
async def test_login_transport_failure_may_retry_once_on_later_poll_after_backoff(failure):
    api, low, http, loader, writer, waits = managed(
        [expiry_reply(), failure, login_reply(), read_reply()], initial=OLD
    )
    with pytest.raises(TransportError):
        await api.async_read_traits(["d1", "d2"])
    assert len(http.calls) == 2 and api.session == OLD
    # No immediate repeat, and the HTTP failure is never relabeled bad password.
    with pytest.raises(RateLimited):
        await api.async_read_traits(["d1", "d2"])
    assert len(http.calls) == 2 and waits == [30]
    low.clock.tick += 60
    await api.async_read_traits(["d1", "d2"])
    assert len(http.calls) == 4 and api.session == NEW
    assert waits == [30, 30]
    assert loader.await_count == 2
    writer.assert_awaited_once_with(NEW)

"""Supplementary read-only endpoints share auth and limits without login loops."""

import asyncio
import json
from dataclasses import replace

import pytest

from custom_components.aqara_presence_lab.api.errors import (
    AccessDenied,
    ApplicationError,
    AuthenticationRequired,
    InvalidResponse,
    ProtocolUnsupported,
    RateLimited,
    SessionExpired,
    TransportError,
)
from custom_components.aqara_presence_lab.api.models import AccountSnapshot
from custom_components.aqara_presence_lab.api.resources import (
    RESOURCE_OPTIONS,
    SETTINGS_OPTIONS,
    DeviceResources,
)
from tests.test_account import NEW, OLD, login_reply, managed, read_reply
from tests.transport_helpers import Response

RESOURCE_PATH = "/app/v1.0/lumi/res/query"
SETTINGS_PATH = "/app/v1.0/lumi/res/query/by/resourceId"
GROUPS = [
    ("async_read_resources", RESOURCE_PATH, RESOURCE_OPTIONS),
    ("async_read_resource_settings", SETTINGS_PATH, SETTINGS_OPTIONS),
]


def resource_reply(*, settings=False, device="d1"):
    identifier = {"resourceId": "14.1.85"} if settings else {"attr": "sleep_state"}
    return Response(
        json.dumps(
            {
                "code": 0,
                "result": [
                    {**identifier, "value": "3", "subjectId": device, "timeStamp": 1700000000000}
                ],
            }
        ).encode()
    )


@pytest.mark.parametrize(("method", "path", "options"), GROUPS)
async def test_one_exact_signed_single_subject_body_for_full_group(method, path, options):
    api, low, http, loader, writer, _ = managed(
        [resource_reply(settings=path == SETTINGS_PATH)], initial=OLD
    )
    result = await getattr(api, method)("d1")
    assert isinstance(result, DeviceResources)
    assert result.device_id == "d1"
    attr = "presence_detection_sens" if path == SETTINGS_PATH else "sleep_state"
    assert result.observations[attr].value == 3
    assert result.observations[attr].quality == "unverified"
    assert result.observations[attr].source_time_utc is None
    assert len(result.observations) == len(options)
    assert len(http.calls) == 1
    _, url, kwargs = http.calls[0]
    assert url == f"https://rpc-ger.aqara.com{path}"
    assert json.loads(kwargs["data"]) == {"data": [{"options": list(options), "subjectId": "d1"}]}
    assert len(options) == (7 if path == SETTINGS_PATH else 81)
    assert len(set(options)) == len(options)
    assert "json" not in kwargs
    assert kwargs["ssl"] is True and kwargs["allow_redirects"] is False
    assert kwargs["auto_decompress"] is False and kwargs["timeout"].total == 20
    headers = kwargs["headers"]
    assert headers["Token"] == OLD.token and headers["Userid"] == OLD.user_id
    assert headers["Sys-Type"] == "1"
    assert low._signer.matches(
        headers["Sign"],
        kwargs["data"],
        nonce=headers["Nonce"],
        time_ms=headers["Time"],
        token=OLD.token,
    )
    assert low._previous is None
    loader.assert_not_called()
    writer.assert_not_called()


async def test_two_subjects_and_settings_are_four_bundled_reads_with_account_cooldown():
    api, _, http, loader, _, waits = managed(
        [
            resource_reply(),
            resource_reply(settings=True),
            resource_reply(device="d2"),
            resource_reply(settings=True, device="d2"),
        ],
        initial=OLD,
    )
    for device_id in ("d1", "d2"):
        await api.async_read_resources(device_id)
        await api.async_read_resource_settings(device_id)
    assert len(http.calls) == 4 and waits == [30, 30, 30]
    assert [call[0] for call in http.calls] == [1000, 1030, 1060, 1090]
    assert [json.loads(call[2]["data"])["data"][0]["subjectId"] for call in http.calls] == [
        "d1",
        "d1",
        "d2",
        "d2",
    ]
    loader.assert_not_called()


@pytest.mark.parametrize(("method", "path", "options"), GROUPS)
async def test_no_committed_session_never_triggers_resource_login(method, path, options):
    api, _, http, loader, writer, _ = managed([])
    with pytest.raises(AuthenticationRequired):
        await getattr(api, method)("d1")
    assert not http.calls
    loader.assert_not_called()
    writer.assert_not_called()


async def test_login_candidate_alone_is_not_enough_for_supplementary_queries():
    api, _, http, loader, _, _ = managed([login_reply()])
    await api.async_validate_credentials()
    assert api.session is None
    with pytest.raises(AuthenticationRequired):
        await api.async_read_resources("d1")
    assert len(http.calls) == 1
    loader.assert_awaited_once()


async def test_pending_renewal_does_not_replace_committed_resource_auth():
    api, low, http, loader, _, _ = managed([resource_reply()], initial=OLD)
    # A successfully issued candidate may be held during mandatory-read backoff.
    api._pending = NEW
    low.set_session(NEW)
    await api.async_read_resources("d1")
    assert http.calls[0][2]["headers"]["Token"] == OLD.token
    assert api.session == OLD and api._pending == NEW
    loader.assert_not_called()


@pytest.mark.parametrize(
    ("reply", "error"),
    [
        (Response(b'{"code":108,"message":"SECRET"}'), ApplicationError),
        (Response(b'{"code":999999,"message":"SECRET"}'), ApplicationError),
        (Response(status=401), AccessDenied),
        (Response(status=403), AccessDenied),
        (Response(status=429), RateLimited),
        (Response(status=503), TransportError),
        (Response(b'{"code":0,"result":"SECRET"}'), InvalidResponse),
        (TimeoutError("SECRET"), TransportError),
    ],
)
async def test_resource_error_has_no_login_or_trait_state_side_effect(reply, error):
    api, low, http, loader, writer, _ = managed([read_reply(), reply], initial=OLD)
    snapshot = await api.async_read_traits(["d1", "d2"])
    with pytest.raises(error) as caught:
        await api.async_read_resources("d1")
    assert not isinstance(caught.value, SessionExpired)
    assert "SECRET" not in repr(caught.value)
    assert api.session == OLD and low._previous is snapshot
    assert len(http.calls) == 2
    loader.assert_not_called()
    writer.assert_not_called()


async def test_settings_108_is_not_authentication_expiry():
    api, _, http, loader, _, _ = managed([Response(b'{"code":108}')], initial=OLD)
    with pytest.raises(ApplicationError) as caught:
        await api.async_read_resource_settings("d1")
    assert not isinstance(caught.value, AuthenticationRequired)
    assert caught.value.code == 108 and caught.value.http_status == 200
    assert len(http.calls) == 1
    loader.assert_not_called()


async def test_http_429_propagates_once_and_never_reenters_local_contention_wait():
    api, _, http, loader, _, waits = managed(
        [Response(status=429, headers={"Retry-After": "600"})], initial=OLD
    )
    with pytest.raises(RateLimited) as caught:
        await api.async_read_resources("d1")
    assert caught.value.request_sent is True and caught.value.retry_after == 600
    assert len(http.calls) == 1 and not waits
    loader.assert_not_called()


async def test_parallel_identical_resource_reads_share_one_http_request():
    api, _, http, _, _, _ = managed([resource_reply()], initial=OLD)
    results = await asyncio.gather(*(api.async_read_resources("d1") for _ in range(8)))
    assert all(value is results[0] for value in results) and len(http.calls) == 1


@pytest.mark.parametrize("failed", [False, True])
async def test_waiting_trait_read_isolated_from_running_resource_result_or_error(failed):
    entered, release = asyncio.Event(), asyncio.Event()

    class SlowContent:
        async def iter_chunked(self, size):
            entered.set()
            await release.wait()
            yield b'{"code":1234}' if failed else resource_reply().content.data

    response = Response()
    response.content = SlowContent()
    api, _, http, loader, _, waits = managed([response, read_reply()], initial=OLD)
    resource_task = asyncio.create_task(api.async_read_resources("d1"))
    await entered.wait()
    trait_task = asyncio.create_task(api.async_read_traits(["d1", "d2"]))
    await asyncio.sleep(0)
    release.set()
    resource, traits = await asyncio.gather(resource_task, trait_task, return_exceptions=True)
    assert isinstance(resource, ApplicationError if failed else DeviceResources)
    assert isinstance(traits, AccountSnapshot) and set(traits.devices) == {"d1", "d2"}
    assert waits == [30] and len(http.calls) == 2
    loader.assert_not_called()


async def test_background_cooldown_does_not_occupy_foreground_shared_operation():
    entered, release = asyncio.Event(), asyncio.Event()
    waits = []

    async def background_sleep(delay):
        waits.append(delay)
        if len(waits) == 1:
            entered.set()
            await release.wait()
        else:
            low.clock.tick += delay
            await asyncio.sleep(0)

    api, low, http, _, _, _ = managed(
        [read_reply(), resource_reply()], initial=OLD, sleep=background_sleep
    )
    await low.limiter.async_claim()
    resource = asyncio.create_task(api.async_read_resources("d1"))
    await entered.wait()
    assert api._task is None
    low.clock.tick += 30
    # Foreground can claim the newly available slot while resources still wait.
    traits = await api.async_read_traits(["d1", "d2"])
    assert isinstance(traits, AccountSnapshot)
    release.set()
    result = await resource
    assert isinstance(result, DeviceResources)
    assert len(http.calls) == 2 and http.calls[0][1].endswith("/trait/read")
    assert http.calls[1][1].endswith(RESOURCE_PATH)
    assert waits == [30, 30] and http.calls[1][0] == 1060


async def test_close_cancels_background_resource_cooldown_without_http():
    entered = asyncio.Event()

    async def background_sleep(delay):
        entered.set()
        await asyncio.Event().wait()

    api, low, http, _, _, _ = managed([], initial=OLD, sleep=background_sleep)
    await low.limiter.async_claim()
    resource = asyncio.create_task(api.async_read_resources("d1"))
    await entered.wait()
    await api.async_close()
    with pytest.raises(asyncio.CancelledError):
        await resource
    assert not http.calls and not api._resource_waiters


async def test_close_cancels_active_resource_request_and_closes_response():
    entered = asyncio.Event()

    class SlowContent:
        async def iter_chunked(self, size):
            entered.set()
            await asyncio.Event().wait()
            yield b""

    response = Response()
    response.content = SlowContent()
    api, _, http, _, _, _ = managed([response], initial=OLD)
    resource = asyncio.create_task(api.async_read_resources("d1"))
    await entered.wait()
    await api.async_close()
    with pytest.raises(asyncio.CancelledError):
        await resource
    assert len(http.calls) == 1 and response.exited and not api._resource_waiters


@pytest.mark.parametrize("device", [None, "", 1, [], "d" * 257])
async def test_invalid_resource_selection_rejected_before_request(device):
    api, _, http, _, _, _ = managed([], initial=OLD)
    with pytest.raises(InvalidResponse):
        await api.async_read_resources(device)
    assert not http.calls


@pytest.mark.parametrize("field", ["resource_query_path", "resource_settings_path"])
async def test_endpoint_cannot_be_replaced_by_arbitrary_path(field):
    api, low, http, _, _, _ = managed([], initial=OLD)
    low.profile = replace(low.profile, **{field: "/unreviewed/write"})
    with pytest.raises(ProtocolUnsupported):
        await api.async_read_resources("d1")
    assert not http.calls


async def test_resource_backoff_longer_than_30_seconds_never_hides_a_long_wait():
    api, low, http, _, _, waits = managed([], initial=OLD)
    low.limiter.failure(600)
    with pytest.raises(RateLimited) as caught:
        await api.async_read_resources("d1")
    assert caught.value.retry_after == 600 and not waits and not http.calls


@pytest.mark.parametrize(("method", "path", "options"), GROUPS)
@pytest.mark.parametrize(("consent", "live"), [(False, True), (True, False)])
async def test_resource_transport_requires_both_consent_layers(
    method, path, options, consent, live
):
    api, _, http, loader, _, _ = managed([], initial=OLD, consent=consent, live=live)
    with pytest.raises((ProtocolUnsupported, AuthenticationRequired)):
        await getattr(api, method)("d1")
    assert not http.calls
    loader.assert_not_called()


async def test_lowlevel_resource_requires_auth_without_inventing_credentials():
    _, low, http, _, _, _ = managed([])
    with pytest.raises(AuthenticationRequired):
        await low.async_read_resources("d1")
    assert not http.calls


async def test_resource_log_events_are_fixed_and_exclude_response_ids_values(caplog):
    api, _, _, _, _, _ = managed(
        [Response(b'{"code":987,"message":"sensitive-resource-SECRET"}')], initial=OLD
    )
    with pytest.raises(ApplicationError):
        await api.async_read_resources("device-sensitive-SECRET")
    payload = json.loads(caplog.records[-1].getMessage())
    assert payload["operation"] == "resource_read" and payload["application_code"] == 987
    assert "SECRET" not in caplog.text

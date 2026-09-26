"""Batching, local liveness and failure classification without cloud access."""

import asyncio
from unittest.mock import Mock

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.aqara_presence_lab.api.errors import (
    AccessDenied,
    ApplicationError,
    AuthenticationRequired,
    InvalidResponse,
    ProtocolUnsupported,
    RateLimited,
    SignatureRejected,
    TransportError,
)
from custom_components.aqara_presence_lab.coordinator import AqaraCoordinator


async def test_coalesces_and_cooldown(hass, aqara_entry, aqara_client, aqara_snapshot):
    now = [100.0]
    coordinator = AqaraCoordinator(hass, aqara_entry, aqara_client, clock=lambda: now[0])
    started, release = asyncio.Event(), asyncio.Event()

    async def read(*args):
        started.set()
        await release.wait()
        return aqara_snapshot

    aqara_client.async_read_traits.side_effect = read
    first = asyncio.create_task(coordinator._async_update_data())
    await started.wait()
    second = asyncio.create_task(coordinator._async_update_data())
    release.set()
    results = await asyncio.gather(first, second)
    assert results == [aqara_snapshot, aqara_snapshot]
    assert aqara_client.async_read_traits.await_count == 1
    assert aqara_client.async_read_traits.call_args.args[0] == tuple(aqara_entry.data["device_ids"])
    coordinator.async_set_updated_data(aqara_snapshot)
    await coordinator._async_update_data()
    assert aqara_client.async_read_traits.await_count == 1
    now[0] += 31
    await coordinator._async_update_data()
    assert aqara_client.async_read_traits.await_count == 2
    await coordinator.async_shutdown()


async def test_stale_timer_does_not_poll_and_stops(hass, aqara_entry, aqara_client):
    now = [100.0]
    coordinator = AqaraCoordinator(hass, aqara_entry, aqara_client, clock=lambda: now[0])
    await coordinator.async_refresh()
    listener = Mock()
    unsubscribe = coordinator.async_add_listener(listener)
    now[0] += 621
    coordinator._async_check_liveness()
    assert coordinator.transport_stale
    assert coordinator.connection_status == "retry_wait"
    listener.assert_called_once()
    aqara_client.async_read_traits.assert_awaited_once()
    handle = coordinator._stale_timer
    assert handle is not None
    unsubscribe()
    await coordinator.async_shutdown()
    assert handle.cancelled()
    assert coordinator._stale_timer is None
    assert coordinator._unsub_refresh is None
    coordinator._async_check_liveness()
    aqara_client.async_read_traits.assert_awaited_once()


@pytest.mark.parametrize(
    ("error", "exception", "status"),
    [
        (AuthenticationRequired(), ConfigEntryAuthFailed, "reauth_required"),
        (ProtocolUnsupported(), ConfigEntryError, "protocol_unsupported"),
        (SignatureRejected(), ConfigEntryError, "protocol_unsupported"),
        (RateLimited(180), UpdateFailed, "retry_wait"),
        (TransportError(), UpdateFailed, "retry_wait"),
        (AccessDenied(), ConfigEntryError, "protocol_unsupported"),
        (ApplicationError(4321), ConfigEntryError, "protocol_unsupported"),
        (InvalidResponse(), ConfigEntryError, "protocol_unsupported"),
    ],
)
async def test_classified_errors(hass, aqara_entry, aqara_client, error, exception, status, caplog):
    aqara_client.async_read_traits.side_effect = error
    coordinator = AqaraCoordinator(hass, aqara_entry, aqara_client)
    with pytest.raises(exception) as raised:
        await coordinator._async_update_data()
    assert coordinator.connection_status == status
    if isinstance(error, RateLimited):
        assert raised.value.retry_after == 180
    assert aqara_client.async_read_traits.await_count == 1
    assert "synthetic-session-secret" not in caplog.text
    await coordinator.async_shutdown()


async def test_unload_cancels_pending_request_without_retry(hass, aqara_entry, aqara_client):
    started = asyncio.Event()

    async def read(*args):
        started.set()
        await asyncio.Event().wait()

    aqara_client.async_read_traits.side_effect = read
    coordinator = AqaraCoordinator(hass, aqara_entry, aqara_client)
    pending = asyncio.create_task(coordinator._async_update_data())
    await started.wait()
    await coordinator.async_shutdown()
    with pytest.raises(asyncio.CancelledError):
        await pending
    aqara_client.async_close.assert_awaited_once()
    aqara_client.async_read_traits.assert_awaited_once()
    await coordinator.async_shutdown()
    aqara_client.async_close.assert_awaited_once()


@pytest.mark.parametrize(
    "error",
    [
        AuthenticationRequired(),
        ProtocolUnsupported(),
        AccessDenied(),
        ApplicationError(123),
        InvalidResponse(),
        SignatureRejected(),
    ],
)
async def test_terminal_failure_stops_polling_and_liveness_preserves_reason(
    hass, aqara_entry, aqara_client, error
):
    now = [100.0]
    coordinator = AqaraCoordinator(hass, aqara_entry, aqara_client, clock=lambda: now[0])
    await coordinator.async_refresh()
    unsubscribe = coordinator.async_add_listener(Mock())
    aqara_client.async_read_traits.side_effect = error
    now[0] += 31
    with pytest.raises((ConfigEntryAuthFailed, ConfigEntryError)):
        await coordinator._async_update_data()
    status, reason = coordinator.connection_status, coordinator.error_key
    assert coordinator.update_interval is None
    assert coordinator._unsub_refresh is None
    now[0] += 4000
    coordinator._async_check_liveness()
    assert coordinator.transport_stale
    assert (coordinator.connection_status, coordinator.error_key) == (status, reason)
    with pytest.raises((ConfigEntryAuthFailed, ConfigEntryError)):
        await coordinator._async_update_data()
    assert aqara_client.async_read_traits.await_count == 2
    unsubscribe()
    await coordinator.async_shutdown()


async def test_factory_shares_server_backoff_across_setup_and_flow(hass, aqara_entry):
    from custom_components.aqara_presence_lab.coordinator import create_client

    first = create_client(hass, dict(aqara_entry.data))
    first.limiter.failure(3600)
    await first.async_close()
    next_attempt = create_client(hass, {**aqara_entry.data, "token": "new-session-token"})
    assert first.limiter is next_attempt.limiter
    with pytest.raises(RateLimited) as error:
        await next_attempt.limiter.async_claim()
    assert error.value.retry_after > 3590
    await next_attempt.async_close()


async def test_manual_refresh_joins_poll_without_trailing_request(
    hass, aqara_entry, aqara_client, aqara_snapshot
):
    started, release = asyncio.Event(), asyncio.Event()

    async def read(*args):
        started.set()
        await release.wait()
        return aqara_snapshot

    aqara_client.async_read_traits.side_effect = read
    coordinator = AqaraCoordinator(hass, aqara_entry, aqara_client)
    scheduled = asyncio.create_task(coordinator.async_refresh())
    await started.wait()
    manual = asyncio.create_task(coordinator.async_request_refresh())
    release.set()
    await asyncio.gather(scheduled, manual)
    await coordinator.async_request_refresh()
    assert aqara_client.async_read_traits.await_count == 1
    assert coordinator._debounced_refresh._timer_task is None
    await coordinator.async_shutdown()

"""Bounded on-account probe: measured cadence, privacy and lifecycle rollback."""

import asyncio
import json
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ServiceValidationError

from custom_components.aqara_presence_lab.api.rate_limit import AccountRateLimiter
from custom_components.aqara_presence_lab.api.resources import parse_resource_response
from custom_components.aqara_presence_lab.const import DOMAIN
from custom_components.aqara_presence_lab.coordinator import AqaraCoordinator
from custom_components.aqara_presence_lab.polling_probe import (
    async_register_probe_service,
    async_run_probe,
)
from tests.transport_helpers import Clock


@pytest.fixture
async def probe(hass, aqara_entry, aqara_client):
    clock = Clock()
    limiter = AccountRateLimiter(clock=clock, jitter=lambda: 0)
    aqara_client.limiter = limiter
    co = AqaraCoordinator(hass, aqara_entry, aqara_client, clock=clock.monotonic)
    co.connection_status = "ready"
    calls = []

    async def read(did):
        clock.tick += limiter.retry_after
        await limiter.async_claim()
        calls.append((did, clock.tick))
        clock.tick += 0.1
        return parse_resource_response(
            {"code": 0, "result": [{"attr": "lux", "value": len(calls)}]}, device_id=did
        )

    aqara_client.async_read_resources.side_effect = read
    yield co, clock, limiter, calls
    await co.async_shutdown()


async def test_ten_read_limit_measurements_restore_and_redaction(probe, aqara_client, caplog):
    co, clock, limiter, calls = probe
    await async_run_probe(co)
    result = co.polling_probe
    assert result["status"] == "completed"
    assert result["successful_reads"] == 10 and len(calls) == 10
    assert [round(calls[i][1] - calls[i - 1][1]) for i in range(1, 10)] == [
        15,
        15,
        15,
        10,
        10,
        10,
        5,
        5,
        5,
    ]
    assert all(s["request_duration_seconds"] == 0.1 for s in result["samples"])
    assert all(s["present_fields"] == 1 for s in result["samples"])
    assert result["samples"][2]["changed_fields"] == 1
    assert limiter.read_spacing == 30 and limiter.retry_after == pytest.approx(29.9)
    assert not co._supplemental_paused
    aqara_client.async_read_traits.assert_not_called()
    aqara_client.async_read_resource_settings.assert_not_called()
    for did in co.device_ids:
        assert did not in json.dumps(result) + caplog.text


async def test_first_failure_stops_without_retry_and_preserves_backoff(probe, aqara_client):
    co, clock, limiter, calls = probe
    limiter.configure_read_spacing(10)

    async def broken(did):
        limiter.failure(900)
        raise ValueError("SECRET")

    aqara_client.async_read_resources.side_effect = broken
    await async_run_probe(co)
    assert co.polling_probe["status"] == "stopped_on_error"
    assert co.polling_probe["completed_reads"] == 1
    aqara_client.async_read_resources.assert_awaited_once()
    assert limiter.requested_read_spacing == 10 and limiter.read_spacing == 30
    assert limiter.retry_after == 900
    assert "SECRET" not in json.dumps(co.polling_probe)


async def test_cancel_restores_and_releases_pause(probe, aqara_client):
    co, clock, limiter, calls = probe
    entered = asyncio.Event()

    async def wait(did):
        entered.set()
        await asyncio.Event().wait()

    aqara_client.async_read_resources.side_effect = wait
    task = asyncio.create_task(async_run_probe(co))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert co.polling_probe["status"] == "cancelled"
    assert not co._supplemental_paused and limiter.read_spacing == 30


async def test_probe_does_not_erase_previous_suspension(probe):
    co, clock, limiter, calls = probe
    limiter.configure_read_spacing(5)
    limiter.suspend_acceleration()
    await async_run_probe(co)
    assert limiter.requested_read_spacing == 5 and limiter.read_spacing == 30


async def test_probe_aborts_if_account_changed_while_draining(probe):
    co, clock, limiter, calls = probe
    co.connection_status = "reauth_required"
    await async_run_probe(co)
    assert co.polling_probe["status"] == "aborted" and not calls
    assert not co._supplemental_paused


async def test_service_rejects_unloaded_or_other_entry(hass, aqara_entry):
    aqara_entry.add_to_hass(hass)
    async_register_probe_service(hass)
    for entry_id in (aqara_entry.entry_id, "missing"):
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                DOMAIN, "benchmark_polling", {"entry_id": entry_id}, blocking=True
            )


async def test_service_response_duplicate_guard_and_no_secrets(hass, aqara_entry, probe):
    co, clock, limiter, calls = probe
    aqara_entry.add_to_hass(hass)
    aqara_entry.runtime_data = co
    aqara_entry._async_set_state(hass, ConfigEntryState.LOADED, None)
    co.resource_status = dict.fromkeys(co.resource_next_due, "ready")
    entered, release = asyncio.Event(), asyncio.Event()

    async def pending(_co):
        entered.set()
        await release.wait()

    async_register_probe_service(hass)
    with patch(
        "custom_components.aqara_presence_lab.polling_probe.async_run_probe", side_effect=pending
    ):
        result = await hass.services.async_call(
            DOMAIN,
            "benchmark_polling",
            {"entry_id": aqara_entry.entry_id},
            blocking=True,
            return_response=True,
        )
        await entered.wait()
        assert result == {"status": "started", "request_limit": 10}
        with pytest.raises(ServiceValidationError, match="already running"):
            await hass.services.async_call(
                DOMAIN, "benchmark_polling", {"entry_id": aqara_entry.entry_id}, blocking=True
            )
        release.set()
        await co._probe_task

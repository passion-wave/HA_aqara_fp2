"""Independent probe lifecycle review through real managed HTTP cancellation."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import Context
from homeassistant.exceptions import Unauthorized, UnknownUser

from custom_components.aqara_presence_lab.api.resources import parse_resource_response
from custom_components.aqara_presence_lab.const import DOMAIN
from custom_components.aqara_presence_lab.coordinator import AqaraCoordinator
from custom_components.aqara_presence_lab.polling_probe import (
    async_register_probe_service,
    async_run_probe,
)
from tests.test_account import OLD, managed
from tests.transport_helpers import Response

A, B = "lumi1.000000000001", "lumi1.000000000002"


class TrackedResponse(Response):
    def __init__(self, tracker, value=12, *, slow=False):
        super().__init__(
            json.dumps({"code": 0, "result": [{"attr": "lux", "value": value}]}).encode()
        )
        self.tracker = tracker
        self.slow = slow
        if slow:
            self.content = self

    async def __aenter__(self):
        self.tracker["active"] += 1
        self.tracker["maximum"] = max(self.tracker["active"], self.tracker["maximum"])
        return self

    async def iter_chunked(self, size):
        self.tracker["entered"].set()
        await asyncio.Event().wait()
        yield b""

    async def __aexit__(self, *args):
        if self.slow:
            self.tracker["cleanup_started"].set()
            await self.tracker["release_cleanup"].wait()
        self.tracker["active"] -= 1
        self.exited = True


def tracker():
    return {
        "active": 0,
        "maximum": 0,
        "entered": asyncio.Event(),
        "cleanup_started": asyncio.Event(),
        "release_cleanup": asyncio.Event(),
    }


def prepare(hass, entry, client, snapshot, clock):
    coordinator = AqaraCoordinator(hass, entry, client, clock=clock.monotonic)
    coordinator.data = snapshot
    coordinator.connection_status = "ready"
    coordinator._supplemental_started = True
    for device in (A, B):
        for kind in ("resources", "settings"):
            key = (device, kind)
            coordinator.resource_status[key] = "ready"
            coordinator.resource_received_monotonic[key] = clock.monotonic()
            coordinator.resource_data[key] = parse_resource_response(
                {"code": 0, "result": [{"attr": "lux", "value": 9}]}, device_id=device
            )
    return coordinator


async def test_probe_waits_for_cancelled_real_http_cleanup_then_only_ten_reads(
    hass, aqara_entry, aqara_snapshot
):
    tracking = tracker()
    slow = TrackedResponse(tracking, slow=True)
    replies = [slow, *(TrackedResponse(tracking, value=index + 20) for index in range(10))]
    api, low, http, loader, writer, waits = managed(replies, initial=OLD)
    co = prepare(hass, aqara_entry, api, aqara_snapshot, low.clock)
    previous = co.resource_data[(A, "resources")]
    co.async_schedule_supplemental()
    await tracking["entered"].wait()
    cancelled_background = co._resource_task
    probe_task = co._probe_task = asyncio.create_task(async_run_probe(co))
    await tracking["cleanup_started"].wait()
    # Cancellation is draining the real response context. Nothing is shielded
    # into the background and no probe read may overlap this unfinished request.
    assert co._supplemental_paused and not probe_task.done()
    assert len(http.calls) == 1 and tracking["active"] == 1
    assert co.resource_data[(A, "resources")] is previous
    tracking["release_cleanup"].set()
    await probe_task
    assert cancelled_background.cancelled() and slow.exited
    assert co.polling_probe["status"] == "completed"
    assert co.polling_probe["completed_reads"] == 10
    assert co.polling_probe["successful_reads"] == 10
    assert len(http.calls) == 11  # One cancelled normal read, then ten probe reads.
    assert tracking["maximum"] == 1 and tracking["active"] == 0
    assert all("/res/query" in url for _, url, _ in http.calls)
    assert all(not url.endswith("/by/resourceId") for _, url, _ in http.calls)
    assert co.resource_failed_reads == 0
    loader.assert_not_called()
    writer.assert_not_called()
    await co.async_shutdown()
    assert api._task is None and not api._resource_waiters


async def test_shutdown_drains_probe_http_before_close_and_cannot_resume(
    hass, aqara_entry, aqara_snapshot
):
    tracking = tracker()
    slow = TrackedResponse(tracking, slow=True)
    api, low, http, loader, writer, waits = managed([slow], initial=OLD)
    co = prepare(hass, aqara_entry, api, aqara_snapshot, low.clock)
    previous = co.resource_data[(A, "resources")]
    probe_task = co._probe_task = asyncio.create_task(async_run_probe(co))
    await tracking["entered"].wait()
    shutdown = asyncio.create_task(co.async_shutdown())
    await tracking["cleanup_started"].wait()
    assert co._closed and not shutdown.done()
    assert co.resource_data[(A, "resources")] is previous
    assert len(http.calls) == 1
    tracking["release_cleanup"].set()
    await shutdown
    assert probe_task.cancelled() and slow.exited
    assert co.polling_probe["status"] == "cancelled"
    assert co._probe_task is None and co._resource_task is None and co._resource_timer is None
    assert co.resource_data[(A, "resources")] is previous
    assert api._closed and low._closed
    assert api._task is None and not api._resource_waiters
    assert tracking["active"] == 0 and tracking["maximum"] == 1
    assert co.client.limiter.read_spacing == 30
    loader.assert_not_called()
    writer.assert_not_called()


async def test_only_admin_user_can_start_probe(
    hass, hass_admin_user, hass_read_only_user, aqara_entry, aqara_client, aqara_snapshot
):
    aqara_entry.add_to_hass(hass)
    co = AqaraCoordinator(hass, aqara_entry, aqara_client)
    co.data = aqara_snapshot
    co.connection_status = "ready"
    co.resource_status = dict.fromkeys(co.resource_next_due, "ready")
    aqara_entry.runtime_data = co
    aqara_entry._async_set_state(hass, ConfigEntryState.LOADED, None)
    async_register_probe_service(hass)
    entered, release = asyncio.Event(), asyncio.Event()

    async def pending(coordinator):
        entered.set()
        await release.wait()

    run = AsyncMock(side_effect=pending)
    with patch("custom_components.aqara_presence_lab.polling_probe.async_run_probe", run):
        for user_id, exception in (
            (hass_read_only_user.id, Unauthorized),
            ("missing-user", UnknownUser),
        ):
            with pytest.raises(exception):
                await hass.services.async_call(
                    DOMAIN,
                    "benchmark_polling",
                    {"entry_id": aqara_entry.entry_id},
                    context=Context(user_id=user_id),
                    blocking=True,
                    return_response=True,
                )
        assert co._probe_task is None
        run.assert_not_called()
        result = await hass.services.async_call(
            DOMAIN,
            "benchmark_polling",
            {"entry_id": aqara_entry.entry_id},
            context=Context(user_id=hass_admin_user.id),
            blocking=True,
            return_response=True,
        )
        await entered.wait()
        assert result == {"status": "started", "request_limit": 10}
        run.assert_awaited_once_with(co)
        release.set()
        await co._probe_task
    await co.async_shutdown()

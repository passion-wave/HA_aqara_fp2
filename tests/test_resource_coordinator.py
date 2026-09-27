"""Supplementary reads stay isolated, fair and cancellable in HA."""

import asyncio
from dataclasses import replace
from unittest.mock import Mock

import pytest

from custom_components.aqara_presence_lab.api.errors import (
    ApplicationError,
    AuthenticationRequired,
    InvalidResponse,
    RateLimited,
    TransportError,
)
from custom_components.aqara_presence_lab.api.resources import parse_resource_response
from custom_components.aqara_presence_lab.coordinator import AqaraCoordinator

A, B = "lumi1.000000000001", "lumi1.000000000002"


def resource(device=A, **values):
    return parse_resource_response(
        {"code": 0, "result": [{"attr": attr, "value": value} for attr, value in values.items()]},
        device_id=device,
    )


async def finish_resources(coordinator):
    task = coordinator._resource_task
    if task is not None:
        await task


async def test_resources_do_not_block_primary_setup_or_add_parallel_sweeps(
    hass, aqara_entry, aqara_client
):
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def read(device):
        calls.append(device)
        entered.set()
        await release.wait()
        return resource(device, lux=13)

    aqara_client.async_read_resources.side_effect = read
    now = [100.0]
    coordinator = AqaraCoordinator(hass, aqara_entry, aqara_client, clock=lambda: now[0])
    await asyncio.wait_for(coordinator.async_refresh(), 1)
    assert coordinator.connection_status == "ready"
    assert coordinator.data.devices[A].traits["4.154.32989"].normalized_value == 9
    await entered.wait()
    task = coordinator._resource_task
    assert coordinator.supplemental_status == "updating"
    now[0] += 301
    await coordinator.async_refresh()
    assert coordinator._resource_task is task
    assert calls == [A]
    assert aqara_client.async_read_traits.await_count == 2
    release.set()
    await task
    assert calls == [A, B]
    assert aqara_client.async_read_resource_settings.await_count == 2
    assert coordinator.supplemental_status == "ready"
    assert coordinator.resource_successful_reads == 4
    await coordinator.async_shutdown()


@pytest.mark.parametrize(
    "error",
    [
        TransportError(),
        AuthenticationRequired(),
        ApplicationError(108),
        InvalidResponse(),
        RuntimeError("SECRET"),
    ],
)
async def test_optional_failure_invalidates_only_its_group(
    hass, aqara_entry, aqara_client, error, caplog
):
    coordinator = AqaraCoordinator(hass, aqara_entry, aqara_client)
    await coordinator.async_refresh()
    await finish_resources(coordinator)
    coordinator.resource_data[(A, "resources")] = resource(A, lux=99)
    old_received = coordinator.resource_received_monotonic[(A, "resources")]

    async def read(device):
        if device == A:
            raise error
        return resource(device, lux=5)

    aqara_client.async_read_resources.side_effect = read
    coordinator.async_schedule_supplemental()
    await finish_resources(coordinator)
    failed = coordinator.resource_data[(A, "resources")]
    assert not failed.available and not failed.observations
    assert coordinator.resource_received_monotonic[(A, "resources")] == old_received
    assert not coordinator.resource_available(A, "resources")
    assert coordinator.resource_available(A, "settings")
    assert coordinator.resource_available(B, "resources")
    assert coordinator.connection_status == "ready"
    assert coordinator.supplemental_status == "partial_failure"
    assert coordinator.failed_reads == 0 and coordinator.resource_failed_reads == 1
    assert coordinator.update_interval is not None
    assert "SECRET" not in caplog.text
    await coordinator.async_shutdown()


async def test_success_replaces_group_without_merging_old_values(hass, aqara_entry, aqara_client):
    coordinator = AqaraCoordinator(hass, aqara_entry, aqara_client)
    coordinator.resource_data[(A, "resources")] = resource(
        A, lux=44, set_device_mode4=9, heartrate_value=60
    )
    aqara_client.async_read_resources.side_effect = lambda device: resource(device, lux=11)
    await coordinator.async_refresh()
    await finish_resources(coordinator)
    observations = coordinator.resource_data[(A, "resources")].observations
    assert {attr for attr, obs in observations.items() if obs.value_status == "present"} == {"lux"}
    assert observations["heartrate_value"].value is None
    assert not coordinator.resource_sleep_mode(A)
    await coordinator.async_shutdown()


async def test_group_wrong_subject_never_cross_contaminates(hass, aqara_entry, aqara_client):
    coordinator = AqaraCoordinator(hass, aqara_entry, aqara_client)
    aqara_client.async_read_resources.side_effect = lambda device: resource(
        "unexpected-device", lux=42
    )
    await coordinator.async_refresh()
    await finish_resources(coordinator)
    assert coordinator.resource_errors[(A, "resources")] == "api_changed"
    assert (A, "resources") not in coordinator.resource_data
    assert coordinator.resource_successful_reads == 2
    await coordinator.async_shutdown()


async def test_retry_cursor_prevents_permanent_settings_starvation(hass, aqara_entry, aqara_client):
    coordinator = AqaraCoordinator(hass, aqara_entry, aqara_client)
    aqara_client.async_read_resource_settings.side_effect = RateLimited(300)
    await coordinator.async_refresh()
    await finish_resources(coordinator)
    assert aqara_client.async_read_resources.call_args_list[0].args == (A,)
    assert aqara_client.async_read_resources.await_count == 1
    assert coordinator._resource_cursor == 1
    aqara_client.async_read_resource_settings.side_effect = lambda device: resource(device)
    coordinator.async_schedule_supplemental()
    await finish_resources(coordinator)
    assert aqara_client.async_read_resource_settings.call_args_list[1].args == (A,)
    assert coordinator.resource_available(B, "resources")
    assert coordinator.resource_available(B, "settings")
    assert coordinator._resource_cursor == 1
    await coordinator.async_shutdown()


async def test_resource_age_is_monotonic_and_update_cannot_revive_stale_data(
    hass, aqara_entry, aqara_client
):
    now = [100.0]
    coordinator = AqaraCoordinator(hass, aqara_entry, aqara_client, clock=lambda: now[0])
    await coordinator.async_refresh()
    await finish_resources(coordinator)
    old = coordinator.resource_data[(A, "resources")]
    # A new response timestamp alone is not a receipt by this coordinator.
    coordinator.resource_data[(A, "resources")] = replace(
        old, received_at_utc=old.received_at_utc.replace(year=2099)
    )
    now[0] += coordinator._resource_max_age + 1
    assert not coordinator.resource_available(A, "resources")
    listener = Mock()
    remove = coordinator.async_add_listener(listener)
    coordinator._async_check_liveness()
    assert coordinator.resource_status[(A, "resources")] == "stale"
    listener.assert_called_once()
    coordinator.resource_status[(A, "resources")] = "updating"
    assert not coordinator.resource_available(A, "resources")
    aqara_client.async_read_resources.assert_awaited()
    assert aqara_client.async_read_resources.await_count == 2
    remove()
    await coordinator.async_shutdown()


async def test_unload_cancels_resource_wait_and_prevents_later_publication(
    hass, aqara_entry, aqara_client
):
    entered = asyncio.Event()

    async def slow(device):
        entered.set()
        await asyncio.Event().wait()

    aqara_client.async_read_resources.side_effect = slow
    coordinator = AqaraCoordinator(hass, aqara_entry, aqara_client)
    await coordinator.async_refresh()
    await entered.wait()
    task = coordinator._resource_task
    await coordinator.async_shutdown()
    assert task.cancelled() and coordinator._resource_task is None
    assert coordinator._closed and not coordinator.resource_data
    coordinator.async_schedule_supplemental()
    aqara_client.async_read_resources.assert_awaited_once()
    aqara_client.async_read_resource_settings.assert_not_called()
    aqara_client.async_close.assert_awaited_once()


async def test_large_account_stale_threshold_includes_two_contended_sweeps(
    hass, aqara_entry, aqara_client
):
    aqara_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        aqara_entry,
        data={
            **aqara_entry.data,
            "device_ids": [f"device-{index}" for index in range(100)],
            "poll_interval": 60,
        },
    )
    coordinator = AqaraCoordinator(hass, aqara_entry, aqara_client)
    assert coordinator._resource_max_age >= 2 * 200 * 60 + 60
    await coordinator.async_shutdown()

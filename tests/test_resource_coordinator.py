"""Independent hot/status polling, settings fairness and bounded probe isolation."""

import asyncio
from dataclasses import replace
from unittest.mock import Mock

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.aqara_presence_lab.api.errors import (
    ApplicationError,
    AuthenticationRequired,
    InvalidResponse,
    ProtocolUnsupported,
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


@pytest.fixture
async def scheduler(hass, aqara_entry, aqara_client):
    now = [100.0]
    aqara_client.limiter.read_spacing = 30
    aqara_client.limiter.retry_after = 30
    coordinator = AqaraCoordinator(hass, aqara_entry, aqara_client, clock=lambda: now[0])
    yield coordinator, now
    await coordinator.async_shutdown()


async def finish_resources(coordinator):
    if task := coordinator._resource_task:
        await task


async def tick(coordinator, now, advance=30):
    now[0] += advance
    if coordinator._resource_timer is not None:
        coordinator._resource_timer.cancel()
    coordinator._async_supplemental_timer()
    await finish_resources(coordinator)


async def startup(coordinator, now):
    await coordinator.async_refresh()
    await finish_resources(coordinator)
    for _ in range(3):
        await tick(coordinator, now)


async def test_initial_priority_one_bounded_read_per_tick_and_no_parallel_tasks(
    scheduler, aqara_client
):
    coordinator, now = scheduler
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def read(device):
        calls.append((device, "resources"))
        entered.set()
        await release.wait()
        return resource(device, lux=13)

    async def settings(device):
        calls.append((device, "settings"))
        return resource(device)

    aqara_client.async_read_resources.side_effect = read
    aqara_client.async_read_resource_settings.side_effect = settings
    await asyncio.wait_for(coordinator.async_refresh(), 1)
    assert coordinator.connection_status == "ready"
    assert coordinator.data.devices[A].traits["4.154.32989"].normalized_value == 9
    await entered.wait()
    task = coordinator._resource_task
    coordinator.async_schedule_supplemental()
    assert coordinator._resource_task is task
    assert coordinator.supplemental_status == "updating"
    release.set()
    await task
    assert calls == [(A, "resources")]
    assert coordinator._resource_timer is not None
    for _ in range(3):
        await tick(coordinator, now)
    assert calls == [(A, "resources"), (B, "resources"), (A, "settings"), (B, "settings")]
    assert coordinator.resource_successful_reads == 4
    assert coordinator.supplemental_status == "ready"
    assert aqara_client.async_read_traits.await_count == 1


async def test_continuous_hot_round_robin_and_rare_settings(scheduler, aqara_client):
    coordinator, now = scheduler
    await startup(coordinator, now)
    assert coordinator.resource_interval == 60
    assert coordinator.settings_interval == 3600
    aqara_client.async_read_resources.reset_mock()
    for _ in range(8):
        await tick(coordinator, now)
    assert [call.args[0] for call in aqara_client.async_read_resources.call_args_list] == [A, B] * 4
    assert aqara_client.async_read_resource_settings.await_count == 2
    assert aqara_client.async_read_traits.await_count == 1


async def test_overdue_settings_get_slot_after_at_most_two_hot_rounds(scheduler, aqara_client):
    coordinator, now = scheduler
    await startup(coordinator, now)
    coordinator.resource_next_due[(A, "settings")] = 0
    coordinator.resource_next_due[(B, "settings")] = 0
    assert coordinator._hot_since_settings == 0
    aqara_client.async_read_resource_settings.reset_mock()
    for _ in range(4):
        await tick(coordinator, now)
    aqara_client.async_read_resource_settings.assert_not_called()
    await tick(coordinator, now)
    aqara_client.async_read_resource_settings.assert_awaited_once_with(A)
    for _ in range(5):
        await tick(coordinator, now)
    assert aqara_client.async_read_resource_settings.call_args.args == (B,)


async def test_scheduler_continues_after_retryable_qlink_failure(scheduler, aqara_client):
    coordinator, now = scheduler
    await startup(coordinator, now)
    aqara_client.async_read_traits.side_effect = TransportError()
    now[0] += 300
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
    assert coordinator.connection_status == "retry_wait"
    previous = coordinator.resource_successful_reads
    await tick(coordinator, now)
    assert coordinator.resource_successful_reads == previous + 1
    assert coordinator.resource_available(A, "resources")
    assert coordinator._resource_timer is not None


@pytest.mark.parametrize(
    "error", [TransportError(), ApplicationError(108), InvalidResponse(), RuntimeError("SECRET")]
)
async def test_optional_failure_invalidates_only_its_group(scheduler, aqara_client, error, caplog):
    coordinator, now = scheduler
    await startup(coordinator, now)
    coordinator.resource_data[(A, "resources")] = resource(A, lux=99)
    received = coordinator.resource_received_monotonic[(A, "resources")]

    async def read(device):
        if device == A:
            raise error
        return resource(device, lux=5)

    aqara_client.async_read_resources.side_effect = read
    await tick(coordinator, now)
    failed = coordinator.resource_data[(A, "resources")]
    assert not failed.available and not failed.observations
    assert coordinator.resource_received_monotonic[(A, "resources")] == received
    assert not coordinator.resource_available(A, "resources")
    assert coordinator.resource_available(A, "settings")
    assert coordinator.resource_available(B, "resources")
    assert coordinator.connection_status == "ready"
    assert coordinator.failed_reads == 0 and coordinator.resource_failed_reads == 1
    assert coordinator._resource_timer is not None
    await tick(coordinator, now)
    assert coordinator.resource_available(B, "resources")
    assert "SECRET" not in caplog.text


@pytest.mark.parametrize("error", [AuthenticationRequired(), ProtocolUnsupported()])
async def test_terminal_resource_error_stops_scheduler_until_reload(scheduler, aqara_client, error):
    coordinator, now = scheduler
    aqara_client.async_read_resources.side_effect = error
    await coordinator.async_refresh()
    await finish_resources(coordinator)
    assert coordinator._supplemental_terminal_error is not None
    assert coordinator._resource_timer is None
    coordinator.async_resume_supplemental()
    assert coordinator._resource_task is None
    aqara_client.async_read_resources.assert_awaited_once()
    # The optional endpoint does not invalidate a successful QLINK batch.
    assert coordinator.connection_status == "ready"


@pytest.mark.parametrize("error", [AuthenticationRequired(), ProtocolUnsupported()])
async def test_terminal_qlink_error_stops_existing_background_timer(scheduler, aqara_client, error):
    coordinator, now = scheduler
    await startup(coordinator, now)
    timer = coordinator._resource_timer
    aqara_client.async_read_traits.side_effect = error
    now[0] += 300
    with pytest.raises((ConfigEntryAuthFailed, ConfigEntryError)):
        await coordinator._async_update_data()
    assert timer.cancelled() and coordinator._resource_timer is None
    coordinator.async_schedule_supplemental()
    assert coordinator._resource_task is None


async def test_success_replaces_group_without_merging_old_values(scheduler, aqara_client):
    coordinator, _ = scheduler
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


async def test_group_wrong_subject_never_cross_contaminates(scheduler, aqara_client):
    coordinator, _ = scheduler
    aqara_client.async_read_resources.side_effect = lambda device: resource(
        "unexpected-device", lux=42
    )
    await coordinator.async_refresh()
    await finish_resources(coordinator)
    assert coordinator.resource_errors[(A, "resources")] == "api_changed"
    assert (A, "resources") not in coordinator.resource_data
    assert coordinator.resource_successful_reads == 0


async def test_rate_limit_preserves_initial_position_and_respects_server_delay(
    scheduler, aqara_client
):
    coordinator, now = scheduler
    await coordinator.async_refresh()
    await finish_resources(coordinator)
    await tick(coordinator, now)
    aqara_client.async_read_resource_settings.side_effect = RateLimited(7200)
    await tick(coordinator, now)
    assert coordinator._initial_cursor == 2
    assert coordinator.resource_next_due[(A, "settings")] == now[0] + 7200
    assert coordinator._resource_timer.when() - coordinator.hass.loop.time() > 7190
    aqara_client.async_read_resource_settings.side_effect = lambda device: resource(device)
    await tick(coordinator, now, 7200)
    assert aqara_client.async_read_resource_settings.call_args.args == (A,)
    assert coordinator._initial_cursor == 3


async def test_settings_age_is_independent_and_stale_hot_data_cannot_revive(
    scheduler, aqara_client
):
    coordinator, now = scheduler
    await startup(coordinator, now)
    old = coordinator.resource_data[(A, "resources")]
    coordinator.resource_data[(A, "resources")] = replace(
        old, received_at_utc=old.received_at_utc.replace(year=2099)
    )
    now[0] += coordinator.resource_max_receive_age("resources") + 1
    assert not coordinator.resource_available(A, "resources")
    assert coordinator.resource_available(A, "settings")
    assert coordinator.resource_max_receive_age("resources") == 300
    assert coordinator.resource_max_receive_age("settings") == 7500
    listener = Mock()
    remove = coordinator.async_add_listener(listener)
    coordinator._async_check_liveness()
    assert coordinator.resource_status[(A, "resources")] == "stale"
    listener.assert_called_once()
    coordinator.resource_status[(A, "resources")] = "updating"
    assert not coordinator.resource_available(A, "resources")
    remove()


async def test_options_and_effective_account_spacing_set_independent_ttls(
    hass, aqara_entry, aqara_client
):
    aqara_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        aqara_entry, options={"resource_interval": 20, "settings_interval": 900}
    )
    aqara_client.limiter.read_spacing = 5
    coordinator = AqaraCoordinator(hass, aqara_entry, aqara_client)
    assert coordinator.resource_interval == 20 and coordinator.settings_interval == 900
    assert coordinator.resource_max_receive_age("resources") == 150
    aqara_client.limiter.read_spacing = 30
    assert coordinator.resource_max_receive_age("resources") == 300
    assert coordinator.resource_max_receive_age("settings") == 2100
    await coordinator.async_shutdown()


async def test_due_timer_can_run_without_any_qlink_refresh(scheduler, aqara_client):
    coordinator, now = scheduler
    await startup(coordinator, now)
    coordinator.resource_next_due = {key: now[0] + 90 for key in coordinator.resource_next_due}
    aqara_client.async_read_resources.reset_mock()
    await tick(coordinator, now, 0)
    aqara_client.async_read_resources.assert_not_called()
    assert coordinator._resource_timer.when() - coordinator.hass.loop.time() > 89
    await tick(coordinator, now, 90)
    aqara_client.async_read_resources.assert_awaited_once_with(A)
    assert aqara_client.async_read_traits.await_count == 1


async def test_pause_blocks_qlink_and_drains_resource_before_probe(scheduler, aqara_client):
    coordinator, now = scheduler
    await startup(coordinator, now)
    timer = coordinator._resource_timer
    await coordinator.async_pause_supplemental()
    assert timer.cancelled() and coordinator._resource_timer is None
    assert coordinator._supplemental_paused
    now[0] += 300
    assert await coordinator._async_update_data() is coordinator.data
    aqara_client.async_read_traits.assert_awaited_once()
    count = coordinator.resource_successful_reads
    assert await coordinator.async_read_supplemental_group(A, "resources")
    assert coordinator.resource_successful_reads == count + 1
    assert coordinator._resource_timer is None and coordinator._resource_task is None
    coordinator.async_resume_supplemental()
    await finish_resources(coordinator)
    assert not coordinator._supplemental_paused and coordinator._resource_timer is not None


async def test_pause_during_active_read_restores_prior_status(scheduler, aqara_client):
    coordinator, now = scheduler
    await startup(coordinator, now)
    entered = asyncio.Event()

    async def slow(device):
        entered.set()
        await asyncio.Event().wait()

    aqara_client.async_read_resources.side_effect = slow
    pending = asyncio.create_task(tick(coordinator, now))
    await entered.wait()
    await coordinator.async_pause_supplemental()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert coordinator._resource_task is None and coordinator._resource_timer is None
    assert coordinator.resource_status[(A, "resources")] == "ready"


async def test_pause_drains_already_running_primary_request(
    scheduler, aqara_client, aqara_snapshot
):
    coordinator, now = scheduler
    await startup(coordinator, now)
    entered, release = asyncio.Event(), asyncio.Event()

    async def read(*args):
        entered.set()
        await release.wait()
        return aqara_snapshot

    aqara_client.async_read_traits.side_effect = read
    now[0] += 300
    primary = asyncio.create_task(coordinator._async_update_data())
    await entered.wait()
    pausing = asyncio.create_task(coordinator.async_pause_supplemental())
    await asyncio.sleep(0)
    assert not pausing.done()
    release.set()
    await asyncio.gather(primary, pausing)
    assert coordinator._supplemental_paused
    assert coordinator._resource_task is None and coordinator._resource_timer is None


async def test_pause_without_primary_snapshot_cannot_fake_data(scheduler):
    coordinator, _ = scheduler
    await coordinator.async_pause_supplemental()
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_unload_cancels_resource_wait_and_probe_without_later_publication(
    scheduler, aqara_client
):
    coordinator, _ = scheduler
    entered = asyncio.Event()

    async def slow(device):
        entered.set()
        await asyncio.Event().wait()

    aqara_client.async_read_resources.side_effect = slow
    await coordinator.async_refresh()
    await entered.wait()
    task = coordinator._resource_task

    async def probe():
        try:
            await asyncio.Event().wait()
        finally:
            coordinator.async_resume_supplemental()

    coordinator._probe_task = asyncio.create_task(probe())
    await asyncio.sleep(0)
    await coordinator.async_shutdown()
    assert task.cancelled() and coordinator._resource_task is None
    assert coordinator._probe_task.cancelled()
    assert coordinator._closed and not coordinator.resource_data
    assert coordinator._resource_timer is None
    aqara_client.async_read_resources.assert_awaited_once()
    aqara_client.async_read_resource_settings.assert_not_called()
    aqara_client.async_close.assert_awaited_once()


async def test_large_account_ttl_scales_with_hot_cycle_not_qlink_or_settings(
    hass, aqara_entry, aqara_client
):
    aqara_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        aqara_entry,
        data={
            **aqara_entry.data,
            "device_ids": [f"device-{index}" for index in range(100)],
            "poll_interval": 3600,
        },
    )
    aqara_client.limiter.read_spacing = 30
    coordinator = AqaraCoordinator(hass, aqara_entry, aqara_client)
    assert coordinator.resource_max_receive_age("resources") == 10100
    assert coordinator.resource_max_receive_age("settings") == 17300
    await coordinator.async_shutdown()


async def test_initial_settings_rate_limit_does_not_block_hot_for_an_hour(scheduler, aqara_client):
    coordinator, now = scheduler
    await coordinator.async_refresh()
    await finish_resources(coordinator)
    await tick(coordinator, now)
    aqara_client.async_read_resource_settings.side_effect = RateLimited(60)
    await tick(coordinator, now)
    assert coordinator.resource_next_due[(A, "settings")] == now[0] + 60
    assert coordinator._resource_timer.when() - coordinator.hass.loop.time() < 61


@pytest.mark.parametrize(
    "error, suspended",
    [
        (InvalidResponse(), True),
        (ApplicationError(108), True),
        (TransportError(), True),
        (RateLimited(60, request_sent=True), True),
        (RateLimited(30), False),
    ],
)
async def test_resource_failures_suspend_acceleration_but_local_wait_does_not(
    scheduler, aqara_client, error, suspended
):
    coordinator, _ = scheduler
    aqara_client.limiter.suspend_acceleration = Mock()
    aqara_client.async_read_resources.side_effect = error
    await coordinator.async_refresh()
    await finish_resources(coordinator)
    assert aqara_client.limiter.suspend_acceleration.called is suspended


@pytest.mark.parametrize(
    "error, suspended",
    [
        (InvalidResponse(), True),
        (ApplicationError(400), True),
        (RateLimited(60, request_sent=True), True),
        (RateLimited(30), False),
    ],
)
async def test_primary_failures_suspend_acceleration_but_local_wait_does_not(
    scheduler, aqara_client, error, suspended
):
    coordinator, _ = scheduler
    aqara_client.limiter.suspend_acceleration = Mock()
    aqara_client.async_read_traits.side_effect = error
    with pytest.raises((UpdateFailed, ConfigEntryError)):
        await coordinator._async_update_data()
    assert aqara_client.limiter.suspend_acceleration.called is suspended

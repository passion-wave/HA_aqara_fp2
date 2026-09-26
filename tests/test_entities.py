"""Properties expose observed values only, with independent diagnostics."""

from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import LIGHT_LUX

from custom_components.aqara_presence_lab.api.parsing import parse_response
from custom_components.aqara_presence_lab.binary_sensor import AqaraConnectionProblem
from custom_components.aqara_presence_lab.button import AqaraRefreshButton
from custom_components.aqara_presence_lab.coordinator import AqaraCoordinator
from custom_components.aqara_presence_lab.sensor import (
    ACCOUNT_SENSORS,
    DEVICE_SENSORS,
    AqaraSensor,
    async_setup_entry,
)


@pytest.fixture
def coordinator(hass, aqara_entry, aqara_client, aqara_snapshot):
    result = AqaraCoordinator(hass, aqara_entry, aqara_client)
    result.data = aqara_snapshot
    result.connection_status = "ready"
    result.last_successful_read = aqara_snapshot.received_at_utc
    return result


def sensor(coordinator, key, device="lumi1.000000000001"):
    description = next(item for item in (*DEVICE_SENSORS, *ACCOUNT_SENSORS) if item.key == key)
    return AqaraSensor(coordinator, description, device)


def test_lux_is_reported_9_without_state_class(coordinator, aqara_client):
    entity = sensor(coordinator, "reported_illuminance")
    assert entity.native_value == 9
    assert entity.device_class == SensorDeviceClass.ILLUMINANCE
    assert entity.native_unit_of_measurement == LIGHT_LUX
    assert entity.state_class is None
    assert entity.extra_state_attributes == {"data_quality": "reported", "value_status": "present"}
    assert entity.available
    assert not entity.should_poll
    aqara_client.async_read_traits.assert_not_called()


def test_raw_zero_is_not_presence(coordinator):
    entity = sensor(coordinator, "presence_raw")
    assert entity.native_value == "0"
    assert entity.device_class is None
    assert entity.state_class is None
    assert not entity.entity_registry_enabled_default
    assert all(
        item.key not in {"person_count", "sleep_stage", "heart_rate", "cloud_occupancy"}
        for item in DEVICE_SENSORS
    )


@pytest.mark.parametrize("value", [None, True, "bad-value", "NaN", "Infinity"])
def test_invalid_lux_never_becomes_zero(coordinator, value):
    coordinator.data = parse_response(
        {
            "code": 0,
            "result": [
                {
                    "deviceId": "lumi1.000000000001",
                    "traits": [{"path": "4.154.32989", "value": value, "defaultValue": "99"}],
                }
            ],
        }
    )
    assert sensor(coordinator, "reported_illuminance").native_value is None


def test_missing_value_never_uses_default_or_history(coordinator):
    coordinator.data = parse_response(
        {
            "code": 0,
            "result": [
                {
                    "deviceId": "lumi1.000000000001",
                    "traits": [{"path": "4.154.32989", "defaultValue": "99"}],
                }
            ],
        },
        previous=coordinator.data,
    )
    entity = sensor(coordinator, "reported_illuminance")
    assert entity.native_value is None
    assert entity.available
    assert entity.extra_state_attributes["value_status"] == "missing"


def test_diagnostics_remain_readable_during_failure(coordinator):
    coordinator.last_update_success = False
    coordinator.connection_status = "retry_wait"
    measurement = sensor(coordinator, "reported_illuminance")
    quality = sensor(coordinator, "data_quality")
    status = sensor(coordinator, "connection_status", None)
    last_read = sensor(coordinator, "last_successful_read", None)
    problem = AqaraConnectionProblem(coordinator)
    assert not measurement.available
    assert quality.available and quality.native_value == "transport_unavailable"
    assert status.available and status.native_value == "retry_wait"
    assert last_read.available and last_read.native_value is not None
    assert problem.available and problem.is_on


def test_partial_response_isolates_device(coordinator):
    coordinator.data = parse_response(
        {
            "code": 0,
            "result": [
                {
                    "deviceId": "lumi1.000000000001",
                    "traits": [{"path": "4.154.32989", "value": "11"}],
                }
            ],
        },
        selected_device_ids=coordinator.device_ids,
    )
    assert sensor(coordinator, "reported_illuminance").available
    assert not sensor(coordinator, "reported_illuminance", "lumi1.000000000002").available


def test_stable_identity_with_name_or_token_changes(coordinator, aqara_entry, aqara_client, hass):
    first = sensor(coordinator, "reported_illuminance")
    changed_data = {**aqara_entry.data, "token": "different-token"}
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    changed_entry = MockConfigEntry(
        domain=aqara_entry.domain, data=changed_data, unique_id=aqara_entry.unique_id
    )
    second_coordinator = AqaraCoordinator(hass, changed_entry, aqara_client)
    renamed_device = replace(coordinator.data.devices["lumi1.000000000001"], name="New name")
    second_coordinator.data = replace(
        coordinator.data, devices={renamed_device.device_id: renamed_device}
    )
    second = sensor(second_coordinator, "reported_illuminance")
    assert first.unique_id == second.unique_id
    assert first.device_info["identifiers"] == second.device_info["identifiers"]
    assert "connections" not in first.device_info
    assert "suggested_area" not in first.device_info


def test_timestamp_is_aware_and_no_receipt_time_substitution(coordinator):
    entity = sensor(coordinator, "presence_source_time")
    assert entity.native_value == datetime(2025, 1, 25, 16, 7, 16, 919000, tzinfo=UTC)
    assert entity.native_value != coordinator.last_successful_read


def test_unchanged_measurement_does_not_write_on_receipt_timestamp(coordinator):
    entity = sensor(coordinator, "reported_illuminance")
    entity.async_write_ha_state = Mock()
    entity._handle_coordinator_update()
    coordinator.data = replace(coordinator.data, received_at_utc=datetime(2026, 9, 27, tzinfo=UTC))
    entity._handle_coordinator_update()
    entity.async_write_ha_state.assert_called_once()
    coordinator.transport_stale = True
    entity._handle_coordinator_update()
    assert entity.async_write_ha_state.call_count == 2


async def test_fall_only_when_observed_and_late_arrival(hass, coordinator, aqara_entry):
    a = "lumi1.000000000001"
    b = "lumi1.000000000002"
    coordinator.data = parse_response(
        {"code": 0, "result": [{"deviceId": a, "traits": []}, {"deviceId": b, "traits": []}]},
        selected_device_ids=(a, b),
        requested_paths={a: ("5.168.33019",), b: ("5.168.33019",)},
    )
    aqara_entry.runtime_data = coordinator
    added = []
    await async_setup_entry(hass, aqara_entry, lambda entities: added.extend(entities))
    assert not any(entity.entity_description.key == "fall_state_raw" for entity in added)
    coordinator.async_set_updated_data(
        parse_response(
            {
                "code": 0,
                "result": [
                    {"deviceId": a, "traits": []},
                    {"deviceId": b, "traits": [{"path": "5.168.33019", "value": "0"}]},
                ],
            },
            selected_device_ids=(a, b),
            requested_paths={a: ("5.168.33019",), b: ("5.168.33019",)},
        )
    )
    falls = [entity for entity in added if entity.entity_description.key == "fall_state_raw"]
    assert len(falls) == 1 and falls[0].device_id == b
    await coordinator.async_shutdown()


async def test_refresh_uses_coordinator(coordinator):
    from unittest.mock import AsyncMock

    coordinator.async_request_refresh = AsyncMock()
    await AqaraRefreshButton(coordinator).async_press()
    coordinator.async_request_refresh.assert_awaited_once()


def test_long_unknown_raw_code_cannot_break_ha_state(coordinator):
    coordinator.data = parse_response(
        {
            "code": 0,
            "result": [
                {
                    "deviceId": "lumi1.000000000001",
                    "traits": [{"path": "2.160.33000", "value": "x" * 300}],
                }
            ],
        }
    )
    assert sensor(coordinator, "presence_raw").native_value is None


def test_private_string_is_not_a_raw_enum_state(coordinator):
    coordinator.data = parse_response(
        {
            "code": 0,
            "result": [
                {
                    "deviceId": "lumi1.000000000001",
                    "traits": [{"path": "2.160.33000", "value": "person@example.invalid"}],
                }
            ],
        }
    )
    assert sensor(coordinator, "presence_raw").native_value is None

"""Observed resource entities do not invent capabilities or live freshness."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import EntityCategory

from custom_components.aqara_presence_lab.api.resources import (
    RESOURCES,
    SETTINGS,
    parse_resource_response,
    parse_resource_settings_response,
)
from custom_components.aqara_presence_lab.binary_sensor import AqaraResourceBinarySensor
from custom_components.aqara_presence_lab.binary_sensor import async_setup_entry as setup_binary
from custom_components.aqara_presence_lab.coordinator import AqaraCoordinator
from custom_components.aqara_presence_lab.diagnostics import async_get_config_entry_diagnostics
from custom_components.aqara_presence_lab.sensor import AqaraResourceEntity, AqaraResourceSensor
from custom_components.aqara_presence_lab.sensor import async_setup_entry as setup_sensor

A = "lumi1.000000000001"


@pytest.fixture
async def coordinator(hass, aqara_entry, aqara_client, aqara_snapshot):
    coordinator = AqaraCoordinator(hass, aqara_entry, aqara_client, clock=lambda: 100.0)
    coordinator.data = aqara_snapshot
    coordinator.connection_status = "ready"
    aqara_entry.runtime_data = coordinator
    yield coordinator
    await coordinator.async_shutdown()


def publish(coordinator, *, kind="resources", **values):
    parser = parse_resource_response if kind == "resources" else parse_resource_settings_response
    group = parser(
        {"code": 0, "result": [{"attr": attr, "value": value} for attr, value in values.items()]},
        device_id=A,
    )
    key = (A, kind)
    coordinator.resource_data[key] = group
    coordinator.resource_status[key] = "ready"
    coordinator.resource_received_monotonic[key] = 100.0
    coordinator.async_update_listeners()
    return group


def sensor(coordinator, attr, kind="resources"):
    return AqaraResourceSensor(
        coordinator, (RESOURCES if kind == "resources" else SETTINGS)[attr], A, kind
    )


async def test_dynamic_entities_only_for_present_values_and_late_sleep_mode(
    hass, aqara_entry, coordinator
):
    added = []
    await setup_sensor(hass, aqara_entry, lambda entities: added.extend(entities))
    await setup_binary(hass, aqara_entry, lambda entities: added.extend(entities))

    def resource_entities():
        return [entity for entity in added if isinstance(entity, AqaraResourceEntity)]

    assert not resource_entities()
    publish(
        coordinator,
        lux=0,
        people_counting=None,
        detection_area1=1,
        heartrate_value=60,
        set_device_mode4=3,
        sleep_state="0",
    )
    assert {entity.spec.attr for entity in resource_entities()} == {
        "lux",
        "detection_area1",
        "set_device_mode4",
    }
    publish(coordinator, lux=0, heartrate_value=60.5, set_device_mode4=9, sleep_state="0")
    assert {entity.spec.attr for entity in resource_entities()} == {
        "lux",
        "detection_area1",
        "set_device_mode4",
        "heartrate_value",
        "sleep_state",
    }
    coordinator.async_update_listeners()
    assert len(resource_entities()) == 5
    heart = next(entity for entity in resource_entities() if entity.spec.attr == "heartrate_value")
    assert heart.native_value == 60.5 and heart.available
    publish(coordinator, heartrate_value=61)
    assert not heart.available  # an old sleep mode cannot be merged into this receipt
    publish(coordinator, set_device_mode4=3, heartrate_value=62)
    assert not heart.available


@pytest.mark.parametrize(
    "attr, value, expected",
    [
        ("people_counting", 0, 0),
        ("people_counting_by_mins", 1.5, 1.5),
        ("lux", 10, 10),
        ("installation_angle", 8, "oblique"),
        ("set_device_mode4", 9, "sleep_monitoring"),
        ("set_device_mode4", 42, None),
    ],
)
async def test_sensor_values_units_enums_and_unknown_codes(coordinator, attr, value, expected):
    publish(coordinator, **{attr: value})
    entity = sensor(coordinator, attr)
    assert entity.native_value == expected
    assert entity.available
    assert entity.state_class is None
    assert entity.extra_state_attributes["data_quality"] == "unverified"
    assert "received_at" not in entity.extra_state_attributes
    if RESOURCES[attr].kind == "enum":
        assert entity.device_class == SensorDeviceClass.ENUM
        assert entity.extra_state_attributes["raw_code"] == value
        assert len(entity.options) == len(set(entity.options))


async def test_source_timestamps_are_never_receipt_substitutes(coordinator):
    group = publish(coordinator, lux=12)
    entity = sensor(coordinator, "lux")
    assert "source_time" not in entity.extra_state_attributes
    observation = replace(
        group.observations["lux"], source_time_utc=datetime(2025, 1, 1, tzinfo=UTC)
    )
    coordinator.resource_data[(A, "resources")] = replace(group, observations={"lux": observation})
    assert entity.extra_state_attributes["source_time"] == "2025-01-01T00:00:00+00:00"


@pytest.mark.parametrize("attr", ["sleep_state", "attitude_status"])
async def test_unmapped_fields_remain_explicitly_unknown(coordinator, attr):
    publish(coordinator, set_device_mode4=9, **{attr: "123"})
    entity = sensor(coordinator, attr)
    assert entity.native_value == 123
    assert entity.extra_state_attributes["semantic_evidence"] == "unknown"
    assert entity.device_class is None and entity.state_class is None


@pytest.mark.parametrize(
    "value, expected", [(0, False), (1, True), (2, None), (True, None), (None, None)]
)
async def test_reported_zone_flags_are_not_occupancy_semantics(coordinator, value, expected):
    publish(coordinator, detection_area1=value)
    entity = AqaraResourceBinarySensor(coordinator, RESOURCES["detection_area1"], A, "resources")
    assert entity.is_on is expected
    assert entity.device_class is None
    assert not entity.entity_registry_enabled_default


async def test_connectivity_uses_documented_direction(coordinator):
    publish(coordinator, device_offline_status=1)
    entity = AqaraResourceBinarySensor(
        coordinator, RESOURCES["device_offline_status"], A, "resources"
    )
    assert entity.device_class == BinarySensorDeviceClass.CONNECTIVITY
    assert entity.is_on
    assert entity.entity_category == EntityCategory.DIAGNOSTIC


async def test_settings_are_disabled_diagnostics_and_separate_group(coordinator):
    publish(coordinator, kind="settings", presence_detection_sens=3)
    entity = sensor(coordinator, "presence_detection_sens", "settings")
    assert entity.native_value == "high"
    assert entity.available
    assert not entity.entity_registry_enabled_default
    assert entity.entity_category == EntityCategory.DIAGNOSTIC
    coordinator.resource_status[(A, "resources")] = "unavailable"
    coordinator.connection_status = "retry_wait"
    coordinator.last_update_success = False
    assert entity.available
    coordinator.resource_status[(A, "settings")] = "unavailable"
    assert not entity.available


async def test_unchanged_resource_does_not_write_receipt_churn(coordinator):
    group = publish(coordinator, lux=12)
    entity = sensor(coordinator, "lux")
    entity.async_write_ha_state = Mock()
    entity._handle_coordinator_update()
    coordinator.resource_data[(A, "resources")] = replace(
        group, received_at_utc=datetime(2027, 1, 1, tzinfo=UTC)
    )
    entity._handle_coordinator_update()
    entity.async_write_ha_state.assert_called_once()
    coordinator.resource_status[(A, "resources")] = "stale"
    entity._handle_coordinator_update()
    assert entity.async_write_ha_state.call_count == 2


async def test_supplemental_diagnostics_never_export_values_ids_or_raw_source_time(
    hass, aqara_entry, coordinator
):
    publish(
        coordinator,
        attitude_status="PRIVATE-RESOURCE-VALUE",
        set_device_mode4=9,
        heartrate_value=66.66,
    )
    result = await async_get_config_entry_diagnostics(hass, aqara_entry)
    text = json.dumps(result)
    assert "PRIVATE-RESOURCE-VALUE" not in text
    assert "66.66" not in text
    assert A not in text and "synthetic-user" not in text
    group = result["supplemental"]["devices"][0]["groups"][0]
    assert group["query_kind"] == "resources"
    assert group["status"] == "ready"
    assert group["receive_age_seconds"] == 0
    observation = next(obs for obs in group["observations"] if obs["field"] == "attitude_status")
    assert observation == {
        "field": "attitude_status",
        "value_status": "invalid",
        "quality": "invalid",
        "has_source_time": False,
    }


def test_all_resource_entities_have_complete_english_german_labels_and_enum_states():
    base = Path(__file__).parent.parent / "custom_components/aqara_presence_lab"
    for file in (
        base / "strings.json",
        base / "translations/en.json",
        base / "translations/de.json",
    ):
        translations = json.loads(file.read_text())
        for spec in (*RESOURCES.values(), *SETTINGS.values()):
            domain = "binary_sensor" if spec.kind == "binary" else "sensor"
            item = translations["entity"][domain][spec.key]
            assert item["name"]
            assert set(item.get("state", {})) == set(spec.enum_map.values())


@pytest.mark.parametrize(
    "value", ["PRIVATE-RESOURCE-VALUE", "42", "a" * 300, True, 1.5, {"secret": "value"}]
)
async def test_entity_defense_rejects_unparsed_raw_server_text(coordinator, value):
    group = publish(coordinator, attitude_status=2)
    observation = replace(group.observations["attitude_status"], value=value)
    coordinator.resource_data[(A, "resources")] = replace(
        group, observations={"attitude_status": observation}
    )
    assert sensor(coordinator, "attitude_status").native_value is None


async def test_supplemental_diagnostics_only_export_known_parser_error(
    hass, aqara_entry, coordinator
):
    group = publish(coordinator, lux=12)
    for error, expected in [
        ("conflicting_resources", "conflicting_resources"),
        ("SECRET-ERROR", None),
    ]:
        coordinator.resource_data[(A, "resources")] = replace(group, error=error)
        result = await async_get_config_entry_diagnostics(hass, aqara_entry)
        assert result["supplemental"]["devices"][0]["groups"][0]["parse_error"] == expected
        assert "SECRET-ERROR" not in json.dumps(result)

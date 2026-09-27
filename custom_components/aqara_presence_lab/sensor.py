"""Reported observations and explicit quality, without guessed semantics."""

import re
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription
from homeassistant.const import LIGHT_LUX, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AqaraConfigEntry
from .api.models import TraitObservation
from .api.resources import RESOURCES, SETTINGS, DeviceResources, ResourceObservation, ResourceSpec
from .const import CONNECTION_STATES, QUALITY_STATES
from .coordinator import AqaraCoordinator
from .entity import AqaraEntity


@dataclass(frozen=True, kw_only=True)
class AqaraSensorDescription(SensorEntityDescription):
    """Map a stable semantic key to an observed trait, where applicable."""

    path: str | None = None


ACCOUNT_SENSORS = (
    AqaraSensorDescription(
        key="supplemental_status",
        device_class=SensorDeviceClass.ENUM,
        options=["idle", "updating", "ready", "partial_failure", "unavailable"],
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AqaraSensorDescription(
        key="connection_status",
        device_class=SensorDeviceClass.ENUM,
        options=CONNECTION_STATES,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AqaraSensorDescription(
        key="last_successful_read",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)
DEVICE_SENSORS = (
    AqaraSensorDescription(
        key="reported_illuminance",
        path="4.154.32989",
        device_class=SensorDeviceClass.ILLUMINANCE,
        native_unit_of_measurement=LIGHT_LUX,
    ),
    AqaraSensorDescription(
        key="data_quality",
        device_class=SensorDeviceClass.ENUM,
        options=QUALITY_STATES,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AqaraSensorDescription(
        key="presence_raw",
        path="2.160.33000",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    AqaraSensorDescription(
        key="device_status_raw",
        path="0.128.32901",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    AqaraSensorDescription(
        key="presence_source_time",
        path="2.160.33000",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    AqaraSensorDescription(
        key="fall_state_raw",
        path="5.168.33019",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: AqaraConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Create only selected devices; late capabilities can be added once seen."""
    coordinator = entry.runtime_data
    async_add_entities(AqaraSensor(coordinator, description) for description in ACCOUNT_SENSORS)
    added: set[tuple[str, str]] = set()

    def add_observed_entities() -> None:
        entities: list[SensorEntity] = []
        for device_id in coordinator.device_ids:
            device = coordinator.data.devices.get(device_id)
            for description in DEVICE_SENSORS:
                identity = (device_id, description.key)
                if identity in added:
                    continue
                if description.key == "fall_state_raw" and (
                    device is None
                    or description.path not in device.traits
                    or description.path in device.requested_not_returned
                ):
                    continue
                added.add(identity)
                entities.append(AqaraSensor(coordinator, description, device_id))
            for query_kind, specs in (("resources", RESOURCES), ("settings", SETTINGS)):
                group = coordinator.resource_data.get((device_id, query_kind))
                if group is None or not group.available:
                    continue
                for attr, observation in group.observations.items():
                    spec = specs.get(attr)
                    if (
                        spec is None
                        or spec.kind == "binary"
                        or observation.value_status != "present"
                        or observation.value is None
                    ):
                        continue
                    identity = (device_id, spec.key)
                    if (
                        identity in added
                        or spec.requires_sleep
                        and not coordinator.resource_sleep_mode(device_id)
                    ):
                        continue
                    added.add(identity)
                    entities.append(AqaraResourceSensor(coordinator, spec, device_id, query_kind))
        if entities:
            async_add_entities(entities)

    add_observed_entities()
    entry.async_on_unload(coordinator.async_add_listener(add_observed_entities))


class AqaraSensor(AqaraEntity, SensorEntity):
    """No state class until current-measurement semantics are demonstrated."""

    entity_description: AqaraSensorDescription

    def __init__(
        self,
        coordinator: AqaraCoordinator,
        description: AqaraSensorDescription,
        device_id: str | None = None,
    ) -> None:
        super().__init__(coordinator, description.key, device_id)
        self.entity_description = description

    @property
    def observation(self) -> TraitObservation | None:
        device = self.snapshot
        return (
            device.traits.get(self.entity_description.path)
            if device and self.entity_description.path
            else None
        )

    @property
    def available(self) -> bool:
        if self.entity_description.key == "data_quality":
            return True
        return super().available

    @property
    def native_value(self) -> str | int | float | datetime | None:
        key = self.entity_description.key
        if key == "supplemental_status":
            return self.coordinator.supplemental_status
        if key == "connection_status":
            return self.coordinator.connection_status
        if key == "last_successful_read":
            return self.coordinator.last_successful_read
        if key == "data_quality":
            if (
                self.coordinator.transport_stale
                or self.coordinator.connection_status != "ready"
                or not self.coordinator.last_update_success
            ):
                return "transport_unavailable"
            return self.snapshot.quality if self.snapshot else "missing"
        observation = self.observation
        if observation is None:
            return None
        if key == "presence_source_time":
            return observation.source_time_utc
        if observation.value_status != "present":
            return None
        value = (
            observation.normalized_value if key == "reported_illuminance" else observation.raw_value
        )
        # Entity state is a scalar; unknown structures never escape as attributes.
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            return None
        if isinstance(value, str) and len(value) > 255:
            return None
        if (
            key != "reported_illuminance"
            and isinstance(value, str)
            and re.fullmatch(r"[+-]?[0-9]{1,20}", value) is None
        ):
            return None
        return value

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        observation = self.observation
        if observation is None:
            return None
        return {"data_quality": observation.data_quality, "value_status": observation.value_status}


class AqaraResourceEntity(AqaraEntity):
    """A separately reported resource group, with no QLINK availability coupling."""

    def __init__(
        self, coordinator: AqaraCoordinator, spec: ResourceSpec, device_id: str, query_kind: str
    ) -> None:
        super().__init__(coordinator, spec.key, device_id)
        self.spec = spec
        self.query_kind = query_kind
        self._attr_entity_category = EntityCategory.DIAGNOSTIC if spec.diagnostic else None
        self._attr_entity_registry_enabled_default = (
            spec.enabled_default and query_kind != "settings"
        )

    @property
    def resource_group(self) -> DeviceResources | None:
        assert self.device_id is not None
        return self.coordinator.resource_data.get((self.device_id, self.query_kind))

    @property
    def resource_observation(self) -> ResourceObservation | None:
        group = self.resource_group
        return group.observations.get(self.spec.attr) if group else None

    @property
    def available(self) -> bool:
        assert self.device_id is not None
        return self.coordinator.resource_available(self.device_id, self.query_kind) and (
            not self.spec.requires_sleep or self.coordinator.resource_sleep_mode(self.device_id)
        )

    @property
    def extra_state_attributes(self) -> dict[str, str | int | float | bool]:
        observation = self.resource_observation
        attributes: dict[str, str | int | float | bool] = {
            "source": "aqara_resource",
            "semantic_evidence": self.spec.semantic_status,
            "data_quality": observation.quality if observation else "missing",
            "value_status": observation.value_status if observation else "missing",
        }
        if observation and observation.source_time_utc is not None:
            attributes["source_time"] = observation.source_time_utc.isoformat()
        if observation and self.spec.kind == "enum" and type(observation.value) is int:
            attributes["raw_code"] = observation.value
        if self.spec.requires_sleep:
            attributes["requires_sleep_mode"] = True
        return attributes


class AqaraResourceSensor(AqaraResourceEntity, SensorEntity):
    """Source-documented values remain reported observations, not live statistics."""

    def __init__(
        self, coordinator: AqaraCoordinator, spec: ResourceSpec, device_id: str, query_kind: str
    ) -> None:
        super().__init__(coordinator, spec, device_id, query_kind)
        self._attr_native_unit_of_measurement = spec.unit
        if spec.kind == "enum":
            self._attr_device_class = SensorDeviceClass.ENUM
            self._attr_options = list(dict.fromkeys(spec.enum_map.values()))
        elif spec.unit == LIGHT_LUX:
            self._attr_device_class = SensorDeviceClass.ILLUMINANCE

    @property
    def native_value(self) -> str | int | float | None:
        observation = self.resource_observation
        if observation is None or observation.value_status != "present":
            return None
        value = observation.value
        if self.spec.kind == "enum":
            return self.spec.enum_map.get(value) if type(value) is int else None
        if self.spec.kind == "raw":
            # Only numeric codes belong in entity states; arbitrary server text
            # can contain account details and must never enter the recorder.
            return value if type(value) is int else None
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            return None
        return value if not isinstance(value, str) or len(value) <= 255 else None

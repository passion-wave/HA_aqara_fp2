"""Integration connection health; no unverified occupancy interpretation."""

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AqaraConfigEntry
from .api.resources import RESOURCES, SETTINGS, ResourceSpec
from .coordinator import AqaraCoordinator
from .entity import AqaraEntity
from .sensor import AqaraResourceEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: AqaraConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([AqaraConnectionProblem(entry.runtime_data)])
    coordinator = entry.runtime_data
    added: set[tuple[str, str]] = set()

    def add_observed_entities() -> None:
        entities = []
        for device_id in coordinator.device_ids:
            for query_kind, specs in (("resources", RESOURCES), ("settings", SETTINGS)):
                group = coordinator.resource_data.get((device_id, query_kind))
                if group is None or not group.available:
                    continue
                for attr, observation in group.observations.items():
                    spec = specs.get(attr)
                    if (
                        spec is None
                        or spec.kind != "binary"
                        or observation.value_status != "present"
                        or type(observation.value) is not int
                        or observation.value not in (0, 1)
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
                    entities.append(
                        AqaraResourceBinarySensor(coordinator, spec, device_id, query_kind)
                    )
        if entities:
            async_add_entities(entities)

    add_observed_entities()
    entry.async_on_unload(coordinator.async_add_listener(add_observed_entities))


class AqaraConnectionProblem(AqaraEntity, BinarySensorEntity):
    """Readable even when every cloud measurement is unavailable."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: AqaraCoordinator) -> None:
        super().__init__(coordinator, "connection_problem")

    @property
    def is_on(self) -> bool:
        return self.coordinator.connection_status != "ready" or self.coordinator.transport_stale


class AqaraResourceBinarySensor(AqaraResourceEntity, BinarySensorEntity):
    """Reported binary flags; zone flags do not assert validated occupancy."""

    def __init__(
        self, coordinator: AqaraCoordinator, spec: ResourceSpec, device_id: str, query_kind: str
    ) -> None:
        super().__init__(coordinator, spec, device_id, query_kind)
        if spec.attr == "device_offline_status":
            # The reviewed source explicitly maps this flag's 1 to connected.
            self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    @property
    def is_on(self) -> bool | None:
        observation = self.resource_observation
        if (
            observation is None
            or observation.value_status != "present"
            or type(observation.value) is not int
            or observation.value not in (0, 1)
        ):
            return None
        return observation.value == 1

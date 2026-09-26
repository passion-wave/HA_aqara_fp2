"""Integration connection health; no unverified occupancy interpretation."""

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AqaraConfigEntry
from .coordinator import AqaraCoordinator
from .entity import AqaraEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: AqaraConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([AqaraConnectionProblem(entry.runtime_data)])


class AqaraConnectionProblem(AqaraEntity, BinarySensorEntity):
    """Readable even when every cloud measurement is unavailable."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: AqaraCoordinator) -> None:
        super().__init__(coordinator, "connection_problem")

    @property
    def is_on(self) -> bool:
        return self.coordinator.connection_status != "ready" or self.coordinator.transport_stale

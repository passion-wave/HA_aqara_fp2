"""Read-only manual refresh through the account coordinator and rate limiter."""

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AqaraConfigEntry
from .coordinator import AqaraCoordinator
from .entity import AqaraEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: AqaraConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([AqaraRefreshButton(entry.runtime_data)])


class AqaraRefreshButton(AqaraEntity, ButtonEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: AqaraCoordinator) -> None:
        super().__init__(coordinator, "refresh")

    async def async_press(self) -> None:
        await self.coordinator.async_request_refresh()

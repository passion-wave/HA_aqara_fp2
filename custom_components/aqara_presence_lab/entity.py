"""Common entities; properties never perform network I/O."""

from typing import Any

from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api.models import DeviceSnapshot
from .const import DOMAIN
from .coordinator import AqaraCoordinator


class AqaraEntity(CoordinatorEntity[AqaraCoordinator]):
    """Stable account/device identity without touching existing HomeKit devices."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: AqaraCoordinator, key: str, device_id: str | None = None
    ) -> None:
        super().__init__(coordinator)
        self.device_id = device_id
        self._attr_translation_key = key
        self._attr_unique_id = f"{coordinator.identity.account_key}:{device_id or 'account'}:{key}"
        self._last_rendered: Any = None
        account_identifier = (DOMAIN, coordinator.identity.account_key)
        if device_id is None:
            self._attr_device_info = DeviceInfo(
                identifiers={account_identifier},
                manufacturer="Aqara",
                name="Aqara Cloud",
                model="Presence Lab account",
            )
        else:
            device = self.snapshot
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, f"{coordinator.identity.account_key}:{device_id}")},
                manufacturer="Aqara",
                name=device.name if device and device.name else "Aqara FP2",
                model=device.device_model if device else "lumi.motion.agl001",
            )
            if hub := dr.async_get(coordinator.hass).async_get_device_by_identifier(
                account_identifier, coordinator.entry.entry_id
            ):
                self._attr_device_info["via_device_id"] = hub.id

    @property
    def snapshot(self) -> DeviceSnapshot | None:
        data = self.coordinator.data
        return data.devices.get(self.device_id) if data is not None and self.device_id else None

    @property
    def available(self) -> bool:
        """Transport success and device completeness are separate checks."""
        if self.device_id is None:
            return True
        return (
            self.coordinator.last_update_success
            and self.coordinator.connection_status == "ready"
            and not self.coordinator.transport_stale
            and self.snapshot is not None
            and self.snapshot.available
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Liveness timestamps must not force unchanged measurement writes."""
        value = getattr(self, "native_value", getattr(self, "is_on", None))
        rendered = (self.available, value, self.extra_state_attributes)
        if rendered != self._last_rendered:
            self._last_rendered = rendered
            self.async_write_ha_state()

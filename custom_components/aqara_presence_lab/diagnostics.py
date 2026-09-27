"""Allowlisted diagnostics, never an export of config entry data."""

from homeassistant.core import HomeAssistant

from . import AqaraConfigEntry
from .api.profiles import PROFILE
from .api.redaction import build_diagnostics
from .const import CONF_CONSENT, CONF_INTERVAL, DEFAULT_INTERVAL, VERSION


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: AqaraConfigEntry) -> dict:
    coordinator = getattr(entry, "runtime_data", None)
    if coordinator is None:
        return {
            "profile": {
                "id": PROFILE.id,
                "version": PROFILE.version,
                "validation_state": PROFILE.validation_state,
            },
            "configured": True,
            "running": False,
        }
    result = build_diagnostics(coordinator.data, profile=PROFILE, integration_version=VERSION)
    result["connection"] = {
        "status": coordinator.connection_status,
        "transport_stale": coordinator.transport_stale,
        "error": coordinator.error_key,
        "selected_device_count": len(coordinator.device_ids),
        "successful_reads": coordinator.successful_reads,
        "failed_reads": coordinator.failed_reads,
        "retry_after_seconds": round(coordinator.client.limiter.retry_after),
        "poll_interval_seconds": entry.data.get(CONF_INTERVAL, DEFAULT_INTERVAL),
        "experimental_cloud_consent": entry.data.get(CONF_CONSENT) is True,
    }
    return result

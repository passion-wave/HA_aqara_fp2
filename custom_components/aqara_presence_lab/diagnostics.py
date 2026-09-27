"""Allowlisted diagnostics, never an export of config entry data."""

from homeassistant.core import HomeAssistant

from . import AqaraConfigEntry
from .api.profiles import PROFILE
from .api.redaction import build_diagnostics
from .api.resources import RESOURCES, SETTINGS
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
    aliases = {
        device_id: f"device_{index}"
        for index, device_id in enumerate(coordinator.data.devices if coordinator.data else (), 1)
    }
    supplemental = []
    for device_id in coordinator.device_ids:
        groups = []
        for query_kind, specs in (("resources", RESOURCES), ("settings", SETTINGS)):
            key = (device_id, query_kind)
            group = coordinator.resource_data.get(key)
            received = coordinator.resource_received_monotonic.get(key)
            groups.append(
                {
                    "query_kind": query_kind,
                    "status": coordinator.resource_status.get(key, "not_read"),
                    "error": coordinator.resource_errors.get(key),
                    "parse_error": "conflicting_resources"
                    if group and group.error == "conflicting_resources"
                    else None,
                    "receive_age_seconds": round(max(0, coordinator._clock() - received))
                    if received is not None
                    else None,
                    "observations": [
                        {
                            "field": attr,
                            "value_status": observation.value_status,
                            "quality": observation.quality,
                            "has_source_time": observation.source_time_utc is not None,
                        }
                        for attr, observation in (group.observations.items() if group else ())
                        if attr in specs
                    ],
                }
            )
        supplemental.append(
            {"alias": aliases.get(device_id, "unavailable_device"), "groups": groups}
        )
    result["supplemental"] = {
        "status": coordinator.supplemental_status,
        "successful_reads": coordinator.resource_successful_reads,
        "failed_reads": coordinator.resource_failed_reads,
        "devices": supplemental,
    }
    return result

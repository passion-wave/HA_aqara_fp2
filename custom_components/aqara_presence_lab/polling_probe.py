"""Explicit, bounded read-spacing experiment using the existing private session."""

import asyncio
import logging
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.service import async_register_admin_service

if TYPE_CHECKING:
    import voluptuous as vol
else:
    import probatio as vol

from .const import CONF_CONSENT, DOMAIN
from .coordinator import AqaraCoordinator

_LOGGER = logging.getLogger(__name__)
SERVICE = "benchmark_polling"
STAGES = (15, 15, 15, 10, 10, 10, 5, 5, 5, 5)


@callback
def async_register_probe_service(hass: HomeAssistant) -> None:
    """Register once; only an admin can start ten reads for a loaded entry."""

    async def start(call: ServiceCall) -> dict:
        entry = hass.config_entries.async_get_entry(call.data["entry_id"])
        coordinator = getattr(entry, "runtime_data", None)
        if (
            entry is None
            or entry.domain != DOMAIN
            or entry.state is not ConfigEntryState.LOADED
            or entry.data.get(CONF_CONSENT) is not True
            or not isinstance(coordinator, AqaraCoordinator)
            or coordinator.connection_status != "ready"
            or coordinator.supplemental_status != "ready"
        ):
            raise ServiceValidationError("Aqara entry must be loaded with healthy completed reads")
        if coordinator._probe_task is not None:
            raise ServiceValidationError("Aqara polling benchmark is already running")
        coordinator.polling_probe = {"status": "starting", "request_limit": len(STAGES)}
        coordinator._probe_task = hass.async_create_background_task(
            async_run_probe(coordinator), name="Aqara bounded polling benchmark", eager_start=False
        )
        return {"status": "started", "request_limit": len(STAGES)}

    async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE,
        start,
        schema=vol.Schema({vol.Required("entry_id"): str}),
        supports_response=SupportsResponse.OPTIONAL,
    )


async def async_run_probe(coordinator: AqaraCoordinator) -> None:
    """No token renewal, settings reads, unbounded retry or exported sensor values."""
    limiter = coordinator.client.limiter
    previous_requested = int(limiter.requested_read_spacing)
    previous_effective = limiter.read_spacing
    result: dict = {
        "status": "running",
        "request_limit": len(STAGES),
        "completed_reads": 0,
        "successful_reads": 0,
        "failed_reads": 0,
        "samples": [],
        "measurement_freshness": "unverified",
    }
    coordinator.polling_probe = result
    started = coordinator._clock()
    last_request: float | None = None
    suspend = previous_effective > previous_requested
    _LOGGER.info("Aqara bounded polling benchmark started: maximum %s reads", len(STAGES))
    try:
        await coordinator.async_pause_supplemental()
        if coordinator._closed or coordinator.connection_status != "ready":
            result["status"] = "aborted"
            return
        for index, spacing in enumerate(STAGES):
            limiter.configure_read_spacing(spacing)
            device_id = coordinator.device_ids[index % len(coordinator.device_ids)]
            key = (device_id, "resources")
            before = coordinator.resource_data.get(key)
            request_started = coordinator._clock()
            success = await coordinator.async_read_supplemental_group(*key)
            request_finished = coordinator._clock()
            claimed = limiter.last_request_monotonic
            group = coordinator.resource_data.get(key)
            observations = group.observations if success and group else {}
            sample = {
                "index": index + 1,
                "requested_spacing_seconds": spacing,
                "elapsed_with_wait_seconds": round(request_finished - request_started, 3),
                "request_duration_seconds": round(request_finished - claimed, 3)
                if claimed is not None and claimed >= request_started
                else None,
                "request_gap_seconds": round(claimed - last_request, 3)
                if claimed is not None and last_request is not None
                else None,
                "success": success,
                "present_fields": sum(o.value_status == "present" for o in observations.values()),
                "changed_fields": sum(
                    before.observations[attr].value != observation.value
                    for attr, observation in observations.items()
                    if before is not None
                    and attr in before.observations
                    and observation.value_status
                    == before.observations[attr].value_status
                    == "present"
                ),
            }
            result["samples"].append(sample)
            result["completed_reads"] += 1
            result["successful_reads"] += int(success)
            result["failed_reads"] += int(not success)
            last_request = claimed
            if not success:
                result["status"] = "stopped_on_error"
                suspend = True
                break
        else:
            result["status"] = "completed"
    except asyncio.CancelledError:
        result["status"] = "cancelled"
        suspend = True
        raise
    except Exception:
        result["status"] = "aborted"
        suspend = True
        _LOGGER.warning("Aqara polling benchmark aborted; no automatic restart")
    finally:
        limiter.configure_read_spacing(previous_requested)
        if suspend:
            limiter.suspend_acceleration()
        result["elapsed_seconds"] = round(coordinator._clock() - started, 3)
        result["restored_spacing_seconds"] = limiter.read_spacing
        _LOGGER.info(
            "Aqara polling benchmark finished: status=%s successful=%s failed=%s spacing=%ss",
            result["status"],
            result["successful_reads"],
            result["failed_reads"],
            limiter.read_spacing,
        )
        coordinator._probe_task = None
        coordinator.async_resume_supplemental()
        coordinator.async_update_listeners()

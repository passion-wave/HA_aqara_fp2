"""Diagnostics are constructed from an allowlist, never scrubbed raw responses."""

from __future__ import annotations

import re
from typing import Any

from .models import AccountSnapshot, TransportHealth
from .profiles import CANDIDATE_PROFILE, ProtocolProfile

_QUALITIES = {
    "unverified",
    "reported",
    "current_validated",
    "missing",
    "invalid",
    "transport_unavailable",
    "stale_confirmed",
    "clock_anomaly",
}
_VALUE_STATUSES = {"present", "missing", "null", "invalid"}
_ERRORS = {
    "invalid_device",
    "invalid_traits",
    "conflicting_traits",
    "conflicting_devices",
    "device_not_returned",
    "api_changed",
    "cannot_connect",
    "rate_limited",
    "auth_required",
    "account_mismatch",
    "protocol_unsupported",
    "request_rejected",
    "access_denied",
    "signature_rejected",
    "application_error",
    "response_too_large",
}
_STATES = {
    "unconfigured",
    "ready",
    "retry_wait",
    "reauth_required",
    "auth_action_required",
    "protocol_unsupported",
    "transient_failure",
    "probing",
    "reauthenticating",
}


def _value_type(value: Any) -> str:
    return {
        type(None): "null",
        bool: "boolean",
        int: "integer",
        float: "number",
        str: "string",
        list: "array",
        dict: "object",
    }.get(type(value), "unknown")


def build_diagnostics(
    snapshot: AccountSnapshot | None,
    *,
    profile: ProtocolProfile = CANDIDATE_PROFILE,
    integration_version: str = "0.1.0",
    health: TransportHealth | None = None,
) -> dict[str, Any]:
    """Return no names, identifiers, values, exact timestamps or unknown strings."""
    result: dict[str, Any] = {
        "integration_version": integration_version
        if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[ab][0-9]+)?", integration_version)
        else "unknown",
        "profile": {
            "id": CANDIDATE_PROFILE.id if profile.id == CANDIDATE_PROFILE.id else "unknown",
            "version": profile.version if type(profile.version) is int else None,
            "validation_state": profile.validation_state
            if profile.validation_state in {"candidate", "signature_matched", "endpoint_validated"}
            else "unknown",
            "production_allowed": profile.production_allowed,
        },
        "device_count": len(snapshot.devices) if snapshot else 0,
        "devices": [],
    }
    if health is not None:
        result["transport"] = {
            "status": health.status if health.status in _STATES else "unknown",
            "error_class": health.error_class if health.error_class in _ERRORS else None,
            "consecutive_failures": health.consecutive_failures
            if type(health.consecutive_failures) is int
            else 0,
            "has_successful_read": health.last_successful_read is not None,
        }
    if snapshot is None:
        return result
    for index, device in enumerate(snapshot.devices.values(), 1):
        traits = []
        for path, observation in device.traits.items():
            if not re.fullmatch(r"[0-9]{1,8}\.[0-9]{1,8}\.[0-9]{1,8}", path):
                continue
            traits.append(
                {
                    "path": path,
                    "value_type": _value_type(observation.raw_value),
                    "value_status": observation.value_status
                    if observation.value_status in _VALUE_STATUSES
                    else "invalid",
                    "quality": observation.data_quality
                    if observation.data_quality in _QUALITIES
                    else "unverified",
                    "has_source_time": observation.source_time_ms is not None,
                }
            )
        result["devices"].append(
            {
                "alias": f"device_{index}",
                "available": bool(device.available),
                "error": device.error if device.error in _ERRORS else None,
                "quality": device.quality if device.quality in _QUALITIES else "unverified",
                "traits": traits,
                "requested_not_returned_count": len(device.requested_not_returned),
            }
        )
    return result

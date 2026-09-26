"""Quality decisions without inventing timestamp semantics."""

import math
from datetime import UTC, datetime


def utc_datetime(value: datetime) -> datetime:
    """Require aware times; never silently interpret local timestamps."""
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone_required")
    return value.astimezone(UTC)


def evaluate_freshness(
    source_time_ms: int | None,
    received_at: datetime,
    *,
    value_status: str = "present",
    semantics: str = "unknown",
    max_age_seconds: float | None = None,
) -> str:
    """Only externally validated measurement/change semantics allow current/stale."""
    received_at = utc_datetime(received_at)
    if value_status in ("missing", "null"):
        return "missing"
    if value_status == "invalid":
        return "invalid"
    if source_time_ms is not None:
        if type(source_time_ms) is not int or source_time_ms < 0:
            return "invalid"
        if source_time_ms > received_at.timestamp() * 1000:
            return "clock_anomaly"
    if semantics == "validated_change":
        return "current_validated"
    if semantics == "validated_measurement" and source_time_ms is not None:
        if max_age_seconds is None or not math.isfinite(max_age_seconds) or max_age_seconds <= 0:
            raise ValueError("measurement_age_required")
        if received_at.timestamp() - source_time_ms / 1000 > max_age_seconds:
            return "stale_confirmed"
        return "current_validated"
    return "reported"


def transport_expired(
    last_received_monotonic: float | None,
    now_monotonic: float,
    max_age_seconds: float,
) -> bool:
    """Evaluate locally, even while the cloud stops answering entirely."""
    if not math.isfinite(max_age_seconds) or max_age_seconds <= 0:
        raise ValueError("invalid_transport_age")
    if last_received_monotonic is None:
        return True
    elapsed = now_monotonic - last_received_monotonic
    return not math.isfinite(elapsed) or elapsed < 0 or elapsed > max_age_seconds

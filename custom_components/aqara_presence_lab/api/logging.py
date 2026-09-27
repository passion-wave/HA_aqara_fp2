"""Small, allowlisted operational events without request or account context."""

from __future__ import annotations

import json
import logging
import math

from .errors import AqaraError

_LOGGER = logging.getLogger(__name__)
_EVENTS = frozenset(
    {
        "request_started",
        "request_succeeded",
        "request_failed",
        "request_cancelled",
        "login_candidate",
        "session_validated",
        "authentication_required",
        "client_closed",
    }
)
_ERROR_KEYS = frozenset(
    {
        "aqara_error",
        "api_changed",
        "response_too_large",
        "protocol_unsupported",
        "auth_required",
        "account_mismatch",
        "cannot_connect",
        "request_rejected",
        "access_denied",
        "signature_rejected",
        "application_error",
        "rate_limited",
        "session_persistence_failed",
    }
)
_LEVELS = {
    "request_started": logging.DEBUG,
    "request_succeeded": logging.DEBUG,
    "request_cancelled": logging.DEBUG,
    "client_closed": logging.DEBUG,
    "login_candidate": logging.INFO,
    "session_validated": logging.INFO,
    "authentication_required": logging.WARNING,
    "request_failed": logging.WARNING,
}


def log_event(
    event: str,
    *,
    error: AqaraError | None = None,
    http_status: int | None = None,
    device_count: int | None = None,
    elapsed: float | None = None,
    operation: str | None = None,
) -> None:
    """Build a fresh record; never pass exceptions, response text or kwargs on."""
    record: dict[str, str | int | float] = {
        "event": event if type(event) is str and event in _EVENTS else "request_failed"
    }
    if error is not None and type(error.error_key) is str and error.error_key in _ERROR_KEYS:
        record["error_key"] = error.error_key
    if error is not None:
        code = getattr(error, "code", None)
        if type(code) is int and -(2**31) <= code <= 2**31 - 1:
            record["application_code"] = code
        if http_status is None:
            http_status = getattr(error, "http_status", None)
    if type(http_status) is int and 100 <= http_status <= 599:
        record["http_status"] = http_status
    if type(device_count) is int and 0 <= device_count <= 100:
        record["device_count"] = device_count
    if type(operation) is str and operation in ("login", "trait_read"):
        record["operation"] = operation
    if (
        elapsed is not None
        and type(elapsed) in (int, float)
        and 0 <= elapsed <= 86400
        and math.isfinite(elapsed)
    ):
        record["elapsed"] = round(elapsed, 3)
    _LOGGER.log(
        _LEVELS[str(record["event"])],
        "%s",
        json.dumps(record, sort_keys=True, separators=(",", ":")),
    )

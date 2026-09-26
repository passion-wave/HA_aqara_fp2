"""Strict, bounded JSON parsing with isolation of partial device failures."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from .errors import ApplicationError, InvalidResponse, ResponseTooLarge
from .freshness import evaluate_freshness, utc_datetime
from .models import AccountSnapshot, DeviceSnapshot, RawTrait, TraitObservation

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_DEVICES = 100
MAX_TRAITS = 200
MAX_DEPTH = 64
LUX_PATH = "4.154.32989"
LIST_PATH = "0.129.33013"
NAME_PATH = "0.130.32913"
_PATH = re.compile(r"[0-9]{1,8}\.[0-9]{1,8}\.[0-9]{1,8}\Z")
_CANDIDATES = {"2.160.33000", "0.128.32901", "5.168.33019"}
_METADATA = {"defaultValue", "enums", "unit", "min", "max", "step", "propertyId", "needSubscribe"}


def _no_constants(_value: str) -> None:
    raise InvalidResponse()


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InvalidResponse()
        result[key] = value
    return result


def _validate_tree(value: Any, depth: int = 0) -> None:
    if depth > MAX_DEPTH:
        raise InvalidResponse()
    if isinstance(value, float) and not math.isfinite(value):
        raise InvalidResponse()
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise InvalidResponse()
            key.encode("utf-8")
            _validate_tree(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _validate_tree(item, depth + 1)
    elif value is not None and type(value) not in (str, int, float, bool):
        raise InvalidResponse()
    elif isinstance(value, str):
        value.encode("utf-8")


def strict_json_loads(payload: bytes | str, *, max_bytes: int = MAX_RESPONSE_BYTES) -> Any:
    """Decode one complete JSON value; reject duplicates and nonfinite values."""
    try:
        if not isinstance(payload, (str, bytes)):
            raise InvalidResponse()
        if len(payload.encode("utf-8") if isinstance(payload, str) else payload) > max_bytes:
            raise ResponseTooLarge()
        text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
        result = json.loads(text, object_pairs_hook=_object_pairs, parse_constant=_no_constants)
        _validate_tree(result)
        return result
    except UnicodeError, ValueError, RecursionError:
        raise InvalidResponse() from None


def _json_equal(left: Any, right: Any) -> bool:
    """Python equates bool with 0/1; protocol duplicate matching must not."""
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            _json_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _json_equal(a, b) for a, b in zip(left, right, strict=True)
        )
    return left == right


def _bounded_fields(fields: Mapping[str, Any]) -> dict[str, Any]:
    """Retain bounded unknown metadata internally, never in diagnostic exports."""
    result: dict[str, Any] = {}
    budget = 16 * 1024
    for key, value in fields.items():
        if len(result) >= 64:
            break
        size = len(json.dumps({key: value}, ensure_ascii=False).encode())
        if size <= min(4096, budget):
            result[key] = value
            budget -= size
    return result


def _numeric(value: Any) -> int | float:
    if type(value) is bool or value is None:
        raise ValueError("invalid_numeric")
    if isinstance(value, str):
        if not re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?", value):
            raise ValueError("invalid_numeric")
        value = float(value) if any(character in value for character in ".eE") else int(value)
    if type(value) not in (int, float) or (isinstance(value, float) and not math.isfinite(value)):
        raise ValueError("invalid_numeric")
    return value


def _observation(
    raw: dict[str, Any], received_at: datetime, previous: TraitObservation | None = None
) -> TraitObservation:
    path = raw["path"]
    has_value = "value" in raw
    value = raw.get("value")
    status = "missing" if not has_value else "null" if value is None else "present"
    normalized = value if status == "present" else None
    source_time = raw.get("traitTime")
    invalid_time = source_time is not None and (type(source_time) is not int or source_time < 0)
    if invalid_time:
        source_time = None
    properties = raw.get("propertyId", [])
    if not isinstance(properties, list) or not all(
        isinstance(prop, str) and _PATH.fullmatch(prop) for prop in properties
    ):
        properties = []
        status = "invalid"
    try:
        if "enums" in raw:
            enums = (
                strict_json_loads(raw["enums"]) if isinstance(raw["enums"], str) else raw["enums"]
            )
            if not isinstance(enums, list):
                raise ValueError("invalid_enums")
        if status == "present" and path == LUX_PATH:
            normalized = _numeric(value)
            if normalized < 0:
                raise ValueError("invalid_illuminance")
        elif status == "present" and path == LIST_PATH:
            normalized = strict_json_loads(value) if isinstance(value, str) else value
            if not isinstance(normalized, list):
                raise ValueError("invalid_list")
    except ValueError, InvalidResponse:
        status = "invalid"
        normalized = None
    if status == "invalid":
        normalized = None
    freshness = (
        "invalid"
        if invalid_time
        else evaluate_freshness(source_time, received_at, value_status=status)
    )
    changed_at = None
    if status == "present":
        changed_at = received_at
        if (
            previous is not None
            and previous.value_status == "present"
            and _json_equal(previous.raw_value, value)
        ):
            changed_at = previous.last_value_change_observed_at
    return TraitObservation(
        path=path,
        has_value=has_value,
        raw_value=value,
        normalized_value=normalized,
        default_value=raw.get("defaultValue"),
        source_time_ms=source_time,
        received_at_utc=received_at,
        property_ids=tuple(properties),
        semantic_status="observed"
        if path == LUX_PATH
        else "candidate"
        if path in _CANDIDATES
        else "unknown",
        freshness_status=freshness,
        value_status=status,
        last_value_change_observed_at=changed_at,
        raw=RawTrait(path, _bounded_fields(raw)),
    )


def _failed_device(
    device_id: str, previous: DeviceSnapshot | None, error: str, paths: Iterable[str]
) -> DeviceSnapshot:
    return DeviceSnapshot(
        device_id=device_id,
        device_model=previous.device_model if previous else None,
        name=previous.name if previous else None,
        metadata=dict(previous.metadata) if previous else {},
        last_values=dict(previous.last_values) if previous else {},
        error=error,
        available=False,
        requested_not_returned=tuple(paths),
        consecutive_failures=(previous.consecutive_failures if previous else 0) + 1,
    )


def _device(
    raw: dict[str, Any],
    received_at: datetime,
    previous: DeviceSnapshot | None,
    requested: Iterable[str],
) -> DeviceSnapshot:
    device_id = raw["deviceId"]
    traits_raw = raw.get("traits")
    if not isinstance(traits_raw, list) or len(traits_raw) > MAX_TRAITS:
        return _failed_device(device_id, previous, "invalid_device", requested)
    grouped: dict[str, dict[str, Any]] = {}
    conflicts: set[str] = set()
    invalid_traits = False
    for trait in traits_raw:
        if (
            not isinstance(trait, dict)
            or not isinstance(trait.get("path"), str)
            or not _PATH.fullmatch(trait["path"])
        ):
            invalid_traits = True
            continue
        path = trait["path"]
        if path in grouped and not _json_equal(grouped[path], trait):
            conflicts.add(path)
        else:
            grouped[path] = trait
    observations: dict[str, TraitObservation] = {}
    metadata = dict(previous.metadata) if previous else {}
    last_values = dict(previous.last_values) if previous else {}
    for path, trait in grouped.items():
        observation = _observation(trait, received_at, last_values.get(path))
        if path in conflicts:
            observation = replace(
                observation,
                normalized_value=None,
                value_status="invalid",
                freshness_status="invalid",
                last_value_change_observed_at=None,
            )
        observations[path] = observation
        new_metadata = _bounded_fields(
            {key: value for key, value in trait.items() if key in _METADATA}
        )
        metadata[path] = {**metadata.get(path, {}), **new_metadata}
        if observation.value_status == "present":
            last_values[path] = observation
    missing = tuple(path for path in requested if path not in grouped)
    for path in missing:
        observations[path] = _observation({"path": path}, received_at)
    name_observation = observations.get(NAME_PATH)
    name = previous.name if previous else None
    if (
        name_observation
        and name_observation.value_status == "present"
        and isinstance(name_observation.raw_value, str)
    ):
        name = name_observation.raw_value
    device_model = raw.get("deviceModel")
    if not isinstance(device_model, str):
        device_model = previous.device_model if previous else None
    return DeviceSnapshot(
        device_id=device_id,
        device_model=device_model,
        name=name,
        traits=observations,
        metadata=metadata,
        last_values=last_values,
        error="conflicting_traits" if conflicts else "invalid_traits" if invalid_traits else None,
        requested_not_returned=missing,
        unknown_fields=_bounded_fields(
            {
                key: value
                for key, value in raw.items()
                if key not in {"deviceId", "deviceModel", "traits"}
            }
        ),
    )


def parse_response(
    payload: bytes | str | dict[str, Any],
    *,
    selected_device_ids: Iterable[str] | None = None,
    requested_paths: Mapping[str, Iterable[str]] | None = None,
    received_at: datetime | None = None,
    requested_at: datetime | None = None,
    previous: AccountSnapshot | None = None,
) -> AccountSnapshot:
    """Parse one successful read, retaining history but never substituting it."""
    received_at = utc_datetime(received_at or datetime.now(UTC))
    requested_at = utc_datetime(requested_at) if requested_at is not None else None
    if isinstance(payload, dict):
        try:
            _validate_tree(payload)
            if (
                len(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode())
                > MAX_RESPONSE_BYTES
            ):
                raise ResponseTooLarge()
        except ValueError, RecursionError, UnicodeError:
            raise InvalidResponse() from None
        data = payload
    else:
        data = strict_json_loads(payload)
    if not isinstance(data, dict) or type(data.get("code")) is not int:
        raise InvalidResponse()
    if data["code"] != 0:
        raise ApplicationError(data["code"])
    result = data.get("result")
    if not isinstance(result, list) or len(result) > MAX_DEVICES:
        raise InvalidResponse()
    selected = (
        tuple(dict.fromkeys(selected_device_ids)) if selected_device_ids is not None else None
    )
    if selected is not None and (
        len(selected) > MAX_DEVICES
        or any(not isinstance(item, str) or not item or len(item) > 256 for item in selected)
    ):
        raise InvalidResponse()
    requested = {
        device: tuple(dict.fromkeys(paths)) for device, paths in (requested_paths or {}).items()
    }
    for paths in requested.values():
        if len(paths) > MAX_TRAITS or any(
            not isinstance(path, str) or not _PATH.fullmatch(path) for path in paths
        ):
            raise InvalidResponse()
    indexed: dict[str, dict[str, Any]] = {}
    conflicts: set[str] = set()
    invalid_count = 0
    ignored_count = 0
    for raw in result:
        if (
            not isinstance(raw, dict)
            or not isinstance(raw.get("deviceId"), str)
            or not raw["deviceId"]
            or len(raw["deviceId"]) > 256
        ):
            invalid_count += 1
            continue
        device_id = raw["deviceId"]
        if selected is not None and device_id not in selected:
            ignored_count += 1
            continue
        if device_id in indexed and not _json_equal(indexed[device_id], raw):
            conflicts.add(device_id)
        else:
            indexed[device_id] = raw
    devices: dict[str, DeviceSnapshot] = {}
    for device_id in selected if selected is not None else indexed:
        old = previous.devices.get(device_id) if previous else None
        if device_id not in indexed or device_id in conflicts:
            error = "conflicting_devices" if device_id in conflicts else "device_not_returned"
            devices[device_id] = _failed_device(device_id, old, error, requested.get(device_id, ()))
        else:
            devices[device_id] = _device(
                indexed[device_id], received_at, old, requested.get(device_id, ())
            )
    return AccountSnapshot(devices, received_at, requested_at, ignored_count, invalid_count)

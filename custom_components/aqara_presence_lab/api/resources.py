"""Bounded, single-device resource observations from documented source contracts.

Attribute names and display metadata are independently implemented from
SleepRadar blob b48a4417deebd04cf4e6b3eb3d918300e6081d25 and the Aqara FP2 fork at
commit ca46546673d52ab819b3da5be7d98d4bb33f854a. These are source contracts, not
captured responses or verified current measurements from the user's devices.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Literal

from .errors import ApplicationError, InvalidResponse, ResponseTooLarge
from .freshness import utc_datetime
from .parsing import MAX_RESPONSE_BYTES, _json_equal, _numeric, _validate_tree, strict_json_loads

type ResourceValue = str | int | float | bool | None
type ResourceKind = Literal["number", "integer", "enum", "binary", "raw"]

# Defensive parser limits, not advertised Aqara or physiological limits.
MAX_RESOURCE_ITEMS = 200
MAX_RESOURCE_NUMBER = 2**63 - 1
_WRAPPERS = ("attributes", "data", "list", "items", "result")
_ATTR = re.compile(r"[a-z][a-z0-9_]{0,95}\Z")
_RESOURCE_ID = re.compile(r"[0-9]{1,8}\.[0-9]{1,8}\.[0-9]{1,8}\Z")


@dataclass(frozen=True, kw_only=True)
class ResourceSpec:
    """One documented, read-only resource and its presentation metadata."""

    attr: str
    key: str
    kind: ResourceKind
    unit: str | None = None
    enum_map: dict[int, str] = field(default_factory=dict)
    enabled_default: bool = True
    diagnostic: bool = False
    requires_sleep: bool = False
    zone: int | None = None
    nonnegative: bool = False
    semantic_status: str = "source_documented"


def _resource(attr: str, kind: ResourceKind, **kwargs: Any) -> ResourceSpec:
    return ResourceSpec(attr=attr, key=f"resource_{attr}", kind=kind, **kwargs)


_STATUS_SPECS = (
    _resource("body_movement_value", "number", requires_sleep=True, nonnegative=True),
    _resource("device_offline_status", "binary", diagnostic=True),
    *(
        _resource(f"detection_area{zone}", "binary", zone=zone, enabled_default=False)
        for zone in range(1, 31)
    ),
    _resource("heartrate_value", "number", unit="bpm", requires_sleep=True, nonnegative=True),
    _resource(
        "respiration_rate_value", "number", unit="br/min", requires_sleep=True, nonnegative=True
    ),
    _resource("sleep_state", "raw", requires_sleep=True, semantic_status="unknown"),
    _resource("lux", "number", unit="lx", nonnegative=True),
    _resource("all_zone_statistics", "integer", nonnegative=True),
    _resource("people_counting", "number", nonnegative=True),
    _resource("people_counting_by_mins", "number", nonnegative=True),
    *(
        _resource(
            f"zone{zone}_statistics",
            "integer",
            zone=zone,
            enabled_default=False,
            nonnegative=True,
        )
        for zone in range(1, 31)
    ),
    *(
        _resource(
            f"zone{zone}_people_counting_by_mins",
            "number",
            zone=zone,
            enabled_default=False,
            nonnegative=True,
        )
        for zone in range(1, 8)
    ),
    _resource(
        "installation_angle",
        "enum",
        enum_map={
            0: "face_up",
            1: "oblique",
            2: "oblique",
            3: "horizontal",
            4: "horizontal",
            5: "face_down",
            6: "oblique",
            7: "oblique",
            8: "oblique",
        },
        diagnostic=True,
    ),
    _resource(
        "set_device_mode4",
        "enum",
        enum_map={3: "zone_detection", 5: "fall_detection", 9: "sleep_monitoring"},
        diagnostic=True,
    ),
    _resource("view_zoom", "enum", enum_map={0: "full", 1: "adaptive"}, diagnostic=True),
    _resource(
        "mounting_position",
        "enum",
        enum_map={1: "wall", 2: "left_corner", 3: "right_corner"},
        diagnostic=True,
    ),
    _resource("attitude_status", "raw", diagnostic=True, semantic_status="unknown"),
)

RESOURCES: dict[str, ResourceSpec] = {spec.attr: spec for spec in _STATUS_SPECS}
RESOURCE_OPTIONS: tuple[str, ...] = tuple(RESOURCES)

_SETTING_DEFINITIONS: tuple[tuple[str, str, dict[int, str]], ...] = (
    ("14.30.85", "fall_detection_sens", {1: "low", 2: "medium", 3: "high"}),
    ("14.55.85", "detection_dir", {0: "default", 1: "left_right"}),
    ("14.51.85", "reverse_coordinate_dir", {0: "disable", 1: "enable", 2: "auto"}),
    ("14.1.85", "presence_detection_sens", {1: "low", 2: "medium", 3: "high"}),
    ("14.47.85", "proximity_sensing_dist", {0: "far", 1: "medium", 2: "close"}),
    ("4.23.85", "anti_light_poll", {0: "disable", 1: "enable"}),
    ("4.72.85", "ai_person_det", {0: "disable", 1: "enable"}),
)
SETTINGS: dict[str, ResourceSpec] = {
    attr: ResourceSpec(
        attr=attr,
        key=f"setting_{attr}",
        kind="enum",
        enum_map=enum_map,
        diagnostic=True,
        enabled_default=False,
    )
    for _, attr, enum_map in _SETTING_DEFINITIONS
}
SETTINGS_OPTIONS: tuple[str, ...] = tuple(item[0] for item in _SETTING_DEFINITIONS)
_SETTING_NAMES = {resource_id: attr for resource_id, attr, _ in _SETTING_DEFINITIONS}


@dataclass(frozen=True)
class ResourceObservation:
    """One response value; raw data and source timestamps are never repr output."""

    attr: str
    value: ResourceValue = field(repr=False)
    value_status: str
    source_time_utc: datetime | None
    received_at_utc: datetime
    quality: str
    source_time_raw: str | int | float | None = field(default=None, repr=False)


@dataclass(frozen=True)
class DeviceResources:
    """A separate resource snapshot; it never restores historic observations."""

    device_id: str = field(repr=False)
    observations: dict[str, ResourceObservation] = field(repr=False)
    received_at_utc: datetime
    available: bool = True
    error: str | None = None


def _decode(payload: bytes | str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload, dict):
        try:
            _validate_tree(payload)
            if (
                len(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8"))
                > MAX_RESPONSE_BYTES
            ):
                raise ResponseTooLarge()
            data = payload
        except ValueError, TypeError, UnicodeError, RecursionError:
            raise InvalidResponse() from None
    else:
        data = strict_json_loads(payload)
    if not isinstance(data, dict) or type(data.get("code")) is not int:
        raise InvalidResponse()
    if data["code"] != 0:
        raise ApplicationError(data["code"])
    return data


def _check_binding(value: Any, device_id: str) -> None:
    """Never combine explicit foreign identities, including in nested wrappers."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"subjectId", "deviceId"} and (
                not isinstance(item, str) or item != device_id
            ):
                raise InvalidResponse()
            _check_binding(item, device_id)
    elif isinstance(value, list):
        for item in value:
            _check_binding(item, device_id)


def _items(data: dict[str, Any]) -> list[dict[str, Any]]:
    result = data.get("result")
    if isinstance(result, dict):
        candidates = [key for key in _WRAPPERS if key in result]
        # A wrapper is supported only if there is one unambiguous list container.
        if len(candidates) != 1:
            raise InvalidResponse()
        result = result[candidates[0]]
    if not isinstance(result, list) or len(result) > MAX_RESOURCE_ITEMS:
        raise InvalidResponse()
    if not all(isinstance(item, dict) for item in result):
        raise InvalidResponse()
    return result


def _attr(item: dict[str, Any], *, settings: bool) -> str | None:
    if not settings:
        attr = item.get("attr")
        if not isinstance(attr, str) or not _ATTR.fullmatch(attr):
            raise InvalidResponse()
        return attr if attr in RESOURCES else None

    identifiers = [item[key] for key in ("resourceId", "attr") if key in item]
    if not identifiers or any(
        not isinstance(value, str) or not (_ATTR.fullmatch(value) or _RESOURCE_ID.fullmatch(value))
        for value in identifiers
    ):
        raise InvalidResponse()
    if "resourceId" in item and not _RESOURCE_ID.fullmatch(item["resourceId"]):
        raise InvalidResponse()
    names = [_SETTING_NAMES.get(value, value) for value in identifiers]
    if len(set(names)) != 1:
        raise InvalidResponse()
    return names[0] if names[0] in SETTINGS else None


def _number(value: Any, spec: ResourceSpec) -> int | float:
    number = _numeric(value)
    if abs(number) > MAX_RESOURCE_NUMBER or (spec.nonnegative and number < 0):
        raise ValueError("invalid_resource_number")
    if spec.kind in {"integer", "enum", "binary"}:
        if isinstance(number, float) and not number.is_integer():
            raise ValueError("invalid_resource_integer")
        number = int(number)
    if spec.kind == "binary" and number not in (0, 1):
        raise ValueError("invalid_resource_binary")
    return number


def _scalar(value: Any, spec: ResourceSpec) -> ResourceValue:
    if spec.kind != "raw":
        return _number(value, spec)
    # Sleep/attitude are documented only as codes. Free server text could echo
    # credentials into HA state, recorder or framework logs, so never publish it.
    if isinstance(value, str) and re.fullmatch(r"-?(?:0|[1-9][0-9]{0,18})", value):
        value = int(value)
    if type(value) is not int or abs(value) > MAX_RESOURCE_NUMBER:
        raise ValueError("invalid_resource_code")
    return value


def _timestamp(item: dict[str, Any]) -> str | int | float | None:
    times = [item[key] for key in ("timeStamp", "timestamp") if key in item]
    if not times:
        return None
    if any(not _json_equal(times[0], value) for value in times[1:]):
        raise ValueError("ambiguous_resource_timestamp")
    value = times[0]
    if value is None:
        return None
    if type(value) in (int, float) and 0 <= value <= MAX_RESOURCE_NUMBER:
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,20}(?:\.[0-9]{1,9})?", value):
        return value
    raise ValueError("invalid_resource_timestamp")


def _observation(
    attr: str, item: dict[str, Any], spec: ResourceSpec, received_at: datetime
) -> ResourceObservation:
    status = "missing"
    value: ResourceValue = None
    if "value" in item:
        raw = item["value"]
        if isinstance(raw, dict) and "value" in raw:
            raw = raw["value"]
        status = "null" if raw is None else "present"
        if raw is not None:
            try:
                value = _scalar(raw, spec)
            except ValueError, TypeError, OverflowError:
                status = "invalid"
    quality = (
        "unverified" if status == "present" else "missing" if status != "invalid" else "invalid"
    )
    try:
        source_time = _timestamp(item)
    except ValueError:
        source_time = None
        if status == "present":
            quality = "invalid"
    # The source mentions timeStamp but establishes no timestamp unit. Preserve
    # the opaque value internally; do not guess seconds versus milliseconds.
    return ResourceObservation(attr, value, status, None, received_at, quality, source_time)


def _parse(
    payload: bytes | str | dict[str, Any],
    *,
    device_id: str,
    received_at: datetime | None,
    requested_at: datetime | None,
    settings: bool,
) -> DeviceResources:
    try:
        if (
            not isinstance(device_id, str)
            or not device_id
            or len(device_id) > 256
            or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in device_id)
        ):
            raise InvalidResponse()
        device_id.encode("utf-8")
        received_at = utc_datetime(datetime.now(UTC) if received_at is None else received_at)
        if requested_at is not None:
            utc_datetime(requested_at)
    except ValueError, TypeError, UnicodeError:
        raise InvalidResponse() from None
    data = _decode(payload)
    _check_binding(data, device_id)
    specs = SETTINGS if settings else RESOURCES
    seen: dict[str, dict[str, Any]] = {}
    conflicts: set[str] = set()
    for item in _items(data):
        attr = _attr(item, settings=settings)
        if attr is None:
            continue
        # Unknown metadata is neither exported nor allowed to disambiguate
        # contradictory values. Exact value/time types remain significant.
        value_fields: dict[str, Any] = {
            key: item[key] for key in ("value", "timeStamp", "timestamp") if key in item
        }
        if attr in seen and not _json_equal(seen[attr], value_fields):
            conflicts.add(attr)
        else:
            seen[attr] = value_fields
    observations = {
        attr: _observation(attr, seen.get(attr, {}), spec, received_at)
        for attr, spec in specs.items()
    }
    for attr in conflicts:
        observations[attr] = replace(
            observations[attr], value=None, value_status="invalid", quality="invalid"
        )
    return DeviceResources(
        device_id,
        observations,
        received_at,
        error="conflicting_resources" if conflicts else None,
    )


def parse_resource_response(
    payload: bytes | str | dict[str, Any],
    *,
    device_id: str,
    received_at: datetime | None = None,
    requested_at: datetime | None = None,
) -> DeviceResources:
    """Parse one /res/query response in its single requested subject's scope."""
    return _parse(
        payload,
        device_id=device_id,
        received_at=received_at,
        requested_at=requested_at,
        settings=False,
    )


def parse_resource_settings_response(
    payload: bytes | str | dict[str, Any],
    *,
    device_id: str,
    received_at: datetime | None = None,
    requested_at: datetime | None = None,
) -> DeviceResources:
    """Parse documented resourceId settings into read-only canonical fields."""
    return _parse(
        payload,
        device_id=device_id,
        received_at=received_at,
        requested_at=requested_at,
        settings=True,
    )

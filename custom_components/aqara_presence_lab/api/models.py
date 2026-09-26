"""Typed observations; current, metadata and historic values stay separate."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

JsonValue = None | bool | int | float | str | list[Any] | dict[str, Any]


@dataclass(frozen=True)
class AccountIdentity:
    area: str
    user_id: str = field(repr=False)

    def __post_init__(self) -> None:
        if self.area != "EU" or not isinstance(self.user_id, str) or not self.user_id:
            raise ValueError("invalid_account_identity")
        try:
            self.user_id.encode("utf-8")
        except UnicodeError:
            raise ValueError("invalid_account_identity") from None

    @property
    def region(self) -> str:
        return self.area

    @property
    def account_key(self) -> str:
        return sha256(f"{self.area}:{self.user_id}".encode()).hexdigest()


@dataclass(frozen=True)
class DeviceSelection:
    device_ids: tuple[str, ...] = field(repr=False)

    def __post_init__(self) -> None:
        if not self.device_ids or len(self.device_ids) > 100:
            raise ValueError("invalid_device_selection")
        if any(
            not isinstance(item, str) or not item or len(item) > 256 for item in self.device_ids
        ):
            raise ValueError("invalid_device_selection")
        if len(set(self.device_ids)) != len(self.device_ids):
            raise ValueError("duplicate_device_selection")


@dataclass(frozen=True)
class RawTrait:
    path: str
    fields: dict[str, JsonValue] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class TraitObservation:
    path: str
    has_value: bool
    raw_value: JsonValue = field(repr=False)
    normalized_value: JsonValue = field(repr=False)
    default_value: JsonValue = field(repr=False)
    source_time_ms: int | None
    received_at_utc: datetime
    property_ids: tuple[str, ...]
    semantic_status: str
    freshness_status: str
    value_status: str
    last_value_change_observed_at: datetime | None = None
    raw: RawTrait | None = field(default=None, repr=False)

    @property
    def source_time_utc(self) -> datetime | None:
        if self.source_time_ms is None:
            return None
        try:
            return datetime.fromtimestamp(self.source_time_ms / 1000, UTC)
        except OverflowError, OSError, ValueError:
            return None

    @property
    def data_quality(self) -> str:
        return self.freshness_status


@dataclass(frozen=True)
class DeviceSnapshot:
    device_id: str = field(repr=False)
    device_model: str | None = field(default=None, repr=False)
    name: str | None = field(default=None, repr=False)
    traits: dict[str, TraitObservation] = field(default_factory=dict)
    metadata: dict[str, dict[str, JsonValue]] = field(default_factory=dict, repr=False)
    last_values: dict[str, TraitObservation] = field(default_factory=dict, repr=False)
    error: str | None = None
    available: bool = True
    requested_not_returned: tuple[str, ...] = ()
    consecutive_failures: int = 0
    unknown_fields: dict[str, JsonValue] = field(default_factory=dict, repr=False)

    @property
    def quality(self) -> str:
        if not self.available:
            return "transport_unavailable"
        illuminance = self.traits.get("4.154.32989")
        if illuminance:
            return illuminance.data_quality
        qualities = {item.data_quality for item in self.traits.values()}
        for quality in ("clock_anomaly", "invalid", "reported", "missing"):
            if quality in qualities:
                return quality
        return "unverified"


@dataclass(frozen=True)
class AccountSnapshot:
    devices: dict[str, DeviceSnapshot] = field(default_factory=dict, repr=False)
    received_at_utc: datetime | None = None
    requested_at_utc: datetime | None = None
    ignored_devices: int = 0
    invalid_devices: int = 0


@dataclass(frozen=True)
class TransportHealth:
    status: str = "unconfigured"
    last_successful_read: datetime | None = None
    last_received_monotonic: float | None = None
    consecutive_failures: int = 0
    error_class: str | None = None
    retry_at_monotonic: float | None = None

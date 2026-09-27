"""Local G1 comparison and bounded, persistent G2/G3 probe accounting."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import ApplicationError, AqaraError, InvalidResponse, ProtocolUnsupported, RateLimited
from .importers import ImportedCapture, strict_json
from .models import AccountSnapshot
from .profiles import EU_CANDIDATE_PROFILE, ProtocolProfile
from .signing import CandidateSigner


def signature_matches(
    capture: ImportedCapture,
    signer: CandidateSigner,
    profile: ProtocolProfile = EU_CANDIDATE_PROFILE,
) -> bool:
    """Constant-time signer comparison; no captured material leaves this function."""
    headers = capture.headers
    if headers.get("appid") != profile.app_id or headers.get("area") != profile.area:
        return False
    return signer.matches(
        headers["sign"].lower(),
        capture.body,
        nonce=headers["nonce"],
        time_ms=headers["time"],
        token=headers["token"],
    )


def signature_report(
    capture: ImportedCapture,
    signer: CandidateSigner,
    profile: ProtocolProfile = EU_CANDIDATE_PROFILE,
) -> dict:
    return {
        "gate": "G1",
        "profile": profile.id,
        "profile_version": profile.version,
        "result": "matched" if signature_matches(capture, signer, profile) else "not_matched",
        "network_requests": 0,
        "production_allowed": False,
    }


def probe_report(
    snapshot: AccountSnapshot, profile: ProtocolProfile = EU_CANDIDATE_PROFILE
) -> dict:
    """Allowlist only: no IDs, raw fields, names, values or signed headers."""
    usable = sum(
        bool(
            device.available
            and any(
                obs.has_value and obs.value_status == "present" for obs in device.traits.values()
            )
        )
        for device in snapshot.devices.values()
    )
    result = (
        "no_selected_device_data"
        if not usable
        else "partial_result"
        if usable < len(snapshot.devices)
        else "schema_validated"
    )
    return {
        "gate": "G2",
        "profile": profile.id,
        "profile_version": profile.version,
        "result": result,
        "device_count": len(snapshot.devices),
        "usable_device_count": usable,
        "network_requests": 1,
        "production_allowed": False,
        "account_identity_verified": False,
        "freshness_verified": False,
    }


def failure_report(
    error: AqaraError,
    *,
    gate: str | None = None,
    profile: ProtocolProfile | None = None,
) -> dict[str, Any]:
    """Allowlist failure metadata; never export raw messages or guess requests.

    Application codes are opaque signed 32-bit integers for reporting only.
    Values outside that project export bound are omitted, never truncated or
    coerced. A status exists only when the transport explicitly observed it.
    """
    known_errors = {
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
    }
    report: dict[str, Any] = {
        "result": "failed",
        "error": error.error_key
        if type(error.error_key) is str and error.error_key in known_errors
        else "aqara_error",
        "production_allowed": False,
    }
    if isinstance(error, ApplicationError):
        if type(error.code) is int and -(2**31) <= error.code <= 2**31 - 1:
            report["application_code"] = error.code
        if type(error.http_status) is int and 100 <= error.http_status <= 599:
            report["http_status"] = error.http_status
    if gate in ("G2", "G3"):
        report["gate"] = gate
    if profile is EU_CANDIDATE_PROFILE:
        report["profile"] = profile.id
        report["profile_version"] = profile.version
    return report


class ProbeBudget:
    """Ten attempts per local investigation step, minimum 30s across restarts.

    POSIX advisory lock prevents simultaneous CLI invocations from racing. State
    contains a one-way account key and counters only, not the token or capture.
    """

    def __init__(self, path: Path, *, now: Callable[[], float] | None = None) -> None:
        self.path = Path(path)
        self._now = now or (lambda: datetime.now(UTC).timestamp())

    @contextmanager
    def _state(self) -> Iterator[dict[str, Any]]:
        import fcntl

        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            mode = os.fstat(descriptor)
            if not stat.S_ISREG(mode.st_mode) or mode.st_mode & 0o077:
                raise InvalidResponse("private_file_permissions_required")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            with os.fdopen(descriptor, "r+", encoding="utf-8", closefd=False) as handle:
                raw = handle.read(65537)
                state = (
                    strict_json(raw, limit=65536)
                    if raw
                    else {"version": 1, "steps": {}, "accounts": {}}
                )
                if (
                    type(state.get("version")) is not int
                    or state["version"] != 1
                    or not isinstance(state.get("steps"), dict)
                ):
                    raise InvalidResponse()
                state.setdefault("accounts", {})
                if not isinstance(state["accounts"], dict):
                    raise InvalidResponse()
                yield state
                handle.seek(0)
                json.dump(state, handle, separators=(",", ":"))
                handle.truncate()
                handle.flush()
                os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _key(user_id: str, step: str) -> str:
        if step not in ("G2", "G3"):
            raise ProtocolUnsupported()
        return hashlib.sha256(("EU:" + user_id).encode()).hexdigest() + ":" + step

    def reserve(self, user_id: str, *, step: str = "G2") -> None:
        key = self._key(user_id, step)
        with self._state() as state:
            entry = state["steps"].get(key, {"count": 0, "next_at": 0})
            if (
                not isinstance(entry, dict)
                or type(entry.get("count")) is not int
                or entry["count"] < 0
                or type(entry.get("next_at")) not in (int, float)
            ):
                raise InvalidResponse()
            if entry["count"] >= 10:
                raise ProtocolUnsupported("probe_budget_exhausted")
            now = self._now()
            account_key = key.split(":")[0]
            account_next = state["accounts"].get(account_key, 0)
            if type(account_next) not in (int, float) or account_next < 0:
                raise InvalidResponse()
            next_at = max(entry["next_at"], account_next)
            if next_at > now:
                raise RateLimited(next_at - now)
            state["accounts"][account_key] = now + 30
            state["steps"][key] = {"count": entry["count"] + 1, "next_at": now + 30}

    def defer(self, user_id: str, seconds: float, *, step: str = "G2") -> None:
        key = self._key(user_id, step)
        with self._state() as state:
            if key not in state["steps"]:
                raise InvalidResponse()
            next_at = max(state["steps"][key]["next_at"], self._now() + seconds)
            state["steps"][key]["next_at"] = next_at
            account_key = key.split(":")[0]
            state["accounts"][account_key] = max(state["accounts"].get(account_key, 0), next_at)

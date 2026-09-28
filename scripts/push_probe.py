#!/usr/bin/env python3
"""Offline validation of decoded RocketMQ-bridge batches; never connects to a broker.

Input: selected_subjects plus frames containing the bridge's JSON snapshot/batch
objects. This is a research model, not an SSE client or a production parser.
Only aggregate metadata is printed. See docs/research/CLOUD_PUSH.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

MAX_BYTES = 2 * 1024 * 1024
MAX_TIMESTAMP_MS = 253402300799999
RESOURCE_IDS = frozenset(
    {
        "0.4.85",
        "0.8.85",
        "0.9.85",
        "13.11.85",
        "13.106.85",
        "3.51.85",
        "3.52.85",
        "4.22.700",
        "13.120.85",
        "0.60.85",
        "0.61.85",
        "14.49.85",
        "8.0.2045",
    }
    | {f"3.{n}.85" for n in range(1, 31)}
    | {f"13.{120 + n}.85" for n in range(1, 31)}
    | {f"0.{120 + n}.85" for n in range(1, 8)}
)


class InvalidReplay(ValueError):
    """A static exception that cannot expose payloads or file paths."""

    def __init__(self) -> None:
        super().__init__("invalid_push_replay")


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise InvalidReplay()
        result[key] = value
    return result


def _json(raw: bytes | str) -> Any:
    try:
        encoded = raw if isinstance(raw, bytes) else raw.encode("utf-8")
        if len(encoded) > MAX_BYTES:
            raise InvalidReplay()
        result = json.loads(encoded.decode("utf-8"), object_pairs_hook=_pairs)
        stack = [(result, 0)]
        while stack:
            value, depth = stack.pop()
            if depth > 16:
                raise InvalidReplay()
            if isinstance(value, str):
                value.encode("utf-8")
            elif isinstance(value, float) and not math.isfinite(value):
                raise InvalidReplay()
            elif isinstance(value, dict):
                stack.extend((key, depth + 1) for key in value)
                stack.extend((item, depth + 1) for item in value.values())
            elif isinstance(value, list):
                stack.extend((item, depth + 1) for item in value)
        return result
    except ValueError, UnicodeError, RecursionError, OverflowError:
        raise InvalidReplay() from None


def _identifier(value: Any) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 256:
        raise InvalidReplay()
    if any(ord(character) < 32 for character in value):
        raise InvalidReplay()
    return value


def _timestamp(value: Any) -> int:
    # The official push format documents milliseconds. Do not guess units by size.
    if isinstance(value, str) and value.isascii() and value.isdecimal() and len(value) <= 15:
        value = int(value)
    if type(value) is not int or not 0 <= value <= MAX_TIMESTAMP_MS:
        raise InvalidReplay()
    return value


def _targets(value: str) -> None:
    targets = _json(value)
    if not isinstance(targets, list) or len(targets) > 32:
        raise InvalidReplay()
    seen: set[str] = set()
    for target in targets:
        if not isinstance(target, dict):
            raise InvalidReplay()
        identity = target.get("id")
        if type(identity) is int:
            identity = str(identity)
        identity = _identifier(identity)
        if identity in seen:
            raise InvalidReplay()
        seen.add(identity)
        state = target.get("state")
        if type(state) not in (int, str) or state not in (0, 1, "0", "1"):
            raise InvalidReplay()
        for coordinate in (target.get("x"), target.get("y")):
            if not isinstance(coordinate, (int, float)) or isinstance(coordinate, bool):
                raise InvalidReplay()
            try:
                if not math.isfinite(coordinate):
                    raise InvalidReplay()
            except OverflowError:
                raise InvalidReplay() from None
        # Range-to-zone conversion and coordinate units are intentionally unproven.


def inspect_replay(raw: bytes | str) -> dict[str, Any]:
    """Inspect synthetic or locally sanitized bridge JSON without exposing its data."""
    root = _json(raw)
    if not isinstance(root, dict):
        raise InvalidReplay()
    selected = root.get("selected_subjects")
    frames = root.get("frames")
    if not isinstance(selected, list) or not 1 <= len(selected) <= 100:
        raise InvalidReplay()
    subjects = {_identifier(item) for item in selected}
    if len(subjects) != len(selected):
        raise InvalidReplay()
    if not isinstance(frames, list) or not 1 <= len(frames) <= 1024:
        raise InvalidReplay()

    counts: Counter[str] = Counter()
    latest: dict[tuple[str, str], tuple[int, bytes]] = {}
    previous_cursor: int | None = None
    reconciliation_required = False
    for frame in frames:
        if not isinstance(frame, dict) or frame.get("type") not in ("snapshot", "batch"):
            raise InvalidReplay()
        kind = frame["type"]
        cursor, events = frame.get("cursor"), frame.get("events")
        if type(cursor) is not int or not 0 <= cursor < 2**63:
            raise InvalidReplay()
        if not isinstance(events, list) or len(events) > 2048:
            raise InvalidReplay()
        if previous_cursor is not None and cursor < previous_cursor:
            if kind != "snapshot":
                raise InvalidReplay()
            counts["cursor_resets"] += 1
            reconciliation_required = True
        previous_cursor = cursor
        counts["frames"] += 1
        for event in events:
            counts["events"] += 1
            if counts["events"] > 8192 or not isinstance(event, dict):
                raise InvalidReplay()
            if event.get("type") != "resource_report":
                counts["unsupported_events"] += 1
                continue
            subject = _identifier(event.get("subjectId"))
            if subject not in subjects:
                counts["foreign_events"] += 1
                continue
            resource = _identifier(event.get("resourceId"))
            if resource not in RESOURCE_IDS:
                counts["unsupported_events"] += 1
                continue
            status = event.get("statusCode")
            if type(status) is not int or not -(2**31) <= status < 2**31:
                raise InvalidReplay()
            if status != 0:
                counts["failed_events"] += 1
                continue
            timestamp = _timestamp(event.get("time"))
            value = event.get("value")
            if not isinstance(value, str) or len(value.encode("utf-8")) > 8192:
                raise InvalidReplay()
            if resource == "4.22.700":
                _targets(value)
            if timestamp == 0:
                counts["undated_events"] += 1
                reconciliation_required = True
                continue
            fingerprint = hashlib.sha256(value.encode("utf-8")).digest()
            key = subject, resource
            current = latest.get(key)
            if current is not None:
                if timestamp < current[0]:
                    counts["stale_events"] += 1
                    continue
                if timestamp == current[0]:
                    if fingerprint == current[1]:
                        counts["duplicate_events"] += 1
                    else:
                        counts["conflicting_events"] += 1
                        reconciliation_required = True
                    continue
            latest[key] = timestamp, fingerprint
            counts["replayed_updates" if kind == "snapshot" else "batch_updates"] += 1

    return {
        "result": "offline_contract_validated",
        "live_verified": False,
        "network_requests": 0,
        "state_keys": len(latest),
        "reconciliation_required": reconciliation_required,
        **{
            key: counts[key]
            for key in (
                "frames",
                "events",
                "batch_updates",
                "replayed_updates",
                "duplicate_events",
                "stale_events",
                "conflicting_events",
                "failed_events",
                "foreign_events",
                "unsupported_events",
                "undated_events",
                "cursor_resets",
            )
        },
    }


def demo_replay() -> bytes:
    """Produce an invented fixture, never purported captured FP2 measurements."""

    def event(time: int, value: str) -> dict[str, Any]:
        return {
            "type": "resource_report",
            "subjectId": "synthetic-fp2",
            "resourceId": "0.8.85",
            "time": time,
            "statusCode": 0,
            "value": value,
        }

    return json.dumps(
        {
            "selected_subjects": ["synthetic-fp2"],
            "frames": [
                {"type": "snapshot", "cursor": 1, "events": [event(1000, "60")]},
                {
                    "type": "batch",
                    "cursor": 4,
                    "events": [event(2000, "61"), event(1000, "60"), event(2000, "61")],
                },
                {"type": "snapshot", "cursor": 1, "events": [event(2000, "61")]},
            ],
        }
    ).encode()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--demo", action="store_true", help="Use invented offline test data")
    group.add_argument("--file", type=Path, help="Read a local decoded replay; never a URL")
    args = parser.parse_args(argv)
    try:
        if args.demo:
            raw = demo_replay()
        else:
            with args.file.open("rb") as handle:
                raw = handle.read(MAX_BYTES + 1)
        report = inspect_replay(raw)
    except InvalidReplay, OSError:
        print(
            json.dumps({"result": "failed", "error": "invalid_push_replay", "network_requests": 0})
        )
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

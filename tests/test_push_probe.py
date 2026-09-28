"""Synthetic, socket-blocked feasibility tests; no claim of live push support."""

import json
from pathlib import Path

import pytest

from scripts.push_probe import MAX_BYTES, InvalidReplay, demo_replay, inspect_replay, main


def event(**changes):
    return {
        "type": "resource_report",
        "subjectId": "test-only-device",
        "resourceId": "0.8.85",
        "time": 1000,
        "value": "60",
        "statusCode": 0,
    } | changes


def replay(events=None, frames=None):
    return json.dumps(
        {
            "selected_subjects": ["test-only-device"],
            "frames": frames
            or [{"type": "batch", "cursor": 1, "events": [event()] if events is None else events}],
        }
    )


def test_demo_models_stale_duplicate_and_restart_without_network():
    result = inspect_replay(demo_replay())
    assert result["result"] == "offline_contract_validated"
    assert result["network_requests"] == 0
    assert result["live_verified"] is False
    assert result["replayed_updates"] == 1
    assert result["batch_updates"] == 1
    assert result["duplicate_events"] == 2
    assert result["stale_events"] == 1
    assert result["cursor_resets"] == 1
    assert result["reconciliation_required"] is True


def test_snapshot_missing_keys_does_not_erase_previous_state():
    result = inspect_replay(
        replay(
            frames=[
                {"type": "batch", "cursor": 7, "events": [event(), event(resourceId="0.9.85")]},
                {"type": "snapshot", "cursor": 0, "events": []},
            ]
        )
    )
    assert result["state_keys"] == 2
    assert result["batch_updates"] == 2
    assert result["cursor_resets"] == 1


@pytest.mark.parametrize(
    "resource", ["0.8.85", "0.9.85", "13.106.85", "3.30.85", "13.150.85", "0.127.85"]
)
def test_source_mapped_fp2_resource_envelopes(resource):
    result = inspect_replay(replay([event(resourceId=resource)]))
    assert result["state_keys"] == 1


def test_source_time_and_value_conflict_needs_reconciliation():
    result = inspect_replay(replay([event(), event(value="61"), event(time=999)]))
    assert result["batch_updates"] == 1
    assert result["conflicting_events"] == 1
    assert result["stale_events"] == 1
    assert result["reconciliation_required"] is True


def test_zero_time_not_promoted_to_fresh_state():
    result = inspect_replay(replay([event(time=0)]))
    assert result["state_keys"] == 0
    assert result["undated_events"] == 1
    assert result["reconciliation_required"] is True


def test_unrecognized_messages_and_foreign_devices_are_isolated():
    result = inspect_replay(
        replay(
            [
                event(subjectId="another-private-device"),
                event(type="spec_report"),
                event(resourceId="unknown"),
                event(statusCode=108),
                event(),
            ]
        )
    )
    assert result["foreign_events"] == 1
    assert result["unsupported_events"] == 2
    assert result["failed_events"] == 1
    assert result["state_keys"] == 1


def test_coordinate_payload_shape_without_units_or_derived_occupancy():
    value = json.dumps([{"id": 1, "x": 2.5, "y": -3, "rangeId": 0, "state": "1"}])
    result = inspect_replay(replay([event(resourceId="4.22.700", value=value)]))
    assert result["state_keys"] == 1
    assert "coordinates" not in result
    assert "presence" not in result


@pytest.mark.parametrize(
    "targets",
    [
        {},
        [None],
        [{"id": 1, "x": 1, "y": 2, "state": True}],
        [{"id": 1, "x": "1", "y": 2, "state": 1}],
        [{"id": 1, "x": 1, "y": float("inf"), "state": 1}],
        [{"id": 1, "x": 10**1000, "y": 2, "state": 1}],
        [{"id": 1, "x": 1, "y": 2, "state": 1}] * 2,
    ],
)
def test_malformed_coordinate_values_are_rejected(targets):
    with pytest.raises(InvalidReplay, match="^invalid_push_replay$"):
        inspect_replay(replay([event(resourceId="4.22.700", value=json.dumps(targets))]))


@pytest.mark.parametrize(
    "change",
    [
        {"time": True},
        {"time": -1},
        {"time": 253402300800000},
        {"time": "1e3"},
        {"time": 1.1},
        {"time": "SECRET"},
        {"statusCode": False},
        {"statusCode": "0"},
        {"statusCode": 2**31},
        {"value": {"token": "SECRET"}},
        {"value": "x" * 8193},
        {"subjectId": None},
        {"resourceId": "\nSECRET"},
    ],
)
def test_strict_event_types(change):
    with pytest.raises(InvalidReplay) as raised:
        inspect_replay(replay([event(**change)]))
    assert "SECRET" not in str(raised.value)
    assert "SECRET" not in repr(raised.value)


@pytest.mark.parametrize(
    "raw",
    [
        b"x" * (MAX_BYTES + 1),
        b"not JSON SECRET",
        b' {"a":1,"a":2}',
        b'{"secret":NaN}',
        b'{"secret":1e9999}',
        b'{"secret":"\\ud800"}',
        b'"\\udfff"',
        b"[]",
        b"{}",
        b'{"selected_subjects":[],"frames":[]}',
        b"[" * 30 + b"0" + b"]" * 30,
    ],
)
def test_bounded_strict_json(raw):
    with pytest.raises(InvalidReplay) as raised:
        inspect_replay(raw)
    assert str(raised.value) == "invalid_push_replay"


@pytest.mark.parametrize("cursor", [True, "1", -1, 2**63])
def test_invalid_cursors(cursor):
    with pytest.raises(InvalidReplay):
        inspect_replay(replay(frames=[{"type": "batch", "cursor": cursor, "events": []}]))


def test_backward_batch_is_not_silently_accepted():
    with pytest.raises(InvalidReplay):
        inspect_replay(
            replay(
                frames=[
                    {"type": "batch", "cursor": 3, "events": [event()]},
                    {"type": "batch", "cursor": 2, "events": [event(time=2000)]},
                ]
            )
        )


def test_report_never_contains_raw_values_ids_or_extra_fields():
    result = inspect_replay(replay([event(value="SECRET-VALUE", token="SECRET-TOKEN")]))
    output = json.dumps(result)
    assert "SECRET" not in output
    assert "test-only-device" not in output
    assert "0.8.85" not in output


def test_cli_demo_and_local_file(tmp_path: Path, capsys):
    assert main(["--demo"]) == 0
    assert json.loads(capsys.readouterr().out)["network_requests"] == 0
    path = tmp_path / "synthetic.json"
    path.write_text(replay())
    assert main(["--file", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["state_keys"] == 1


def test_cli_missing_file_reports_static_error(tmp_path: Path, capsys):
    assert main(["--file", str(tmp_path / "SECRET-PATH")]) == 1
    output = capsys.readouterr().out
    assert "SECRET" not in output
    assert json.loads(output)["error"] == "invalid_push_replay"

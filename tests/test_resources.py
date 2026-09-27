"""Source-contract tests with synthetic responses, never evidence of live access."""

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.aqara_presence_lab.api.errors import (
    ApplicationError,
    InvalidResponse,
    ResponseTooLarge,
)
from custom_components.aqara_presence_lab.api.parsing import MAX_RESPONSE_BYTES
from custom_components.aqara_presence_lab.api.resources import (
    MAX_RESOURCE_ITEMS,
    MAX_RESOURCE_NUMBER,
    RESOURCE_OPTIONS,
    RESOURCES,
    SETTINGS,
    SETTINGS_OPTIONS,
    parse_resource_response,
    parse_resource_settings_response,
)

DEVICE = "synthetic-fp2-resource-device"
RECEIVED = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)


def response(*items):
    return {"code": 0, "result": list(items)}


def read(payload, **kwargs):
    return parse_resource_response(payload, device_id=DEVICE, received_at=RECEIVED, **kwargs)


def observation(attr, value):
    return read(response({"attr": attr, "value": value})).observations[attr]


def settings(payload):
    return parse_resource_settings_response(payload, device_id=DEVICE, received_at=RECEIVED)


def test_catalog_matches_documented_status_families_and_separate_setting_ids():
    base = {
        "body_movement_value",
        "device_offline_status",
        "heartrate_value",
        "respiration_rate_value",
        "sleep_state",
        "lux",
        "installation_angle",
        "set_device_mode4",
        "view_zoom",
        "mounting_position",
        "attitude_status",
        "all_zone_statistics",
        "people_counting",
        "people_counting_by_mins",
    }
    expected = (
        base
        | {f"detection_area{zone}" for zone in range(1, 31)}
        | {f"zone{zone}_statistics" for zone in range(1, 31)}
        | {f"zone{zone}_people_counting_by_mins" for zone in range(1, 8)}
    )
    assert type(RESOURCE_OPTIONS) is tuple
    assert set(RESOURCE_OPTIONS) == set(RESOURCES) == expected
    assert len(RESOURCE_OPTIONS) == 81
    assert SETTINGS_OPTIONS == (
        "14.30.85",
        "14.55.85",
        "14.51.85",
        "14.1.85",
        "14.47.85",
        "4.23.85",
        "4.72.85",
    )
    assert len(SETTINGS) == 7
    assert not set(RESOURCES).intersection(SETTINGS)
    specs = (*RESOURCES.values(), *SETTINGS.values())
    assert len({spec.key for spec in specs}) == 88
    assert all(spec.key.startswith(("resource_", "setting_")) for spec in specs)
    assert all(spec.zone is None or not spec.enabled_default for spec in specs)


def test_catalog_units_sleep_requirements_and_only_documented_enum_labels():
    assert RESOURCES["heartrate_value"].unit == "bpm"
    assert RESOURCES["respiration_rate_value"].unit == "br/min"
    assert RESOURCES["lux"].unit == "lx"
    assert RESOURCES["body_movement_value"].unit is None
    assert {spec.attr for spec in RESOURCES.values() if spec.requires_sleep} == {
        "heartrate_value",
        "respiration_rate_value",
        "sleep_state",
        "body_movement_value",
    }
    assert RESOURCES["set_device_mode4"].enum_map == {
        3: "zone_detection",
        5: "fall_detection",
        9: "sleep_monitoring",
    }
    assert RESOURCES["sleep_state"].enum_map == {}
    assert RESOURCES["attitude_status"].enum_map == {}
    assert all(spec.diagnostic for spec in SETTINGS.values())
    assert all(not spec.enabled_default for spec in SETTINGS.values())
    assert SETTINGS["proximity_sensing_dist"].enum_map == {0: "far", 1: "medium", 2: "close"}


@pytest.mark.parametrize(
    ("attr", "value", "expected"),
    [
        ("heartrate_value", "62", 62),
        ("respiration_rate_value", "14.5", 14.5),
        ("body_movement_value", 0, 0),
        ("lux", "9", 9),
        ("lux", "1e2", 100),
        ("people_counting", "1.75", 1.75),
        ("people_counting_by_mins", 0.25, 0.25),
        ("all_zone_statistics", "3", 3),
        ("zone30_statistics", 2.0, 2),
        ("zone7_people_counting_by_mins", "0.5", 0.5),
        ("detection_area30", "1", 1),
        ("detection_area1", 0, 0),
        ("device_offline_status", "0", 0),
        ("set_device_mode4", "9", 9),
        ("set_device_mode4", "99", 99),
        ("sleep_state", "2", 2),
        ("sleep_state", 2, 2),
        ("attitude_status", "99", 99),
    ],
)
def test_documented_scalar_forms_keep_zero_precision_and_unknown_enum_codes(attr, value, expected):
    item = observation(attr, value)
    assert item.value == expected
    assert item.value_status == "present"
    assert item.quality == "unverified"
    assert item.source_time_utc is None
    assert item.received_at_utc == RECEIVED


@pytest.mark.parametrize(
    "value", [True, False, "", "nan", "NaN", "Infinity", "1e999", [], {}, " 12", "01", -1]
)
def test_invalid_numeric_values_do_not_become_zero(value):
    item = observation("heartrate_value", value)
    assert item.value is None and item.value_status == "invalid"
    assert item.quality == "invalid"


@pytest.mark.parametrize(
    ("attr", "value"),
    [
        ("all_zone_statistics", 1.5),
        ("zone1_statistics", "1.01"),
        ("set_device_mode4", 3.2),
        ("detection_area1", 2),
        ("device_offline_status", -1),
        ("device_offline_status", True),
        ("sleep_state", False),
        ("sleep_state", [1, 2]),
        ("sleep_state", 2.0),
        ("sleep_state", "2.0"),
        ("sleep_state", "02"),
        ("sleep_state", "+2"),
        ("sleep_state", "2e0"),
        ("sleep_state", "x" * 256),
        ("attitude_status", "line\nbreak"),
        ("attitude_status", "x\x7f"),
        ("attitude_status", MAX_RESOURCE_NUMBER + 1),
        ("lux", MAX_RESOURCE_NUMBER + 1),
        ("lux", str(MAX_RESOURCE_NUMBER + 1)),
    ],
)
def test_kind_specific_limits_and_types(attr, value):
    item = observation(attr, value)
    assert item.value is None and item.value_status == "invalid"


def test_missing_null_defaults_and_empty_results_remain_distinct():
    data = read(
        response(
            {"attr": "heartrate_value", "defaultValue": 65},
            {"attr": "respiration_rate_value", "value": None, "defaultValue": 14},
            {"attr": "lux", "value": 0},
        )
    )
    assert len(data.observations) == 81
    assert data.observations["heartrate_value"].value_status == "missing"
    assert data.observations["respiration_rate_value"].value_status == "null"
    assert data.observations["respiration_rate_value"].value is None
    assert data.observations["lux"].value == 0
    assert data.observations["sleep_state"].value_status == "missing"
    later = read(response())
    assert later.available
    assert all(
        item.value is None and item.value_status == "missing"
        for item in later.observations.values()
    )
    assert all(item.quality == "missing" for item in later.observations.values())


@pytest.mark.parametrize("wrapper", ["attributes", "data", "list", "items", "result"])
def test_documented_single_list_wrappers_and_single_value_wrapper(wrapper):
    data = read(
        {
            "code": 0,
            "result": {
                "subjectId": DEVICE,
                wrapper: [{"attr": "lux", "subjectId": DEVICE, "value": {"value": "9"}}],
            },
        }
    )
    assert data.observations["lux"].value == 9


@pytest.mark.parametrize(
    "result",
    [
        {"items": [], "data": []},
        {"items": [], "data": "not-list"},
        {"items": {"items": []}},
        {},
        None,
        '[{"attr":"lux","value":9}]',
        [None],
        [9],
        [{}],
        [{"attr": None}],
        [{"attr": "bad attr"}],
    ],
)
def test_invalid_or_ambiguous_resource_containers_are_rejected(result):
    with pytest.raises(InvalidResponse):
        read({"code": 0, "result": result})


def test_arbitrary_deeper_value_objects_are_not_guessed():
    data = read(
        response(
            {"attr": "lux", "value": {"value": {"value": 9}}},
            {"attr": "heartrate_value", "value": {"unrelated": 62}},
        )
    )
    assert data.observations["lux"].value_status == "invalid"
    assert data.observations["heartrate_value"].value_status == "invalid"


@pytest.mark.parametrize("location", ["top", "result", "item", "value", "unknown"])
@pytest.mark.parametrize("foreign", ["foreign-secret-device", None, 1])
def test_explicit_foreign_subject_is_rejected_at_every_wrapper_level(location, foreign):
    item = {"attr": "lux", "value": 9}
    data = response(item)
    if location == "top":
        data["subjectId"] = foreign
    elif location == "result":
        data["result"] = {"subjectId": foreign, "items": [item]}
    elif location == "item":
        item["subjectId"] = foreign
    elif location == "value":
        item["value"] = {"subjectId": foreign, "value": 9}
    else:
        item["metadata"] = {"nested": [{"subjectId": foreign}]}
    with pytest.raises(InvalidResponse) as caught:
        read(data)
    assert "foreign-secret-device" not in repr(caught.value)


def test_matching_subjects_are_bound_by_request_context_without_array_index_assignment():
    data = read(
        response(
            {"attr": "lux", "value": 9, "subjectId": DEVICE},
            {"attr": "heartrate_value", "value": 61},
            {"attr": "future_unknown_field", "value": "SECRET-unexported"},
        )
    )
    assert data.device_id == DEVICE
    assert data.observations["heartrate_value"].value == 61
    assert "future_unknown_field" not in data.observations
    assert "SECRET" not in repr(data)


def test_identical_duplicates_coalesce_and_conflicting_values_are_isolated():
    first = {"attr": "lux", "value": "9", "timeStamp": 1790355356562}
    data = read(response(first, deepcopy(first), {"attr": "heartrate_value", "value": 61}))
    assert data.error is None and data.observations["lux"].value == 9
    conflict = {"attr": "lux", "value": 9, "timeStamp": 1790355356562}
    data = read(response(first, conflict, {"attr": "heartrate_value", "value": 61}))
    assert data.error == "conflicting_resources"
    assert data.available
    assert data.observations["lux"].value is None
    assert data.observations["lux"].value_status == "invalid"
    assert data.observations["heartrate_value"].value == 61


def test_boolean_integer_duplicates_cannot_silently_match():
    data = read(
        response(
            {"attr": "detection_area1", "value": True},
            {"attr": "detection_area1", "value": 1},
        )
    )
    assert data.error == "conflicting_resources"
    assert data.observations["detection_area1"].value is None


@pytest.mark.parametrize("timestamp", [1790355356, 1790355356562, "1790355356562", 1790355356.5])
def test_opaque_source_time_never_uses_seconds_or_milliseconds_heuristics(timestamp):
    item = read(response({"attr": "lux", "value": 9, "timeStamp": timestamp})).observations["lux"]
    assert item.source_time_raw == timestamp
    assert item.source_time_utc is None
    assert item.quality == "unverified"


@pytest.mark.parametrize(
    "fields",
    [
        {"timeStamp": -1},
        {"timestamp": True},
        {"timestamp": []},
        {"timeStamp": "2026-09-27"},
        {"timeStamp": 123, "timestamp": 124},
        {"timeStamp": "123", "timestamp": 123},
    ],
)
def test_invalid_time_metadata_preserves_value_but_marks_quality_invalid(fields):
    item = read(response({"attr": "lux", "value": 9, **fields})).observations["lux"]
    assert item.value == 9 and item.value_status == "present"
    assert item.quality == "invalid"
    assert item.source_time_raw is None and item.source_time_utc is None


@pytest.mark.parametrize(
    "identity",
    [
        {"resourceId": "14.30.85"},
        {"attr": "14.30.85"},
        {"attr": "fall_detection_sens"},
        {"resourceId": "14.30.85", "attr": "fall_detection_sens"},
    ],
)
def test_settings_bind_resource_ids_and_explicit_attribute_fallback(identity):
    data = settings(response({**identity, "value": "2"}))
    assert len(data.observations) == 7
    assert data.observations["fall_detection_sens"].value == 2
    assert data.observations["fall_detection_sens"].value_status == "present"
    assert data.observations["ai_person_det"].value_status == "missing"


@pytest.mark.parametrize(
    "item",
    [
        {"resourceId": "14.30.85", "attr": "ai_person_det", "value": 1},
        {"resourceId": "4.72.85", "attr": "14.30.85", "value": 1},
        {"resourceId": "fall_detection_sens", "value": 1},
        {"resourceId": None, "value": 1},
        {"resourceId": "", "value": 1},
    ],
)
def test_settings_reject_malformed_or_conflicting_identifiers(item):
    with pytest.raises(InvalidResponse):
        settings(response(item))


def test_settings_do_not_invent_unknown_enum_meanings_or_copy_unknown_resources():
    data = settings(
        response(
            {"resourceId": "14.30.85", "value": "999"},
            {"resourceId": "999.999.999", "value": "SECRET-value"},
        )
    )
    assert data.observations["fall_detection_sens"].value == 999
    assert 999 not in SETTINGS["fall_detection_sens"].enum_map
    assert len(data.observations) == 7


@pytest.mark.parametrize(
    "payload",
    [
        b'{"code":0,"code":0,"result":[]}',
        b'{"code":0,"result":[],"bad":NaN}',
        b'{"code":0,"result":[],"bad":Infinity}',
        b'{"code":0,"result":[],"bad":1e999}',
        b'{"code":0,"result":[],"bad":"\\ud800"}',
        b'{"code":0,"result":[]}{}',
        b'{"code":0,"result":',
        b"\xff",
        [],
        {"code": True, "result": []},
        {"code": "0", "result": []},
        {"code": 0, "result": [], "bad": float("nan")},
        {"code": 0, "result": [], "bad": "\ud800"},
        {"code": 0, "result": [], 2: "invalid-key"},
    ],
)
def test_strict_json_envelope_and_nonfinite_unicode_rejection(payload):
    with pytest.raises(InvalidResponse):
        read(payload)


def test_application_errors_have_only_safe_numeric_metadata():
    with pytest.raises(ApplicationError) as caught:
        read({"code": 108, "message": "SECRET-message", "result": []})
    assert caught.value.code == 108
    assert "SECRET" not in repr(caught.value)


def test_input_size_depth_and_item_limits_cover_bytes_and_dict_inputs():
    with pytest.raises(ResponseTooLarge):
        read(b" " * (MAX_RESPONSE_BYTES + 1))
    with pytest.raises(ResponseTooLarge):
        read({"code": 0, "result": [], "huge": "x" * MAX_RESPONSE_BYTES})
    with pytest.raises(InvalidResponse):
        read(response(*({"attr": "lux", "value": 9} for _ in range(MAX_RESOURCE_ITEMS + 1))))
    with pytest.raises(InvalidResponse):
        read("[" * 70 + "]" * 70)


@pytest.mark.parametrize("device_id", ["", "a b", "a\n", "a" * 257, "\ud800", None, 123])
def test_request_context_requires_bounded_valid_device_identity(device_id):
    with pytest.raises(InvalidResponse):
        parse_resource_response(response(), device_id=device_id)


def test_local_times_are_aware_and_do_not_become_source_times():
    requested = RECEIVED - timedelta(seconds=1)
    data = read(json.dumps(response({"attr": "lux", "value": 9})).encode(), requested_at=requested)
    assert data.received_at_utc == RECEIVED
    assert data.observations["lux"].source_time_utc is None
    assert parse_resource_response(response(), device_id=DEVICE).received_at_utc.tzinfo is UTC
    for value in (datetime(2026, 9, 27), 0, "not-a-datetime"):
        with pytest.raises(InvalidResponse):
            parse_resource_response(response(), device_id=DEVICE, received_at=value)
        with pytest.raises(InvalidResponse):
            read(response(), requested_at=value)


def test_resource_values_and_raw_timestamps_are_not_in_repr_or_logs(caplog):
    data = read(
        response({"attr": "sleep_state", "value": "123456789", "timeStamp": "1790355356562"})
    )
    item = data.observations["sleep_state"]
    assert item.value == 123456789
    assert "123456789" not in repr(data) + repr(item) + caplog.text
    assert DEVICE not in repr(data)
    assert "1790355356562" not in repr(data) + repr(item)


@pytest.mark.parametrize("attr", ["sleep_state", "attitude_status"])
@pytest.mark.parametrize(
    "canary",
    [
        "Token SECRET-token",
        "password=SECRET-password",
        "person@example.invalid",
        "arbitrary_state_name",
        "NaN",
        "Infinity",
    ],
)
def test_unknown_raw_text_cannot_escape_into_entity_values_or_diagnostics(attr, canary, caplog):
    data = read(response({"attr": attr, "value": canary}))
    item = data.observations[attr]
    assert item.value is None
    assert item.value_status == "invalid"
    assert item.quality == "invalid"
    assert canary not in repr(data) + repr(item) + caplog.text

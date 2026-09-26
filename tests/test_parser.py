"""Contract tests against the reconstructed capture and adversarial input."""

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from custom_components.aqara_presence_lab.api.errors import (
    ApplicationError,
    InvalidResponse,
    ResponseTooLarge,
)
from custom_components.aqara_presence_lab.api.models import AccountIdentity, DeviceSelection
from custom_components.aqara_presence_lab.api.parsing import (
    MAX_RESPONSE_BYTES,
    parse_response,
    strict_json_loads,
)
from custom_components.aqara_presence_lab.api.profiles import CANDIDATE_PROFILE

ROOT = Path(__file__).resolve().parents[1]
RECEIVED = datetime.fromtimestamp(1790355356562 / 1000, UTC)
A, B = "lumi1.000000000001", "lumi1.000000000002"
LUX = "4.154.32989"


@pytest.fixture
def response():
    return json.loads((ROOT / "fixtures/trait_read.response.json").read_text())


def read(data, **kwargs):
    return parse_response(data, received_at=RECEIVED, **kwargs)


def tiny(trait, device_id=A):
    return {"code": 0, "result": [{"deviceId": device_id, "traits": [trait]}]}


def test_complete_fixture_and_request_order(response):
    request = json.loads((ROOT / "fixtures/trait_read.request.json").read_text())
    requested = {d["deviceId"]: [t["path"] for t in d["traits"]] for d in request["devices"]}
    snapshot = read(response, selected_device_ids=(B, A), requested_paths=requested)
    assert list(snapshot.devices) == [B, A]
    assert snapshot.devices[A].traits[LUX].normalized_value == 9
    assert snapshot.devices[B].traits[LUX].normalized_value == 110
    assert snapshot.devices[A].traits[LUX].source_time_ms == 1790354656410
    assert snapshot.devices[A].traits[LUX].freshness_status == "reported"
    assert snapshot.devices[A].traits["2.160.33000"].normalized_value == "0"
    assert snapshot.devices[A].traits["2.160.33000"].semantic_status == "candidate"
    assert snapshot.devices[A].traits["2.160.33000"].freshness_status == "reported"
    assert snapshot.devices[B].traits["2.160.33044"].normalized_value == 3731446
    assert snapshot.devices[A].traits["2.160.33044"].value_status == "missing"
    assert snapshot.devices[A].traits["0.129.33013"].normalized_value == [4, 6]
    assert "0.129.32909" in snapshot.devices[A].requested_not_returned
    assert snapshot.devices[A].traits["0.129.32909"].value_status == "missing"
    assert snapshot.devices[B].name == "Praesenzsensor B"
    assert len(request["devices"][0]["traits"]) == 31
    assert len(request["devices"][1]["traits"]) == 37
    assert len(response["result"][0]["traits"]) == 20
    assert len(response["result"][1]["traits"]) == 25


def test_catalog_contains_exactly_all_requested_paths():
    request = json.loads((ROOT / "fixtures/trait_read.request.json").read_text())
    catalog = json.loads((ROOT / "config/trait_catalog.json").read_text())
    paths = {t["path"] for d in request["devices"] for t in d["traits"]}
    assert {t["path"] for t in catalog["traits"]} == paths
    assert len(catalog["traits"]) == 31
    assert set(CANDIDATE_PROFILE.read_paths) == paths
    assert len(CANDIDATE_PROFILE.read_paths) == 31
    assert all(t["presence_mapping"] is None for t in catalog["traits"])


@pytest.mark.parametrize(
    ("fields", "status", "value", "has_value"),
    [
        ({"defaultValue": 0}, "missing", None, False),
        ({"value": None, "defaultValue": 1}, "null", None, True),
        ({"value": "0"}, "present", "0", True),
        ({"value": 0}, "present", 0, True),
        ({"value": False}, "present", False, True),
        ({"value": ""}, "present", "", True),
    ],
)
def test_value_states_remain_distinct(fields, status, value, has_value):
    observation = read(tiny({"path": "2.160.33000", **fields})).devices[A].traits["2.160.33000"]
    assert observation.value_status == status
    assert observation.has_value == has_value
    assert observation.normalized_value == value
    assert type(observation.normalized_value) is type(value)


@pytest.mark.parametrize(
    "value", [False, True, "", "nan", "Infinity", "1e999", "--1", [], {}, "-1", -1]
)
def test_invalid_lux_never_becomes_zero(value):
    observation = read(tiny({"path": LUX, "value": value})).devices[A].traits[LUX]
    assert observation.value_status == "invalid"
    assert observation.normalized_value is None
    assert observation.freshness_status == "invalid"


@pytest.mark.parametrize(
    ("value", "expected"), [("9", 9), ("0", 0), (9.5, 9.5), ("1e2", 100), ("1.25", 1.25)]
)
def test_valid_lux_does_not_use_step_rounding(value, expected):
    observation = read(tiny({"path": LUX, "value": value, "step": 10.0})).devices[A].traits[LUX]
    assert observation.normalized_value == expected


def test_unicode_and_large_integer_identifiers_are_preserved():
    device_id = "lumi1.99999999999999999999999999999"
    data = tiny({"path": "0.130.32913", "value": "传感器 • Küche 🏠"}, device_id)
    snapshot = read(json.dumps(data, ensure_ascii=False).encode())
    assert snapshot.devices[device_id].name == "传感器 • Küche 🏠"
    assert (
        AccountIdentity("EU", "99999999999999999999999999").account_key
        != AccountIdentity("EU", "99999999999999999999999998").account_key
    )


@pytest.mark.parametrize(
    "payload",
    [
        b'{"code":0,"code":0,"result":[]}',
        b'{"code":0,"result":[{"deviceId":"a","deviceId":"b"}]}',
        b'{"code":0,"result":[],"x":NaN}',
        b'{"code":0,"result":[],"x":Infinity}',
        b'{"code":0,"result":[],"x":1e999}',
        b'{"code":0,"result":[]}{"code":0,"result":[]}',
        b'{"code":0,"result":',
        b"<html>failure</html>",
        b"\xff",
        b"[]",
        b"null",
        b'{"code":true,"result":[]}',
        b'{"code":"0","result":[]}',
        b'{"code":0,"result":{}}',
        b'{"result":[]}',
        b'{"code":0,"result":[],"unknown":"\\ud800"}',
        b'{"code":0,"result":[],"\\udfff":1}',
    ],
)
def test_invalid_envelope_rejected_without_repair(payload):
    with pytest.raises(InvalidResponse):
        read(payload)


def test_limits_bound_every_input_form(response):
    with pytest.raises(ResponseTooLarge):
        read(b" " * (MAX_RESPONSE_BYTES + 1))
    with pytest.raises(ResponseTooLarge):
        read({"code": 0, "result": [], "unknown": "x" * MAX_RESPONSE_BYTES})
    response["result"] *= 51
    with pytest.raises(InvalidResponse):
        read(response)
    with pytest.raises(InvalidResponse):
        strict_json_loads("[" * 70 + "]" * 70)


def test_application_failure_is_not_success_and_message_not_exported():
    with pytest.raises(ApplicationError) as caught:
        read({"code": 999, "message": "SECRET response", "result": []})
    assert caught.value.code == 999
    assert "SECRET" not in str(caught.value)


def test_identical_duplicates_coalesce_but_type_conflicts_are_isolated(response):
    response["result"][0]["traits"].append(deepcopy(response["result"][0]["traits"][4]))
    assert len(read(response).devices[A].traits) == 20
    response["result"][0]["traits"].append({"path": LUX, "value": 9})
    snapshot = read(response)
    assert snapshot.devices[A].error == "conflicting_traits"
    assert snapshot.devices[A].traits[LUX].value_status == "invalid"
    assert snapshot.devices[B].traits[LUX].normalized_value == 110


def test_boolean_integer_duplicate_conflict():
    data = tiny({"path": "0.128.32901", "value": 1})
    data["result"][0]["traits"].append({"path": "0.128.32901", "value": True})
    assert read(data).devices[A].error == "conflicting_traits"


def test_device_duplicates_conflicting_payloads_cannot_last_win(response):
    duplicate = deepcopy(response["result"][0])
    duplicate["traits"] = []
    response["result"].append(duplicate)
    snapshot = read(response)
    assert not snapshot.devices[A].available
    assert snapshot.devices[A].error == "conflicting_devices"
    assert snapshot.devices[B].available


def test_partial_device_failure_isolated_and_unsolicited_not_registered(response):
    response["result"][0]["traits"] = "invalid"
    snapshot = read(response)
    assert not snapshot.devices[A].available
    assert snapshot.devices[B].traits[LUX].normalized_value == 110
    snapshot = read(response, selected_device_ids=[B])
    assert set(snapshot.devices) == {B}
    assert snapshot.ignored_devices == 1


def test_trait_count_limit_and_malformed_traits_do_not_affect_other_device(response):
    response["result"][0]["traits"] *= 11
    assert not read(response).devices[A].available
    response["result"][0]["traits"] = [{"path": LUX, "value": 9}, {"path": "not a path"}, None]
    snapshot = read(response)
    assert snapshot.devices[A].error == "invalid_traits"
    assert snapshot.devices[A].traits[LUX].normalized_value == 9
    assert snapshot.devices[B].available


def test_current_metadata_and_history_are_separate():
    first = read(tiny({"path": LUX, "value": "9", "unit": "lux", "traitTime": 1700000000000}))
    next_time = RECEIVED + timedelta(seconds=300)
    second = parse_response(
        tiny({"path": LUX, "defaultValue": "0"}), received_at=next_time, previous=first
    )
    device = second.devices[A]
    assert device.traits[LUX].normalized_value is None
    assert device.traits[LUX].received_at_utc == next_time
    assert device.last_values[LUX].normalized_value == 9
    assert device.last_values[LUX].received_at_utc == RECEIVED
    assert device.metadata[LUX]["unit"] == "lux"
    assert device.metadata[LUX]["defaultValue"] == "0"
    missing = parse_response(
        {"code": 0, "result": []}, received_at=next_time, selected_device_ids=[A], previous=second
    )
    assert not missing.devices[A].available
    assert missing.devices[A].traits == {}
    assert missing.devices[A].last_values[LUX].received_at_utc == RECEIVED
    again = read({"code": 0, "result": []}, selected_device_ids=[A], previous=missing)
    assert again.devices[A].consecutive_failures == 2


def test_unchanged_value_keeps_local_change_time():
    first = read(tiny({"path": LUX, "value": "9", "traitTime": 1700000000000}))
    second = parse_response(
        tiny({"path": LUX, "value": "9", "traitTime": 1700000000000}),
        received_at=RECEIVED + timedelta(seconds=300),
        previous=first,
    )
    observation = second.devices[A].traits[LUX]
    assert observation.last_value_change_observed_at == RECEIVED
    assert observation.source_time_ms == 1700000000000
    assert observation.received_at_utc != RECEIVED
    assert observation.freshness_status == "reported"


@pytest.mark.parametrize("value", [-1, True, "1234", 1.2])
def test_invalid_source_times_are_not_accepted(value):
    observation = read(tiny({"path": LUX, "value": "9", "traitTime": value})).devices[A].traits[LUX]
    assert observation.source_time_ms is None
    assert observation.freshness_status == "invalid"


def test_future_timestamp_preserved_as_clock_anomaly():
    observation = (
        read(tiny({"path": LUX, "value": "9", "traitTime": 999999999999999999999}))
        .devices[A]
        .traits[LUX]
    )
    assert observation.source_time_ms == 999999999999999999999
    assert observation.source_time_utc is None
    assert observation.freshness_status == "clock_anomaly"


@pytest.mark.parametrize(
    "value", ["__import__('os').system('echo NO')", "[1,NaN]", "[1,]", "{'key':1}", "false"]
)
def test_json_encoded_list_is_strict_data_only(value):
    observation = (
        read(tiny({"path": "0.129.33013", "value": value})).devices[A].traits["0.129.33013"]
    )
    assert observation.value_status == "invalid"


def test_unknown_fields_retained_but_bounded():
    snapshot = read(
        tiny({"path": LUX, "value": "9", "unknown": {"future": 123}, "huge": "x" * 5000})
    )
    assert snapshot.devices[A].traits[LUX].raw.fields["unknown"] == {"future": 123}
    assert "huge" not in snapshot.devices[A].traits[LUX].raw.fields


@pytest.mark.parametrize("ids", [(), ("a", "a"), ("",), (1,), tuple(str(x) for x in range(101))])
def test_device_selection_rejects_invalid(ids):
    with pytest.raises(ValueError):
        DeviceSelection(ids)


def test_no_secret_ids_in_repr(response):
    identity = AccountIdentity("EU", "SECRET-ID")
    assert "SECRET-ID" not in repr(identity)
    assert "SECRET-ID" not in repr(DeviceSelection(("SECRET-ID",)))
    assert A not in repr(read(response))
    assert "Praesenzsensor" not in repr(read(response).devices[A])
    response["result"][0]["deviceModel"] = "SECRET-MODEL"
    assert "SECRET-MODEL" not in repr(read(response).devices[A])

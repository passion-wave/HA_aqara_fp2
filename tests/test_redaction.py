"""Test secrets at every layer, including arbitrary unknown nested fields."""

import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from custom_components.aqara_presence_lab.api.errors import (
    AccessDenied,
    AccountMismatch,
    ApplicationError,
    AuthenticationRequired,
    InvalidResponse,
    ProtocolUnsupported,
    RequestRejected,
    SignatureRejected,
    TransportError,
)
from custom_components.aqara_presence_lab.api.models import TransportHealth
from custom_components.aqara_presence_lab.api.parsing import parse_response
from custom_components.aqara_presence_lab.api.profiles import CANDIDATE_PROFILE
from custom_components.aqara_presence_lab.api.redaction import build_diagnostics


def test_allowlist_has_no_identity_names_raw_values_or_unknown_strings():
    data = {
        "code": 0,
        "message": "SECRET-MESSAGE",
        "requestId": "SECRET-REQUEST",
        "result": [
            {
                "deviceId": "SECRET-DEVICE",
                "deviceModel": "SECRET-MODEL",
                "positionId": "SECRET-ROOMID",
                "headers": {"Token": "SECRET-TOKEN", "Phoneid": "SECRET-PHONE"},
                "traits": [
                    {
                        "path": "0.130.32913",
                        "value": "SECRET-NAME",
                        "defaultValue": "SECRET-DEFAULT",
                    },
                    {"path": "0.130.33016", "value": "SECRET-ROOM"},
                    {
                        "path": "4.154.32989",
                        "value": "9",
                        "unknown": {"array": [{"cookie": "SECRET-COOKIE"}]},
                    },
                    {"path": "1.2.3", "value": {"nested": [{"Token": "SECRET-NESTED"}]}},
                ],
            }
        ],
    }
    snapshot = parse_response(data, received_at=datetime(2026, 9, 26, tzinfo=UTC))
    diagnostic = build_diagnostics(snapshot)
    text = json.dumps(diagnostic)
    assert "SECRET" not in text
    assert "raw_value" not in text
    assert "defaultValue" not in text
    assert "received_at" not in text
    assert diagnostic["devices"][0]["alias"] == "device_1"
    assert diagnostic["devices"][0]["traits"][0]["value_type"] == "string"
    assert diagnostic["device_count"] == 1
    assert text == json.dumps(build_diagnostics(snapshot))


def test_arbitrary_status_model_fields_cannot_leak_secrets():
    data = {
        "code": 0,
        "result": [{"deviceId": "SECRET", "traits": [{"path": "1.2.3", "value": 4}]}],
    }
    snapshot = parse_response(data)
    device = snapshot.devices["SECRET"]
    bad_observation = replace(
        device.traits["1.2.3"], value_status="SECRET-VALUE", freshness_status="SECRET-QUALITY"
    )
    device = replace(
        device,
        error="SECRET-ERROR",
        traits={"1.2.3": bad_observation, "SECRET-PATH": bad_observation},
    )
    snapshot = replace(snapshot, devices={"SECRET": device})
    profile = replace(CANDIDATE_PROFILE, id="SECRET-PROFILE", validation_state="SECRET-STATE")
    health = TransportHealth(status="SECRET-STATUS", error_class="SECRET-ERROR")
    result = build_diagnostics(
        snapshot, profile=profile, integration_version="SECRET-VERSION", health=health
    )
    assert "SECRET" not in json.dumps(result)


@pytest.mark.parametrize(
    "error",
    [
        AccessDenied,
        AccountMismatch,
        ApplicationError,
        AuthenticationRequired,
        InvalidResponse,
        ProtocolUnsupported,
        RequestRejected,
        SignatureRejected,
        TransportError,
    ],
)
def test_errors_never_echo_server_or_credential_text(error):
    exception = error("SECRET-CREDENTIAL-OR-RESPONSE")
    assert "SECRET" not in repr(exception)
    assert "SECRET" not in str(exception)


def test_empty_and_unavailable_diagnostics_stay_readable():
    result = build_diagnostics(
        None,
        health=TransportHealth(
            status="retry_wait", error_class="cannot_connect", consecutive_failures=2
        ),
    )
    assert result["device_count"] == 0
    assert result["transport"]["status"] == "retry_wait"
    assert result["transport"]["error_class"] == "cannot_connect"
    assert result["transport"]["consecutive_failures"] == 2

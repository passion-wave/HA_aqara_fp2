"""Only allowlisted, bounded operational facts may reach logging handlers."""

import json
import logging

import pytest

from custom_components.aqara_presence_lab.api.errors import ApplicationError, AqaraError
from custom_components.aqara_presence_lab.api.logging import log_event
from tests.test_account import OLD, expiry_reply, login_reply, managed, read_reply

LOGGER = "custom_components.aqara_presence_lab.api.logging"


@pytest.mark.parametrize(
    ("event", "level"),
    [
        ("request_started", logging.DEBUG),
        ("request_succeeded", logging.DEBUG),
        ("request_cancelled", logging.DEBUG),
        ("client_closed", logging.DEBUG),
        ("login_candidate", logging.INFO),
        ("session_validated", logging.INFO),
        ("authentication_required", logging.WARNING),
        ("request_failed", logging.WARNING),
    ],
)
def test_event_levels_and_static_operation(caplog, event, level):
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        log_event(event, operation="trait_read")
    record = caplog.records[-1]
    assert record.levelno == level
    assert json.loads(record.getMessage()) == {"event": event, "operation": "trait_read"}
    assert record.exc_info is None


def test_bounded_numeric_diagnostics_and_observed_status_precedence(caplog):
    error = ApplicationError(108, "password-SECRET", http_status=201)
    log_event(
        "request_failed",
        error=error,
        http_status=200,
        device_count=2,
        elapsed=12.12345,
        operation="login",
    )
    assert json.loads(caplog.records[-1].getMessage()) == {
        "event": "request_failed",
        "error_key": "application_error",
        "application_code": 108,
        "http_status": 200,
        "device_count": 2,
        "elapsed": 12.123,
        "operation": "login",
    }
    log_event("request_failed", error=error)
    assert json.loads(caplog.records[-1].getMessage())["http_status"] == 201
    assert "SECRET" not in caplog.text


@pytest.mark.parametrize("bad", [True, False, "SECRET", 2**80, -(2**80), None, [], {}])
def test_untrusted_error_attributes_and_fields_cannot_leak(caplog, bad):
    error = AqaraError("password-SECRET")
    error.error_key = "password-SECRET"
    error.code = bad
    error.http_status = bad
    log_event(
        "password-SECRET",
        error=error,
        http_status=bad,
        device_count=bad,
        operation="account-SECRET",
    )
    assert json.loads(caplog.records[-1].getMessage()) == {"event": "request_failed"}
    assert "SECRET" not in caplog.text


@pytest.mark.parametrize(
    "elapsed", [float("inf"), float("nan"), -1, True, 86401, 2**4000, "SECRET"]
)
def test_invalid_elapsed_not_logged(caplog, elapsed):
    log_event("request_failed", elapsed=elapsed)
    assert json.loads(caplog.records[-1].getMessage()) == {"event": "request_failed"}


async def test_full_renewal_logging_has_no_credentials_account_ids_headers_or_body(caplog):
    api, _, http, _, _, _ = managed([expiry_reply(), login_reply(), read_reply()], initial=OLD)
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        await api.async_read_traits(["d1", "d2"])
        await api.async_close()
    records = [record for record in caplog.records if record.name == LOGGER]
    values = [json.loads(record.getMessage()) for record in records]
    allowed = {
        "event",
        "error_key",
        "application_code",
        "http_status",
        "device_count",
        "elapsed",
        "operation",
    }
    assert all(set(value) <= allowed for value in values)
    assert any(value.get("application_code") == 108 for value in values)
    assert any(
        value["event"] == "session_validated" and value["device_count"] == 2 for value in values
    )
    for forbidden in (
        "SECRET",
        "d1",
        "d2",
        "https://",
        "Token",
        "Userid",
        "password",
        "Sign",
        "Nonce",
    ):
        assert forbidden not in caplog.text
    for _, _, call in http.calls:
        assert call["headers"]["Sign"] not in caplog.text
        assert call["headers"]["PhoneId"] not in caplog.text
    assert all(record.exc_info is None for record in records)

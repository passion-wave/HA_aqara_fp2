import json
from dataclasses import replace

import pytest

from custom_components.aqara_presence_lab.api.errors import (
    InvalidResponse,
    ProtocolUnsupported,
    RateLimited,
)
from custom_components.aqara_presence_lab.api.parsing import parse_response
from custom_components.aqara_presence_lab.api.validation import (
    ProbeBudget,
    probe_report,
    signature_matches,
    signature_report,
)
from tests.transport_helpers import capture


def test_signature_report_safe_and_bound_to_exact_body():
    item, signer = capture()
    assert signature_matches(item, signer)
    assert signature_report(item, signer)["result"] == "matched"
    changed = replace(item, body=item.body + b" ")
    assert not signature_matches(changed, signer)
    serialized = json.dumps(signature_report(item, signer))
    for secret in ("private-token", "private-user", "private-device", item.headers["sign"]):
        assert secret not in serialized
    assert signature_report(item, signer)["production_allowed"] is False


def test_probe_budget_persists_cooldown_limits_and_cross_step(tmp_path):
    now = [1000.0]
    path = tmp_path / "budget.json"
    budget = ProbeBudget(path, now=lambda: now[0])
    budget.reserve("private-user")
    assert path.stat().st_mode & 0o777 == 0o600
    for step in ("G2", "G3"):
        with pytest.raises(RateLimited):
            ProbeBudget(path, now=lambda: now[0]).reserve("private-user", step=step)
    budget.defer("private-user", 120)
    now[0] += 30
    with pytest.raises(RateLimited):
        budget.reserve("private-user", step="G3")
    now[0] += 90
    for _ in range(9):
        budget.reserve("private-user")
        now[0] += 30
    with pytest.raises(ProtocolUnsupported):
        budget.reserve("private-user")
    assert "private-user" not in path.read_text()


def test_budget_clock_rollback_and_corruption_fail_closed(tmp_path):
    now = [1000.0]
    path = tmp_path / "budget.json"
    budget = ProbeBudget(path, now=lambda: now[0])
    budget.reserve("u")
    now[0] -= 100
    with pytest.raises(RateLimited):
        budget.reserve("u")
    path.write_text('{"version":1,"version":1}')
    with pytest.raises(InvalidResponse):
        budget.reserve("u")


def test_no_device_report_is_not_success():
    snapshot = parse_response({"code": 0, "result": []}, selected_device_ids=["private-device"])
    report = probe_report(snapshot)
    assert report["result"] == "no_selected_device_data"
    assert not report["production_allowed"]


def test_empty_traits_are_not_usable_device_data():
    snapshot = parse_response(
        {"code": 0, "result": [{"deviceId": "d", "traits": []}]}, selected_device_ids=["d"]
    )
    assert probe_report(snapshot)["result"] == "no_selected_device_data"


def test_partial_probe_report_does_not_hide_missing_device():
    snapshot = parse_response(
        {
            "code": 0,
            "result": [{"deviceId": "d", "traits": [{"path": "4.154.32989", "value": "9"}]}],
        },
        selected_device_ids=["d", "missing"],
    )
    report = probe_report(snapshot)
    assert report["result"] == "partial_result"
    assert report["usable_device_count"] == 1 and report["device_count"] == 2


def test_budget_rejects_public_permissions_and_symlinks(tmp_path):
    path = tmp_path / "budget.json"
    path.write_text("{}")
    path.chmod(0o644)
    with pytest.raises(InvalidResponse):
        ProbeBudget(path).reserve("u")
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(OSError):
        ProbeBudget(link).reserve("u")


def test_failure_report_preserves_observed_numeric_metadata_without_raw_fields():
    from custom_components.aqara_presence_lab.api.errors import ApplicationError
    from custom_components.aqara_presence_lab.api.profiles import PROFILE
    from custom_components.aqara_presence_lab.api.validation import failure_report

    error = ApplicationError(123456, "SECRET-message", http_status=201)
    error.message = "SECRET-message"
    error.raw = {"token": "SECRET-token", "deviceId": "SECRET-device"}
    report = failure_report(error, gate="G2", profile=PROFILE)
    assert report == {
        "result": "failed",
        "error": "application_error",
        "production_allowed": False,
        "application_code": 123456,
        "http_status": 201,
        "gate": "G2",
        "profile": PROFILE.id,
        "profile_version": PROFILE.version,
    }
    assert "SECRET" not in json.dumps(report) + str(error) + repr(error)
    assert "network_requests" not in report


@pytest.mark.parametrize("code", [-(2**31), -1, 0, 1, 2**31 - 1])
def test_failure_report_preserves_exact_integer_boundaries(code):
    from custom_components.aqara_presence_lab.api.errors import ApplicationError
    from custom_components.aqara_presence_lab.api.validation import failure_report

    assert failure_report(ApplicationError(code))["application_code"] == code


@pytest.mark.parametrize(
    "code", [-(2**31) - 1, 2**31, 10**100, True, False, 1.0, "123", "SECRET", None, {}, []]
)
def test_failure_report_excludes_invalid_or_oversized_codes(code):
    from custom_components.aqara_presence_lab.api.errors import ApplicationError
    from custom_components.aqara_presence_lab.api.validation import failure_report

    error = ApplicationError(code)
    # Defense at the export boundary also handles tampered/internal attributes.
    error.code = code
    report = failure_report(error)
    assert "application_code" not in report
    assert "SECRET" not in json.dumps(report) + str(error) + repr(error)


@pytest.mark.parametrize("status", [100, 200, 201, 299, 429, 599])
def test_application_error_accepts_only_real_http_status_integer_range(status):
    from custom_components.aqara_presence_lab.api.errors import ApplicationError
    from custom_components.aqara_presence_lab.api.validation import failure_report

    error = ApplicationError(1, http_status=status)
    assert error.http_status == status
    assert failure_report(error)["http_status"] == status


@pytest.mark.parametrize(
    "status", [99, 600, 10**100, True, False, 200.0, "200", "SECRET", None, {}, []]
)
def test_failure_report_excludes_invalid_status_without_coercion(status):
    from custom_components.aqara_presence_lab.api.errors import ApplicationError
    from custom_components.aqara_presence_lab.api.validation import failure_report

    error = ApplicationError(1, http_status=status)
    assert error.http_status is None
    error.http_status = status
    assert "http_status" not in failure_report(error)


def test_local_parser_failure_never_invents_http_status_or_requests():
    from custom_components.aqara_presence_lab.api.errors import ApplicationError
    from custom_components.aqara_presence_lab.api.validation import failure_report

    with pytest.raises(ApplicationError) as caught:
        parse_response({"code": 987, "message": "SECRET"})
    report = failure_report(caught.value)
    assert report["application_code"] == 987
    assert "http_status" not in report and "network_requests" not in report


def test_failure_report_drops_untrusted_error_key_gate_and_profile():
    from custom_components.aqara_presence_lab.api.profiles import PROFILE
    from custom_components.aqara_presence_lab.api.validation import failure_report

    error = InvalidResponse("SECRET")
    error.error_key = "SECRET"
    report = failure_report(error, gate="SECRET", profile=replace(PROFILE, id="SECRET"))
    assert report == {"result": "failed", "error": "aqara_error", "production_allowed": False}

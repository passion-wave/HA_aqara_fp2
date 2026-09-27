import importlib.util
import json

import pytest

from tests.test_importers import har_text
from tests.transport_helpers import capture


@pytest.fixture
def lab():
    spec = importlib.util.spec_from_file_location("test_lab_cli", "scripts/lab.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_import_private_package_safe_preview(lab, tmp_path, capsys):
    source = tmp_path / "source.har"
    source.write_text(har_text())
    target = tmp_path / "package.json"
    assert lab.main(["import", "har", str(source), "--output", str(target)]) == 0
    output = capsys.readouterr().out
    assert "private-token" not in output and "private-device" not in output
    assert target.stat().st_mode & 0o777 == 0o600
    assert lab.main(["import", "har", str(source), "--output", str(target)]) == 1


def test_probe_requires_explicit_consent_without_network(lab, tmp_path, capsys):
    item, _ = capture()
    source = tmp_path / "package.json"
    source.write_text(json.dumps(item.package()))
    assert lab.main(["probe", str(source)]) == 1
    assert "private-token" not in capsys.readouterr().out
    assert not (tmp_path / "budget.json").exists()


def test_offline_fixture_cli_uses_same_api(lab, capsys):
    assert lab.main(["offline", "fixtures/trait_read.response.json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["network_requests"] == 0 and report["device_count"] == 2


def test_signature_mismatch_does_not_print_capture(lab, tmp_path, capsys):
    item, _ = capture()
    source = tmp_path / "package.json"
    source.write_text(json.dumps(item.package()))
    assert lab.main(["signature", str(source)]) == 1
    output = capsys.readouterr().out
    assert json.loads(output)["result"] == "not_matched"
    assert "private" not in output


def test_probe_cli_failure_reports_only_safe_numeric_metadata(lab, tmp_path, capsys, monkeypatch):
    from unittest.mock import AsyncMock

    errors = importlib.import_module("aqara_lab_api.errors")
    item, _ = capture()
    source = tmp_path / "package.json"
    source.write_text(json.dumps(item.package()))
    mock_probe = AsyncMock(side_effect=errors.ApplicationError(54321, "SECRET", http_status=201))
    monkeypatch.setattr(lab, "run_probe", mock_probe)
    assert lab.main(["probe", str(source), "--allow-live", "--step", "G3"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["application_code"] == 54321 and report["http_status"] == 201
    assert report["result"] == "failed" and report["error"] == "application_error"
    assert report["gate"] == "G3" and report["profile"] == lab.PROFILE.id
    assert report["production_allowed"] is False and "network_requests" not in report
    assert "SECRET" not in json.dumps(report) and "private-token" not in json.dumps(report)
    mock_probe.assert_awaited_once()


def test_probe_preflight_failure_does_not_claim_network_or_http_status(lab, tmp_path, capsys):
    item, _ = capture()
    source = tmp_path / "package.json"
    source.write_text(json.dumps(item.package()))
    assert lab.main(["probe", str(source)]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["gate"] == "G2" and report["production_allowed"] is False
    assert "http_status" not in report and "application_code" not in report
    assert "network_requests" not in report

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

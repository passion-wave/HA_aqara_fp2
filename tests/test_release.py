"""Exercise the actual distributable instead of relying on source layout alone."""

import json
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile

from scripts.build_release import build
from scripts.check_repository import check


def test_repository_contracts():
    assert check() == []


def test_release_is_reproducible_and_contains_only_runtime_files():
    output = build()
    first = output.read_bytes()
    assert build().read_bytes() == first
    assert output.with_suffix(".zip.sha256").read_text().startswith(sha256(first).hexdigest())
    with ZipFile(output) as archive:
        paths = archive.namelist()
        prefix = "custom_components/aqara_presence_lab/"
        assert all(p.startswith(prefix) for p in paths)
        assert all(
            "__pycache__" not in p and "/private/" not in p and "/captures/" not in p for p in paths
        )
        assert prefix + "brand/icon.png" in paths
        assert prefix + "LICENSE.txt" in paths
        assert prefix + "api/SleepRadar-LICENSE.txt" in paths
        assert prefix + "api/AqaraDevices-LICENSE.txt" in paths
        assert prefix + "api/resources.py" in paths
        assert prefix + "polling_probe.py" in paths
        assert prefix + "services.yaml" in paths
        manifest = json.loads(archive.read(prefix + "manifest.json"))
        assert manifest["domain"] == "aqara_presence_lab"
        assert manifest["version"] == "0.4.0b1"
        for name in paths:
            if name.endswith(".py"):
                compile(archive.read(name), name, "exec")
            elif name.endswith(".json"):
                json.loads(archive.read(name))


def test_published_fixtures_remain_pseudonymised():
    root = Path(__file__).parents[1]
    provenance = json.loads((root / "fixtures/provenance.json").read_text())
    assert provenance["wire_exact"] is False
    assert provenance["live_validated"] is False
    response = json.loads((root / "fixtures/trait_read.response.json").read_text())
    assert {d["deviceId"] for d in response["result"]} == {
        "lumi1.000000000001",
        "lumi1.000000000002",
    }
    assert response["requestId"] == "REDACTED_REQUEST_ID"

"""Check package contracts in addition to official Hassfest/HACS CI checks."""

import ast
import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "aqara_presence_lab"


def leaf_keys(value: dict, prefix: str = "") -> set[str]:
    """Compare translation coverage without comparing translated wording."""
    result = set()
    for key, item in value.items():
        path = f"{prefix}.{key}"
        if isinstance(item, dict):
            result |= leaf_keys(item, path)
        else:
            result.add(path)
    return result


def check() -> list[str]:
    """Return human-readable repository contract violations."""
    errors = []
    manifest = json.loads((COMPONENT / "manifest.json").read_text())
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    if manifest["version"] != project["project"]["version"]:
        errors.append("Manifest/project version mismatch")
    constants = ast.parse((COMPONENT / "const.py").read_text())
    versions = [
        node.value.value
        for node in constants.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "VERSION" for target in node.targets)
        and isinstance(node.value, ast.Constant)
    ]
    if versions != [manifest["version"]]:
        errors.append("Manifest/runtime version mismatch")
    if manifest.get("domain") != COMPONENT.name or not manifest.get("config_flow"):
        errors.append("Invalid domain/config-flow metadata")
    required = [
        "__init__.py",
        "config_flow.py",
        "coordinator.py",
        "sensor.py",
        "binary_sensor.py",
        "button.py",
        "diagnostics.py",
        "repairs.py",
        "credential_store.py",
        "api/account.py",
        "brand/icon.png",
    ]
    errors.extend(
        f"Missing runtime file: {name}" for name in required if not (COMPONENT / name).exists()
    )
    strings = json.loads((COMPONENT / "strings.json").read_text())
    for language in ("de", "en"):
        translated = json.loads((COMPONENT / "translations" / f"{language}.json").read_text())
        if leaf_keys(strings) != leaf_keys(translated):
            errors.append(f"Translation key mismatch: {language}")
    for path in (COMPONENT / "api").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("homeassistant"):
                errors.append(f"HA import in API core: {path.name}")
            if isinstance(node, ast.Import) and any(
                n.name.startswith("homeassistant") for n in node.names
            ):
                errors.append(f"HA import in API core: {path.name}")
    catalog = json.loads((ROOT / "config/trait_catalog.json").read_text())
    request = json.loads((ROOT / "fixtures/trait_read.request.json").read_text())
    paths = {t["path"] for d in request["devices"] for t in d["traits"]}
    if len(paths) != 31 or not all(path in json.dumps(catalog) for path in paths):
        errors.append("Trait catalog does not cover all 31 observed paths")
    return errors


if __name__ == "__main__":
    problems = check()
    print("\n".join(problems) if problems else "Repository contracts: OK")
    sys.exit(bool(problems))

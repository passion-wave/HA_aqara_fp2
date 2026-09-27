"""Repairs explain safe next steps without remote strings."""

import json
from pathlib import Path

from homeassistant.helpers import issue_registry as ir

from custom_components.aqara_presence_lab.const import DOMAIN
from custom_components.aqara_presence_lab.repairs import (
    ISSUES,
    async_clear_connection_issues,
    async_remove_issues,
    async_set_issue,
)


async def test_repair_lifecycle(hass, aqara_entry):
    for key in ISSUES:
        async_set_issue(hass, aqara_entry.entry_id, key)
    registry = ir.async_get(hass)
    assert len(registry.issues) == 5
    async_set_issue(hass, aqara_entry.entry_id, "synthetic-secret")
    assert len(registry.issues) == 5
    async_clear_connection_issues(hass, aqara_entry.entry_id)
    assert list(registry.issues) == [(DOMAIN, f"{aqara_entry.entry_id}_freshness_unverified")]
    async_remove_issues(hass, aqara_entry.entry_id)
    assert not registry.issues


def test_translations_are_complete_and_historical():
    folder = Path(__file__).parents[1] / "custom_components/aqara_presence_lab"
    en = json.loads((folder / "strings.json").read_text())
    de = json.loads((folder / "translations/de.json").read_text())
    assert en == json.loads((folder / "translations/en.json").read_text())

    def keys(value, prefix=""):
        result = set()
        if isinstance(value, dict):
            for key, child in value.items():
                result.add(f"{prefix}/{key}")
                result |= keys(child, f"{prefix}/{key}")
        return result

    assert keys(en) == keys(de)
    assert "25.09.2026" in de["config"]["step"]["offline"]["description"]
    assert "9 lx" in en["config"]["step"]["offline"]["description"]
    assert "110 lx" in en["config"]["step"]["offline"]["description"]

"""HA exports do not leak secrets or arbitrary metadata."""

import json

from custom_components.aqara_presence_lab.coordinator import AqaraCoordinator
from custom_components.aqara_presence_lab.diagnostics import async_get_config_entry_diagnostics


async def test_diagnostics_allowlist(hass, aqara_entry, aqara_client, aqara_snapshot):
    coordinator = AqaraCoordinator(hass, aqara_entry, aqara_client)
    coordinator.data = aqara_snapshot
    coordinator.connection_status = "retry_wait"
    coordinator.error_key = "cannot_connect"
    aqara_entry.runtime_data = coordinator
    result = await async_get_config_entry_diagnostics(hass, aqara_entry)
    serialized = json.dumps(result)
    for secret in (
        "synthetic-session-secret",
        "synthetic-user",
        "lumi1.000000000001",
        "lumi1.000000000002",
        "Praesenzsensor",
        "Raum A",
        "real2.",
    ):
        assert secret not in serialized
    assert result["connection"]["status"] == "retry_wait"
    assert result["device_count"] == 2
    assert result["devices"][0]["alias"] == "device_1"


async def test_diagnostics_on_unloaded_entry(hass, aqara_entry):
    result = await async_get_config_entry_diagnostics(hass, aqara_entry)
    assert result["running"] is False
    assert result["profile"]["validation_state"] == "candidate"
    assert "token" not in json.dumps(result)

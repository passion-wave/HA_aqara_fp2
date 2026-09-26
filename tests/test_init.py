"""Real HA setup/unload paths with a simulated, separately gated transport."""

from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er

from custom_components.aqara_presence_lab import async_migrate_entry
from custom_components.aqara_presence_lab.api.errors import AuthenticationRequired, TransportError
from custom_components.aqara_presence_lab.const import DOMAIN

INTEGRATION = "custom_components.aqara_presence_lab"


async def test_real_candidate_setup_stays_closed(hass, aqara_entry):
    aqara_entry.add_to_hass(hass)
    with patch(f"{INTEGRATION}.create_client") as client:
        assert not await hass.config_entries.async_setup(aqara_entry.entry_id)
    await hass.async_block_till_done()
    assert aqara_entry.state == ConfigEntryState.SETUP_ERROR
    client.assert_not_called()
    assert not hass.states.async_all()


async def test_setup_unload_reload_no_homekit_changes(hass, aqara_entry, aqara_client):
    aqara_entry.add_to_hass(hass)
    hass.states.async_set(
        "binary_sensor.existing_homekit_presence", "on", {"friendly_name": "Local presence"}
    )
    with (
        patch(f"{INTEGRATION}.require_production"),
        patch(f"{INTEGRATION}.create_client", return_value=aqara_client),
    ):
        assert await hass.config_entries.async_setup(aqara_entry.entry_id)
        await hass.async_block_till_done()
        assert aqara_entry.state == ConfigEntryState.LOADED
        coordinator = aqara_entry.runtime_data
        assert coordinator._stale_timer is not None
        entities_before = {
            entity.unique_id: entity.entity_id
            for entity in er.async_entries_for_config_entry(
                er.async_get(hass), aqara_entry.entry_id
            )
        }
        assert len(entities_before) == 15  # 4 account + 5 per device + 1 observed fall field
        assert hass.states.get("binary_sensor.existing_homekit_presence").state == "on"
        assert await hass.config_entries.async_reload(aqara_entry.entry_id)
        await hass.async_block_till_done()
        entities_after = {
            entity.unique_id: entity.entity_id
            for entity in er.async_entries_for_config_entry(
                er.async_get(hass), aqara_entry.entry_id
            )
        }
        assert entities_after == entities_before
        assert coordinator._closed
        assert coordinator._stale_timer is None
        new_coordinator = aqara_entry.runtime_data
        assert await hass.config_entries.async_unload(aqara_entry.entry_id)
        await hass.async_block_till_done()
        assert new_coordinator._closed
        assert new_coordinator._stale_timer is None
        assert new_coordinator._unsub_refresh is None
        assert hass.states.get("binary_sensor.existing_homekit_presence").state == "on"
    assert aqara_client.async_close.await_count == 2


@pytest.mark.parametrize(
    ("error", "state"),
    [
        (TransportError(), ConfigEntryState.SETUP_RETRY),
        (AuthenticationRequired(), ConfigEntryState.SETUP_ERROR),
    ],
)
async def test_startup_failure_classification(hass, aqara_entry, aqara_client, error, state):
    aqara_entry.add_to_hass(hass)
    aqara_client.async_validate_credentials.side_effect = error
    with (
        patch(f"{INTEGRATION}.require_production"),
        patch(f"{INTEGRATION}.create_client", return_value=aqara_client),
    ):
        assert not await hass.config_entries.async_setup(aqara_entry.entry_id)
        await hass.async_block_till_done()
    assert aqara_entry.state == state
    aqara_client.async_close.assert_awaited_once()
    aqara_client.async_read_traits.assert_not_called()


async def test_first_read_failure_is_retry_not_fake_cached_data(hass, aqara_entry, aqara_client):
    aqara_entry.add_to_hass(hass)
    aqara_client.async_read_traits.side_effect = TransportError()
    with (
        patch(f"{INTEGRATION}.require_production"),
        patch(f"{INTEGRATION}.create_client", return_value=aqara_client),
    ):
        assert not await hass.config_entries.async_setup(aqara_entry.entry_id)
    assert aqara_entry.state == ConfigEntryState.SETUP_RETRY
    assert not hass.states.async_all()
    aqara_client.async_close.assert_awaited_once()


async def test_schema_version_guard(hass, aqara_entry):
    assert await async_migrate_entry(hass, aqara_entry)
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    future = MockConfigEntry(domain=DOMAIN, version=2)
    assert not await async_migrate_entry(hass, future)
    future_minor = MockConfigEntry(domain=DOMAIN, version=1, minor_version=2)
    assert not await async_migrate_entry(hass, future_minor)


async def test_unclassified_access_denial_stops_setup_retry(hass, aqara_entry, aqara_client):
    from custom_components.aqara_presence_lab.api.errors import AccessDenied

    aqara_entry.add_to_hass(hass)
    aqara_client.async_read_traits.side_effect = AccessDenied()
    with (
        patch(f"{INTEGRATION}.require_production"),
        patch(f"{INTEGRATION}.create_client", return_value=aqara_client),
    ):
        assert not await hass.config_entries.async_setup(aqara_entry.entry_id)
    assert aqara_entry.state == ConfigEntryState.SETUP_ERROR
    aqara_client.async_close.assert_awaited_once()


async def test_invalid_local_session_requests_reauth(hass, aqara_entry):
    aqara_entry.add_to_hass(hass)
    with (
        patch(f"{INTEGRATION}.require_production"),
        patch(f"{INTEGRATION}.create_client", side_effect=AuthenticationRequired()),
    ):
        assert not await hass.config_entries.async_setup(aqara_entry.entry_id)
    assert aqara_entry.state == ConfigEntryState.SETUP_ERROR
    await hass.async_block_till_done()
    assert any(
        flow["context"]["source"] == "reauth" for flow in hass.config_entries.flow.async_progress()
    )

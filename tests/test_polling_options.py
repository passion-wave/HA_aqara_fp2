"""Polling options validate separate cadences without opening a cloud session."""

from unittest.mock import patch

import pytest
from homeassistant.data_entry_flow import FlowResultType, InvalidData

from custom_components.aqara_presence_lab.const import (
    CONF_INTERVAL,
    CONF_REQUEST_SPACING,
    CONF_RESOURCE_INTERVAL,
    CONF_SETTINGS_INTERVAL,
)

FLOW = "custom_components.aqara_presence_lab.config_flow"
VALID = {
    CONF_INTERVAL: 300,
    CONF_RESOURCE_INTERVAL: 60,
    CONF_SETTINGS_INTERVAL: 3600,
    CONF_REQUEST_SPACING: 30,
}


async def test_options_defaults_use_existing_interval_and_conservative_spacing(hass, aqara_entry):
    aqara_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        aqara_entry, data={**aqara_entry.data, CONF_INTERVAL: 600}
    )
    with patch(f"{FLOW}.async_create_client") as create:
        result = await hass.config_entries.options.async_init(aqara_entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    defaults = {key.schema: key.default() for key in result["data_schema"].schema}
    assert defaults == {**VALID, CONF_INTERVAL: 600}
    create.assert_not_called()


async def test_existing_options_win_over_entry_defaults(hass, aqara_entry):
    aqara_entry.add_to_hass(hass)
    configured = {
        CONF_INTERVAL: 900,
        CONF_RESOURCE_INTERVAL: 15,
        CONF_SETTINGS_INTERVAL: 7200,
        CONF_REQUEST_SPACING: 10,
    }
    hass.config_entries.async_update_entry(aqara_entry, options=configured)
    result = await hass.config_entries.options.async_init(aqara_entry.entry_id)
    defaults = {key.schema: key.default() for key in result["data_schema"].schema}
    assert defaults == configured


@pytest.mark.parametrize("spacing", [30, 15, 10, 5])
async def test_save_polling_options_preserves_credentials_and_unrelated_options(
    hass, aqara_entry, spacing
):
    aqara_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(aqara_entry, options={"existing_option": "preserve"})
    original_data = dict(aqara_entry.data)
    payload = {
        CONF_INTERVAL: 60.0,
        CONF_RESOURCE_INTERVAL: 10.0,
        CONF_SETTINGS_INTERVAL: 86400.0,
        CONF_REQUEST_SPACING: spacing,
    }
    with (
        patch(f"{FLOW}.async_create_client") as create,
        patch(f"{FLOW}.async_store_credentials") as store,
        patch(f"{FLOW}.async_save_session") as save,
    ):
        result = await hass.config_entries.options.async_init(aqara_entry.entry_id)
        result = await hass.config_entries.options.async_configure(result["flow_id"], payload)
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        "existing_option": "preserve",
        **{key: int(value) for key, value in payload.items()},
    }
    assert all(type(result["data"][key]) is int for key in payload)
    assert dict(aqara_entry.data) == original_data
    assert dict(aqara_entry.options) == result["data"]
    create.assert_not_called()
    store.assert_not_called()
    save.assert_not_called()


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        (CONF_INTERVAL, 59),
        (CONF_INTERVAL, 3601),
        (CONF_INTERVAL, 60.5),
        (CONF_INTERVAL, float("nan")),
        (CONF_INTERVAL, float("inf")),
        (CONF_INTERVAL, True),
        (CONF_RESOURCE_INTERVAL, 9),
        (CONF_RESOURCE_INTERVAL, 3601),
        (CONF_RESOURCE_INTERVAL, 10.5),
        (CONF_SETTINGS_INTERVAL, 899),
        (CONF_SETTINGS_INTERVAL, 86401),
        (CONF_SETTINGS_INTERVAL, 900.5),
        (CONF_REQUEST_SPACING, 0),
        (CONF_REQUEST_SPACING, 1),
        (CONF_REQUEST_SPACING, 6),
        (CONF_REQUEST_SPACING, True),
        (CONF_REQUEST_SPACING, "5"),
        (CONF_REQUEST_SPACING, None),
    ],
)
async def test_invalid_options_do_not_modify_entry(hass, aqara_entry, field, invalid):
    aqara_entry.add_to_hass(hass)
    original_data = dict(aqara_entry.data)
    with patch(f"{FLOW}.async_create_client") as create:
        result = await hass.config_entries.options.async_init(aqara_entry.entry_id)
        try:
            result = await hass.config_entries.options.async_configure(
                result["flow_id"], {**VALID, field: invalid}
            )
        except InvalidData as error:
            # HA rejects selector violations before calling the flow handler.
            assert field in error.schema_errors
        else:
            # Additional semantic validation rejects fractional/NaN intervals.
            assert result["type"] == FlowResultType.FORM
            assert field in result["errors"]
    assert not aqara_entry.options
    assert dict(aqara_entry.data) == original_data
    create.assert_not_called()


async def test_invalid_submission_can_be_corrected_without_restarting_flow(hass, aqara_entry):
    aqara_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(aqara_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**VALID, CONF_SETTINGS_INTERVAL: 900.5}
    )
    assert result["type"] == FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(result["flow_id"], VALID)
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"] == VALID

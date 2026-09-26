"""UI paths use simulated accounts; no mock is a live protocol approval."""

from dataclasses import replace
from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.aqara_presence_lab.api.errors import (
    AccessDenied,
    AccountMismatch,
    ApplicationError,
    AuthenticationRequired,
    InvalidResponse,
    ProtocolUnsupported,
    RateLimited,
    RequestRejected,
    TransportError,
)
from custom_components.aqara_presence_lab.api.models import AccountIdentity
from custom_components.aqara_presence_lab.const import DOMAIN

FLOW = "custom_components.aqara_presence_lab.config_flow"
INPUT = {
    "region": "EU",
    "token": "synthetic-session-secret",
    "user_id": "synthetic-user",
    "device_ids": "lumi1.000000000001\nlumi1.000000000002",
}


async def _live(hass):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == FlowResultType.MENU
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "live"}
    )


async def test_offline_preview_creates_nothing(hass):
    with patch(f"{FLOW}.create_client") as client:
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "offline"}
        )
        assert result["step_id"] == "offline"
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["reason"] == "offline_complete"
    assert not hass.config_entries.async_entries(DOMAIN)
    assert not hass.states.async_all()
    client.assert_not_called()


async def test_candidate_is_closed_before_credentials(hass):
    with patch(f"{FLOW}.create_client") as client:
        result = await _live(hass)
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "signature_unverified"
    client.assert_not_called()


async def test_complete_simulated_flow_and_duplicate(hass, aqara_client, aqara_entry):
    with (
        patch(f"{FLOW}.require_production"),
        patch(f"{FLOW}.create_client", return_value=aqara_client),
        patch("custom_components.aqara_presence_lab.async_setup_entry", return_value=True),
    ):
        result = await _live(hass)
        result = await hass.config_entries.flow.async_configure(result["flow_id"], INPUT)
        assert result["step_id"] == "devices"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"device_ids": ["lumi1.000000000001"], "poll_interval": 300}
        )
        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["data"]["device_ids"] == ["lumi1.000000000001"]
        assert result["result"].unique_id == aqara_entry.unique_id
        assert "password" not in result["data"]
        result = await _live(hass)
        result = await hass.config_entries.flow.async_configure(result["flow_id"], INPUT)
        assert result["reason"] == "already_configured"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1
    assert aqara_client.async_close.await_count == 2


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ProtocolUnsupported(), "signature_unverified"),
        (AccountMismatch(), "account_mismatch"),
        (AuthenticationRequired(), "auth_required"),
        (RateLimited(60), "rate_limited"),
        (TransportError(), "cannot_connect"),
        (AccessDenied(), "api_changed"),
        (ApplicationError(1234), "api_changed"),
        (InvalidResponse(), "api_changed"),
        (RequestRejected(), "api_changed"),
    ],
)
async def test_flow_failures_are_sanitized(hass, aqara_client, error, expected):
    aqara_client.async_validate_credentials.side_effect = error
    with (
        patch(f"{FLOW}.require_production"),
        patch(f"{FLOW}.create_client", return_value=aqara_client),
    ):
        result = await _live(hass)
        result = await hass.config_entries.flow.async_configure(result["flow_id"], INPUT)
    assert result["errors"] == {"base": expected}
    assert "synthetic-session-secret" not in str(result)
    aqara_client.async_close.assert_awaited_once()


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("token", " ", "missing_credentials"),
        ("user_id", " ", "missing_credentials"),
        ("device_ids", " ", "invalid_device_ids"),
        ("device_ids", "invalid id", "invalid_device_ids"),
    ],
)
async def test_bad_local_fields_do_not_call_cloud(hass, aqara_client, field, value, expected):
    with (
        patch(f"{FLOW}.require_production"),
        patch(f"{FLOW}.create_client", return_value=aqara_client) as create,
    ):
        result = await _live(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**INPUT, field: value}
        )
        assert expected in result["errors"].values()
        create.assert_not_called()


async def test_wrong_region_rejected_in_flow_method(hass):
    from custom_components.aqara_presence_lab.config_flow import AqaraConfigFlow

    flow = AqaraConfigFlow()
    flow.hass = hass
    result = await flow.async_step_credentials({**INPUT, "region": "US"})
    assert result["errors"] == {"region": "unsupported_region"}


async def test_identity_is_not_taken_from_user_input(hass, aqara_client):
    aqara_client.async_validate_credentials.return_value = AccountIdentity("EU", "other-user")
    with (
        patch(f"{FLOW}.require_production"),
        patch(f"{FLOW}.create_client", return_value=aqara_client),
    ):
        result = await _live(hass)
        result = await hass.config_entries.flow.async_configure(result["flow_id"], INPUT)
    assert result["errors"] == {"base": "account_mismatch"}
    aqara_client.async_read_traits.assert_not_awaited()


async def test_missing_device_results_no_entry(hass, aqara_client, aqara_snapshot):
    aqara_client.async_read_traits.return_value = replace(aqara_snapshot, devices={})
    with (
        patch(f"{FLOW}.require_production"),
        patch(f"{FLOW}.create_client", return_value=aqara_client),
    ):
        result = await _live(hass)
        result = await hass.config_entries.flow.async_configure(result["flow_id"], INPUT)
    assert result["reason"] == "no_selected_device_data"


async def test_reauth_same_entry_preserves_selection(hass, aqara_entry, aqara_client):
    aqara_entry.add_to_hass(hass)
    with (
        patch(f"{FLOW}.require_production"),
        patch(f"{FLOW}.create_client", return_value=aqara_client),
        patch.object(hass.config_entries, "async_reload", return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_REAUTH, "entry_id": aqara_entry.entry_id},
            data=aqara_entry.data,
        )
        assert result["step_id"] == "reauth_confirm"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"token": "replacement-secret", "user_id": "synthetic-user"}
        )
    assert result["reason"] == "reauth_successful"
    assert aqara_entry.data["token"] == "replacement-secret"
    assert len(aqara_entry.data["device_ids"]) == 2
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_reauth_cannot_change_account(hass, aqara_entry, aqara_client):
    aqara_entry.add_to_hass(hass)
    aqara_client.async_validate_credentials.return_value = AccountIdentity("EU", "other-user")
    with (
        patch(f"{FLOW}.require_production"),
        patch(f"{FLOW}.create_client", return_value=aqara_client),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "reauth", "entry_id": aqara_entry.entry_id},
            data=aqara_entry.data,
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"token": "replacement-secret", "user_id": "other-user"}
        )
    assert result["reason"] == "account_mismatch"
    assert aqara_entry.data["token"] == "synthetic-session-secret"


async def test_reauth_requires_existing_selection(hass, aqara_entry, aqara_client, aqara_snapshot):
    aqara_entry.add_to_hass(hass)
    aqara_client.async_read_traits.return_value = replace(aqara_snapshot, devices={})
    with (
        patch(f"{FLOW}.require_production"),
        patch(f"{FLOW}.create_client", return_value=aqara_client),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "reauth", "entry_id": aqara_entry.entry_id},
            data=aqara_entry.data,
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"token": "replacement-secret", "user_id": "synthetic-user"}
        )
    assert result["errors"] == {"base": "no_selected_device_data"}
    assert aqara_entry.data["token"] == "synthetic-session-secret"


async def test_reconfigure_same_entry(hass, aqara_entry, aqara_client):
    aqara_entry.add_to_hass(hass)
    with (
        patch(f"{FLOW}.require_production"),
        patch(f"{FLOW}.create_client", return_value=aqara_client),
        patch.object(hass.config_entries, "async_reload", return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "reconfigure", "entry_id": aqara_entry.entry_id}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"device_ids": "lumi1.000000000001", "poll_interval": 600}
        )
    assert result["reason"] == "reconfigure_successful"
    assert aqara_entry.data["device_ids"] == ["lumi1.000000000001"]
    assert aqara_entry.data["poll_interval"] == 600
    assert aqara_entry.data["token"] == "synthetic-session-secret"

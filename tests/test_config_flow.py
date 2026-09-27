"""Login UI and secret references
all transport calls are synthetic mocks."""

import asyncio
from dataclasses import replace
from unittest.mock import patch

import pytest
from homeassistant.data_entry_flow import FlowResultType

from custom_components.aqara_presence_lab.api.auth import SessionCredentials
from custom_components.aqara_presence_lab.api.errors import (
    AccessDenied,
    AccountMismatch,
    AuthenticationRequired,
    ProtocolUnsupported,
    RateLimited,
    TransportError,
)
from custom_components.aqara_presence_lab.api.models import AccountIdentity
from custom_components.aqara_presence_lab.const import DOMAIN
from custom_components.aqara_presence_lab.credential_store import CredentialStoreError

FLOW = "custom_components.aqara_presence_lab.config_flow"
INPUT = {
    "region": "EU",
    "account": "synthetic-account@example.invalid",
    "password": "synthetic-password-secret",
    "device_ids": "lumi1.000000000001\nlumi1.000000000002",
}
REFS = {
    "region": "EU",
    "account_secret": "existing_account",
    "password_secret": "existing_password",
    "device_ids": INPUT["device_ids"],
}


@pytest.fixture
def flow_client(aqara_client):
    async def factory(hass, **kwargs):
        async def read(*args):
            await kwargs["persist_session"](
                SessionCredentials("synthetic-session-secret", "synthetic-user")
            )
            return aqara_client.async_read_traits.return_value

        if aqara_client.async_read_traits.side_effect is None:
            aqara_client.async_read_traits.side_effect = read
        return aqara_client

    with (
        patch(f"{FLOW}.async_create_client", side_effect=factory) as create,
        patch(
            f"{FLOW}.async_store_credentials",
            return_value=("generated_account", "generated_password"),
        ) as store,
        patch(f"{FLOW}.async_save_session") as save,
        patch("custom_components.aqara_presence_lab.async_setup_entry", return_value=True),
    ):
        yield create, store, save


async def _login(hass, *, source="user", entry=None, mode="credentials"):
    context = {"source": source}
    if entry:
        context["entry_id"] = entry.entry_id
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context=context, data=entry.data if source == "reauth" else None
    )
    if source == "user":
        assert result["type"] == FlowResultType.MENU
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "live"}
        )
    elif source == "reauth":
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "live"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"allow_experimental_cloud": True}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": mode}
    )
    assert result["step_id"] == mode
    return result


async def _validate(hass, result, user_input):
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input)
    if result["type"] == FlowResultType.SHOW_PROGRESS:
        await hass.async_block_till_done()
        return await hass.config_entries.flow.async_configure(result["flow_id"])
    return result


async def test_offline_preview_creates_nothing(hass):
    with patch(f"{FLOW}.async_create_client") as client:
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "offline"}
        )
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["reason"] == "offline_complete"
    assert not hass.config_entries.async_entries(DOMAIN)
    client.assert_not_called()


async def test_consent_is_explicit(hass):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "live"}
    )
    with patch(f"{FLOW}.async_create_client") as client:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"allow_experimental_cloud": False}
        )
    assert result["errors"] == {"allow_experimental_cloud": "consent_required"}
    client.assert_not_called()


async def test_complete_login_only_stores_references_and_private_session(
    hass, flow_client, aqara_entry
):
    create, store, save = flow_client
    result = await _validate(hass, await _login(hass), INPUT)
    assert result["step_id"] == "devices"
    store.assert_not_called()
    save.assert_not_called()
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"device_ids": ["lumi1.000000000001"], "poll_interval": 300}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["result"].version == 2
    assert result["result"].unique_id == aqara_entry.unique_id
    assert result["data"]["account_secret"] == "generated_account"
    assert result["data"]["password_secret"] == "generated_password"
    assert result["data"]["allow_experimental_cloud"] is True
    assert not {"password", "account", "token"}.intersection(result["data"])
    assert "synthetic-password-secret" not in str(result)
    assert "synthetic-session-secret" not in str(result)
    store.assert_awaited_once_with(hass, INPUT["account"], INPUT["password"])
    assert save.call_args.args[1] == result["data"]["session_store_id"]
    assert create.call_args.kwargs["consent"] is True


async def test_existing_secret_names_are_preserved(hass, flow_client):
    result = await _validate(hass, await _login(hass, mode="secrets"), REFS)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"device_ids": ["lumi1.000000000001"], "poll_interval": 600}
    )
    assert result["data"]["account_secret"] == "existing_account"
    flow_client[1].assert_not_called()


async def test_duplicate_account_never_writes_secrets(hass, flow_client, aqara_entry):
    aqara_entry.add_to_hass(hass)
    result = await _validate(hass, await _login(hass), INPUT)
    assert result["reason"] == "already_configured"
    flow_client[1].assert_not_called()
    flow_client[2].assert_not_called()


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (AuthenticationRequired(), "auth_required"),
        (AccountMismatch(), "account_mismatch"),
        (RateLimited(180), "rate_limited"),
        (TransportError(), "cannot_connect"),
        (AccessDenied(), "api_changed"),
        (ProtocolUnsupported(), "protocol_unsupported"),
        (CredentialStoreError("secret_not_found"), "secret_not_found"),
    ],
)
async def test_validation_errors_are_sanitized(
    hass, flow_client, aqara_client, error, expected, caplog
):
    aqara_client.async_validate_credentials.side_effect = error
    result = await _validate(hass, await _login(hass), INPUT)
    assert result["step_id"] == "credentials"
    assert result["errors"] == {"base": expected}
    for secret in (INPUT["account"], INPUT["password"], "synthetic-session-secret"):
        assert secret not in str(result) + caplog.text
    flow_client[1].assert_not_called()
    flow_client[2].assert_not_called()
    aqara_client.async_close.assert_awaited_once()


async def test_partial_device_read_does_not_commit_login(
    hass, flow_client, aqara_client, aqara_snapshot
):
    aqara_client.async_read_traits.return_value = replace(aqara_snapshot, devices={})
    result = await _validate(hass, await _login(hass), INPUT)
    assert result["errors"] == {"base": "no_selected_device_data"}
    flow_client[1].assert_not_called()
    flow_client[2].assert_not_called()


async def test_cancelled_flow_cancels_progress_and_does_not_store(hass, flow_client, aqara_client):
    started = asyncio.Event()

    async def blocked():
        started.set()
        await asyncio.Event().wait()

    aqara_client.async_validate_credentials.side_effect = blocked
    result = await _login(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], INPUT)
    await started.wait()
    hass.config_entries.flow.async_abort(result["flow_id"])
    await hass.async_block_till_done()
    aqara_client.async_close.assert_awaited_once()
    flow_client[1].assert_not_called()
    flow_client[2].assert_not_called()


async def test_abandon_after_validated_read_writes_no_secrets(hass, flow_client):
    result = await _validate(hass, await _login(hass), INPUT)
    hass.config_entries.flow.async_abort(result["flow_id"])
    flow_client[1].assert_not_called()
    flow_client[2].assert_not_called()


async def test_reauth_same_account_preserves_identity_selection(hass, flow_client, aqara_entry):
    aqara_entry.add_to_hass(hass)
    old_id = aqara_entry.unique_id
    with patch.object(hass.config_entries, "async_reload", return_value=True):
        result = await _validate(
            hass,
            await _login(hass, source="reauth", entry=aqara_entry),
            {key: value for key, value in INPUT.items() if key != "device_ids"},
        )
    assert result["reason"] == "reauth_successful"
    assert aqara_entry.unique_id == old_id
    assert len(aqara_entry.data["device_ids"]) == 2
    assert aqara_entry.data["session_store_id"] == "synthetic-session-store"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1
    assert "token" not in aqara_entry.data


async def test_reauth_account_mismatch_preserves_old_refs(
    hass, flow_client, aqara_entry, aqara_client
):
    aqara_entry.add_to_hass(hass)
    aqara_client.async_validate_credentials.return_value = AccountIdentity("EU", "other-user")
    result = await _validate(
        hass,
        await _login(hass, source="reauth", entry=aqara_entry),
        {key: value for key, value in INPUT.items() if key != "device_ids"},
    )
    assert result["errors"] == {"base": "account_mismatch"}
    assert aqara_entry.data["account_secret"] == "aqara_test_account"
    aqara_client.async_read_traits.assert_not_called()
    flow_client[1].assert_not_called()
    flow_client[2].assert_not_called()


async def test_reconfigure_secret_refs_devices_interval(hass, flow_client, aqara_entry):
    aqara_entry.add_to_hass(hass)
    with patch.object(hass.config_entries, "async_reload", return_value=True):
        result = await _validate(
            hass, await _login(hass, source="reconfigure", entry=aqara_entry, mode="secrets"), REFS
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"device_ids": ["lumi1.000000000001"], "poll_interval": 900}
        )
    assert result["reason"] == "reconfigure_successful"
    assert aqara_entry.data["poll_interval"] == 900
    assert aqara_entry.data["device_ids"] == ["lumi1.000000000001"]
    assert aqara_entry.data["account_secret"] == "existing_account"


async def test_storage_failure_is_visible_not_silent_success(hass, flow_client):
    flow_client[1].side_effect = CredentialStoreError("credential_store_failed")
    result = await _validate(hass, await _login(hass), INPUT)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"device_ids": ["lumi1.000000000001"], "poll_interval": 300}
    )
    assert result["errors"] == {"base": "secret_store_failed"}
    assert not hass.config_entries.async_entries(DOMAIN)


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("account", " ", "missing_credentials"),
        ("password", "", "missing_credentials"),
        ("device_ids", " ", "invalid_device_ids"),
        ("device_ids", "invalid id", "invalid_device_ids"),
    ],
)
async def test_invalid_local_input_makes_no_request(hass, flow_client, field, value, expected):
    result = await _login(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**INPUT, field: value}
    )
    assert expected in result["errors"].values()
    flow_client[0].assert_not_called()


async def test_missing_secret_is_detected_before_transport_construction(hass):
    with (
        patch(
            f"{FLOW}.async_resolve_credentials",
            side_effect=CredentialStoreError("secret_not_found"),
        ),
        patch("custom_components.aqara_presence_lab.coordinator.AsyncAqaraClient") as transport,
    ):
        result = await _validate(hass, await _login(hass, mode="secrets"), REFS)
    assert result["errors"] == {"base": "secret_not_found"}
    transport.assert_not_called()


async def test_unexpected_exception_never_echoes_credentials_at_debug(
    hass, flow_client, aqara_client, caplog
):
    import logging

    caplog.set_level(logging.DEBUG)
    aqara_client.async_validate_credentials.side_effect = RuntimeError(
        INPUT["password"] + INPUT["account"] + "synthetic-session-secret"
    )
    result = await _validate(hass, await _login(hass), INPUT)
    assert result["errors"] == {"base": "unknown"}
    for secret in (INPUT["password"], INPUT["account"], "synthetic-session-secret"):
        assert secret not in caplog.text + str(result)


async def test_session_save_failure_keeps_old_entry_data(hass, flow_client, aqara_entry):
    aqara_entry.add_to_hass(hass)
    old_data = dict(aqara_entry.data)
    flow_client[2].side_effect = CredentialStoreError("session_store_failed")
    result = await _validate(
        hass,
        await _login(hass, source="reauth", entry=aqara_entry),
        {key: value for key, value in INPUT.items() if key != "device_ids"},
    )
    assert result["errors"] == {"base": "secret_store_failed"}
    assert dict(aqara_entry.data) == old_data


async def test_finalization_retry_reuses_one_private_session_file(hass, flow_client):
    flow_client[2].side_effect = [CredentialStoreError("session_store_failed"), None]
    result = await _validate(hass, await _login(hass), INPUT)
    confirmation = {"device_ids": ["lumi1.000000000001"], "poll_interval": 300}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], confirmation)
    assert result["errors"] == {"base": "secret_store_failed"}
    first_id = flow_client[2].call_args.args[1]
    result = await hass.config_entries.flow.async_configure(result["flow_id"], confirmation)
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["session_store_id"] == first_id
    assert [call.args[1] for call in flow_client[2].call_args_list] == [first_id, first_id]
    flow_client[1].assert_awaited_once()


async def test_abort_after_partial_session_write_cleans_only_new_flow_store(hass, flow_client):
    flow_client[2].side_effect = CredentialStoreError("session_store_failed")
    result = await _validate(hass, await _login(hass), INPUT)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"device_ids": ["lumi1.000000000001"], "poll_interval": 300}
    )
    store_id = flow_client[2].call_args.args[1]
    with patch(f"{FLOW}.async_delete_session") as delete:
        hass.config_entries.flow.async_abort(result["flow_id"])
        await hass.async_block_till_done()
    delete.assert_awaited_once_with(hass, store_id)


async def test_aborted_reauth_storage_error_does_not_delete_existing_session(
    hass, flow_client, aqara_entry
):
    aqara_entry.add_to_hass(hass)
    flow_client[2].side_effect = CredentialStoreError("session_store_failed")
    result = await _validate(
        hass,
        await _login(hass, source="reauth", entry=aqara_entry),
        {key: value for key, value in INPUT.items() if key != "device_ids"},
    )
    with patch(f"{FLOW}.async_delete_session") as delete:
        hass.config_entries.flow.async_abort(result["flow_id"])
        await hass.async_block_till_done()
    delete.assert_not_called()

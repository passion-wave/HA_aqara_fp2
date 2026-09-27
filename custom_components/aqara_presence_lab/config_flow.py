"""Consented account login with private storage and HA progress reporting."""

import asyncio
import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    import voluptuous as vol
else:
    import probatio as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult
from homeassistant.core import callback
from homeassistant.helpers import selector

from .api.auth import SessionCredentials
from .api.errors import (
    AccountMismatch,
    AqaraError,
    AuthenticationRequired,
    ProtocolUnsupported,
    RateLimited,
    TransportError,
)
from .api.models import AccountIdentity, AccountSnapshot
from .const import (
    CONF_ACCOUNT_SECRET,
    CONF_CONSENT,
    CONF_DEVICE_IDS,
    CONF_INTERVAL,
    CONF_PASSWORD_SECRET,
    CONF_REGION,
    CONF_SESSION_STORE_ID,
    CONF_USER_ID,
    DEFAULT_INTERVAL,
    DOMAIN,
    MAX_INTERVAL,
    MIN_INTERVAL,
)
from .coordinator import async_create_client
from .credential_store import (
    CredentialStoreError,
    async_delete_session,
    async_resolve_credentials,
    async_save_session,
    async_store_credentials,
)

_LOGGER = logging.getLogger(__name__)


def _device_ids(value: str) -> list[str]:
    result = list(
        dict.fromkeys(
            part.strip() for part in value.replace(",", "\n").splitlines() if part.strip()
        )
    )
    if (
        not result
        or len(result) > 100
        or any(len(item) > 256 or any(char.isspace() for char in item) for item in result)
    ):
        raise ValueError("invalid_device_ids")
    return result


class AqaraConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Login establishes identity; a complete read precedes any credential commit."""

    VERSION = 2
    MINOR_VERSION = 1

    def __init__(self) -> None:
        self._pending: dict[str, Any] = {}
        self._snapshot: AccountSnapshot | None = None
        self._identity: AccountIdentity | None = None
        self._credential_values: tuple[str, str] | None = None
        self._references: tuple[str, str] | None = None
        self._staged_session: SessionCredentials | None = None
        self._probe_task: asyncio.Task[None] | None = None
        self._flow_error: str | None = None
        self._source_step = "credentials"
        self._consent = False
        self._target_entry: ConfigEntry | None = None
        self._session_store_id = uuid4().hex
        self._session_write_attempted = False
        self._committed = False

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=["live", "offline"])

    async def async_step_offline(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_abort(reason="offline_complete")
        return self.async_show_form(step_id="offline", data_schema=vol.Schema({}))

    async def async_step_live(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input.get(CONF_CONSENT) is True:
                self._consent = True
                return await self.async_step_login_source()
            errors[CONF_CONSENT] = "consent_required"
        return self.async_show_form(
            step_id="live",
            data_schema=vol.Schema(
                {vol.Required(CONF_CONSENT, default=False): selector.BooleanSelector()}
            ),
            errors=errors,
        )

    async def async_step_login_source(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(step_id="login_source", menu_options=["credentials", "secrets"])

    def _login_schema(self, references: bool) -> vol.Schema:
        fields: dict[Any, Any] = {}
        if references:
            fields[vol.Required(CONF_ACCOUNT_SECRET)] = selector.TextSelector()
            fields[vol.Required(CONF_PASSWORD_SECRET)] = selector.TextSelector()
        else:
            fields[vol.Required("account")] = selector.TextSelector()
            fields[vol.Required("password")] = selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            )
        fields[vol.Required(CONF_REGION, default="EU")] = selector.SelectSelector(
            selector.SelectSelectorConfig(options=["EU"])
        )
        if self.source != config_entries.SOURCE_REAUTH:
            default = (
                "\n".join(self._target_entry.data[CONF_DEVICE_IDS]) if self._target_entry else ""
            )
            fields[vol.Required(CONF_DEVICE_IDS, default=default)] = selector.TextSelector(
                selector.TextSelectorConfig(multiline=True)
            )
        return vol.Schema(fields)

    async def async_step_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_login_form("credentials", user_input)

    async def async_step_secrets(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_login_form("secrets", user_input)

    async def _async_login_form(
        self, step: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        if not self._consent:
            return await self.async_step_live()
        self._source_step = step
        errors: dict[str, str] = {}
        if self._flow_error is not None:
            errors["base"] = self._flow_error
            self._flow_error = None
        if user_input is not None:
            try:
                if user_input.get(CONF_REGION) != "EU":
                    errors[CONF_REGION] = "unsupported_region"
                else:
                    ids = (
                        list(self._target_entry.data[CONF_DEVICE_IDS])
                        if self.source == config_entries.SOURCE_REAUTH and self._target_entry
                        else _device_ids(user_input[CONF_DEVICE_IDS])
                    )
                    if step == "credentials":
                        account, password = (
                            user_input.get("account", ""),
                            user_input.get("password", ""),
                        )
                        if not account.strip() or not password:
                            errors["base"] = "missing_credentials"
                        else:
                            self._credential_values = (account.strip(), password)
                            self._references = None
                    else:
                        refs = (
                            user_input.get(CONF_ACCOUNT_SECRET, "").strip(),
                            user_input.get(CONF_PASSWORD_SECRET, "").strip(),
                        )
                        if not all(refs):
                            errors["base"] = "missing_credentials"
                        else:
                            self._references = refs
                            self._credential_values = None
                    if not errors:
                        self._pending = {
                            CONF_REGION: "EU",
                            CONF_DEVICE_IDS: ids,
                            CONF_CONSENT: True,
                        }
                        self._probe_task = None
                        return await self.async_step_validate()
            except ValueError, KeyError:
                errors[CONF_DEVICE_IDS] = "invalid_device_ids"
        return self.async_show_form(
            step_id=step, data_schema=self._login_schema(step == "secrets"), errors=errors
        )

    async def _credentials(self) -> tuple[str, str]:
        if self._credential_values is not None:
            return self._credential_values
        if self._references is not None:
            return await async_resolve_credentials(self.hass, *self._references)
        raise AuthenticationRequired()

    async def _async_probe(self) -> None:
        self._staged_session = None
        self._snapshot = None
        self._identity = None
        self._flow_error = None

        async def stage(session: SessionCredentials) -> None:
            self._staged_session = session

        client = None
        try:
            client = await async_create_client(
                self.hass,
                credential_loader=self._credentials,
                persist_session=stage,
                expected_user_id=self._target_entry.data.get(CONF_USER_ID)
                if self._target_entry
                else None,
                consent=self._consent,
            )
            self._identity = await client.async_validate_credentials()
            self.async_update_progress(0.4)
            if self._identity.area != "EU":
                raise AccountMismatch()
            if (
                self._target_entry is not None
                and self._identity.account_key != self._target_entry.unique_id
            ):
                raise AccountMismatch()
            self._snapshot = await client.async_read_traits(tuple(self._pending[CONF_DEVICE_IDS]))
            self.async_update_progress(1.0)
            if not _selection_complete(self._snapshot, self._pending[CONF_DEVICE_IDS]):
                self._flow_error = "no_selected_device_data"
            if self._staged_session is None and self._flow_error is None:
                self._flow_error = "auth_required"
        except (AqaraError, CredentialStoreError) as err:
            self._flow_error = _error_key(err)
        except Exception:
            # UI/log output never includes exception strings or user-supplied fields.
            _LOGGER.error("Aqara login validation failed unexpectedly")
            self._flow_error = "unknown"
        finally:
            if client is not None:
                await client.async_close()
            if self._flow_error:
                self._credential_values = None
                self._staged_session = None

    async def async_step_validate(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if self._probe_task is None:
            self._probe_task = self.hass.async_create_task(
                self._async_probe(), name="Aqara login and read validation"
            )
        if self._probe_task.done():
            self._probe_task.result()
            return self.async_show_progress_done(next_step_id="validation_complete")
        return self.async_show_progress(
            step_id="validate", progress_action="login_and_read", progress_task=self._probe_task
        )

    async def async_step_validation_complete(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if self._flow_error is not None:
            return await self._async_login_form(self._source_step, None)
        assert self._identity is not None
        await self.async_set_unique_id(self._identity.account_key)
        if self._target_entry is not None:
            self._abort_if_unique_id_mismatch(reason="account_mismatch")
        else:
            self._abort_if_unique_id_configured()
        if self.source == config_entries.SOURCE_REAUTH:
            return await self._async_finish()
        return await self.async_step_devices()

    async def async_step_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._snapshot is not None
        devices = {
            device_id: device
            for device_id, device in self._snapshot.devices.items()
            if device_id in self._pending[CONF_DEVICE_IDS] and device.available
        }
        if not devices:
            return self.async_abort(reason="no_selected_device_data")
        errors: dict[str, str] = {}
        if user_input is not None:
            selected = user_input.get(CONF_DEVICE_IDS, [])
            interval = user_input.get(CONF_INTERVAL, DEFAULT_INTERVAL)
            if (
                not selected
                or not isinstance(selected, list)
                or any(item not in devices for item in selected)
            ):
                errors[CONF_DEVICE_IDS] = "no_selected_device_data"
            elif (
                isinstance(interval, bool)
                or not isinstance(interval, (int, float))
                or not MIN_INTERVAL <= interval <= MAX_INTERVAL
            ):
                errors[CONF_INTERVAL] = "invalid_interval"
            else:
                self._pending[CONF_DEVICE_IDS] = list(dict.fromkeys(selected))
                self._pending[CONF_INTERVAL] = int(interval)
                return await self._async_finish()
        if self._flow_error:
            errors["base"] = self._flow_error
            self._flow_error = None
        options: list[selector.SelectOptionDict] = [
            {"value": device_id, "label": device.name or "Aqara FP2"}
            for device_id, device in devices.items()
        ]
        default_interval = (
            self._target_entry.data.get(CONF_INTERVAL, DEFAULT_INTERVAL)
            if self._target_entry
            else DEFAULT_INTERVAL
        )
        return self.async_show_form(
            step_id="devices",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE_IDS, default=list(devices)): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=options, multiple=True)
                    ),
                    vol.Required(CONF_INTERVAL, default=default_interval): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=MIN_INTERVAL,
                            max=MAX_INTERVAL,
                            step=1,
                            mode=selector.NumberSelectorMode.BOX,
                            unit_of_measurement="s",
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def _async_finish(self) -> ConfigFlowResult:
        assert self._identity is not None and self._staged_session is not None
        try:
            if self._credential_values is not None:
                # Final confirmation only: cancelled flows have written no passwords.
                self._references = await async_store_credentials(
                    self.hass, *self._credential_values
                )
                self._credential_values = None
            assert self._references is not None
            store_id = (
                self._target_entry.data.get(CONF_SESSION_STORE_ID, self._session_store_id)
                if self._target_entry
                else self._session_store_id
            )
            self._session_write_attempted = True
            await async_save_session(self.hass, store_id, self._staged_session)
        except CredentialStoreError as err:
            self._flow_error = _error_key(err)
            if self.source == config_entries.SOURCE_REAUTH:
                return await self._async_login_form(self._source_step, None)
            return await self.async_step_devices()
        data = {
            **self._pending,
            CONF_USER_ID: self._identity.user_id,
            CONF_ACCOUNT_SECRET: self._references[0],
            CONF_PASSWORD_SECRET: self._references[1],
            CONF_SESSION_STORE_ID: store_id,
            CONF_INTERVAL: self._pending.get(
                CONF_INTERVAL,
                self._target_entry.data.get(CONF_INTERVAL, DEFAULT_INTERVAL)
                if self._target_entry
                else DEFAULT_INTERVAL,
            ),
        }
        self._committed = True
        _LOGGER.info("Aqara account and selected device access validated")
        if self._target_entry is not None:
            return self.async_update_reload_and_abort(
                self._target_entry,
                data=data,
                reason="reauth_successful"
                if self.source == config_entries.SOURCE_REAUTH
                else "reconfigure_successful",
            )
        return self.async_create_entry(title="Aqara Presence Lab (EU)", data=data)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        self._target_entry = self._get_reauth_entry()
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return await self.async_step_live()
        return self.async_show_form(step_id="reauth_confirm", data_schema=vol.Schema({}))

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._target_entry = self._get_reconfigure_entry()
        return await self.async_step_live(user_input)

    @callback
    def async_remove(self) -> None:
        """Home Assistant also cancels a pending progress task when removed."""
        self._credential_values = None
        self._staged_session = None
        self._snapshot = None
        if self._session_write_attempted and not self._committed and self._target_entry is None:
            # A filesystem error can happen after atomic replacement. Remove an
            # unreferenced new-flow token, but never touch an existing account.
            self.hass.async_create_task(
                self._async_cleanup_session(), name="Aqara abandoned session cleanup"
            )

    async def _async_cleanup_session(self) -> None:
        try:
            await async_delete_session(self.hass, self._session_store_id)
        except CredentialStoreError:
            _LOGGER.warning("Aqara abandoned session cleanup could not complete")


def _selection_complete(snapshot: AccountSnapshot, selected: list[str]) -> bool:
    return all(item in snapshot.devices and snapshot.devices[item].available for item in selected)


def _error_key(error: Exception) -> str:
    if isinstance(error, CredentialStoreError):
        return (
            "secret_not_found" if error.error_key == "secret_not_found" else "secret_store_failed"
        )
    if isinstance(error, AccountMismatch):
        return "account_mismatch"
    if isinstance(error, AuthenticationRequired):
        return "auth_required"
    if isinstance(error, RateLimited):
        return "rate_limited"
    if isinstance(error, TransportError):
        return "cannot_connect"
    if isinstance(error, ProtocolUnsupported):
        return "protocol_unsupported"
    return "api_changed"

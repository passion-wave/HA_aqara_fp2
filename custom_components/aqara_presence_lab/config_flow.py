"""Explicit offline preview and evidence-gated, same-account configuration."""

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # HA 2026.9 annotates Schema as voluptuous; runtime HA replaces it with
    # probatio. Follow its public runtime API and its static annotation here.
    import voluptuous as vol
else:
    import probatio as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers import selector

from .api.errors import (
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
from .api.models import AccountIdentity, AccountSnapshot
from .api.profiles import PROFILE, require_production
from .const import (
    CONF_DEVICE_IDS,
    CONF_INTERVAL,
    CONF_REGION,
    CONF_TOKEN,
    CONF_USER_ID,
    DEFAULT_INTERVAL,
    DOMAIN,
    MAX_INTERVAL,
    MIN_INTERVAL,
)
from .coordinator import create_client


def _device_ids(value: str) -> list[str]:
    """Manual selection is explicit; no unverified discovery API is called."""
    device_ids = list(
        dict.fromkeys(
            part.strip() for part in value.replace(",", "\n").splitlines() if part.strip()
        )
    )
    if (
        not device_ids
        or len(device_ids) > 100
        or any(len(value) > 256 or any(char.isspace() for char in value) for value in device_ids)
    ):
        raise ValueError("invalid_device_ids")
    return device_ids


def _credentials_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_REGION, default="EU"): selector.SelectSelector(
                selector.SelectSelectorConfig(options=["EU"])
            ),
            vol.Required(CONF_TOKEN): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
            vol.Required(CONF_USER_ID): selector.TextSelector(),
            vol.Required(CONF_DEVICE_IDS): selector.TextSelector(
                selector.TextSelectorConfig(multiline=True)
            ),
        }
    )


class AqaraConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Never convert an unverified client-side user ID into account evidence."""

    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        self._pending: dict[str, Any] = {}
        self._snapshot: AccountSnapshot | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=["offline", "live"])

    async def async_step_offline(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Historical examples are explanatory UI only, never a config entry."""
        if user_input is not None:
            return self.async_abort(reason="offline_complete")
        return self.async_show_form(step_id="offline", data_schema=vol.Schema({}))

    async def async_step_live(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Fail closed before accepting secrets when no reviewed profile exists."""
        try:
            require_production(PROFILE)
        except ProtocolUnsupported:
            return self.async_abort(reason="signature_unverified")
        return await self.async_step_credentials()

    async def _async_validate(
        self, data: dict[str, Any]
    ) -> tuple[AccountIdentity, AccountSnapshot]:
        require_production(PROFILE)
        client = create_client(self.hass, data)
        try:
            identity = await client.async_validate_credentials()
            if identity.area != "EU" or identity.user_id != data[CONF_USER_ID]:
                raise AccountMismatch()
            snapshot = await client.async_read_traits(tuple(data[CONF_DEVICE_IDS]), PROFILE)
            return identity, snapshot
        finally:
            await client.async_close()

    async def async_step_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = dict(user_input)
            try:
                if data[CONF_REGION] != "EU":
                    errors[CONF_REGION] = "unsupported_region"
                elif not data[CONF_TOKEN].strip() or not data[CONF_USER_ID].strip():
                    errors["base"] = "missing_credentials"
                else:
                    data[CONF_DEVICE_IDS] = _device_ids(data[CONF_DEVICE_IDS])
                    identity, snapshot = await self._async_validate(data)
                    await self.async_set_unique_id(identity.account_key)
                    self._abort_if_unique_id_configured()
                    self._pending = data
                    self._snapshot = snapshot
                    return await self.async_step_devices()
            except ValueError:
                errors[CONF_DEVICE_IDS] = "invalid_device_ids"
            except (
                ProtocolUnsupported,
                AccountMismatch,
                AuthenticationRequired,
                RateLimited,
                TransportError,
                AccessDenied,
                ApplicationError,
                InvalidResponse,
                RequestRejected,
            ) as err:
                errors["base"] = _error_key(err)
        return self.async_show_form(
            step_id="credentials", data_schema=_credentials_schema(), errors=errors
        )

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
                or any(device_id not in devices for device_id in selected)
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
                return self.async_create_entry(title="Aqara Presence Lab (EU)", data=self._pending)
        options: list[selector.SelectOptionDict] = [
            {"value": device_id, "label": device.name or "Aqara FP2"}
            for device_id, device in devices.items()
        ]
        schema = vol.Schema(
            {
                vol.Required(CONF_DEVICE_IDS, default=list(devices)): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=options, multiple=True)
                ),
                vol.Required(CONF_INTERVAL, default=DEFAULT_INTERVAL): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=MIN_INTERVAL,
                        max=MAX_INTERVAL,
                        step=1,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="s",
                    )
                ),
            }
        )
        return self.async_show_form(step_id="devices", data_schema=schema, errors=errors)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            entry = self._get_reauth_entry()
            data = {**entry.data, **user_input}
            if not data[CONF_TOKEN].strip() or not data[CONF_USER_ID].strip():
                errors["base"] = "missing_credentials"
            else:
                try:
                    identity, snapshot = await self._async_validate(data)
                    await self.async_set_unique_id(identity.account_key)
                    self._abort_if_unique_id_mismatch(reason="account_mismatch")
                    if not _selection_complete(snapshot, data[CONF_DEVICE_IDS]):
                        errors["base"] = "no_selected_device_data"
                    else:
                        return self.async_update_reload_and_abort(
                            entry,
                            data_updates={
                                CONF_TOKEN: data[CONF_TOKEN],
                                CONF_USER_ID: data[CONF_USER_ID],
                            },
                        )
                except (
                    ProtocolUnsupported,
                    AccountMismatch,
                    AuthenticationRequired,
                    RateLimited,
                    TransportError,
                    AccessDenied,
                    ApplicationError,
                    InvalidResponse,
                    RequestRejected,
                ) as err:
                    errors["base"] = _error_key(err)
        schema = vol.Schema(
            {
                vol.Required(CONF_TOKEN): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
                vol.Required(CONF_USER_ID): selector.TextSelector(),
            }
        )
        return self.async_show_form(step_id="reauth_confirm", data_schema=schema, errors=errors)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                selected = _device_ids(user_input[CONF_DEVICE_IDS])
                interval = user_input[CONF_INTERVAL]
                if (
                    isinstance(interval, bool)
                    or not isinstance(interval, (int, float))
                    or not MIN_INTERVAL <= interval <= MAX_INTERVAL
                ):
                    errors[CONF_INTERVAL] = "invalid_interval"
                else:
                    data = {**entry.data, CONF_DEVICE_IDS: selected, CONF_INTERVAL: int(interval)}
                    identity, snapshot = await self._async_validate(data)
                    await self.async_set_unique_id(identity.account_key)
                    self._abort_if_unique_id_mismatch(reason="account_mismatch")
                    if not _selection_complete(snapshot, selected):
                        errors["base"] = "no_selected_device_data"
                    else:
                        return self.async_update_reload_and_abort(
                            entry,
                            data_updates={CONF_DEVICE_IDS: selected, CONF_INTERVAL: int(interval)},
                            reason="reconfigure_successful",
                        )
            except ValueError:
                errors[CONF_DEVICE_IDS] = "invalid_device_ids"
            except (
                ProtocolUnsupported,
                AccountMismatch,
                AuthenticationRequired,
                RateLimited,
                TransportError,
                AccessDenied,
                ApplicationError,
                InvalidResponse,
                RequestRejected,
            ) as err:
                errors["base"] = _error_key(err)
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_DEVICE_IDS, default="\n".join(entry.data[CONF_DEVICE_IDS])
                ): selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
                vol.Required(
                    CONF_INTERVAL, default=entry.data.get(CONF_INTERVAL, DEFAULT_INTERVAL)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=MIN_INTERVAL,
                        max=MAX_INTERVAL,
                        step=1,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="s",
                    )
                ),
            }
        )
        return self.async_show_form(step_id="reconfigure", data_schema=schema, errors=errors)


def _selection_complete(snapshot: AccountSnapshot, selected: list[str]) -> bool:
    return all(
        device_id in snapshot.devices and snapshot.devices[device_id].available
        for device_id in selected
    )


def _error_key(error: Exception) -> str:
    """Never interpolate a server body, exception text or credentials into UI."""
    if isinstance(error, ProtocolUnsupported):
        return "signature_unverified"
    if isinstance(error, AccountMismatch):
        return "account_mismatch"
    if isinstance(error, AuthenticationRequired):
        return "auth_required"
    if isinstance(error, RateLimited):
        return "rate_limited"
    if isinstance(error, TransportError):
        return "cannot_connect"
    return "api_changed"

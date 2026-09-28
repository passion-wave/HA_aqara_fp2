"""Aqara Presence Lab: complementary read-only cloud observations."""

from uuid import uuid4

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr

from .api.errors import (
    AccountMismatch,
    AuthenticationRequired,
    InvalidResponse,
    ProtocolUnsupported,
    RequestRejected,
    TransportError,
)
from .api.models import AccountIdentity
from .const import (
    CONF_CONSENT,
    CONF_DEVICE_IDS,
    CONF_INTERVAL,
    CONF_REGION,
    CONF_SESSION_STORE_ID,
    CONF_USER_ID,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import AqaraCoordinator, async_create_entry_client
from .credential_store import CredentialStoreError, async_delete_session
from .polling_probe import async_register_probe_service
from .repairs import async_remove_issues, async_set_issue

type AqaraConfigEntry = ConfigEntry[AqaraCoordinator]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register account-scoped administrative diagnostics actions."""
    async_register_probe_service(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: AqaraConfigEntry) -> bool:
    """Validate identity, obtain fresh data and set up shared entity platforms."""
    identity = AccountIdentity(entry.data.get(CONF_REGION, "EU"), entry.data[CONF_USER_ID])
    try:
        client = await async_create_entry_client(hass, entry)
    except (AuthenticationRequired, CredentialStoreError, AccountMismatch) as err:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN, translation_key="auth_required"
        ) from err
    except ProtocolUnsupported as err:
        raise ConfigEntryError(
            translation_domain=DOMAIN, translation_key="protocol_unsupported"
        ) from err
    coordinator = AqaraCoordinator(hass, entry, client)
    try:
        validated_identity = await client.async_validate_credentials()
        if (
            validated_identity.account_key != identity.account_key
            or entry.unique_id != identity.account_key
        ):
            raise AccountMismatch()
        await coordinator.async_config_entry_first_refresh()
    except (AuthenticationRequired, CredentialStoreError) as err:
        await coordinator.async_shutdown()
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN, translation_key="auth_required"
        ) from err
    except (ProtocolUnsupported, AccountMismatch) as err:
        await coordinator.async_shutdown()
        async_set_issue(hass, entry.entry_id, "protocol_unsupported")
        raise ConfigEntryError(
            translation_domain=DOMAIN, translation_key="protocol_unsupported"
        ) from err
    except TransportError as err:
        await coordinator.async_shutdown()
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN, translation_key="cannot_connect"
        ) from err
    except (RequestRejected, InvalidResponse) as err:
        await coordinator.async_shutdown()
        raise ConfigEntryError(translation_domain=DOMAIN, translation_key="api_changed") from err
    except BaseException:
        await coordinator.async_shutdown()
        raise
    entry.runtime_data = coordinator
    # The 2026.9 device API links children through a registry ID, not a tuple.
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, identity.account_key)},
        manufacturer="Aqara",
        name="Aqara Cloud",
        model="Presence Lab account",
    )
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        await coordinator.async_shutdown()
        raise
    coordinator.async_start_liveness()
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AqaraConfigEntry) -> bool:
    """Do not close a still active entry when a platform declines unload."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    await entry.runtime_data.async_shutdown()
    return True


async def async_reload_entry(hass: HomeAssistant, entry: AqaraConfigEntry) -> None:
    """Apply options through HA's normal unload/setup lifecycle."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove only this entry's explanatory repairs."""
    async_remove_issues(hass, entry.entry_id)
    if store_id := entry.data.get(CONF_SESSION_STORE_ID):
        await async_delete_session(hass, store_id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Replace legacy token entries with a same-account login requirement."""
    if entry.version == 2:
        return entry.minor_version == 1
    if entry.version != 1 or entry.minor_version != 1:
        return False
    data = {
        key: entry.data[key]
        for key in (CONF_REGION, CONF_USER_ID, CONF_DEVICE_IDS, CONF_INTERVAL)
        if key in entry.data
    }
    if not data.get(CONF_USER_ID) or not data.get(CONF_DEVICE_IDS):
        return False
    data.update({CONF_CONSENT: False, CONF_SESSION_STORE_ID: uuid4().hex})
    # Old user IDs remain an expected identity, never server identity evidence.
    # Reauth requires login to return the same ID before it updates the entry.
    hass.config_entries.async_update_entry(entry, data=data, version=2, minor_version=1)
    return True

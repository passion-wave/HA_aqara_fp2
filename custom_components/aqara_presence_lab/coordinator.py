"""One cloud batch per account, with independent local liveness checking."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import datetime, timedelta
from hashlib import sha256
from time import monotonic

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api.account import ManagedAqaraClient
from .api.auth import SessionCredentials
from .api.client import AsyncAqaraClient
from .api.errors import (
    AccessDenied,
    AccountMismatch,
    ApplicationError,
    AqaraError,
    AuthenticationRequired,
    InvalidResponse,
    ProtocolUnsupported,
    RateLimited,
    RequestRejected,
    SessionPersistenceError,
    SignatureRejected,
    TransportError,
)
from .api.models import AccountIdentity, AccountSnapshot
from .api.profiles import PROFILE
from .api.rate_limit import AccountRateLimiter
from .api.resources import DeviceResources
from .api.signing import CandidateSigner
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
    REFRESH_COOLDOWN,
    TRANSPORT_TIMEOUT,
)
from .credential_store import (
    CredentialStoreError,
    async_load_session,
    async_resolve_credentials,
    async_save_session,
)
from .repairs import async_clear_connection_issues, async_set_issue

_LOGGER = logging.getLogger(__name__)


async def async_create_client(
    hass: HomeAssistant,
    *,
    credential_loader: Callable[[], Awaitable[tuple[str, str]]],
    persist_session: Callable[[SessionCredentials], Awaitable[None]],
    initial_session: SessionCredentials | None = None,
    expected_user_id: str | None = None,
    consent: bool = False,
) -> ManagedAqaraClient:
    """Share account limits across flow, setup retries, reload and token renewal."""
    if not consent or PROFILE.app_key is None:
        raise AuthenticationRequired()
    account, _ = await credential_loader()
    limiter_key = sha256(f"EU:login:{account.casefold()}".encode()).hexdigest()
    limiters = hass.data.setdefault(DOMAIN, {}).setdefault("account_limiters", {})
    limiter = limiters.setdefault(limiter_key, AccountRateLimiter())
    transport = AsyncAqaraClient(
        async_get_clientsession(hass),
        None,
        CandidateSigner(PROFILE.app_key, app_id=PROFILE.app_id),
        profile=PROFILE,
        limiter=limiter,
        live_consent=True,
    )
    return ManagedAqaraClient(
        transport,
        credential_loader,
        persist_session,
        initial_session=initial_session,
        expected_user_id=expected_user_id,
        consent=True,
    )


async def async_create_entry_client(hass: HomeAssistant, entry: ConfigEntry) -> ManagedAqaraClient:
    """Resolve secret references locally; tokens live in a separate private store."""
    data = entry.data
    if data.get(CONF_CONSENT) is not True or not all(
        data.get(key) for key in (CONF_ACCOUNT_SECRET, CONF_PASSWORD_SECRET, CONF_SESSION_STORE_ID)
    ):
        raise AuthenticationRequired()

    async def credentials() -> tuple[str, str]:
        return await async_resolve_credentials(
            hass, data[CONF_ACCOUNT_SECRET], data[CONF_PASSWORD_SECRET]
        )

    async def persist(session: SessionCredentials) -> None:
        await async_save_session(hass, data[CONF_SESSION_STORE_ID], session)

    return await async_create_client(
        hass,
        credential_loader=credentials,
        persist_session=persist,
        initial_session=await async_load_session(hass, data[CONF_SESSION_STORE_ID]),
        expected_user_id=data[CONF_USER_ID],
        consent=True,
    )


class AqaraCoordinator(DataUpdateCoordinator[AccountSnapshot]):
    """Fetch selected devices together and retain readable connection state."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: ManagedAqaraClient,
        *,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        interval = entry.options.get(CONF_INTERVAL, entry.data.get(CONF_INTERVAL, DEFAULT_INTERVAL))
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=interval),
            request_refresh_debouncer=Debouncer(
                hass, _LOGGER, cooldown=REFRESH_COOLDOWN, immediate=True
            ),
            always_update=True,
        )
        self.client = client
        self.entry = entry
        self.identity = AccountIdentity(entry.data.get(CONF_REGION, "EU"), entry.data[CONF_USER_ID])
        self.device_ids = tuple(entry.data[CONF_DEVICE_IDS])
        self.connection_status = "unconfigured"
        self.last_successful_read: datetime | None = None
        self.error_key: str | None = None
        self.transport_stale = False
        self._clock = clock
        self._last_received: float | None = None
        self._last_attempt: float | None = None
        self._max_receive_age = 2 * interval + TRANSPORT_TIMEOUT
        self._stale_timer: asyncio.TimerHandle | None = None
        self._inflight: asyncio.Task[AccountSnapshot] | None = None
        self._closed = False
        self._terminal_error: str | None = None
        self.successful_reads = 0
        self.failed_reads = 0
        self.resource_data: dict[tuple[str, str], DeviceResources] = {}
        self.resource_status: dict[tuple[str, str], str] = {}
        self.resource_errors: dict[tuple[str, str], str] = {}
        self.resource_received_monotonic: dict[tuple[str, str], float] = {}
        self.resource_successful_reads = 0
        self.resource_failed_reads = 0
        self._resource_task: asyncio.Task[None] | None = None
        self._resource_cursor = 0
        self._resource_max_age = max(
            self._max_receive_age,
            interval
            + len(self.device_ids) * 4 * max(interval, REFRESH_COOLDOWN + TRANSPORT_TIMEOUT),
        )

    @callback
    def async_start_liveness(self) -> None:
        """Schedule a local-only check, including while a request is stuck."""
        if self._closed or self._stale_timer is not None:
            return
        self._stale_timer = self.hass.loop.call_later(30, self._async_check_liveness)

    @callback
    def _async_check_liveness(self) -> None:
        self._stale_timer = None
        if self._closed:
            return
        changed = False
        if (
            self._last_received is not None
            and self._clock() - self._last_received > self._max_receive_age
        ):
            if not self.transport_stale:
                self.transport_stale = True
                if self._terminal_error is None:
                    self.connection_status = "retry_wait"
                    self.error_key = "cannot_connect"
                    async_set_issue(self.hass, self.entry.entry_id, "cannot_connect")
                changed = True
        for key, received in self.resource_received_monotonic.items():
            if self._clock() - received > self._resource_max_age and self.resource_status.get(
                key
            ) in ("ready", "updating"):
                self.resource_status[key] = "stale"
                changed = True
        if changed:
            self.async_update_listeners()
        self.async_start_liveness()

    async def _async_update_data(self) -> AccountSnapshot:
        """Coalesce concurrent refreshes; never multiply client retry loops."""
        if self._closed:
            raise UpdateFailed(translation_domain=DOMAIN, translation_key="cannot_connect")
        if self._terminal_error is not None:
            error_type = (
                ConfigEntryAuthFailed
                if self.connection_status == "reauth_required"
                else ConfigEntryError
            )
            raise error_type(translation_domain=DOMAIN, translation_key=self._terminal_error)
        if self._inflight is not None:
            return await asyncio.shield(self._inflight)
        if self._last_attempt is not None and self._clock() - self._last_attempt < REFRESH_COOLDOWN:
            if self.data is not None and self.connection_status == "ready":
                return self.data
            raise UpdateFailed(
                translation_domain=DOMAIN, translation_key=self.error_key or "cannot_connect"
            )
        self._last_attempt = self._clock()
        self._inflight = self.hass.async_create_task(
            self._async_read_once(), name="Aqara cloud batch"
        )
        try:
            return await self._inflight
        finally:
            self._inflight = None

    async def async_request_refresh(self) -> None:
        """Manual requests join an existing read without scheduling a second one."""
        if self._inflight is not None:
            await asyncio.shield(self._inflight)
            return
        if self._last_attempt is not None and self._clock() - self._last_attempt < REFRESH_COOLDOWN:
            return
        await super().async_request_refresh()

    async def _async_read_once(self) -> AccountSnapshot:
        try:
            snapshot = await self.client.async_read_traits(self.device_ids, PROFILE)
        except SessionPersistenceError as err:
            self._set_failure("retry_wait", "secret_store_failed")
            raise UpdateFailed(
                translation_domain=DOMAIN, translation_key="secret_store_failed"
            ) from err
        except (AuthenticationRequired, CredentialStoreError) as err:
            self._set_failure("reauth_required", "auth_required")
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="auth_required"
            ) from err
        except (ProtocolUnsupported, AccountMismatch) as err:
            self._set_failure("protocol_unsupported", "protocol_unsupported")
            raise ConfigEntryError(
                translation_domain=DOMAIN, translation_key="protocol_unsupported"
            ) from err
        except RateLimited as err:
            self._set_failure("retry_wait", "rate_limited")
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="rate_limited",
                retry_after=getattr(err, "retry_after", None),
            ) from err
        except SignatureRejected as err:
            self._set_failure("protocol_unsupported", "signature_rejected")
            raise ConfigEntryError(
                translation_domain=DOMAIN, translation_key="signature_rejected"
            ) from err
        except (AccessDenied, ApplicationError, InvalidResponse, RequestRejected) as err:
            self._set_failure("protocol_unsupported", "api_changed")
            raise ConfigEntryError(
                translation_domain=DOMAIN, translation_key="api_changed"
            ) from err
        except TransportError as err:
            self._set_failure("retry_wait", "cannot_connect")
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                retry_after=self.client.limiter.retry_after,
            ) from err
        if self.connection_status != "ready":
            _LOGGER.info("Aqara cloud connection ready")
        self.successful_reads += 1
        self.connection_status = "ready"
        self.error_key = None
        self.transport_stale = False
        self._last_received = self._clock()
        self.last_successful_read = snapshot.received_at_utc
        async_clear_connection_issues(self.hass, self.entry.entry_id)
        async_set_issue(self.hass, self.entry.entry_id, "freshness_unverified")
        self.async_schedule_supplemental()
        return snapshot

    @property
    def supplemental_status(self) -> str:
        """Account summary; each device/query retains an independent status."""
        if self._resource_task is not None and not self._resource_task.done():
            return "updating"
        statuses = list(self.resource_status.values())
        if not statuses:
            return "idle"
        if len(statuses) == 2 * len(self.device_ids) and all(
            status == "ready" for status in statuses
        ):
            return "ready"
        return "partial_failure" if "ready" in statuses else "unavailable"

    def resource_available(self, device_id: str, query_kind: str) -> bool:
        """A fresh resource group is independent of the QLINK response status."""
        key = (device_id, query_kind)
        group = self.resource_data.get(key)
        received = self.resource_received_monotonic.get(key)
        return (
            not self._closed
            and group is not None
            and group.available
            and self.resource_status.get(key) in ("ready", "updating")
            and received is not None
            and self._clock() - received <= self._resource_max_age
        )

    def resource_sleep_mode(self, device_id: str) -> bool:
        if not self.resource_available(device_id, "resources"):
            return False
        mode = self.resource_data[(device_id, "resources")].observations.get("set_device_mode4")
        return (
            mode is not None
            and mode.value_status == "present"
            and type(mode.value) is int
            and mode.value == 9
        )

    @callback
    def async_schedule_supplemental(self) -> None:
        """Supplemental calls never hold up setup or replace the primary batch."""
        if self._closed or self._resource_task is not None:
            return
        self._resource_task = self.hass.async_create_background_task(
            self._async_fetch_supplemental(), name="Aqara supplemental reads", eager_start=False
        )

    async def _async_fetch_supplemental(self) -> None:
        queries = [
            (device_id, kind) for device_id in self.device_ids for kind in ("resources", "settings")
        ]
        try:
            for _ in queries:
                if self._closed:
                    return
                key = queries[self._resource_cursor]
                device_id, query_kind = key
                method = (
                    self.client.async_read_resources
                    if query_kind == "resources"
                    else self.client.async_read_resource_settings
                )
                self.resource_status[key] = "updating"
                self.async_update_listeners()
                try:
                    group = await method(device_id)
                    if group.device_id != device_id or not group.available:
                        raise InvalidResponse()
                except RateLimited as error:
                    self._resource_failed(key, error)
                    # Keep this position for the next primary poll. Otherwise
                    # phase-aligned primary reads can permanently skip a group.
                    return
                except (AqaraError, CredentialStoreError) as error:
                    self._resource_failed(key, error)
                except Exception:
                    # Do not render arbitrary upstream errors or resource values.
                    self._resource_failed(key, InvalidResponse())
                else:
                    self.resource_data[key] = group
                    self.resource_status[key] = "ready"
                    self.resource_errors.pop(key, None)
                    self.resource_received_monotonic[key] = self._clock()
                    self.resource_successful_reads += 1
                self._resource_cursor = (self._resource_cursor + 1) % len(queries)
                self.async_update_listeners()
        finally:
            self._resource_task = None
            if not self._closed:
                self.async_update_listeners()

    @callback
    def _resource_failed(self, key: tuple[str, str], error: Exception) -> None:
        error_key = (
            "rate_limited"
            if isinstance(error, RateLimited)
            else "auth_required"
            if isinstance(error, AuthenticationRequired)
            else "cannot_connect"
            if isinstance(error, TransportError)
            else "api_changed"
        )
        if self.resource_errors.get(key) != error_key:
            _LOGGER.warning("Aqara supplemental %s read failed: %s", key[1], error_key)
        self.resource_errors[key] = error_key
        self.resource_status[key] = "unavailable"
        self.resource_failed_reads += 1
        if old := self.resource_data.get(key):
            self.resource_data[key] = replace(
                old, observations={}, available=False, error=error_key
            )

    @callback
    def _set_failure(self, status: str, key: str) -> None:
        self.failed_reads += 1
        if self.error_key != key:
            _LOGGER.warning("Aqara cloud update requires attention: %s", key)
        self.connection_status = status
        self.error_key = key
        if status in ("reauth_required", "protocol_unsupported"):
            self._terminal_error = key
            self.update_interval = None
            self._unschedule_refresh()
        async_set_issue(
            self.hass,
            self.entry.entry_id,
            "protocol_unsupported" if key in ("api_changed", "signature_rejected") else key,
        )
        # Auth errors cause the base coordinator to stop polling; diagnostics still update.
        self.async_update_listeners()

    async def async_shutdown(self) -> None:
        """Stop every integration-owned timer and pending read before closing."""
        if self._closed:
            return
        self._closed = True
        if self._resource_task is not None:
            self._resource_task.cancel()
            await asyncio.gather(self._resource_task, return_exceptions=True)
        if self._stale_timer is not None:
            self._stale_timer.cancel()
            self._stale_timer = None
        if self._inflight is not None:
            self._inflight.cancel()
            await asyncio.gather(self._inflight, return_exceptions=True)
        await super().async_shutdown()
        await self.client.async_close()

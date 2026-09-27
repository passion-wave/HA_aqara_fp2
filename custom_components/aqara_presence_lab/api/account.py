"""Consented account lifecycle, with verified sessions and a storage callback."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable, Coroutine, Iterable
from typing import Any

from .auth import SessionCredentials, _credential
from .client import AsyncAqaraClient
from .errors import (
    AccountMismatch,
    AqaraError,
    AuthenticationRequired,
    InvalidResponse,
    ProtocolUnsupported,
    RateLimited,
    SessionExpired,
    SessionPersistenceError,
    TransportError,
)
from .logging import log_event
from .models import AccountIdentity, AccountSnapshot, DeviceSelection
from .profiles import ProtocolProfile
from .rate_limit import AccountRateLimiter
from .resources import DeviceResources

CredentialLoader = Callable[[], Awaitable[tuple[str, str]]]
SessionWriter = Callable[[SessionCredentials], Awaitable[None]]
Sleep = Callable[[float], Awaitable[None]]
MAX_AUTH_WAIT = 30.0


class ManagedAqaraClient:
    """One shared account operation and at most one login per failed generation.

    A returned login token is only a candidate. The public session remains the
    last accepted session until the server identity matches, all selected
    devices return useful current values, and the storage callback succeeds.
    Transport failures and unknown denials never initiate a login.

    Runtime callbacks durably save the session. A config flow may stage it until
    final confirmation; the neutral session_validated event makes no claim that
    this callback has written to disk.
    """

    def __init__(
        self,
        client: AsyncAqaraClient,
        credential_loader: CredentialLoader,
        persist_session: SessionWriter,
        *,
        initial_session: SessionCredentials | None = None,
        expected_user_id: str | None = None,
        consent: bool = False,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._client = client
        self._credential_loader = credential_loader
        self._persist_session = persist_session
        self._session = initial_session
        self._expected_user_id = (
            _credential(expected_user_id) if expected_user_id is not None else None
        )
        if initial_session is not None:
            if self._expected_user_id is not None and (
                initial_session.user_id != self._expected_user_id
            ):
                raise AccountMismatch()
            self._expected_user_id = initial_session.user_id
        self._consent = consent is True
        self._sleep = sleep
        self._pending: SessionCredentials | None = None
        self._pending_snapshot: AccountSnapshot | None = None
        self._pending_key: tuple | None = None
        self._pending_verified_at: float | None = None
        self._failed_generation: str | None = None
        self._expired_generation: str | None = None
        self._task: asyncio.Task[Any] | None = None
        self._task_key: tuple | None = None
        self._resource_waiters: set[asyncio.Task[Any]] = set()
        self._closed = False
        self._client.set_session(initial_session)

    @property
    def profile(self) -> ProtocolProfile:
        return self._client.profile

    @property
    def limiter(self) -> AccountRateLimiter:
        return self._client.limiter

    @property
    def session(self) -> SessionCredentials | None:
        """Verified and accepted by the callback; never an unchecked candidate."""
        return self._session

    @property
    def identity(self) -> AccountIdentity | None:
        if self._expected_user_id is None:
            return None
        return AccountIdentity(self.profile.area, self._expected_user_id)

    def _require_open(self) -> None:
        if self._closed:
            raise ProtocolUnsupported()
        if not self._consent:
            raise AuthenticationRequired()
        self.profile.require_experimental_login()

    async def _shared(self, key: tuple, operation: Callable[[], Coroutine[Any, Any, Any]]) -> Any:
        self._require_open()
        while (running := self._task) is not None and not running.done():
            if key == self._task_key:
                return await running
            # A validate call and its subsequent read may arrive concurrently.
            # Join that work; different simultaneous device batches stay bounded.
            if key[0] == "read" and self._task_key and self._task_key[0] == "read":
                raise RateLimited(self.limiter.retry_after)
            running_key = self._task_key
            try:
                await running
            except AqaraError:
                # An optional resource error belongs only to its own caller.
                # It must not poison a foreground trait read waiting its turn.
                if not running_key or running_key[0] not in ("resources", "resource_settings"):
                    raise
            self._require_open()
        task = asyncio.create_task(operation())
        self._task, self._task_key = task, key
        try:
            return await task
        finally:
            if self._task is task and task.done():
                self._task = self._task_key = None

    async def async_validate_credentials(self) -> AccountIdentity:
        """Bind a new login's identity; selected reads validate saved sessions.

        Existing sessions already carry the previously server-bound identity.
        Their current validity is checked by async_read_traits, which can renew
        an expired session without requiring a login on each restart.
        """
        return await self._shared(("validate",), self._validate)

    async def _validate(self) -> AccountIdentity:
        if self._session is None and self._pending is None:
            await self._login_candidate()
        identity = self.identity
        if identity is None:
            raise AuthenticationRequired()
        return identity

    async def async_read_resources(self, device_id: str) -> DeviceResources:
        return await self._supplementary(device_id, settings=False)

    async def async_read_resource_settings(self, device_id: str) -> DeviceResources:
        return await self._supplementary(device_id, settings=True)

    async def _supplementary(self, device_id: str, *, settings: bool) -> DeviceResources:
        self._require_open()
        try:
            DeviceSelection((device_id,))
        except ValueError, TypeError:
            raise InvalidResponse() from None
        if self._session is None:
            # A supplementary endpoint never initiates login or validates a
            # candidate which has not yet passed the mandatory trait read.
            raise AuthenticationRequired()
        waiter = asyncio.current_task()
        if waiter is not None:
            self._resource_waiters.add(waiter)
        try:
            # Let foreground polling proceed during this background cooldown.
            key = ("resource_settings" if settings else "resources", device_id)
            while True:
                await self._wait_cooldown()
                try:
                    return await self._shared(
                        key, lambda: self._resource_query(device_id, settings=settings)
                    )
                except RateLimited as error:
                    # A foreground request may have claimed the slot while we
                    # woke up. Preserve this group and await the next local slot.
                    # No HTTP request was sent; a server 429 is never retried.
                    if (
                        error.request_sent
                        or error.retry_after is None
                        or not 0 < error.retry_after <= MAX_AUTH_WAIT
                    ):
                        raise
        finally:
            if waiter is not None:
                self._resource_waiters.discard(waiter)

    async def _resource_query(self, device_id: str, *, settings: bool) -> DeviceResources:
        credentials = self._session
        if credentials is None:
            raise AuthenticationRequired()
        operation = (
            self._client.async_read_resource_settings
            if settings
            else self._client.async_read_resources
        )
        # The low-level auth provider may hold a pending renewal candidate.
        # Resource reads explicitly use only the last accepted session instead.
        return await operation(device_id, credentials=credentials)

    async def _wait_cooldown(self) -> None:
        delay = self.limiter.retry_after
        if delay > MAX_AUTH_WAIT:
            # Server backoff is not a reason to park a config flow indefinitely.
            # Keep a successfully issued candidate for the next permitted call.
            raise RateLimited(delay)
        if delay > 0:
            await self._sleep(delay)
        self._require_open()

    def _generation(self) -> str:
        token = self._session.token if self._session is not None else ""
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    async def _login_candidate(self) -> None:
        self._require_open()
        if self._pending is not None:
            return
        generation = self._generation()
        if self._failed_generation == generation:
            raise AuthenticationRequired()
        await self._wait_cooldown()
        self._failed_generation = generation
        try:
            try:
                account, password = await self._credential_loader()
                _credential(account)
                _credential(password)
            except asyncio.CancelledError:
                raise
            except Exception:
                raise AuthenticationRequired() from None
            candidate = await self._client.async_login(account, password, consent=True)
            if self._expected_user_id is not None and candidate.user_id != self._expected_user_id:
                raise AccountMismatch()
            self._expected_user_id = candidate.user_id
            self._pending = candidate
            self._client.set_session(candidate)
            log_event("login_candidate", operation="login")
        except asyncio.CancelledError:
            # No candidate was issued; an intentional later call may retry.
            self._failed_generation = None
            raise
        except TransportError as error:
            # A temporary transport failure did not reject the credentials.
            # A later poll may make one new attempt after the shared backoff;
            # this invocation never loops or repeats the login immediately.
            self._failed_generation = None
            log_event("request_failed", error=error, operation="login")
            raise
        except AqaraError as error:
            log_event("authentication_required", error=error, operation="login")
            raise
        except Exception:
            log_event("authentication_required", error=AuthenticationRequired(), operation="login")
            raise AuthenticationRequired() from None

    async def async_read_traits(
        self, device_ids: Iterable[str], profile: ProtocolProfile | None = None
    ) -> AccountSnapshot:
        try:
            ids = DeviceSelection(tuple(dict.fromkeys(device_ids))).device_ids
        except ValueError, TypeError:
            raise InvalidResponse() from None
        active_profile = profile or self.profile
        active_profile.require_experimental_login()
        return await self._shared(
            ("read", ids, active_profile), lambda: self._read(ids, active_profile)
        )

    async def _read(self, ids: tuple[str, ...], profile: ProtocolProfile) -> AccountSnapshot:
        key = (ids, profile)
        if (
            self._pending is not None
            and self._pending_key == key
            and self._pending_verified_at is not None
            and 0 <= self._client.clock.monotonic() - self._pending_verified_at <= 30
        ):
            assert self._pending_snapshot is not None
            return await self._commit_candidate(self._pending_snapshot)
        if self._session is None and self._pending is None:
            await self._login_candidate()
        if self._pending is not None:
            await self._wait_cooldown()
            return await self._read_candidate(ids, profile, key)
        if self._expired_generation == self._generation():
            await self._login_candidate()
            await self._wait_cooldown()
            return await self._read_candidate(ids, profile, key)
        await self._wait_cooldown()
        try:
            return await self._client.async_read_traits(ids, profile)
        except SessionExpired:
            # Exactly one source-evidenced renewal; no generic status/code guessing.
            self._expired_generation = self._generation()
            await self._login_candidate()
            await self._wait_cooldown()
            return await self._read_candidate(ids, profile, key)

    async def _read_candidate(
        self, ids: tuple[str, ...], profile: ProtocolProfile, key: tuple
    ) -> AccountSnapshot:
        try:
            snapshot = await self._client.async_read_traits(ids, profile)
        except SessionExpired:
            self._pending = None
            self._client.set_session(self._session)
            raise AuthenticationRequired() from None
        if any(
            device_id not in snapshot.devices
            or not snapshot.devices[device_id].available
            or snapshot.devices[device_id].error is not None
            or not any(
                trait.has_value and trait.value_status == "present"
                for trait in snapshot.devices[device_id].traits.values()
            )
            for device_id in ids
        ):
            raise InvalidResponse()
        self._pending_snapshot, self._pending_key = snapshot, key
        self._pending_verified_at = self._client.clock.monotonic()
        return await self._commit_candidate(snapshot)

    async def _commit_candidate(self, snapshot: AccountSnapshot) -> AccountSnapshot:
        assert self._pending is not None
        try:
            await self._persist_session(self._pending)
        except asyncio.CancelledError:
            raise
        except Exception:
            log_event("request_failed", error=SessionPersistenceError())
            raise SessionPersistenceError() from None
        self._session, self._pending = self._pending, None
        self._pending_snapshot = self._pending_key = None
        self._pending_verified_at = None
        self._failed_generation = None
        self._expired_generation = None
        log_event("session_validated", device_count=len(snapshot.devices))
        return snapshot

    async def async_close(self) -> None:
        self._closed = True
        waiters = tuple(
            task for task in self._resource_waiters if task is not asyncio.current_task()
        )
        for waiter in waiters:
            waiter.cancel()
        if waiters:
            await asyncio.gather(*waiters, return_exceptions=True)
        task = self._task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await self._client.async_close()
        self._session = self._pending = None
        self._pending_snapshot = self._pending_key = None
        self._pending_verified_at = None
        self._client.set_session(None)
        log_event("client_closed")

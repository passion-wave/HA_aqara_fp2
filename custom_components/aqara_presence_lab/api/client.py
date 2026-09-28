"""Asynchronous exact-byte HTTP transport with a closed production gate."""

from __future__ import annotations

import asyncio
import secrets
import ssl
import zlib
from collections.abc import Iterable
from dataclasses import replace
from uuid import uuid4

import aiohttp

from .auth import (
    AuthProvider,
    SessionAuthProvider,
    SessionCredentials,
    _credential,
    encrypt_password,
    parse_login_response,
)
from .errors import (
    AccessDenied,
    ApplicationError,
    AqaraError,
    AuthenticationRequired,
    InvalidResponse,
    LoginRejected,
    ProtocolUnsupported,
    RateLimited,
    RequestRejected,
    ResponseTooLarge,
    SessionExpired,
    TransportError,
)
from .importers import HOST, MAX_BODY_BYTES, PATH, ImportedCapture, request_paths, strict_json
from .logging import log_event
from .models import AccountIdentity, AccountSnapshot, DeviceSelection
from .parsing import parse_response
from .profiles import EU_CANDIDATE_PROFILE, ProtocolProfile
from .rate_limit import AccountRateLimiter, SystemClock, parse_retry_after
from .resources import (
    RESOURCE_OPTIONS,
    SETTINGS_OPTIONS,
    DeviceResources,
    parse_resource_response,
    parse_resource_settings_response,
)
from .signing import CandidateSigner, serialize_body

LOGIN_PATH = "/app/v1.0/lumi/user/login"
RESOURCE_PATH = "/app/v1.0/lumi/res/query"
RESOURCE_SETTINGS_PATH = "/app/v1.0/lumi/res/query/by/resourceId"


class AsyncAqaraClient:
    """One shared account client. Retries are exclusively coordinator-owned."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        auth: AuthProvider | None,
        signer: CandidateSigner,
        *,
        profile: ProtocolProfile = EU_CANDIDATE_PROFILE,
        clock: SystemClock | None = None,
        limiter: AccountRateLimiter | None = None,
        own_session: bool = False,
        live_consent: bool = False,
    ) -> None:
        self._session, self._auth, self._signer = session, auth, signer
        self.profile = profile
        self.clock = clock or SystemClock()
        self.limiter = limiter or AccountRateLimiter(clock=self.clock)
        self._own_session = own_session
        self._live_consent = live_consent is True
        self._read_task: asyncio.Task | None = None
        self._read_key: tuple | None = None
        self._closed = False
        self._previous: AccountSnapshot | None = None

    def set_session(self, credentials: SessionCredentials | None) -> None:
        """The account facade owns candidate installation and persistence."""
        self._auth = SessionAuthProvider(credentials) if credentials is not None else None

    def _require_runtime(self, profile: ProtocolProfile) -> None:
        if self._live_consent:
            profile.require_experimental_login()
        else:
            profile.require_production_ready()

    async def async_read_traits(
        self, device_ids: Iterable[str], profile: ProtocolProfile | None = None
    ) -> AccountSnapshot:
        profile = profile or self.profile
        self._require_runtime(profile)
        ids = tuple(dict.fromkeys(device_ids))
        if not ids or len(ids) > 100 or any(not isinstance(x, str) or not x for x in ids):
            raise InvalidResponse()
        key = (ids, profile.id, profile.version)
        if self._read_task and not self._read_task.done():
            if self._read_key != key:
                raise RateLimited(self.limiter.retry_after)
            return await self._read_task
        body = serialize_body(
            {
                "devices": [
                    {
                        "deviceId": device_id,
                        "traits": [
                            {"path": path, "needSubscribe": True} for path in profile.read_paths
                        ],
                    }
                    for device_id in ids
                ],
                "needParam": True,
            }
        )
        self._read_key = key
        self._read_task = asyncio.create_task(self._read_body(body, profile))
        try:
            return await self._read_task
        finally:
            if self._read_task.done():
                self._read_task = None
                self._read_key = None

    async def _read_body(self, body: bytes, profile: ProtocolProfile) -> AccountSnapshot:
        if profile.trait_read_path != PATH:
            raise ProtocolUnsupported()
        requested_paths = request_paths(body)
        started = self.clock.now()
        if self._auth is None:
            raise AuthenticationRequired()
        credentials = await self._auth.async_credentials()
        payload = await self._post(profile.trait_read_path, body, credentials, profile)
        snapshot = parse_response(
            payload,
            selected_device_ids=requested_paths,
            requested_paths=requested_paths,
            requested_at=started,
            received_at=self.clock.now(),
            previous=self._previous,
        )
        self._previous = snapshot
        return snapshot

    async def async_probe_capture(
        self, capture: ImportedCapture, *, consent: bool
    ) -> AccountSnapshot:
        """Explicit single probe only; G1 recomputed over exact imported bytes.

        The lab CLI additionally persists a cross-process budget/cooldown. This
        method neither opens the production gate nor establishes account identity.
        """
        from .validation import signature_matches

        if not consent or not signature_matches(capture, self._signer, self.profile):
            raise ProtocolUnsupported()
        if self._auth is None or capture.credentials != await self._auth.async_credentials():
            raise ProtocolUnsupported()
        return await self._read_body(capture.body, self.profile)

    async def async_read_resources(
        self, device_id: str, *, credentials: SessionCredentials | None = None
    ) -> DeviceResources:
        """One source-backed single-subject query for the complete resource list."""
        return await self._read_resources(device_id, credentials, settings=False)

    async def async_read_resource_settings(
        self, device_id: str, *, credentials: SessionCredentials | None = None
    ) -> DeviceResources:
        """Read seven documented configuration resources; never write settings."""
        return await self._read_resources(device_id, credentials, settings=True)

    async def _read_resources(
        self, device_id: str, credentials: SessionCredentials | None, *, settings: bool
    ) -> DeviceResources:
        self._require_runtime(self.profile)
        try:
            DeviceSelection((device_id,))
        except ValueError, TypeError:
            raise InvalidResponse() from None
        if credentials is None:
            if self._auth is None:
                raise AuthenticationRequired()
            credentials = await self._auth.async_credentials()
        options = SETTINGS_OPTIONS if settings else RESOURCE_OPTIONS
        path = self.profile.resource_settings_path if settings else self.profile.resource_query_path
        body = serialize_body({"data": [{"options": list(options), "subjectId": device_id}]})
        started = self.clock.now()
        payload = await self._post(path, body, credentials, self.profile)
        parser = parse_resource_settings_response if settings else parse_resource_response
        return parser(
            payload, device_id=device_id, requested_at=started, received_at=self.clock.now()
        )

    async def async_validate_credentials(self) -> AccountIdentity:
        self._require_runtime(self.profile)
        # Trait reads alone do not establish that the supplied Userid belongs to
        # the token. A future reviewed identity adapter must replace this block.
        raise ProtocolUnsupported("identity_unverified")

    async def async_login(
        self, account: str, password: str, *, consent: bool = False
    ) -> SessionCredentials:
        self._require_runtime(self.profile)
        if not consent or not self.profile.public_rsa_key or self.profile.login_path != LOGIN_PATH:
            raise ProtocolUnsupported()
        _credential(account)
        encrypted = encrypt_password(password, self.profile.public_rsa_key)
        body = serialize_body({"account": account, "encryptType": 2, "password": encrypted})
        try:
            payload = await self._post(self.profile.login_path, body, None, self.profile)
            # Caller must verify identity+selected-device read before atomic install.
            result = parse_login_response(payload)
        except AuthenticationRequired:
            raise
        except InvalidResponse, RequestRejected:
            raise AuthenticationRequired() from None
        return replace(result, sys_type="1")

    async def _post(
        self,
        path: str,
        body: bytes,
        credentials: SessionCredentials | None,
        profile: ProtocolProfile,
    ) -> dict:
        if (
            self._closed
            or profile.allowed_host != HOST
            or profile.area != "EU"
            or path not in (PATH, LOGIN_PATH, RESOURCE_PATH, RESOURCE_SETTINGS_PATH)
            or getattr(self._session, "trust_env", False)
        ):
            raise ProtocolUnsupported()
        if len(body) > MAX_BODY_BYTES:
            raise ResponseTooLarge()
        await self.limiter.async_claim(authentication=path == LOGIN_PATH)
        nonce = secrets.token_hex(16)
        timestamp = str(int(self.clock.now().timestamp() * 1000))
        headers = {
            "Content-Type": "application/json",
            "Area": profile.area,
            "Appid": profile.app_id,
            "App-Version": profile.tested_app_version,
            "Time": timestamp,
            "Nonce": nonce,
            "Accept-Encoding": "gzip",
        }
        if path == LOGIN_PATH or (credentials and credentials.sys_type == "1"):
            headers.update(
                {
                    "Sys-Type": "1",
                    "Lang": "en",
                    "User-Agent": "pyAqara/1.0.0",
                    "PhoneId": str(uuid4()).upper(),
                }
            )
        if path == LOGIN_PATH:
            headers["App-Version"] = profile.login_app_version
        if credentials:
            headers.update({"Token": credentials.token, "Userid": credentials.user_id})
            if credentials.sys_type is not None:
                headers["Sys-Type"] = credentials.sys_type
        headers["Sign"] = self._signer.sign(
            body, nonce=nonce, time_ms=timestamp, token=credentials.token if credentials else None
        )
        started = self.clock.monotonic()
        status = None
        operation = {
            LOGIN_PATH: "login",
            PATH: "trait_read",
            RESOURCE_PATH: "resource_read",
            RESOURCE_SETTINGS_PATH: "resource_settings_read",
        }[path]
        log_event("request_started", operation=operation)
        try:
            async with self._session.post(
                f"https://{HOST}{path}",
                data=body,
                headers=headers,
                allow_redirects=False,
                ssl=True,
                auto_decompress=False,
                timeout=aiohttp.ClientTimeout(total=20, connect=10),
            ) as response:
                status = response.status
                if status == 429:
                    delay = parse_retry_after(response.headers.get("Retry-After"), self.clock.now())
                    raise RateLimited(self.limiter.failure(delay), request_sent=True)
                if status >= 500:
                    self.limiter.failure()
                    raise TransportError()
                if status in (401, 403):
                    self.limiter.failure()
                    raise AccessDenied()
                if status < 200 or status >= 300:
                    raise RequestRejected()
                raw = await self._bounded_response(response)
                payload = strict_json(raw, limit=MAX_BODY_BYTES)
                if type(payload.get("code")) is not int:
                    raise InvalidResponse()
                if payload["code"] != 0:
                    if path == LOGIN_PATH:
                        raise LoginRejected(payload["code"], http_status=status)
                    if profile.is_confirmed_expiry(path, payload["code"]):
                        raise SessionExpired(payload["code"], http_status=status)
                    raise ApplicationError(payload["code"], http_status=status)
                self.limiter.success()
                log_event(
                    "request_succeeded",
                    http_status=status,
                    elapsed=self.clock.monotonic() - started,
                    operation=operation,
                )
                return payload
        except asyncio.CancelledError:
            log_event("request_cancelled", http_status=status, operation=operation)
            raise
        except AqaraError as error:
            log_event(
                "request_failed",
                error=error,
                http_status=status,
                elapsed=self.clock.monotonic() - started,
                operation=operation,
            )
            raise
        except aiohttp.ClientError, TimeoutError, OSError, ssl.SSLError:
            self.limiter.failure()
            log_event(
                "request_failed", error=TransportError(), http_status=status, operation=operation
            )
            raise TransportError() from None

    @staticmethod
    async def _bounded_response(response: aiohttp.ClientResponse) -> bytes:
        """Bound decompression itself, including chunked/no Content-Length data."""
        encoding = response.headers.get("Content-Encoding", "identity").lower()
        if encoding not in ("identity", "gzip", "deflate"):
            raise InvalidResponse()
        decoder = (
            None if encoding == "identity" else zlib.decompressobj(31 if encoding == "gzip" else 15)
        )
        output = bytearray()
        wire_size = 0
        try:
            async for chunk in response.content.iter_chunked(16384):
                wire_size += len(chunk)
                if wire_size > MAX_BODY_BYTES:
                    raise ResponseTooLarge()
                decoded = (
                    decoder.decompress(chunk, MAX_BODY_BYTES - len(output) + 1)
                    if decoder
                    else chunk
                )
                output.extend(decoded)
                if len(output) > MAX_BODY_BYTES or (decoder and decoder.unconsumed_tail):
                    raise ResponseTooLarge()
            if decoder:
                if not decoder.eof or decoder.unused_data:
                    raise InvalidResponse()
                output.extend(decoder.flush(MAX_BODY_BYTES - len(output) + 1))
                if len(output) > MAX_BODY_BYTES:
                    raise ResponseTooLarge()
        except zlib.error:
            raise InvalidResponse() from None
        return bytes(output)

    async def async_close(self) -> None:
        self._closed = True
        if self._read_task and not self._read_task.done():
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
        if self._own_session:
            await self._session.close()

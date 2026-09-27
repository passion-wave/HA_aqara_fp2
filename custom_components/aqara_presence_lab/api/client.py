"""Asynchronous exact-byte HTTP transport with a closed production gate."""

from __future__ import annotations

import asyncio
import secrets
import ssl
import zlib
from collections.abc import Iterable

import aiohttp

from .auth import AuthProvider, SessionCredentials, encrypt_password, parse_login_response
from .errors import (
    AccessDenied,
    ApplicationError,
    InvalidResponse,
    ProtocolUnsupported,
    RateLimited,
    RequestRejected,
    ResponseTooLarge,
    TransportError,
)
from .importers import HOST, MAX_BODY_BYTES, PATH, ImportedCapture, request_paths, strict_json
from .models import AccountIdentity, AccountSnapshot
from .parsing import parse_response
from .profiles import EU_CANDIDATE_PROFILE, ProtocolProfile
from .rate_limit import AccountRateLimiter, SystemClock, parse_retry_after
from .signing import CandidateSigner, serialize_body

LOGIN_PATH = "/app/v1.0/lumi/user/login"


class AsyncAqaraClient:
    """One shared account client. Retries are exclusively coordinator-owned."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        auth: AuthProvider,
        signer: CandidateSigner,
        *,
        profile: ProtocolProfile = EU_CANDIDATE_PROFILE,
        clock: SystemClock | None = None,
        limiter: AccountRateLimiter | None = None,
        own_session: bool = False,
    ) -> None:
        self._session, self._auth, self._signer = session, auth, signer
        self.profile = profile
        self.clock = clock or SystemClock()
        self.limiter = limiter or AccountRateLimiter(clock=self.clock)
        self._own_session = own_session
        self._read_task: asyncio.Task | None = None
        self._read_key: tuple | None = None
        self._closed = False
        self._previous: AccountSnapshot | None = None

    async def async_read_traits(
        self, device_ids: Iterable[str], profile: ProtocolProfile | None = None
    ) -> AccountSnapshot:
        profile = profile or self.profile
        profile.require_production_ready()
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
        if capture.credentials != await self._auth.async_credentials():
            raise ProtocolUnsupported()
        return await self._read_body(capture.body, self.profile)

    async def async_validate_credentials(self) -> AccountIdentity:
        self.profile.require_production_ready()
        # Trait reads alone do not establish that the supplied Userid belongs to
        # the token. A future reviewed identity adapter must replace this block.
        raise ProtocolUnsupported("identity_unverified")

    async def async_login(
        self, account: str, password: str, *, consent: bool = False
    ) -> SessionCredentials:
        self.profile.require_production_ready()
        if not consent or not self.profile.public_rsa_key or self.profile.login_path != LOGIN_PATH:
            raise ProtocolUnsupported()
        encrypted = encrypt_password(password, self.profile.public_rsa_key)
        body = serialize_body({"account": account, "encryptType": 2, "password": encrypted})
        payload = await self._post(self.profile.login_path, body, None, self.profile)
        # Caller must verify identity+selected-device read before atomic install.
        return parse_login_response(payload)

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
            or path not in (PATH, LOGIN_PATH)
            or getattr(self._session, "trust_env", False)
        ):
            raise ProtocolUnsupported()
        if len(body) > MAX_BODY_BYTES:
            raise ResponseTooLarge()
        await self.limiter.async_claim()
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
        if credentials:
            headers.update({"Token": credentials.token, "Userid": credentials.user_id})
        headers["Sign"] = self._signer.sign(
            body, nonce=nonce, time_ms=timestamp, token=credentials.token if credentials else None
        )
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
                    raise RateLimited(self.limiter.failure(delay))
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
                    raise ApplicationError(payload["code"], http_status=status)
                self.limiter.success()
                return payload
        except asyncio.CancelledError:
            raise
        except aiohttp.ClientError, TimeoutError, OSError, ssl.SSLError:
            self.limiter.failure()
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

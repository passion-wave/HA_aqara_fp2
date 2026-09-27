"""Credential handling and one shared, consented reauthentication attempt."""

from __future__ import annotations

import asyncio
import base64
import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol

from .errors import AccountMismatch, AuthenticationRequired, InvalidResponse, ProtocolUnsupported


def _credential(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 8192:
        raise AuthenticationRequired("missing_credentials")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise AuthenticationRequired("invalid_credentials")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise AuthenticationRequired("invalid_credentials") from None
    return value


@dataclass(frozen=True)
class SessionCredentials:
    """Private values intentionally excluded from repr and equality output."""

    token: str = field(repr=False)
    user_id: str = field(repr=False)
    sys_type: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        _credential(self.token)
        _credential(self.user_id)
        if self.sys_type not in (None, "0", "1") or (
            self.sys_type is not None and type(self.sys_type) is not str
        ):
            raise AuthenticationRequired()


class AuthProvider(Protocol):
    async def async_credentials(self) -> SessionCredentials: ...


class SessionAuthProvider:
    """Session import cannot establish server-proven account identity by itself."""

    def __init__(self, credentials: SessionCredentials) -> None:
        self._credentials = credentials
        self._reauth_lock = asyncio.Lock()
        self._failed_generation: str | None = None

    async def async_credentials(self) -> SessionCredentials:
        return self._credentials

    async def async_reauthenticate(
        self,
        failed_token: str,
        *,
        consent: bool,
        profile: object,
        login: Callable[[], Awaitable[SessionCredentials]],
        verify: Callable[[SessionCredentials], Awaitable[bool]],
    ) -> SessionCredentials:
        """Only called after evidenced expiry; never after an unknown 401/403.

        Candidate installation is atomic after identity and selected-device read
        verification. Failure is remembered per credential generation to avoid a
        new login from every waiting caller. Cancellation permits a later retry.
        """
        profile.require_production_ready()  # type: ignore[attr-defined]
        if not consent or getattr(profile, "login_strategy", "unsupported") == "unsupported":
            raise AuthenticationRequired("auth_required")
        async with self._reauth_lock:
            if self._credentials.token != failed_token:
                return self._credentials
            generation = hashlib.sha256(failed_token.encode()).hexdigest()
            if self._failed_generation == generation:
                raise AuthenticationRequired("auth_required")
            self._failed_generation = generation
            try:
                candidate = await login()
                if candidate.user_id != self._credentials.user_id:
                    raise AccountMismatch("account_mismatch")
                if not await verify(candidate):
                    raise AuthenticationRequired("auth_required")
            except asyncio.CancelledError:
                self._failed_generation = None
                raise
            self._credentials = candidate
            self._failed_generation = None
            return candidate


def parse_login_response(payload: object) -> SessionCredentials:
    """A successful login binds userId/token; no application codes are guessed."""
    if not isinstance(payload, dict) or type(payload.get("code")) is not int:
        raise InvalidResponse("invalid_login_response")
    if payload["code"] != 0:
        # Includes MFA/CAPTCHA/unknown rejection: manual user action, no retry.
        raise AuthenticationRequired("login_not_accepted")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise InvalidResponse("invalid_login_response")
    return SessionCredentials(_credential(result.get("token")), _credential(result.get("userId")))


def encrypt_password(password: str, public_key: str) -> str:
    """Legacy protocol candidate using the established cryptography library."""
    _credential(password)
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import padding, rsa

        key = serialization.load_pem_public_key(public_key.encode("ascii"))
        if not isinstance(key, rsa.RSAPublicKey):
            raise ValueError
        digest = hashlib.md5(password.encode("utf-8"), usedforsecurity=False).hexdigest()
        encrypted = key.encrypt(digest.encode("ascii"), padding.PKCS1v15())
    except ValueError, TypeError, UnicodeError, ImportError:
        raise ProtocolUnsupported("login_crypto_unavailable") from None
    return base64.b64encode(encrypted).decode("ascii")

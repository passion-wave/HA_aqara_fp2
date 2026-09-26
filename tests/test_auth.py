import asyncio
import base64
import hashlib
from unittest.mock import AsyncMock, Mock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from custom_components.aqara_presence_lab.api.auth import (
    SessionAuthProvider,
    SessionCredentials,
    encrypt_password,
    parse_login_response,
)
from custom_components.aqara_presence_lab.api.errors import (
    AccountMismatch,
    AuthenticationRequired,
    InvalidResponse,
    ProtocolUnsupported,
)
from custom_components.aqara_presence_lab.api.profiles import PROFILE


@pytest.mark.parametrize(
    ("token", "user"),
    [
        ("", "user"),
        ("token", ""),
        (None, "u"),
        ("SECRET\ud800", "u"),
        ("t\r\nsecret", "u"),
        ("t", 42),
    ],
)
def test_credentials_validation(token, user):
    with pytest.raises(AuthenticationRequired):
        SessionCredentials(token, user)


def test_login_schema_and_unknown_rejection():
    assert parse_login_response(
        {"code": 0, "result": {"token": "t", "userId": "u"}}
    ) == SessionCredentials("t", "u")
    for code in (106, 401, 999):
        with pytest.raises(AuthenticationRequired) as error:
            parse_login_response({"code": code, "message": "SECRET"})
        assert "SECRET" not in str(error.value)
    with pytest.raises(InvalidResponse):
        parse_login_response({"code": False, "result": {}})
    with pytest.raises(AuthenticationRequired):
        parse_login_response({"code": 0, "result": {"token": "t"}})


def test_rsa_password_candidate_round_trip():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    encrypted = encrypt_password("Pässword-test", public)
    assert (
        key.decrypt(base64.b64decode(encrypted), padding.PKCS1v15()).decode()
        == hashlib.md5("Pässword-test".encode(), usedforsecurity=False).hexdigest()
    )
    with pytest.raises(ProtocolUnsupported):
        encrypt_password("secret", "not-key")


async def test_concurrent_reauth_once_then_atomic_install():
    provider = SessionAuthProvider(SessionCredentials("old", "user"))
    login = AsyncMock(return_value=SessionCredentials("new", "user"))
    verify = AsyncMock(return_value=True)
    profile = Mock(login_strategy="verified")
    results = await asyncio.gather(
        *(
            provider.async_reauthenticate(
                "old", consent=True, profile=profile, login=login, verify=verify
            )
            for _ in range(10)
        )
    )
    assert all(item.token == "new" for item in results)
    assert login.await_count == verify.await_count == 1


@pytest.mark.parametrize("failure", ["reject", "mismatch", "unverified"])
async def test_failed_reauth_once_preserves_credentials(failure):
    original = SessionCredentials("old", "user")
    provider = SessionAuthProvider(original)
    login = AsyncMock(
        return_value=SessionCredentials("new", "other" if failure == "mismatch" else "user")
    )
    if failure == "reject":
        login.side_effect = AuthenticationRequired()
    verify = AsyncMock(return_value=failure != "unverified")
    for _ in range(3):
        with pytest.raises((AuthenticationRequired, AccountMismatch)):
            await provider.async_reauthenticate(
                "old",
                consent=True,
                profile=Mock(login_strategy="verified"),
                login=login,
                verify=verify,
            )
    assert login.await_count == 1
    assert await provider.async_credentials() is original


async def test_gate_and_consent_precede_login():
    provider = SessionAuthProvider(SessionCredentials("old", "user"))
    login, verify = AsyncMock(), AsyncMock()
    with pytest.raises(ProtocolUnsupported):
        await provider.async_reauthenticate(
            "old", consent=True, profile=PROFILE, login=login, verify=verify
        )
    with pytest.raises(AuthenticationRequired):
        await provider.async_reauthenticate(
            "old", consent=False, profile=Mock(), login=login, verify=verify
        )
    login.assert_not_awaited()


async def test_cancelled_reauth_preserves_old_session_and_allows_later_attempt():
    provider = SessionAuthProvider(SessionCredentials("old", "user"))
    entered = asyncio.Event()

    async def cancelled_login():
        entered.set()
        await asyncio.Event().wait()

    profile = Mock(login_strategy="verified")
    task = asyncio.create_task(
        provider.async_reauthenticate(
            "old",
            consent=True,
            profile=profile,
            login=cancelled_login,
            verify=AsyncMock(return_value=True),
        )
    )
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await provider.async_credentials()).token == "old"
    login = AsyncMock(return_value=SessionCredentials("new", "user"))
    result = await provider.async_reauthenticate(
        "old", consent=True, profile=profile, login=login, verify=AsyncMock(return_value=True)
    )
    assert result.token == "new"
    login.assert_awaited_once()

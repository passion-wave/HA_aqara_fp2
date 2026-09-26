"""Exact-body MD5 candidate; synthetic correctness is not live validation."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass, field
from typing import Any


def serialize_body(payload: Any) -> bytes:
    """Serialize exactly once; the resulting bytes must also be the HTTP body."""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(
        "utf-8"
    )


def sign_request(
    *,
    app_id: str,
    app_key: str,
    body: bytes,
    nonce: str,
    time_ms: int | str,
    token: str | None = None,
) -> str:
    if not isinstance(body, bytes):
        raise ValueError("body_bytes_required")
    for value in (app_id, app_key, nonce):
        if (
            not isinstance(value, str)
            or not value
            or any(char in value for char in ("\r", "\n", "&"))
        ):
            raise ValueError("invalid_signing_input")
        try:
            value.encode("utf-8")
        except UnicodeError:
            raise ValueError("invalid_signing_input") from None
    if type(time_ms) not in (int, str) or not re.fullmatch(r"[0-9]{1,20}", str(time_ms)):
        raise ValueError("invalid_signing_time")
    if token is not None and (
        not isinstance(token, str) or any(char in token for char in ("\r", "\n", "&"))
    ):
        raise ValueError("invalid_signing_input")
    if token is not None:
        try:
            token.encode("utf-8")
        except UnicodeError:
            raise ValueError("invalid_signing_input") from None
    try:
        body.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("body_utf8_required") from None
    segments = [f"Appid={app_id}".encode(), f"Nonce={nonce}".encode(), f"Time={time_ms}".encode()]
    if token:
        segments.append(f"Token={token}".encode())
    if body:
        segments.append(body)
    segments.append(app_key.encode())
    # MD5 is imposed by this legacy protocol candidate, never used for passwords at rest.
    return hashlib.md5(b"&".join(segments), usedforsecurity=False).hexdigest()


@dataclass(frozen=True)
class CandidateSigner:
    app_key: str = field(repr=False)
    app_id: str = "7be1984f0556276133336839"

    def sign(self, body: bytes, *, nonce: str, time_ms: int | str, token: str | None = None) -> str:
        return sign_request(
            app_id=self.app_id,
            app_key=self.app_key,
            body=body,
            nonce=nonce,
            time_ms=time_ms,
            token=token,
        )

    def matches(
        self,
        expected_signature: str,
        body: bytes,
        *,
        nonce: str,
        time_ms: int | str,
        token: str | None = None,
    ) -> bool:
        candidate = self.sign(body, nonce=nonce, time_ms=time_ms, token=token)
        if not isinstance(expected_signature, str) or not re.fullmatch(
            r"[0-9a-fA-F]{32}", expected_signature
        ):
            return False
        return hmac.compare_digest(candidate, expected_signature.lower())

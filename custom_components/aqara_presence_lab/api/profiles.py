"""Versioned evidence for the EU candidate. No production profile is approved."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .errors import ProtocolUnsupported
from .models import AccountIdentity
from .protocol_constants import EU_APP_KEY, RSA_PUBLIC_KEY


@dataclass(frozen=True)
class ProtocolProfile:
    id: str
    version: int
    source_reference: str
    allowed_host: str = "rpc-ger.aqara.com"
    area: str = "EU"
    app_id: str = "7be1984f0556276133336839"
    signing_strategy: str = "md5_exact_body_candidate"
    login_strategy: str = "rsa_pkcs1v15_md5_candidate"
    header_policy: tuple[str, ...] = (
        "Content-Type",
        "Area",
        "Appid",
        "App-Version",
        "Token",
        "Userid",
        "Time",
        "Nonce",
        "Sign",
    )
    body_serialization_policy: str = "compact_utf8"
    trait_read_path: str = "/app/v1.0/lumi/app/qlink/trait/read"
    read_paths: tuple[str, ...] = (
        "0.128.32901",
        "0.129.32907",
        "0.129.33013",
        "0.129.32909",
        "0.129.32906",
        "0.129.32912",
        "0.130.32914",
        "0.130.32913",
        "0.130.33016",
        "1.147.32969",
        "2.160.33001",
        "2.160.33044",
        "2.160.33000",
        "2.160.33045",
        "2.130.32913",
        "2.130.32915",
        "2.130.33108",
        "2.130.32919",
        "2.130.33012",
        "4.154.32989",
        "4.130.32913",
        "4.130.32915",
        "4.130.33108",
        "4.130.32919",
        "4.130.33012",
        "5.130.32913",
        "5.130.32915",
        "5.130.33108",
        "5.130.32919",
        "5.130.33012",
        "5.168.33019",
    )
    login_path: str = "/app/v1.0/lumi/user/login"
    login_app_version: str = "3.0.0"
    subscribe_policy: str = "captured_true"
    error_map: tuple[tuple[int, str], ...] = ()
    validation_state: str = "candidate"
    tested_app_version: str = "6.4.1"
    tested_at: datetime | None = None
    evidence_refs: tuple[str, ...] = ()
    app_key: str | None = field(default=None, repr=False)
    public_rsa_key: str | None = field(default=None, repr=False)

    @property
    def production_allowed(self) -> bool:
        """Closed until G1–G3, G5/G6 and subscription evidence are reviewed.

        This is intentionally not a dataclass field or a user preference.
        Merely changing validation_state or adding an evidence filename cannot
        authorize continuous credential-bearing network traffic.
        """
        return False

    def require_production_ready(self, account_key: str | None = None) -> None:
        raise ProtocolUnsupported()

    def require_experimental_login(self) -> None:
        """Constrain the explicitly consented runtime to the implemented protocol.

        This check is independent of the still-closed production evidence gate.
        It cannot turn a different host, signing scheme or login into a supported
        experimental account flow by reusing the profile's name.
        """
        candidate = CANDIDATE_PROFILE
        fields = (
            "id",
            "version",
            "source_reference",
            "allowed_host",
            "area",
            "app_id",
            "signing_strategy",
            "login_strategy",
            "body_serialization_policy",
            "trait_read_path",
            "login_path",
            "login_app_version",
            "subscribe_policy",
            "tested_app_version",
            "header_policy",
            "read_paths",
        )
        if any(getattr(self, name) != getattr(candidate, name) for name in fields):
            raise ProtocolUnsupported()

    def is_confirmed_expiry(self, path: str, code: int) -> bool:
        """A private qlink response established code108; other APIs stay unknown."""
        try:
            self.require_experimental_login()
        except ProtocolUnsupported:
            return False
        return path == CANDIDATE_PROFILE.trait_read_path and type(code) is int and code == 108


CANDIDATE_PROFILE = ProtocolProfile(
    id="sleepradar_eu_candidate_v1",
    version=1,
    source_reference="https://github.com/florianhorner/ha-fp2-sleep/blob/3af017fc995d5f05e65720ae5b1ed0690a04504c/aqara_fp2_sleep/aqara_fp2_sleep_poller.py",
    evidence_refs=(
        "source_blob:b48a4417deebd04cf4e6b3eb3d918300e6081d25",
        "pseudonymised_capture:2026-09-25",
    ),
    app_key=EU_APP_KEY,
    public_rsa_key=RSA_PUBLIC_KEY,
)
EU_CANDIDATE_PROFILE = CANDIDATE_PROFILE
PROFILE = CANDIDATE_PROFILE


def require_production(
    profile: ProtocolProfile = CANDIDATE_PROFILE,
    account_identity: AccountIdentity | None = None,
) -> None:
    profile.require_production_ready(account_identity.account_key if account_identity else None)

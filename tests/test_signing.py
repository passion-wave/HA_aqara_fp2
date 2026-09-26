"""Exact byte regression tests do not claim any server acceptance."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from custom_components.aqara_presence_lab.api.errors import ProtocolUnsupported
from custom_components.aqara_presence_lab.api.profiles import CANDIDATE_PROFILE, require_production
from custom_components.aqara_presence_lab.api.signing import (
    CandidateSigner,
    serialize_body,
    sign_request,
)


def test_synthetic_vector():
    fixture = json.loads(
        (Path(__file__).resolve().parents[1] / "fixtures/signing.synthetic.json").read_text()
    )
    signer = CandidateSigner(fixture["app_key"], fixture["app_id"])
    kwargs = dict(nonce=fixture["nonce"], time_ms=fixture["time_ms"], token=fixture["token"])
    body = fixture["body_utf8"].encode()
    assert signer.sign(body, **kwargs) == fixture["expected_signature"]
    assert signer.matches(fixture["expected_signature"], body, **kwargs)
    assert not signer.matches("0" * 32, body, **kwargs)


@pytest.mark.parametrize(
    ("body", "token", "material"),
    [
        (b"{}", None, b"Appid=app&Nonce=nonce&Time=1&{}&key"),
        (b"{}", "", b"Appid=app&Nonce=nonce&Time=1&{}&key"),
        (b"", None, b"Appid=app&Nonce=nonce&Time=1&key"),
        (b"", "token", b"Appid=app&Nonce=nonce&Time=1&Token=token&key"),
    ],
)
def test_optional_segments(body, token, material):
    assert (
        sign_request(app_id="app", app_key="key", body=body, nonce="nonce", time_ms=1, token=token)
        == hashlib.md5(material, usedforsecurity=False).hexdigest()
    )


@pytest.mark.parametrize("body", [b'{ "a":true}', b'{"a":true}\n', b'{"a": true}', b'{"a":false}'])
def test_every_body_byte_affects_digest(body):
    signer = CandidateSigner("key", "app")
    assert signer.sign(body, nonce="n", time_ms=1) != signer.sign(
        b'{"a":true}', nonce="n", time_ms=1
    )


def test_unicode_serialization_and_order_are_not_rewritten():
    signer = CandidateSigner("key", "app")
    body = serialize_body({"name": "Küche", "boolean": True})
    assert body == '{"name":"Küche","boolean":true}'.encode()
    escaped = b'{"name":"K\\u00fcche","boolean":true}'
    assert signer.sign(body, nonce="n", time_ms=1) != signer.sign(escaped, nonce="n", time_ms=1)
    assert signer.sign(body, nonce="new", time_ms=1) != signer.sign(body, nonce="n", time_ms=1)
    assert signer.sign(body, nonce="n", time_ms=2) != signer.sign(body, nonce="n", time_ms=1)


def test_compare_uses_constant_time_primitive(monkeypatch):
    called = []
    monkeypatch.setattr(
        "custom_components.aqara_presence_lab.api.signing.hmac.compare_digest",
        lambda a, b: called.append((a, b)) or True,
    )
    signer = CandidateSigner("SECRET-KEY", "app")
    assert signer.matches("a" * 32, b"{}", nonce="nonce", time_ms=1, token="SECRET-TOKEN")
    assert len(called) == 1
    assert "SECRET" not in repr(signer)


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_serialization_rejects_nonfinite(value):
    with pytest.raises(ValueError):
        serialize_body({"value": value})


@pytest.mark.parametrize(
    "kwargs",
    [
        {"body": "{}"},
        {"body": b"\xff"},
        {"time_ms": True},
        {"time_ms": -1},
        {"nonce": "a&b"},
        {"token": "secret\nheader"},
        {"app_key": ""},
    ],
)
def test_signing_inputs_cannot_be_ambiguous(kwargs):
    arguments = dict(app_id="app", app_key="key", body=b"{}", nonce="nonce", time_ms=1)
    arguments.update(kwargs)
    with pytest.raises(ValueError):
        sign_request(**arguments)


def test_production_gate_cannot_be_opened_by_boolean_or_report_metadata():
    assert not CANDIDATE_PROFILE.production_allowed
    fake = replace(
        CANDIDATE_PROFILE,
        validation_state="endpoint_validated",
        evidence_refs=("all_tests_passed",),
    )
    assert not fake.production_allowed
    with pytest.raises(ProtocolUnsupported):
        require_production(fake)
    with pytest.raises(TypeError):
        replace(CANDIDATE_PROFILE, production_allowed=True)


@pytest.mark.parametrize("field", ["app_id", "app_key", "nonce", "token"])
def test_invalid_unicode_signing_field_does_not_leak_secret(field):
    arguments = dict(app_id="app", app_key="key", body=b"{}", nonce="n", time_ms=1)
    arguments[field] = "SECRET\ud800"
    with pytest.raises(ValueError) as caught:
        sign_request(**arguments)
    assert "SECRET" not in repr(caught.value)
    assert "SECRET" not in str(caught.value)

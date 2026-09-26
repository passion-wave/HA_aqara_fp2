"""Strict local import. A cURL export is data and is never executed."""

from __future__ import annotations

import base64
import binascii
import shlex
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .auth import SessionCredentials
from .errors import InvalidResponse, ResponseTooLarge
from .parsing import strict_json_loads

MAX_IMPORT_BYTES = 4 * 1024 * 1024
MAX_BODY_BYTES = 2 * 1024 * 1024
HOST = "rpc-ger.aqara.com"
PATH = "/app/v1.0/lumi/app/qlink/trait/read"
REQUIRED = {"appid", "area", "token", "userid", "time", "nonce", "sign"}
RETAINED = REQUIRED | {"content-type", "app-version"}


def strict_json(data: str | bytes, *, limit: int = MAX_IMPORT_BYTES) -> dict:
    parsed = strict_json_loads(data, max_bytes=limit)
    if not isinstance(parsed, dict):
        raise InvalidResponse("invalid_capture")
    return parsed


def allowed_url(url: object) -> str:
    if not isinstance(url, str) or any(ord(c) < 33 for c in url):
        raise InvalidResponse("unsupported_endpoint")
    try:
        parsed = urlsplit(url)
        valid = (
            parsed.scheme == "https"
            and parsed.hostname == HOST
            and parsed.port in (None, 443)
            and parsed.path == PATH
            and not parsed.query
            and not parsed.fragment
            and parsed.username is None
            and parsed.password is None
        )
    except ValueError:
        valid = False
    if not valid:
        raise InvalidResponse("unsupported_endpoint")
    return f"https://{HOST}{PATH}"


def _headers(items: list[tuple[str, str]]) -> dict[str, str]:
    result: dict[str, str] = {}
    seen = set()
    for key, value in items:
        if not isinstance(key, str) or not isinstance(value, str):
            raise InvalidResponse("invalid_headers")
        name = key.strip().lower()
        if name in seen or any(ord(c) < 32 or ord(c) == 127 for c in key + value):
            raise InvalidResponse("ambiguous_headers")
        seen.add(name)
        if name in RETAINED:
            result[name] = value.strip()
    if not REQUIRED <= result.keys():
        raise InvalidResponse("missing_credentials")
    if result["appid"] != "7be1984f0556276133336839" or result["area"] != "EU":
        raise InvalidResponse("unsupported_profile")
    if not result["time"].isascii() or not result["time"].isdecimal():
        raise InvalidResponse("invalid_time")
    if len(result["sign"]) != 32 or any(c not in "0123456789abcdefABCDEF" for c in result["sign"]):
        raise InvalidResponse("invalid_signature")
    SessionCredentials(result["token"], result["userid"])
    return result


@dataclass(frozen=True)
class ImportedCapture:
    """Body and headers can contain account data; no public repr."""

    headers: dict[str, str] = field(repr=False)
    body: bytes = field(repr=False)
    wire_exact: bool = False
    source: str = "structured"

    @property
    def credentials(self) -> SessionCredentials:
        return SessionCredentials(self.headers["token"], self.headers["userid"])

    def preview(self) -> dict:
        payload = strict_json(self.body, limit=MAX_BODY_BYTES)
        return {
            "profile": "sleepradar_eu_candidate_v1",
            "region": "EU",
            "device_count": len(payload.get("devices", [])),
            "body_bytes": len(self.body),
            "wire_exact_claimed": self.wire_exact,
            "source": self.source,
        }

    def package(self) -> dict:
        """Private local package, never an issue attachment or diagnostic."""
        return {
            "format": "aqara-presence-lab-capture",
            "version": 1,
            "url": f"https://{HOST}{PATH}",
            "method": "POST",
            "headers": self.headers,
            "body_base64": base64.b64encode(self.body).decode("ascii"),
            "wire_exact": self.wire_exact,
            "source": self.source,
        }


def _capture(
    headers: list[tuple[str, str]], body: object, *, wire_exact: bool, source: str
) -> ImportedCapture:
    if not isinstance(body, bytes):
        raise InvalidResponse("invalid_body")
    request_paths(body)  # Validates without modifying the signed bytes.
    return ImportedCapture(_headers(headers), body, wire_exact, source)


def request_paths(body: bytes) -> dict[str, tuple[str, ...]]:
    payload = strict_json(body, limit=MAX_BODY_BYTES)
    if set(payload) != {"devices", "needParam"} or payload["needParam"] is not True:
        raise InvalidResponse("unsupported_read_request")
    devices = payload["devices"]
    if not isinstance(devices, list) or not 1 <= len(devices) <= 100:
        raise InvalidResponse("invalid_devices")
    result = {}
    for device in devices:
        if not isinstance(device, dict) or set(device) != {"deviceId", "traits"}:
            raise InvalidResponse("invalid_device")
        device_id, traits = device["deviceId"], device["traits"]
        if (
            not isinstance(device_id, str)
            or not device_id
            or len(device_id) > 256
            or device_id in result
        ):
            raise InvalidResponse("invalid_device")
        if not isinstance(traits, list) or not 1 <= len(traits) <= 200:
            raise InvalidResponse("invalid_traits")
        paths = []
        for trait in traits:
            if (
                not isinstance(trait, dict)
                or set(trait) != {"path", "needSubscribe"}
                or trait["needSubscribe"] is not True
            ):
                raise InvalidResponse("unsupported_subscribe_variant")
            path = trait["path"]
            if (
                not isinstance(path, str)
                or len(path) > 64
                or not all(p.isascii() and p.isdecimal() for p in path.split("."))
                or len(path.split(".")) != 3
            ):
                raise InvalidResponse("invalid_path")
            paths.append(path)
        result[device_id] = tuple(paths)
    return result


def import_package(data: str | bytes) -> ImportedCapture:
    payload = strict_json(data)
    if (
        payload.get("format") != "aqara-presence-lab-capture"
        or type(payload.get("version")) is not int
        or payload["version"] != 1
    ):
        raise InvalidResponse("invalid_capture")
    allowed_url(payload.get("url"))
    if payload.get("method") != "POST" or not isinstance(payload.get("headers"), dict):
        raise InvalidResponse("invalid_capture")
    try:
        body = base64.b64decode(payload["body_base64"], validate=True)
    except KeyError, ValueError, TypeError, binascii.Error:
        raise InvalidResponse("invalid_body") from None
    return _capture(
        list(payload["headers"].items()),
        body,
        wire_exact=payload.get("wire_exact") is True,
        source="structured",
    )


def import_har(data: str | bytes, *, entry_index: int | None = None) -> ImportedCapture:
    payload = strict_json(data)
    try:
        entries = payload["log"]["entries"]
        if not isinstance(entries, list):
            raise ValueError
        matches = []
        for index, entry in enumerate(entries):
            request = entry.get("request", {})
            try:
                allowed_url(request.get("url"))
            except InvalidResponse:
                continue
            if entry_index is None or index == entry_index:
                matches.append(request)
        if len(matches) != 1:
            raise ValueError
        request = matches[0]
        if request["method"] != "POST":
            raise ValueError
        post = request["postData"]
        if post.get("encoding") or post.get("_encoding") or "params" in post:
            raise ValueError
        body = post["text"].encode("utf-8")
        headers = [(item["name"], item["value"]) for item in request["headers"]]
    except KeyError, TypeError, ValueError, AttributeError, UnicodeError:
        raise InvalidResponse("invalid_capture") from None
    # HAR text does not prove wire fidelity; a successful G1 match is still needed.
    return _capture(headers, body, wire_exact=False, source="har_text")


def import_curl(data: str | bytes) -> ImportedCapture:
    try:
        text = data.decode("utf-8") if isinstance(data, bytes) else data
        if len(text.encode("utf-8")) > MAX_IMPORT_BYTES:
            raise ResponseTooLarge("response_too_large")
        # Conservative POSIX subset. PowerShell/cmd/bash ANSI-C quoting rejected.
        if any(item in text for item in ("$", "`", "|", ";", ">", "<", "\r")):
            raise ValueError
        args = shlex.split(text, posix=True)
        if not args or args.pop(0) != "curl":
            raise ValueError
        headers, urls, body = [], [], None
        method = None
        while args:
            arg = args.pop(0)
            if arg in ("-H", "--header"):
                name, sep, value = args.pop(0).partition(":")
                if not sep:
                    raise ValueError
                headers.append((name, value.strip()))
            elif arg in ("--data-raw", "--data-binary", "--data", "-d"):
                value = args.pop(0)
                if body is not None or value.startswith("@"):
                    raise ValueError
                body = value.encode("utf-8")
            elif arg in ("-X", "--request"):
                if method is not None:
                    raise ValueError
                method = args.pop(0)
            elif arg == "--url":
                urls.append(args.pop(0))
            elif arg.startswith("https://"):
                urls.append(arg)
            else:
                raise ValueError
        if len(urls) != 1 or method not in (None, "POST"):
            raise ValueError
        allowed_url(urls[0])
    except ValueError, IndexError, TypeError, UnicodeError, AttributeError:
        raise InvalidResponse("unsupported_curl_syntax") from None
    return _capture(headers, body, wire_exact=False, source="curl_posix")

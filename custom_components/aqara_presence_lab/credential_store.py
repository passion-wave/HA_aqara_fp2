"""Local HA secrets and private sessions, without credential-bearing diagnostics.

Passwords follow Home Assistant's plaintext secrets.yaml convention. Only secret
names belong in ConfigEntry.data. No encryption at rest is claimed here.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import secrets
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers.storage import Store
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode  # type: ignore[import-untyped]

from .api.auth import SessionCredentials
from .api.parsing import strict_json_loads

_LOCK_KEY = "aqara_presence_lab_credential_io_lock"
_MAX_SECRET_BYTES = 1024 * 1024
_REF = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}\Z")
_OWNED_ACCOUNT = re.compile(r"aqara_presence_lab_([0-9a-f]{32})_account\Z")
_ENTRY_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_TAGS = {
    f"tag:yaml.org,2002:{tag}"
    for tag in ("str", "null", "bool", "int", "float", "timestamp", "binary", "map", "seq")
}


class CredentialStoreError(Exception):
    """Only static error keys can leave the private storage boundary."""

    def __init__(self, error_key: str = "credential_store_failed") -> None:
        self.error_key = (
            error_key
            if error_key
            in {
                "secret_not_found",
                "invalid_secret",
                "invalid_secret_reference",
                "credential_store_failed",
                "unsafe_storage_path",
                "session_store_failed",
            }
            else "credential_store_failed"
        )
        super().__init__(self.error_key)


def _lock(hass: HomeAssistant) -> asyncio.Lock:
    return hass.data.setdefault(_LOCK_KEY, asyncio.Lock())


def _value(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 8192:
        raise CredentialStoreError("invalid_secret")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise CredentialStoreError("invalid_secret") from None
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise CredentialStoreError("invalid_secret")
    return str(value)


def _refs(account_secret: str, password_secret: str) -> tuple[str, str]:
    if (
        any(
            not isinstance(item, str) or not _REF.fullmatch(item)
            for item in (account_secret, password_secret)
        )
        or account_secret == password_secret
    ):
        raise CredentialStoreError("invalid_secret_reference")
    return account_secret, password_secret


def _root(config_dir: str) -> Path:
    path = Path(config_dir)
    if not path.is_absolute() or ".." in path.parts:
        raise CredentialStoreError("unsafe_storage_path")
    try:
        if not stat.S_ISDIR(path.lstat().st_mode):
            raise CredentialStoreError("unsafe_storage_path")
        return path.resolve(strict=True)
    except OSError:
        raise CredentialStoreError("unsafe_storage_path") from None


def _regular(path: Path, *, private: bool = False) -> os.stat_result | None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise CredentialStoreError("unsafe_storage_path")
    if private and metadata.st_mode & 0o077:
        raise CredentialStoreError("unsafe_storage_path")
    return metadata


def _read(path: Path, *, private: bool = False) -> bytes | None:
    metadata = _regular(path, private=private)
    if metadata is None:
        return None
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino) or not stat.S_ISREG(
            opened.st_mode
        ):
            raise CredentialStoreError("unsafe_storage_path")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            content = handle.read(_MAX_SECRET_BYTES + 1)
        if len(content) > _MAX_SECRET_BYTES:
            raise CredentialStoreError("invalid_secret")
        return content
    finally:
        os.close(descriptor)


@contextmanager
def _file_lock(root: Path, name: str) -> Iterator[None]:
    """Advisory lock shared by processes using this integration's writer."""
    import fcntl

    descriptor = os.open(root / name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or metadata.st_mode & 0o077:
            raise CredentialStoreError("unsafe_storage_path")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def _yaml(content: bytes | None) -> tuple[str, Node | None, dict[str, Node]]:
    """Parse without annotatedyaml logging or execution of !include/!env_var.

    HA's Secrets.get calls a loader which logs untrusted malformed YAML and even
    a 'logger' value. This constrained root-secrets parser deliberately uses only
    PyYAML nodes, preserving standard scalar-secret semantics and comments.
    """
    try:
        text = (content or b"").decode("utf-8")
        node = yaml.compose(text, Loader=yaml.SafeLoader)
        if node is None:
            return text, None, {}
        if (
            isinstance(node, ScalarNode)
            and node.tag == "tag:yaml.org,2002:null"
            and node.value == ""
        ):
            return text, node, {}
        if not isinstance(node, MappingNode) or node.flow_style:
            raise CredentialStoreError("invalid_secret")
        count = [0]

        def validate(current: Node, active: set[int], depth: int = 0) -> None:
            count[0] += 1
            if depth > 32 or count[0] > 10000 or id(current) in active or current.tag not in _TAGS:
                raise CredentialStoreError("invalid_secret")
            active = active | {id(current)}
            if isinstance(current, MappingNode):
                seen = set()
                for key, value in current.value:
                    if (
                        not isinstance(key, ScalarNode)
                        or key.tag != "tag:yaml.org,2002:str"
                        or key.value in seen
                    ):
                        raise CredentialStoreError("invalid_secret")
                    seen.add(key.value)
                    validate(value, active, depth + 1)
            elif isinstance(current, SequenceNode):
                for item in current.value:
                    validate(item, active, depth + 1)
            elif isinstance(current, ScalarNode):
                current.value.encode("utf-8")

        validate(node, set())
        return text, node, {key.value: value for key, value in node.value}
    except yaml.YAMLError, UnicodeError, ValueError, RecursionError:
        raise CredentialStoreError("invalid_secret") from None


def _resolve(config_dir: str, refs: tuple[str, str]) -> tuple[str, str]:
    try:
        root = _root(config_dir)
        _, _, mapping = _yaml(_read(root / "secrets.yaml"))
        resolved = []
        for ref in refs:
            node = mapping.get(ref)
            if node is None:
                raise CredentialStoreError("secret_not_found")
            if not isinstance(node, ScalarNode) or node.tag != "tag:yaml.org,2002:str":
                raise CredentialStoreError("invalid_secret")
            resolved.append(_value(node.value))
        return resolved[0], resolved[1]
    except OSError:
        raise CredentialStoreError() from None


def _atomic_write(path: Path, content: bytes, previous: bytes | None) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=".aqara-presence-lab-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        # Editors outside our advisory lock must not have their changes replaced.
        if _read(path) != previous:
            raise CredentialStoreError()
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if descriptor != -1:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _store(
    config_dir: str, account: str, password: str, existing_refs: tuple[str, str] | None
) -> tuple[str, str]:
    try:
        root = _root(config_dir)
        with _file_lock(root, ".aqara_presence_lab.secrets.lock"):
            path = root / "secrets.yaml"
            previous = _read(path)
            text, document, mapping = _yaml(previous)
            refs = None
            if existing_refs is not None:
                owned = _OWNED_ACCOUNT.fullmatch(existing_refs[0])
                if owned and existing_refs[1] == f"aqara_presence_lab_{owned[1]}_password":
                    nodes = [mapping.get(key) for key in existing_refs]
                    if all(
                        isinstance(node, ScalarNode)
                        and node.style == '"'
                        and text[node.start_mark.index : node.end_mark.index].startswith('"')
                        for node in nodes
                    ):
                        # Alias references may share a node; never edit an anchor.
                        if all(
                            sum(value is node for value in mapping.values()) == 1 for node in nodes
                        ):
                            refs = existing_refs
            if refs is None:
                while True:
                    prefix = f"aqara_presence_lab_{secrets.token_hex(16)}"
                    refs = f"{prefix}_account", f"{prefix}_password"
                    if all(ref not in mapping for ref in refs):
                        break
                addition = (
                    "\n# Aqara Presence Lab credentials (local plaintext secrets)\n"
                    + "".join(
                        f"{key}: {json.dumps(value, ensure_ascii=False)}\n"
                        for key, value in zip(refs, (account, password), strict=True)
                    )
                )
                position = document.end_mark.index if document else len(text)
                if position and text[position - 1] != "\n":
                    addition = "\n" + addition
                text = text[:position] + addition + text[position:]
            else:
                replacements = [
                    (
                        mapping[key].start_mark.index,
                        mapping[key].end_mark.index,
                        json.dumps(value, ensure_ascii=False),
                    )
                    for key, value in zip(refs, (account, password), strict=True)
                ]
                for start, end, value in sorted(replacements, reverse=True):
                    text = text[:start] + value + text[end:]
            encoded = text.encode("utf-8")
            if len(encoded) > _MAX_SECRET_BYTES:
                raise CredentialStoreError("invalid_secret")
            _yaml(encoded)
            _atomic_write(path, encoded, previous)
            return refs
    except OSError, UnicodeError, ValueError, TypeError:
        raise CredentialStoreError() from None


async def async_resolve_credentials(
    hass: HomeAssistant, account_secret: str, password_secret: str
) -> tuple[str, str]:
    """Resolve two named scalar entries in the root secrets.yaml."""
    refs = _refs(account_secret, password_secret)
    async with _lock(hass):
        return await hass.async_add_executor_job(_resolve, hass.config.config_dir, refs)


async def async_store_credentials(
    hass: HomeAssistant,
    account: str,
    password: str,
    *,
    existing_refs: tuple[str, str] | None = None,
) -> tuple[str, str]:
    """Store only owned keys atomically; unrelated bytes and old refs survive."""
    account, password = _value(account), _value(password)
    if existing_refs is not None:
        existing_refs = _refs(*existing_refs)
    async with _lock(hass):
        return await hass.async_add_executor_job(
            _store, hass.config.config_dir, account, password, existing_refs
        )


def _session_key(entry_id: str) -> str:
    if not isinstance(entry_id, str) or not _ENTRY_ID.fullmatch(entry_id):
        raise CredentialStoreError("unsafe_storage_path")
    return f"aqara_presence_lab.session.{hashlib.sha256(entry_id.encode()).hexdigest()}"


def _session_path(config_dir: str, key: str, *, create: bool = False) -> Path:
    root = _root(config_dir)
    directory = root / ".storage"
    if create:
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            pass
    try:
        if not stat.S_ISDIR(directory.lstat().st_mode):
            raise CredentialStoreError("unsafe_storage_path")
    except FileNotFoundError:
        return directory / key
    path = directory / key
    _regular(path, private=True)
    return path


def _session_data(config_dir: str, key: str) -> dict[str, Any] | None:
    try:
        raw = _read(_session_path(config_dir, key), private=True)
        if raw is None:
            return None
        envelope = strict_json_loads(raw, max_bytes=_MAX_SECRET_BYTES)
        if (
            not isinstance(envelope, dict)
            or set(envelope) != {"version", "minor_version", "key", "data"}
            or type(envelope.get("version")) is not int
            or envelope["version"] != 1
            or type(envelope.get("minor_version")) is not int
            or envelope["minor_version"] != 1
            or envelope.get("key") != key
            or not isinstance(envelope.get("data"), dict)
        ):
            raise CredentialStoreError("session_store_failed")
        return envelope["data"]
    except CredentialStoreError:
        raise
    except Exception:
        raise CredentialStoreError("session_store_failed") from None


class _PrivateSessionStore(Store[dict[str, Any]]):
    """Use HA's store lifecycle, with secure atomic writes and static errors."""

    async def async_save(self, data: dict[str, Any]) -> None:
        """Do not defer a credential write beyond its caller's transaction."""
        if self.hass.state is CoreState.stopping:
            raise CredentialStoreError("session_store_failed")
        await super().async_save(data)

    async def _async_write_data(self, data: dict[str, Any]) -> None:
        """Finish a started file write before cancellation releases our lock.

        Executor threads cannot be cancelled. An abandoned-flow cleanup must
        therefore wait until a started replacement has completed, otherwise a
        late replacement could recreate the token after cleanup deleted it.
        """
        pending = self.hass.async_add_executor_job(self._write_data, data)
        try:
            await asyncio.shield(pending)
        except asyncio.CancelledError:
            while not pending.done():
                try:
                    await asyncio.shield(pending)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if not pending.cancelled():
                pending.exception()
            raise

    async def _async_load_data(self) -> dict[str, Any] | None:
        """Keep untrusted session files out of HA's generic corruption logger.

        Read only once: a preflight followed by the stock reader could race with
        an external editor replacing the previously valid JSON file.
        """
        return await self.hass.async_add_executor_job(
            _session_data, self.hass.config.config_dir, self.key
        )

    def _write_prepared_data(self, mode: str, json_data: str | bytes) -> None:
        try:
            path = _session_path(self.hass.config.config_dir, self.key, create=True)
            with _file_lock(path.parent, ".aqara_presence_lab.sessions.lock"):
                previous = _read(path, private=True)
                content = json_data.encode("utf-8") if isinstance(json_data, str) else json_data
                _atomic_write(path, content, previous)
        except CredentialStoreError:
            raise
        except Exception:
            # This deliberately bypasses Store's WriteError logging with raw text.
            raise CredentialStoreError("session_store_failed") from None


def _session_store(hass: HomeAssistant, key: str) -> _PrivateSessionStore:
    return _PrivateSessionStore(
        hass, 1, key, private=True, atomic_writes=True, serialize_in_event_loop=False
    )


async def async_load_session(hass: HomeAssistant, entry_id: str) -> SessionCredentials | None:
    """Load a private token after restart; malformed files never enter HA logs."""
    key = _session_key(entry_id)
    async with _lock(hass):
        try:
            data = await _session_store(hass, key).async_load()
            if data is None:
                return None
            if not set(data) <= {"token", "user_id", "sys_type"}:
                raise CredentialStoreError("session_store_failed")
            kwargs = {"token": _value(data["token"]), "user_id": _value(data["user_id"])}
            if "sys_type" in data:
                if data["sys_type"] not in ("0", "1"):
                    raise CredentialStoreError("session_store_failed")
                kwargs["sys_type"] = data["sys_type"]
            return SessionCredentials(**kwargs)
        except CredentialStoreError:
            raise
        except Exception:
            raise CredentialStoreError("session_store_failed") from None


async def async_save_session(
    hass: HomeAssistant, entry_id: str, credentials: SessionCredentials
) -> None:
    """Persist a verified session separately from ConfigEntry.data."""
    key = _session_key(entry_id)
    data: dict[str, Any] = {
        "token": _value(credentials.token),
        "user_id": _value(credentials.user_id),
    }
    if (sys_type := getattr(credentials, "sys_type", None)) is not None:
        if sys_type not in ("0", "1"):
            raise CredentialStoreError("session_store_failed")
        data["sys_type"] = sys_type
    async with _lock(hass):
        try:
            await hass.async_add_executor_job(
                partial(_session_path, hass.config.config_dir, key, create=True)
            )
            await _session_store(hass, key).async_save(data)
            if (
                await hass.async_add_executor_job(_session_data, hass.config.config_dir, key)
                != data
            ):
                raise CredentialStoreError("session_store_failed")
        except CredentialStoreError:
            raise
        except Exception:
            raise CredentialStoreError("session_store_failed") from None


async def async_delete_session(hass: HomeAssistant, entry_id: str) -> None:
    """Delete only the owned session, retaining user-managed secrets.yaml keys."""
    key = _session_key(entry_id)
    async with _lock(hass):
        try:
            await hass.async_add_executor_job(_session_path, hass.config.config_dir, key)
            await _session_store(hass, key).async_remove()
        except CredentialStoreError:
            raise
        except Exception:
            raise CredentialStoreError("session_store_failed") from None

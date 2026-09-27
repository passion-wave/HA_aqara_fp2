"""Private local persistence: no Aqara access, no credential-bearing logs."""

import asyncio
import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from homeassistant.core import CoreState, HomeAssistant

from custom_components.aqara_presence_lab.api.auth import SessionCredentials
from custom_components.aqara_presence_lab.credential_store import (
    _MAX_SECRET_BYTES,
    CredentialStoreError,
    _PrivateSessionStore,
    _resolve,
    _session_key,
    _store,
    async_delete_session,
    async_load_session,
    async_resolve_credentials,
    async_save_session,
    async_store_credentials,
)


@pytest.fixture
def hass_storage():
    """Exercise actual HA Store files, not the plugin's secret-logging test double."""
    return {}


@pytest.fixture
def hass_config_dir(tmp_path):
    return str(tmp_path)


@pytest.fixture
def config(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    return tmp_path


async def test_store_resolve_restart_and_preserve_unrelated_bytes(hass, config):
    original = '# User comments remain exactly here\nother: "untouched" # inline\n\n'
    (config / "secrets.yaml").write_text(original)
    refs = await async_store_credentials(
        hass, "synthetic@example.test", "Synthetic: Pässword # one"
    )
    text = (config / "secrets.yaml").read_text()
    assert text.startswith(original)
    assert "synthetic" not in refs[0]
    assert refs[0].startswith("aqara_presence_lab_")
    assert refs[1] == refs[0].removesuffix("_account") + "_password"
    assert await async_resolve_credentials(hass, *refs) == (
        "synthetic@example.test",
        "Synthetic: Pässword # one",
    )
    # A fresh reader reopens the file, independent of any HA or YAML cache.
    assert await hass.async_add_executor_job(_resolve, str(config), refs) == (
        "synthetic@example.test",
        "Synthetic: Pässword # one",
    )
    assert (config / "secrets.yaml").stat().st_mode & 0o777 == 0o600


async def test_updates_only_owned_keys_and_keeps_comments(hass, config):
    refs = await async_store_credentials(hass, "old-account", "old-password")
    path = config / "secrets.yaml"
    path.write_text(
        path.read_text().replace('"old-account"', '"old-account" # keep inline')
        + 'unrelated: "keep"\n'
    )
    assert (
        await async_store_credentials(hass, "new-account", "new-password", existing_refs=refs)
        == refs
    )
    text = path.read_text()
    assert '"new-account" # keep inline' in text
    assert 'unrelated: "keep"' in text
    assert "old-password" not in text
    assert await async_resolve_credentials(hass, *refs) == ("new-account", "new-password")


async def test_user_named_secret_references_are_never_overwritten(hass, config):
    original = 'account: "original-user"\npassword: "original-password"\n'
    (config / "secrets.yaml").write_text(original)
    refs = await async_store_credentials(
        hass, "new-user", "new-password", existing_refs=("account", "password")
    )
    assert refs != ("account", "password")
    assert (config / "secrets.yaml").read_text().startswith(original)
    assert await async_resolve_credentials(hass, "account", "password") == (
        "original-user",
        "original-password",
    )


@pytest.mark.parametrize(
    "contents", ["# only comments\n", "---\n# before\n", "---\nother: ok\n...\n# after\n"]
)
async def test_comments_and_explicit_document_boundaries(hass, config, contents):
    path = config / "secrets.yaml"
    path.write_text(contents)
    refs = await async_store_credentials(hass, "account", "password")
    assert await async_resolve_credentials(hass, *refs) == ("account", "password")
    assert "#" in path.read_text()


async def test_alias_does_not_change_unrelated_data(hass, config):
    refs = await async_store_credentials(hass, "old-account", "old-password")
    path = config / "secrets.yaml"
    text = (
        path.read_text().replace('"old-password"', '&shared "old-password"')
        + "unrelated: *shared\n"
    )
    path.write_text(text)
    updated_refs = await async_store_credentials(
        hass, "new-account", "new-password", existing_refs=refs
    )
    assert updated_refs != refs
    assert path.read_text().startswith(text)
    assert await async_resolve_credentials(hass, *updated_refs) == ("new-account", "new-password")


@pytest.mark.parametrize(
    "contents",
    [
        'account: "SECRET\npassword: foo\n',
        "account: one\naccount: SECRET\npassword: two\n",
        "account: !include /SECRET/path\npassword: two\n",
        "account: !env_var SECRET\npassword: two\n",
        "- SECRET\n",
        "account: &recursive [*recursive]\npassword: x\n",
        "account: one\n---\npassword: SECRET\n",
        'account: "\\uD800"\npassword: x\n',
    ],
)
async def test_malformed_yaml_is_silent_and_not_rewritten(hass, config, contents, caplog):
    path = config / "secrets.yaml"
    path.write_text(contents)
    caplog.set_level(logging.DEBUG)
    for operation in (
        async_resolve_credentials(hass, "account", "password"),
        async_store_credentials(hass, "new", "SECRET-new"),
    ):
        with pytest.raises(CredentialStoreError) as caught:
            await operation
        assert "SECRET" not in str(caught.value) + repr(caught.value)
    assert path.read_text() == contents
    assert "SECRET" not in caplog.text


async def test_logger_key_is_data_and_does_not_log_credentials(hass, config, caplog):
    path = config / "secrets.yaml"
    path.write_text(
        'logger: SECRET-IN-LOGGER\naccount: "SECRET-user"\npassword: "SECRET-password"\n'
    )
    caplog.set_level(logging.DEBUG)
    assert await async_resolve_credentials(hass, "account", "password") == (
        "SECRET-user",
        "SECRET-password",
    )
    assert "SECRET" not in caplog.text


@pytest.mark.parametrize("value", ["", "a\nheader", "a\ud800", None, 1, "x" * 8193])
async def test_invalid_credentials_never_create_file(hass, config, value):
    with pytest.raises(CredentialStoreError):
        await async_store_credentials(hass, "valid", value)
    assert not (config / "secrets.yaml").exists()


@pytest.mark.parametrize(
    "refs",
    [
        ("../secret", "password"),
        ("account", "account"),
        ("", "password"),
        ("account name", "password"),
    ],
)
async def test_invalid_reference_names(hass, config, refs):
    with pytest.raises(CredentialStoreError) as caught:
        await async_resolve_credentials(hass, *refs)
    assert caught.value.error_key == "invalid_secret_reference"


async def test_missing_and_nonstrings_are_distinct(hass, config):
    with pytest.raises(CredentialStoreError) as caught:
        await async_resolve_credentials(hass, "account", "password")
    assert caught.value.error_key == "secret_not_found"
    path = config / "secrets.yaml"
    for value in ("null", "12345", "true", "[one, two]", "{key: val}"):
        path.write_text(f"account: user\npassword: {value}\n")
        with pytest.raises(CredentialStoreError) as caught:
            await async_resolve_credentials(hass, "account", "password")
        assert caught.value.error_key == "invalid_secret"


async def test_secrets_symlink_and_hardlink_are_rejected(hass, config, tmp_path):
    target = tmp_path / "outside.txt"
    target.write_text("account: original\npassword: untouched\n")
    path = config / "secrets.yaml"
    path.symlink_to(target)
    with pytest.raises(CredentialStoreError):
        await async_store_credentials(hass, "new", "password")
    with pytest.raises(CredentialStoreError):
        await async_resolve_credentials(hass, "account", "password")
    path.unlink()
    os.link(target, path)
    with pytest.raises(CredentialStoreError):
        await async_store_credentials(hass, "new", "password")
    assert target.read_text() == "account: original\npassword: untouched\n"


async def test_lock_symlink_is_rejected(hass, config):
    target = config / "unrelated"
    target.write_text("unchanged")
    (config / ".aqara_presence_lab.secrets.lock").symlink_to(target)
    with pytest.raises(CredentialStoreError):
        await async_store_credentials(hass, "user", "password")
    assert target.read_text() == "unchanged"


async def test_atomic_replace_failure_preserves_original_and_has_no_secret_log(
    hass, config, caplog
):
    refs = await async_store_credentials(hass, "old-user", "old-password")
    original = (config / "secrets.yaml").read_bytes()
    with patch(
        "custom_components.aqara_presence_lab.credential_store.os.replace",
        side_effect=OSError("SECRET-WRITE-ERROR"),
    ):
        with pytest.raises(CredentialStoreError) as caught:
            await async_store_credentials(hass, "new-user", "SECRET-password", existing_refs=refs)
    assert "SECRET" not in repr(caught.value) + caplog.text
    assert (config / "secrets.yaml").read_bytes() == original
    assert not list(config.glob(".aqara-presence-lab-*"))


async def test_appending_near_size_limit_does_not_commit_unreadable_file(hass, config):
    path = config / "secrets.yaml"
    original = b"account: user\npassword: old\n#" + b"x" * (_MAX_SECRET_BYTES - 100)
    assert len(original) < _MAX_SECRET_BYTES
    path.write_bytes(original)
    assert await async_resolve_credentials(hass, "account", "password") == ("user", "old")
    with pytest.raises(CredentialStoreError) as caught:
        await async_store_credentials(hass, "new-user", "new-password")
    assert caught.value.error_key == "invalid_secret"
    assert path.read_bytes() == original
    assert await async_resolve_credentials(hass, "account", "password") == ("user", "old")
    assert not list(config.glob(".aqara-presence-lab-*"))


async def test_parallel_async_writes_do_not_lose_secrets(hass, config):
    refs = await asyncio.gather(
        *(
            async_store_credentials(hass, f"account-{index}", f"password-{index}")
            for index in range(10)
        )
    )
    assert len({ref[0] for ref in refs}) == 10
    for index, pair in enumerate(refs):
        assert await async_resolve_credentials(hass, *pair) == (
            f"account-{index}",
            f"password-{index}",
        )


def test_independent_executor_writers_share_file_lock(tmp_path):
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [
            pool.submit(_store, str(tmp_path), f"user-{index}", f"password-{index}", None)
            for index in range(12)
        ]
        pairs = [future.result() for future in futures]
    assert len({pair[0] for pair in pairs}) == 12
    for index, refs in enumerate(pairs):
        assert _resolve(str(tmp_path), refs) == (f"user-{index}", f"password-{index}")


async def test_session_persistence_private_permissions_and_deletion(hass, config, caplog):
    caplog.set_level(logging.DEBUG)
    session = SessionCredentials("SECRET-session-token", "SECRET-user-id")
    assert await async_load_session(hass, "test-entry") is None
    await async_save_session(hass, "test-entry", session)
    path = config / ".storage" / _session_key("test-entry")
    assert path.stat().st_mode & 0o777 == 0o600
    assert await async_load_session(hass, "test-entry") == session
    assert "SECRET" not in repr(session) + caplog.text
    assert "test-entry" not in path.name
    await async_delete_session(hass, "test-entry")
    assert await async_load_session(hass, "test-entry") is None
    await async_delete_session(hass, "test-entry")


async def test_session_distinct_entries_and_parallel_updates(hass, config):
    sessions = [SessionCredentials(f"token-{index}", "user") for index in range(10)]
    await asyncio.gather(
        *(async_save_session(hass, f"entry-{index}", value) for index, value in enumerate(sessions))
    )
    assert (
        await asyncio.gather(*(async_load_session(hass, f"entry-{index}") for index in range(10)))
        == sessions
    )
    await asyncio.gather(*(async_save_session(hass, "same-entry", value) for value in sessions))
    assert await async_load_session(hass, "same-entry") in sessions


async def test_session_survives_fresh_ha_instance_with_sys_type(hass, config):
    session = SessionCredentials("token-after-restart", "same-user", "1")
    await async_save_session(hass, "independent-entry", session)
    restarted = HomeAssistant(str(config))
    try:
        assert await async_load_session(restarted, "independent-entry") == session
    finally:
        await restarted.async_stop(force=True)


async def test_bad_session_sys_type_is_sanitized(hass, config, caplog):
    await async_save_session(hass, "entry", SessionCredentials("token", "user"))
    path = config / ".storage" / _session_key("entry")
    envelope = json.loads(path.read_text())
    envelope["data"]["sys_type"] = "SECRET-invalid-type"
    path.write_text(json.dumps(envelope))
    with pytest.raises(CredentialStoreError) as caught:
        await async_load_session(hass, "entry")
    assert "SECRET" not in str(caught.value) + repr(caught.value) + caplog.text


@pytest.mark.parametrize(
    "contents",
    [
        b'{"SECRET":',
        b'{"version":1,"minor_version":"SECRET-VERSION","key":"x","data":{}}',
        b"[]",
        b'{"version":1,"version":1}',
        b'{"token":"SECRET"}',
    ],
)
async def test_corrupt_session_is_not_logged_or_renamed(hass, config, contents, caplog):
    directory = config / ".storage"
    directory.mkdir()
    path = directory / _session_key("entry")
    path.write_bytes(contents)
    path.chmod(0o600)
    with pytest.raises(CredentialStoreError) as caught:
        await async_load_session(hass, "entry")
    assert path.read_bytes() == contents
    assert "SECRET" not in repr(caught.value) + caplog.text
    assert not list(directory.glob("*.corrupt*"))


async def test_session_reader_never_invokes_raw_ha_corruption_logger(hass, config):
    session = SessionCredentials("token", "user", "1")
    await async_save_session(hass, "entry", session)
    with patch(
        "homeassistant.helpers.storage.json_util.load_json",
        side_effect=AssertionError("untrusted second read"),
    ):
        assert await async_load_session(hass, "entry") == session


async def test_session_read_os_error_is_sanitized(hass, config, caplog):
    await async_save_session(hass, "entry", SessionCredentials("token", "user"))
    with patch(
        "custom_components.aqara_presence_lab.credential_store._read",
        side_effect=OSError("SECRET read failure"),
    ):
        with pytest.raises(CredentialStoreError) as caught:
            await async_load_session(hass, "entry")
    assert "SECRET" not in str(caught.value) + repr(caught.value) + caplog.text


async def test_session_path_and_parent_symlinks_rejected(hass, config):
    target = config / "elsewhere"
    target.mkdir()
    directory = config / ".storage"
    directory.symlink_to(target, target_is_directory=True)
    session = SessionCredentials("secret", "user")
    with pytest.raises(CredentialStoreError):
        await async_save_session(hass, "entry", session)
    directory.unlink()
    directory.mkdir()
    external = config / "external"
    external.write_text("untouched")
    (directory / _session_key("entry")).symlink_to(external)
    for operation in (
        async_load_session(hass, "entry"),
        async_save_session(hass, "entry", session),
        async_delete_session(hass, "entry"),
    ):
        with pytest.raises(CredentialStoreError):
            await operation
    assert external.read_text() == "untouched"


async def test_session_write_failure_is_reported_without_credentials(hass, config, caplog):
    session = SessionCredentials("SECRET-token", "user")
    with patch(
        "custom_components.aqara_presence_lab.credential_store.os.replace",
        side_effect=OSError("SECRET failure"),
    ):
        with pytest.raises(CredentialStoreError) as caught:
            await async_save_session(hass, "entry", session)
    assert "SECRET" not in repr(caught.value) + caplog.text
    assert await async_load_session(hass, "entry") is None


async def test_cancelled_session_write_finishes_before_abandoned_session_cleanup(hass, config):
    started = asyncio.Event()
    release = threading.Event()
    original = _PrivateSessionStore._write_prepared_data

    def slow_write(store, mode, content):
        hass.loop.call_soon_threadsafe(started.set)
        assert release.wait(5), "Test did not release the local file writer"
        original(store, mode, content)

    with patch.object(_PrivateSessionStore, "_write_prepared_data", slow_write):
        writer = asyncio.create_task(
            async_save_session(hass, "entry", SessionCredentials("token", "user"))
        )
        await asyncio.wait_for(started.wait(), 2)
        writer.cancel()
        await asyncio.sleep(0)
        cleanup = asyncio.create_task(async_delete_session(hass, "entry"))
        await asyncio.sleep(0)
        try:
            assert not writer.done()
            assert not cleanup.done()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await writer
        await cleanup
    assert await async_load_session(hass, "entry") is None
    assert not list((config / ".storage").glob(".aqara-presence-lab-*"))


async def test_stopping_session_save_never_defers_write_after_transaction(hass, config):
    original_state = hass.state
    hass.set_state(CoreState.stopping)
    try:
        with patch.object(_PrivateSessionStore, "_async_ensure_final_write_listener") as defer:
            with pytest.raises(CredentialStoreError):
                await async_save_session(hass, "entry", SessionCredentials("token", "user"))
        defer.assert_not_called()
    finally:
        hass.set_state(original_state)
    assert await async_load_session(hass, "entry") is None


async def test_too_open_session_is_refused(hass, config):
    await async_save_session(hass, "entry", SessionCredentials("token", "user"))
    path = config / ".storage" / _session_key("entry")
    path.chmod(0o644)
    with pytest.raises(CredentialStoreError):
        await async_load_session(hass, "entry")


@pytest.mark.parametrize("entry_id", ["../secrets.yaml", "/tmp/x", "", "with space", "x" * 129])
async def test_session_id_cannot_select_paths(hass, config, entry_id):
    with pytest.raises(CredentialStoreError):
        await async_save_session(hass, entry_id, SessionCredentials("token", "user"))
    assert not (config / ".storage").exists()


def test_error_repr_only_uses_allowlisted_key():
    error = CredentialStoreError("SECRET arbitrary text")
    assert "SECRET" not in repr(error) + str(error) + error.error_key

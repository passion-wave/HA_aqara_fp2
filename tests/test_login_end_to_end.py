"""Whole login lifecycle with real HA storage and synthetic HTTP responses."""

import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.data_entry_flow import FlowResultType

from custom_components.aqara_presence_lab.api.account import ManagedAqaraClient
from custom_components.aqara_presence_lab.api.rate_limit import AccountRateLimiter
from custom_components.aqara_presence_lab.const import DOMAIN
from custom_components.aqara_presence_lab.credential_store import async_load_session
from tests.transport_helpers import Clock, Response

ROOT = "custom_components.aqara_presence_lab"
ACCOUNT = "end-to-end-account@example.invalid"
PASSWORD = "end-to-end-password-sensitive"
USER_ID = "end-to-end-server-user"
FIRST_TOKEN = "end-to-end-first-sensitive-token"
SECOND_TOKEN = "end-to-end-second-sensitive-token"
DEVICE_IDS = ["lumi1.000000000001", "lumi1.000000000002"]


@pytest.fixture
def hass_storage():
    # The default HA test Store mock logs its complete payload, including tokens.
    return {}


@pytest.fixture
def hass_config_dir(tmp_path):
    return str(tmp_path)


class QueuedSession:
    trust_env = False

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        assert self.responses, "Unexpected extra HTTP call"
        return self.responses.pop(0)


def login_response(token):
    return Response(json.dumps({"code": 0, "result": {"token": token, "userId": USER_ID}}).encode())


def device_response():
    return Response(Path("fixtures/trait_read.response.json").read_bytes())


async def test_real_flow_storage_startup_expiry_renewal_and_restart(
    hass, tmp_path, monkeypatch, caplog
):
    hass.config.config_dir = str(tmp_path)
    caplog.set_level(logging.DEBUG)
    clock = Clock()
    limiter = AccountRateLimiter(clock=clock, jitter=lambda: 0)
    session = QueuedSession(
        [
            login_response(FIRST_TOKEN),
            device_response(),  # flow validates
            device_response(),  # setup reuses stored session
            Response(b'{"code":108,"msgDetails":"Token has expired"}'),
            login_response(SECOND_TOKEN),
            device_response(),  # renewal validates + saves
            device_response(),  # restart reuses new token
        ]
    )

    async def advance(seconds):
        clock.tick += seconds

    def managed(*args, **kwargs):
        return ManagedAqaraClient(*args, **kwargs, sleep=advance)

    monkeypatch.setattr(f"{ROOT}.coordinator.AccountRateLimiter", lambda: limiter)
    monkeypatch.setattr(f"{ROOT}.coordinator.ManagedAqaraClient", managed)
    monkeypatch.setattr(f"{ROOT}.coordinator.async_get_clientsession", lambda hass: session)

    # Run the actual HTTP/RSA/parser/auth stack; only network IO is replaced.
    with patch.object(hass.config_entries, "async_setup", AsyncMock(return_value=True)):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "live"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"allow_experimental_cloud": True}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "credentials"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "region": "EU",
                "account": ACCOUNT,
                "password": PASSWORD,
                "device_ids": "\n".join(DEVICE_IDS),
            },
        )
        assert result["type"] == FlowResultType.SHOW_PROGRESS
        await hass.async_block_till_done()
        result = await hass.config_entries.flow.async_configure(result["flow_id"])
        assert result["step_id"] == "devices"
        assert len(session.calls) == 2
        assert not (tmp_path / "secrets.yaml").exists()
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "device_ids": DEVICE_IDS,
                "poll_interval": 300,
            },
        )
        assert result["type"] == FlowResultType.CREATE_ENTRY
        entry = result["result"]
        await hass.async_block_till_done()

    assert not {"account", "password", "token"}.intersection(entry.data)
    assert len(session.calls) == 2
    saved = await async_load_session(hass, entry.data["session_store_id"])
    assert saved.token == FIRST_TOKEN and saved.sys_type == "1"
    assert (tmp_path / "secrets.yaml").stat().st_mode & 0o777 == 0o600
    original_unique_id = entry.unique_id

    clock.tick += 60
    with (
        patch.object(hass.config_entries, "async_forward_entry_setups", AsyncMock()),
        patch.object(hass.config_entries, "async_unload_platforms", AsyncMock(return_value=True)),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        assert len(session.calls) == 3
        coordinator = entry.runtime_data
        clock.tick += 300
        coordinator._last_attempt = None
        snapshot = await coordinator._async_update_data()
        assert len(snapshot.devices) == 2
        assert len(session.calls) == 6
        saved = await async_load_session(hass, entry.data["session_store_id"])
        assert saved.token == SECOND_TOKEN
        assert entry.unique_id == original_unique_id
        assert await hass.config_entries.async_unload(entry.entry_id)

        clock.tick += 300
        assert await hass.config_entries.async_setup(entry.entry_id)
        assert len(session.calls) == 7
        assert session.calls[-1][1]["headers"]["Token"] == SECOND_TOKEN
        assert await hass.config_entries.async_unload(entry.entry_id)

    login_calls = [kwargs for url, kwargs in session.calls if url.endswith("/user/login")]
    assert len(login_calls) == 2
    for kwargs in login_calls:
        assert "Token" not in kwargs["headers"]
        assert kwargs["headers"]["Sys-Type"] == "1"
        body = json.loads(kwargs["data"])
        assert body["account"] == ACCOUNT and body["password"] != PASSWORD
        assert kwargs["ssl"] is True and kwargs["allow_redirects"] is False
    assert not session.responses
    for secret in (ACCOUNT, PASSWORD, FIRST_TOKEN, SECOND_TOKEN, USER_ID):
        assert secret not in caplog.text
    assert FIRST_TOKEN not in json.dumps(dict(entry.data))
    assert SECOND_TOKEN not in json.dumps(dict(entry.data))

"""Whole login lifecycle with real HA storage and synthetic HTTP responses."""

import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from custom_components.aqara_presence_lab.api.account import ManagedAqaraClient
from custom_components.aqara_presence_lab.api.rate_limit import AccountRateLimiter
from custom_components.aqara_presence_lab.const import DOMAIN
from custom_components.aqara_presence_lab.coordinator import AqaraCoordinator
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

    @property
    def primary_calls(self):
        return [(url, kwargs) for url, kwargs in self.calls if "/res/query" not in url]

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if "/res/query" in url:
            device_id = json.loads(kwargs["data"])["data"][0]["subjectId"]
            if url.endswith("/by/resourceId"):
                result = [{"resourceId": "14.1.85", "value": "3", "subjectId": device_id}]
            else:
                values = {
                    "lux": 14 if device_id == DEVICE_IDS[0] else 115,
                    "set_device_mode4": 9 if device_id == DEVICE_IDS[0] else 3,
                    "heartrate_value": 65,
                    "respiration_rate_value": 14,
                    "sleep_state": "2",
                    "people_counting": 1.5,
                    "detection_area1": 1,
                    "device_offline_status": 1,
                }
                result = [
                    {"subjectId": device_id, "attr": attr, "value": value}
                    for attr, value in values.items()
                ]
            return Response(json.dumps({"code": 0, "result": result}).encode())
        assert self.responses, "Unexpected extra HTTP call"
        return self.responses.pop(0)


def login_response(token):
    return Response(json.dumps({"code": 0, "result": {"token": token, "userId": USER_ID}}).encode())


def device_response():
    return Response(Path("fixtures/trait_read.response.json").read_bytes())


async def resource_tick(coordinator):
    """Drive one local scheduler timer; the real shared limiter controls HTTP."""
    if coordinator._resource_timer is not None:
        coordinator._resource_timer.cancel()
    coordinator._async_supplemental_timer()
    if coordinator._resource_task is not None:
        await coordinator._resource_task


async def finish_initial_resources(coordinator):
    if coordinator._resource_task is not None:
        await coordinator._resource_task
    for _ in range(4 - coordinator.resource_successful_reads):
        await resource_tick(coordinator)
    assert coordinator.resource_successful_reads == 4


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
    monkeypatch.setattr(
        f"{ROOT}.AqaraCoordinator",
        lambda hass, entry, client: AqaraCoordinator(hass, entry, client, clock=clock.monotonic),
    )

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
        assert len(session.primary_calls) == 2
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
    assert len(session.primary_calls) == 2
    saved = await async_load_session(hass, entry.data["session_store_id"])
    assert saved.token == FIRST_TOKEN and saved.sys_type == "1"
    assert (tmp_path / "secrets.yaml").stat().st_mode & 0o777 == 0o600
    original_unique_id = entry.unique_id

    clock.tick += 60
    # Exercise the actual entity platforms, unload and restart as well.
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert len(session.primary_calls) == 3
    coordinator = entry.runtime_data
    await finish_initial_resources(coordinator)
    await hass.async_block_till_done()
    assert coordinator.supplemental_status == "ready"
    assert coordinator.resource_successful_reads == 4
    registry = er.async_get(hass)

    def registered(device_id, key):
        return next(
            (
                entity
                for entity in registry.entities.values()
                if entity.config_entry_id == entry.entry_id
                and entity.unique_id.endswith(f":{device_id}:{key}")
            ),
            None,
        )

    heart = registered(DEVICE_IDS[0], "resource_heartrate_value")
    assert heart is not None
    assert hass.states.get(heart.entity_id).state == "65"
    assert hass.states.get(heart.entity_id).attributes["unit_of_measurement"] == "bpm"
    assert registered(DEVICE_IDS[1], "resource_heartrate_value") is None
    for device_id, lux in zip(DEVICE_IDS, (14, 115), strict=True):
        resource_lux = registered(device_id, "resource_lux")
        assert hass.states.get(resource_lux.entity_id).state == str(lux)
        assert registered(device_id, "resource_detection_area1").disabled_by is not None
        assert registered(device_id, "setting_presence_detection_sens").disabled_by is not None
        assert registered(device_id, "resource_detection_area2") is None
    assert hass.states.get(heart.entity_id).attributes["data_quality"] == "unverified"
    assert "state_class" not in hass.states.get(heart.entity_id).attributes
    clock.tick += 300
    coordinator._last_attempt = None
    snapshot = await coordinator._async_update_data()
    assert len(snapshot.devices) == 2
    # QLINK renewal does not trigger another settings sweep. The independently
    # scheduled next tick reads one due hot group with the renewed token.
    assert coordinator.resource_successful_reads == 4
    await resource_tick(coordinator)
    assert coordinator.resource_successful_reads == 5
    assert len(session.primary_calls) == 6
    saved = await async_load_session(hass, entry.data["session_store_id"])
    assert saved.token == SECOND_TOKEN
    assert entry.unique_id == original_unique_id
    assert await hass.config_entries.async_unload(entry.entry_id)

    clock.tick += 300
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert len(session.primary_calls) == 7
    restarted = entry.runtime_data
    await finish_initial_resources(restarted)
    await hass.async_block_till_done()
    assert session.primary_calls[-1][1]["headers"]["Token"] == SECOND_TOKEN
    assert restarted.resource_successful_reads == 4
    assert registered(DEVICE_IDS[0], "resource_heartrate_value").entity_id == heart.entity_id
    assert hass.states.get(heart.entity_id).state == "65"
    assert await hass.config_entries.async_unload(entry.entry_id)

    login_calls = [kwargs for url, kwargs in session.calls if url.endswith("/user/login")]
    assert len(login_calls) == 2
    for kwargs in login_calls:
        assert "Token" not in kwargs["headers"]
        assert kwargs["headers"]["Sys-Type"] == "1"
        body = json.loads(kwargs["data"])
        assert body["account"] == ACCOUNT and body["password"] != PASSWORD
        assert kwargs["ssl"] is True and kwargs["allow_redirects"] is False
    resource_calls = [(url, kwargs) for url, kwargs in session.calls if "/res/query" in url]
    assert len(resource_calls) == 9
    assert sum(url.endswith("/by/resourceId") for url, _ in resource_calls) == 4
    for index, (_url, kwargs) in enumerate(resource_calls):
        expected_token = FIRST_TOKEN if index < 4 else SECOND_TOKEN
        assert kwargs["headers"]["Token"] == expected_token
        assert len(json.loads(kwargs["data"])["data"]) == 1
    assert not session.responses
    for secret in (ACCOUNT, PASSWORD, FIRST_TOKEN, SECOND_TOKEN, USER_ID):
        assert secret not in caplog.text
    assert FIRST_TOKEN not in json.dumps(dict(entry.data))
    assert SECOND_TOKEN not in json.dumps(dict(entry.data))

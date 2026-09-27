"""Run the integration against Home Assistant with all network sockets blocked."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.aqara_presence_lab.api.models import AccountIdentity
from custom_components.aqara_presence_lab.api.parsing import parse_response
from custom_components.aqara_presence_lab.api.resources import DeviceResources
from custom_components.aqara_presence_lab.const import DOMAIN


@pytest.fixture
def aqara_snapshot():
    return parse_response(
        (Path(__file__).parent.parent / "fixtures/trait_read.response.json").read_bytes(),
        received_at=datetime(2026, 9, 26, tzinfo=UTC),
    )


@pytest.fixture
def aqara_entry():
    return MockConfigEntry(
        domain=DOMAIN,
        title="Aqara Presence Lab (EU)",
        version=2,
        unique_id=AccountIdentity("EU", "synthetic-user").account_key,
        data={
            "region": "EU",
            "user_id": "synthetic-user",
            "account_secret": "aqara_test_account",
            "password_secret": "aqara_test_password",
            "session_store_id": "synthetic-session-store",
            "allow_experimental_cloud": True,
            "device_ids": ["lumi1.000000000001", "lumi1.000000000002"],
            "poll_interval": 300,
        },
    )


@pytest.fixture
def aqara_client(aqara_snapshot):
    async def empty_resources(device_id):
        return DeviceResources(
            device_id=device_id, observations={}, received_at_utc=aqara_snapshot.received_at_utc
        )

    return SimpleNamespace(
        async_validate_credentials=AsyncMock(return_value=AccountIdentity("EU", "synthetic-user")),
        async_read_traits=AsyncMock(return_value=aqara_snapshot),
        async_read_resources=AsyncMock(side_effect=empty_resources),
        async_read_resource_settings=AsyncMock(side_effect=empty_resources),
        async_close=AsyncMock(),
        limiter=SimpleNamespace(retry_after=60),
    )


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    """Allow loading this repository's custom integration in HA tests."""
    yield

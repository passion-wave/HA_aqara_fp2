"""Accelerated reads keep one shared budget and conservative authentication."""

import asyncio

import pytest

from custom_components.aqara_presence_lab.api.errors import RateLimited, TransportError
from custom_components.aqara_presence_lab.api.rate_limit import AccountRateLimiter
from tests.test_account import OLD, expiry_reply, login_reply, managed, read_reply
from tests.transport_helpers import Clock, Response


@pytest.mark.parametrize("spacing", [5, 10, 15, 30])
async def test_read_spacing_has_one_request_per_slot(spacing):
    clock = Clock()
    limiter = AccountRateLimiter(clock=clock, jitter=lambda: 0)
    limiter.configure_read_spacing(spacing)
    results = await asyncio.gather(
        *(limiter.async_claim() for _ in range(4)), return_exceptions=True
    )
    assert results.count(None) == 1
    rejected = [result for result in results if isinstance(result, RateLimited)]
    assert len(rejected) == 3
    assert all(error.retry_after == spacing and not error.request_sent for error in rejected)
    assert limiter.last_request_monotonic == clock.tick
    clock.tick += spacing - 0.001
    with pytest.raises(RateLimited):
        await limiter.async_claim()
    clock.tick += 0.001
    await limiter.async_claim()


@pytest.mark.parametrize("invalid", [True, False, 5.0, 0, -5, 6, 60, "5", None])
def test_read_spacing_rejects_unsupported_input_without_mutation(invalid):
    limiter = AccountRateLimiter(clock=Clock())
    with pytest.raises(ValueError, match="^invalid_request_spacing$"):
        limiter.configure_read_spacing(invalid)
    assert limiter.read_spacing == limiter.requested_read_spacing == 30


async def test_read_acceleration_does_not_erase_existing_slot():
    clock = Clock()
    limiter = AccountRateLimiter(clock=clock)
    await limiter.async_claim()
    clock.tick += 5
    limiter.configure_read_spacing(5)
    assert limiter.retry_after == 25
    with pytest.raises(RateLimited):
        await limiter.async_claim()
    clock.tick += 25
    await limiter.async_claim()
    assert limiter.retry_after == 5


@pytest.mark.parametrize("action", ["suspend", "increase_spacing"])
async def test_slower_profile_applies_to_in_flight_request_slot(action):
    clock = Clock()
    limiter = AccountRateLimiter(clock=clock)
    limiter.configure_read_spacing(5)
    await limiter.async_claim()
    clock.tick += 2
    if action == "suspend":
        limiter.suspend_acceleration()
    else:
        limiter.configure_read_spacing(30)
    assert limiter.read_spacing == 30
    assert limiter.retry_after == 28
    clock.tick += 3
    with pytest.raises(RateLimited) as caught:
        await limiter.async_claim()
    assert caught.value.retry_after == 25


async def test_failure_preserves_requested_setting_but_success_cannot_resume_it():
    clock = Clock()
    limiter = AccountRateLimiter(clock=clock, jitter=lambda: 0)
    limiter.configure_read_spacing(5)
    await limiter.async_claim()
    assert limiter.failure(900) == 900
    assert limiter.requested_read_spacing == 5
    assert limiter.read_spacing == 30
    limiter.success()
    limiter.configure_read_spacing(5)
    assert limiter.read_spacing == 30
    assert limiter.retry_after == 900
    limiter.configure_read_spacing(5, reset_suspension=True)
    assert limiter.read_spacing == 5
    assert limiter.retry_after == 900
    clock.tick += 900
    await limiter.async_claim()
    assert limiter.retry_after == 5


async def test_authentication_stays_thirty_seconds_away_from_adjacent_reads():
    clock = Clock()
    limiter = AccountRateLimiter(clock=clock)
    limiter.configure_read_spacing(5)
    await limiter.async_claim()
    clock.tick += 5
    await limiter.async_claim()
    assert limiter.retry_after == 5
    assert limiter.authentication_retry_after == 30
    clock.tick += 5
    with pytest.raises(RateLimited) as caught:
        await limiter.async_claim(authentication=True)
    assert caught.value.retry_after == 25
    clock.tick += 25
    await limiter.async_claim(authentication=True)
    assert limiter.retry_after == 30
    clock.tick += 5
    with pytest.raises(RateLimited):
        await limiter.async_claim()
    clock.tick += 25
    await limiter.async_claim()
    assert limiter.retry_after == 5


async def test_acceleration_never_shortens_authentication_server_backoff():
    clock = Clock()
    limiter = AccountRateLimiter(clock=clock, jitter=lambda: 0)
    await limiter.async_claim(authentication=True)
    limiter.failure(600)
    limiter.configure_read_spacing(5, reset_suspension=True)
    assert limiter.authentication_retry_after == limiter.retry_after == 600
    with pytest.raises(RateLimited) as caught:
        await limiter.async_claim(authentication=True)
    assert caught.value.retry_after == 600


async def test_managed_session_expiry_uses_auth_spacing_with_fast_reads():
    api, low, http, loader, writer, waits = managed(
        [expiry_reply(), login_reply(), read_reply(["d1"])], initial=OLD
    )
    low.limiter.configure_read_spacing(5)
    result = await api.async_read_traits(["d1"])
    assert result.devices["d1"].available
    assert waits == [30, 30]
    assert [call[0] for call in http.calls] == [1000, 1030, 1060]
    assert api.limiter.retry_after == 5
    loader.assert_awaited_once()
    writer.assert_awaited_once()
    await api.async_close()


async def test_initial_login_keeps_thirty_seconds_before_first_fast_read():
    api, low, http, _, _, waits = managed([login_reply(), read_reply(["d1"]), read_reply(["d1"])])
    low.limiter.configure_read_spacing(5)
    await api.async_read_traits(["d1"])
    await api.async_read_traits(["d1"])
    assert waits == [30, 5]
    assert [call[0] for call in http.calls] == [1000, 1030, 1035]
    await api.async_close()


@pytest.mark.parametrize(
    ("response", "error", "delay"),
    [
        (Response(status=429, headers={"Retry-After": "900"}), RateLimited, 900),
        (Response(status=503), TransportError, 60),
        (TimeoutError("synthetic-secret"), TransportError, 60),
    ],
)
async def test_transport_error_suspends_fast_profile_without_hidden_retry(response, error, delay):
    api, low, http, loader, writer, waits = managed([response], initial=OLD)
    low.limiter.configure_read_spacing(5)
    with pytest.raises(error):
        await api.async_read_traits(["d1"])
    assert len(http.calls) == 1
    assert low.limiter.read_spacing == 30
    assert low.limiter.requested_read_spacing == 5
    assert low.limiter.retry_after == delay
    assert not waits
    loader.assert_not_called()
    writer.assert_not_called()
    await api.async_close()

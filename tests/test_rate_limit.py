from datetime import UTC, datetime
from email.utils import format_datetime

import pytest

from custom_components.aqara_presence_lab.api.errors import RateLimited
from custom_components.aqara_presence_lab.api.rate_limit import (
    AccountRateLimiter,
    parse_retry_after,
)
from tests.transport_helpers import Clock


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("120", 120),
        ("0", 0),
        ("-1", None),
        ("1.5", None),
        ("Infinity", None),
        ("", None),
        (None, None),
        ("x" * 129, None),
    ],
)
def test_retry_after_seconds(value, expected):
    assert parse_retry_after(value, datetime.now(UTC)) == expected


def test_retry_after_date_and_past():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    assert parse_retry_after(format_datetime(datetime(2026, 1, 1, 0, 2, tzinfo=UTC)), now) == 120
    assert parse_retry_after(format_datetime(datetime(2025, 1, 1, tzinfo=UTC)), now) == 0


async def test_shared_cooldown_backoff_and_server_pause():
    clock = Clock()
    limiter = AccountRateLimiter(clock=clock, cooldown=0, jitter=lambda: 0)
    await limiter.async_claim()
    with pytest.raises(RateLimited) as error:
        await limiter.async_claim()
    assert error.value.retry_after == 30
    assert error.value.request_sent is False
    assert limiter.failure() == 60
    assert limiter.failure() == 120
    assert limiter.failure(9000) == 9000
    clock.tick += 9000
    await limiter.async_claim()
    limiter.success()
    assert limiter.failure() == 60
    for _ in range(20):
        limiter.failure()
    assert limiter.retry_after == 3600


def test_request_sent_marker_is_optional_exact_bool_and_never_in_exception_text():
    assert RateLimited().request_sent is False
    assert RateLimited(30).request_sent is False
    assert RateLimited(30, request_sent=True).request_sent is True
    assert RateLimited(30, request_sent="SECRET").request_sent is False
    assert "SECRET" not in repr(RateLimited(30, request_sent="SECRET"))

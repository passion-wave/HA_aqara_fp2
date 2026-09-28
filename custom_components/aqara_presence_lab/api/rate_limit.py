"""Shared monotonic account cooldown and conservative bounded backoff."""

from __future__ import annotations

import asyncio
import math
import random
import time
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from .errors import RateLimited


class SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def now(self) -> datetime:
        return datetime.now(UTC)


def parse_retry_after(value: str | None, now: datetime) -> float | None:
    if not value or len(value) > 128:
        return None
    try:
        if value.isascii() and value.isdecimal():
            seconds = float(value)
        else:
            target = parsedate_to_datetime(value)
            if target.tzinfo is None:
                return None
            seconds = (target - now).total_seconds()
        return max(0.0, seconds) if math.isfinite(seconds) else None
    except ValueError, OverflowError, TypeError:
        return None


class AccountRateLimiter:
    """No hidden sleeps/retries: the coordinator decides when to try again."""

    def __init__(
        self,
        *,
        clock: SystemClock | None = None,
        cooldown: float = 30,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self.clock = clock or SystemClock()
        self.cooldown = max(30.0, cooldown)
        self._requested_spacing = self.cooldown
        self._last_claim: float | None = None
        self._jitter = jitter
        self._next = 0.0
        self._failures = 0
        self._lock = asyncio.Lock()

    @property
    def retry_after(self) -> float:
        return max(0.0, self._next - self.clock.monotonic())

    @property
    def read_spacing(self) -> float:
        """Effective spacing; errors suspend an accelerated setting."""
        return self.cooldown

    @property
    def requested_read_spacing(self) -> float:
        return self._requested_spacing

    @property
    def last_request_monotonic(self) -> float | None:
        """Timestamp of the latest claimed request, without request metadata."""
        return self._last_claim

    def suspend_acceleration(self) -> None:
        """Return to conservative spacing without shortening any backoff."""
        self.cooldown = max(30.0, self.cooldown)
        if self._last_claim is not None:
            self._next = max(self._next, self._last_claim + self.cooldown)

    @property
    def authentication_retry_after(self) -> float:
        previous = self._last_claim
        return max(
            self.retry_after, 0.0 if previous is None else previous + 30 - self.clock.monotonic()
        )

    def configure_read_spacing(self, seconds: int, *, reset_suspension: bool = False) -> None:
        """Explicit experimental read profile; never shorten an existing pause."""
        if type(seconds) is not int or seconds not in (5, 10, 15, 30):
            raise ValueError("invalid_request_spacing")
        if seconds != self._requested_spacing or reset_suspension:
            self._requested_spacing = self.cooldown = float(seconds)
            if self._last_claim is not None:
                self._next = max(self._next, self._last_claim + self.cooldown)

    async def async_claim(self, *, authentication: bool = False) -> None:
        async with self._lock:
            delay = self.authentication_retry_after if authentication else self.retry_after
            if delay > 0:
                raise RateLimited(delay)
            self._last_claim = self.clock.monotonic()
            self._next = self._last_claim + (
                max(30.0, self.cooldown) if authentication else self.cooldown
            )

    def failure(self, retry_after: float | None = None) -> float:
        self.suspend_acceleration()
        self._failures = min(7, self._failures + 1)
        backoff = min(3600.0, 60.0 * 2 ** (self._failures - 1))
        # Positive jitter never shortens a server Retry-After requirement.
        backoff = min(3600.0, backoff * (1 + 0.1 * max(0.0, min(1.0, self._jitter()))))
        delay = max(backoff, retry_after or 0)
        self._next = max(self._next, self.clock.monotonic() + delay)
        return self.retry_after

    def success(self) -> None:
        self._failures = 0

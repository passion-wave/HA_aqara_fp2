"""Transport age is monotonic; trait freshness needs validated semantics."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from custom_components.aqara_presence_lab.api.freshness import (
    evaluate_freshness,
    transport_expired,
    utc_datetime,
)

NOW = datetime(2026, 9, 26, tzinfo=UTC)
OLD = int((NOW - timedelta(days=1000)).timestamp() * 1000)


def test_old_unverified_time_is_reported_never_automatically_stale():
    assert evaluate_freshness(OLD, NOW) == "reported"
    assert evaluate_freshness(None, NOW) == "reported"
    assert evaluate_freshness(OLD, NOW, semantics="validated_change") == "current_validated"
    assert (
        evaluate_freshness(OLD, NOW, semantics="validated_measurement", max_age_seconds=300)
        == "stale_confirmed"
    )


def test_recent_measurement_only_current_after_validation():
    recent = int((NOW - timedelta(seconds=30)).timestamp() * 1000)
    assert evaluate_freshness(recent, NOW) == "reported"
    assert (
        evaluate_freshness(recent, NOW, semantics="validated_measurement", max_age_seconds=300)
        == "current_validated"
    )


@pytest.mark.parametrize(
    ("status", "expected"), [("missing", "missing"), ("null", "missing"), ("invalid", "invalid")]
)
def test_value_state_beats_timestamp(status, expected):
    assert evaluate_freshness(OLD, NOW, value_status=status) == expected


@pytest.mark.parametrize("semantics", ["unknown", "validated_change", "validated_measurement"])
def test_future_time_always_anomaly(semantics):
    assert (
        evaluate_freshness(
            int(NOW.timestamp() * 1000) + 1, NOW, semantics=semantics, max_age_seconds=300
        )
        == "clock_anomaly"
    )


@pytest.mark.parametrize("source", [-1, True, 1.2, "1"])
def test_invalid_times(source):
    assert evaluate_freshness(source, NOW) == "invalid"


@pytest.mark.parametrize("age", [None, 0, -1, float("nan"), float("inf")])
def test_measurement_semantics_needs_valid_age(age):
    with pytest.raises(ValueError):
        evaluate_freshness(OLD, NOW, semantics="validated_measurement", max_age_seconds=age)


def test_transport_age_without_any_successful_requests():
    assert transport_expired(None, 100, 600)
    assert not transport_expired(100, 500, 600)
    assert transport_expired(100, 701, 600)
    assert transport_expired(100, 99, 600)
    assert transport_expired(100, float("nan"), 600)


def test_timezone_is_explicit_and_utc():
    assert utc_datetime(datetime(2026, 9, 26, 2, tzinfo=timezone(timedelta(hours=2)))) == NOW
    with pytest.raises(ValueError):
        evaluate_freshness(OLD, datetime(2026, 9, 26))

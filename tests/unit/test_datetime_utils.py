"""
Unit tests for the datetime utility module.
"""

from datetime import datetime, timezone

import pytest

from core.utils.datetime import format_date_hint, localize, utcnow


class TestUtcnow:
    def test_returns_aware_datetime(self):
        now = utcnow()
        assert now.tzinfo is not None
        assert now.tzinfo == timezone.utc

    def test_returns_current_time(self):
        before = datetime.now(tz=timezone.utc)
        now = utcnow()
        after = datetime.now(tz=timezone.utc)
        assert before <= now <= after


class TestLocalize:
    def test_localize_naive_datetime(self):
        dt = datetime(2024, 6, 1, 12, 0, 0)
        result = localize(dt, "Europe/Moscow")
        assert result.tzinfo is not None

    def test_localize_aware_datetime_converts(self):
        dt = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        result = localize(dt, "US/Eastern")
        assert result.tzinfo is not None
        # UTC 12:00 -> EDT 08:00
        assert result.hour == 8

    def test_localize_invalid_timezone(self):
        dt = datetime(2024, 6, 1, 12, 0, 0)
        with pytest.raises(Exception):
            localize(dt, "Invalid/Timezone")


class TestFormatDateHint:
    def test_formats_datetime(self):
        dt = datetime(2024, 6, 15, 10, 30)
        assert format_date_hint(dt) == "2024-06-15"

    def test_none_returns_none(self):
        assert format_date_hint(None) is None

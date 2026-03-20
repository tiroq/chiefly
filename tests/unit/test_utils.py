"""
Unit tests for core utility modules.
"""

import uuid

import pytest

from core.utils.ids import new_uuid, parse_uuid, short_id
from core.utils.text import sanitize_callback_part, slugify, truncate


class TestSlugify:
    def test_basic(self):
        assert slugify("Hello World") == "hello-world"

    def test_special_characters(self):
        assert slugify("Hello, World!") == "hello-world"

    def test_multiple_spaces(self):
        assert slugify("  Hello   World  ") == "hello-world"

    def test_underscores(self):
        assert slugify("hello_world_test") == "hello-world-test"

    def test_leading_trailing_hyphens(self):
        assert slugify("-hello-world-") == "hello-world"

    def test_empty_string(self):
        assert slugify("") == ""

    def test_unicode(self):
        result = slugify("Привет мир")
        assert isinstance(result, str)


class TestTruncate:
    def test_no_truncation_needed(self):
        assert truncate("short", max_len=100) == "short"

    def test_exact_length(self):
        text = "x" * 100
        assert truncate(text, max_len=100) == text

    def test_truncation(self):
        text = "x" * 200
        result = truncate(text, max_len=100)
        assert len(result) == 100
        assert result.endswith("…")

    def test_custom_suffix(self):
        text = "x" * 200
        result = truncate(text, max_len=50, suffix="...")
        assert len(result) == 50
        assert result.endswith("...")


class TestSanitizeCallbackPart:
    def test_removes_colons(self):
        assert sanitize_callback_part("a:b:c") == "a_b_c"

    def test_removes_spaces(self):
        assert sanitize_callback_part("hello world") == "hello_world"

    def test_no_change_needed(self):
        assert sanitize_callback_part("abc123") == "abc123"


class TestIds:
    def test_new_uuid_returns_uuid4(self):
        uid = new_uuid()
        assert isinstance(uid, uuid.UUID)
        assert uid.version == 4

    def test_short_id_is_hex(self):
        uid = uuid.UUID("12345678-1234-5678-1234-567812345678")
        assert short_id(uid) == "12345678123456781234567812345678"

    def test_short_id_no_dashes(self):
        uid = new_uuid()
        result = short_id(uid)
        assert "-" not in result

    def test_parse_uuid_from_standard(self):
        uid = uuid.UUID("12345678-1234-5678-1234-567812345678")
        parsed = parse_uuid("12345678-1234-5678-1234-567812345678")
        assert parsed == uid

    def test_parse_uuid_from_hex(self):
        uid = uuid.UUID("12345678-1234-5678-1234-567812345678")
        parsed = parse_uuid("12345678123456781234567812345678")
        assert parsed == uid

    def test_parse_uuid_invalid(self):
        with pytest.raises(ValueError):
            parse_uuid("not-a-uuid")

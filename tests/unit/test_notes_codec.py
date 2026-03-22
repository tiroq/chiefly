from uuid import UUID, uuid4

from core.domain.notes_codec import (
    ENVELOPE_END,
    ENVELOPE_START,
    extract_user_notes,
    format,
    parse,
)

STABLE_ID = uuid4()
STABLE_ID_STR = str(STABLE_ID)


class TestParse:
    def test_returns_none_for_none(self):
        assert parse(None) is None

    def test_returns_none_for_empty_string(self):
        assert parse("") is None

    def test_returns_none_for_plain_notes(self):
        assert parse("Just some user text here") is None

    def test_returns_none_for_malformed_json(self):
        notes = f"{ENVELOPE_START}\n{{invalid json\n{ENVELOPE_END}"
        assert parse(notes) is None

    def test_returns_none_for_missing_end_delimiter(self):
        notes = f'{ENVELOPE_START}\n{{"stable_id": "{STABLE_ID_STR}"}}\n'
        assert parse(notes) is None

    def test_returns_none_for_missing_stable_id_key(self):
        notes = f'{ENVELOPE_START}\n{{"project": "inbox"}}\n{ENVELOPE_END}'
        assert parse(notes) is None

    def test_returns_none_for_non_dict_json(self):
        notes = f"{ENVELOPE_START}\n[1, 2, 3]\n{ENVELOPE_END}"
        assert parse(notes) is None

    def test_returns_none_for_empty_payload(self):
        notes = f"{ENVELOPE_START}\n\n{ENVELOPE_END}"
        assert parse(notes) is None

    def test_parses_valid_envelope(self):
        notes = (
            f'{ENVELOPE_START}\n{{"stable_id":"{STABLE_ID_STR}","project":"inbox"}}\n{ENVELOPE_END}'
        )
        result = parse(notes)
        assert result is not None
        assert result["stable_id"] == STABLE_ID_STR
        assert result["project"] == "inbox"

    def test_parses_envelope_with_user_text_above(self):
        notes = (
            f'Buy groceries\n\n{ENVELOPE_START}\n{{"stable_id":"{STABLE_ID_STR}"}}\n{ENVELOPE_END}'
        )
        result = parse(notes)
        assert result is not None
        assert result["stable_id"] == STABLE_ID_STR

    def test_parses_envelope_with_user_text_below(self):
        notes = (
            f'{ENVELOPE_START}\n{{"stable_id":"{STABLE_ID_STR}"}}\n{ENVELOPE_END}\nExtra text below'
        )
        result = parse(notes)
        assert result is not None
        assert result["stable_id"] == STABLE_ID_STR


class TestFormat:
    def test_format_without_existing_notes(self):
        result = format(STABLE_ID, {"project": "inbox"})
        assert ENVELOPE_START in result
        assert ENVELOPE_END in result
        parsed = parse(result)
        assert parsed is not None
        assert parsed["stable_id"] == STABLE_ID_STR
        assert parsed["project"] == "inbox"

    def test_format_preserves_user_notes(self):
        result = format(STABLE_ID, {}, existing_notes="My task notes")
        assert result.startswith("My task notes")
        assert ENVELOPE_START in result

    def test_format_with_none_existing(self):
        result = format(STABLE_ID, {}, existing_notes=None)
        assert result.startswith(ENVELOPE_START)

    def test_format_replaces_existing_envelope(self):
        original = format(STABLE_ID, {"project": "old"}, existing_notes="User text")
        new_id = uuid4()
        replaced = format(new_id, {"project": "new"}, existing_notes=original)
        parsed = parse(replaced)
        assert parsed is not None
        assert parsed["stable_id"] == str(new_id)
        assert parsed["project"] == "new"
        assert "old" not in replaced
        assert "User text" in replaced

    def test_envelope_appears_once_after_replacement(self):
        step1 = format(STABLE_ID, {"project": "v1"}, existing_notes="notes")
        step2 = format(STABLE_ID, {"project": "v2"}, existing_notes=step1)
        step3 = format(STABLE_ID, {"project": "v3"}, existing_notes=step2)
        assert step3.count(ENVELOPE_START) == 1
        assert step3.count(ENVELOPE_END) == 1
        parsed = parse(step3)
        assert parsed is not None
        assert parsed["project"] == "v3"

    def test_format_with_empty_existing_notes(self):
        result = format(STABLE_ID, {}, existing_notes="")
        assert result.startswith(ENVELOPE_START)

    def test_format_with_whitespace_only_existing_notes(self):
        result = format(STABLE_ID, {}, existing_notes="   \n  ")
        assert result.startswith(ENVELOPE_START)


class TestExtractUserNotes:
    def test_returns_empty_for_none(self):
        assert extract_user_notes(None) == ""

    def test_returns_empty_for_empty(self):
        assert extract_user_notes("") == ""

    def test_returns_user_text_from_plain_notes(self):
        assert extract_user_notes("Just user text") == "Just user text"

    def test_strips_envelope_returns_user_text(self):
        notes = format(STABLE_ID, {"project": "inbox"}, existing_notes="My task")
        assert extract_user_notes(notes) == "My task"

    def test_strips_envelope_only(self):
        notes = format(STABLE_ID, {})
        assert extract_user_notes(notes) == ""


class TestRoundTrip:
    def test_round_trip_preserves_all_metadata(self):
        metadata = {
            "project": "inbox",
            "kind": "task",
            "confidence": 0.85,
            "next_action": "reply to John",
            "normalized_title": "Reply to John about the budget",
        }
        user_text = "Original user notes\nWith multiple lines"
        notes = format(STABLE_ID, metadata, existing_notes=user_text)

        parsed = parse(notes)
        assert parsed is not None
        assert parsed["stable_id"] == STABLE_ID_STR
        assert parsed["project"] == "inbox"
        assert parsed["kind"] == "task"
        assert parsed["confidence"] == 0.85
        assert parsed["next_action"] == "reply to John"
        assert parsed["normalized_title"] == "Reply to John about the budget"

        extracted = extract_user_notes(notes)
        assert extracted == user_text

    def test_round_trip_empty_metadata(self):
        notes = format(STABLE_ID, {})
        parsed = parse(notes)
        assert parsed is not None
        assert parsed["stable_id"] == STABLE_ID_STR
        assert len(parsed) == 1

    def test_uuid_round_trip(self):
        notes = format(STABLE_ID, {})
        parsed = parse(notes)
        assert parsed is not None
        assert UUID(parsed["stable_id"]) == STABLE_ID

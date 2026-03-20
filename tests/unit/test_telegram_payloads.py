"""
Unit tests for Telegram callback payload encoding/decoding.
"""

import pytest

from core.domain.enums import ReviewAction
from core.schemas.telegram import (
    CallbackPayload,
    KindSelectPayload,
    ProjectSelectPayload,
)


class TestCallbackPayload:
    def test_encode(self):
        p = CallbackPayload(action=ReviewAction.CONFIRM, task_id="abc123")
        assert p.encode() == "confirm:abc123"

    def test_decode(self):
        p = CallbackPayload.decode("confirm:abc123")
        assert p.action == ReviewAction.CONFIRM
        assert p.task_id == "abc123"

    def test_roundtrip(self):
        original = CallbackPayload(action=ReviewAction.EDIT, task_id="deadbeef")
        decoded = CallbackPayload.decode(original.encode())
        assert decoded.action == original.action
        assert decoded.task_id == original.task_id

    def test_all_actions_encode_decode(self):
        for action in ReviewAction:
            p = CallbackPayload(action=action, task_id="test123")
            decoded = CallbackPayload.decode(p.encode())
            assert decoded.action == action

    def test_decode_invalid_format_no_colon(self):
        with pytest.raises(ValueError, match="Invalid callback data"):
            CallbackPayload.decode("invaliddata")

    def test_decode_invalid_action(self):
        with pytest.raises(ValueError):
            CallbackPayload.decode("unknown_action:abc123")

    def test_decode_with_colon_in_task_id(self):
        # task_id part contains a colon — split(":", 1) handles this
        p = CallbackPayload.decode("confirm:abc:123")
        assert p.task_id == "abc:123"


class TestProjectSelectPayload:
    def test_encode(self):
        p = ProjectSelectPayload(task_id="abc123", project_slug="nft-gateway")
        assert p.encode() == "proj:abc123:nft-gateway"

    def test_decode(self):
        p = ProjectSelectPayload.decode("proj:abc123:nft-gateway")
        assert p.task_id == "abc123"
        assert p.project_slug == "nft-gateway"

    def test_roundtrip(self):
        original = ProjectSelectPayload(task_id="deadbeef", project_slug="personal")
        decoded = ProjectSelectPayload.decode(original.encode())
        assert decoded.task_id == original.task_id
        assert decoded.project_slug == original.project_slug

    def test_decode_invalid_format(self):
        with pytest.raises(ValueError, match="Invalid project callback data"):
            ProjectSelectPayload.decode("proj:onlyonepart")

    def test_decode_missing_prefix(self):
        with pytest.raises(ValueError, match="Invalid project callback data"):
            ProjectSelectPayload.decode("notproj")


class TestKindSelectPayload:
    def test_encode(self):
        p = KindSelectPayload(task_id="abc123", kind="task")
        assert p.encode() == "kind:abc123:task"

    def test_decode(self):
        p = KindSelectPayload.decode("kind:abc123:waiting")
        assert p.task_id == "abc123"
        assert p.kind == "waiting"

    def test_roundtrip(self):
        original = KindSelectPayload(task_id="deadbeef", kind="idea")
        decoded = KindSelectPayload.decode(original.encode())
        assert decoded.task_id == original.task_id
        assert decoded.kind == original.kind

    def test_decode_invalid_format(self):
        with pytest.raises(ValueError, match="Invalid kind callback data"):
            KindSelectPayload.decode("kind:onlyonepart")

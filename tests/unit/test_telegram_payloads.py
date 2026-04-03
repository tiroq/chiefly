"""
Unit tests for Telegram callback payload encoding/decoding.
"""

import pytest

from core.domain.enums import ReviewAction
from core.schemas.telegram import (
    CallbackPayload,
    DisambiguationPayload,
    KindSelectPayload,
    ProjectSelectPayload,
    QueueActionPayload,
    SettingPayload,
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
            _ = CallbackPayload.decode("invaliddata")

    def test_decode_invalid_action(self):
        with pytest.raises(ValueError):
            _ = CallbackPayload.decode("unknown_action:abc123")

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
            _ = ProjectSelectPayload.decode("proj:onlyonepart")

    def test_decode_missing_prefix(self):
        with pytest.raises(ValueError, match="Invalid project callback data"):
            _ = ProjectSelectPayload.decode("notproj")


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
            _ = KindSelectPayload.decode("kind:onlyonepart")


class TestDisambiguationPayload:
    def test_encode(self):
        p = DisambiguationPayload(task_id="abc123", option_index=2)
        assert p.encode() == "disambig:abc123:2"

    def test_decode(self):
        p = DisambiguationPayload.decode("disambig:abc123:2")
        assert p.task_id == "abc123"
        assert p.option_index == 2

    def test_roundtrip(self):
        original = DisambiguationPayload(task_id="deadbeef", option_index=1)
        decoded = DisambiguationPayload.decode(original.encode())
        assert decoded.task_id == original.task_id
        assert decoded.option_index == original.option_index

    def test_decode_invalid_format(self):
        with pytest.raises(ValueError, match="Invalid disambiguation callback data"):
            _ = DisambiguationPayload.decode("disambig:onlyonepart")


class TestQueueActionPayload:
    def test_encode(self):
        p = QueueActionPayload(action="queue:start")
        assert p.encode() == "queue:start"

    def test_decode(self):
        p = QueueActionPayload.decode("queue:start")
        assert p.action == "queue:start"

    def test_sub_action(self):
        p = QueueActionPayload(action="queue:start")
        assert p.sub_action == "start"

    def test_batch_size(self):
        p = QueueActionPayload(action="queue:batch:5")
        assert p.batch_size == 5

    def test_batch_size_none_for_non_batch(self):
        p = QueueActionPayload(action="queue:start")
        assert p.batch_size is None

    def test_decode_invalid_prefix(self):
        with pytest.raises(ValueError, match="Invalid queue callback data"):
            _ = QueueActionPayload.decode("notqueue:start")


class TestSettingPayload:
    def test_encode(self):
        p = SettingPayload(key="auto_next")
        assert p.encode() == "setting:auto_next"

    def test_decode(self):
        p = SettingPayload.decode("setting:auto_next")
        assert p.key == "auto_next"

    def test_roundtrip(self):
        original = SettingPayload(key="batch_size")
        decoded = SettingPayload.decode(original.encode())
        assert decoded.key == original.key

    def test_decode_invalid(self):
        with pytest.raises(ValueError, match="Invalid setting callback data"):
            _ = SettingPayload.decode("settingonlyonepart")

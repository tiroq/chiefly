from __future__ import annotations

from apps.api.config import Settings


class TestLLMConfigDefaults:
    def test_multi_model_fields_default_empty(self, monkeypatch):
        monkeypatch.delenv("LLM_FAST_MODEL", raising=False)
        monkeypatch.delenv("LLM_QUALITY_MODEL", raising=False)
        monkeypatch.delenv("LLM_FALLBACK_MODEL", raising=False)
        s = Settings(database_url="sqlite:///:memory:", _env_file=None)
        assert s.llm_fast_model == ""
        assert s.llm_quality_model == ""
        assert s.llm_fallback_model == ""

    def test_auto_mode_default_false(self, monkeypatch):
        monkeypatch.delenv("LLM_AUTO_MODE", raising=False)
        s = Settings(database_url="sqlite:///:memory:", _env_file=None)
        assert s.llm_auto_mode is False

    def test_env_override_multi_model_fields(self, monkeypatch):
        monkeypatch.setenv("LLM_FAST_MODEL", "openai/gpt-4o-mini")
        monkeypatch.setenv("LLM_QUALITY_MODEL", "openai/gpt-4o")
        monkeypatch.setenv("LLM_FALLBACK_MODEL", "openai/gpt-4o-mini")
        monkeypatch.setenv("LLM_AUTO_MODE", "true")

        s = Settings(database_url="sqlite:///:memory:", _env_file=None)
        assert s.llm_fast_model == "openai/gpt-4o-mini"
        assert s.llm_quality_model == "openai/gpt-4o"
        assert s.llm_fallback_model == "openai/gpt-4o-mini"
        assert s.llm_auto_mode is True


class TestSyncIntervalBackwardCompat:
    def test_default_sync_interval(self):
        s = Settings(database_url="sqlite:///:memory:", _env_file=None)
        assert s.effective_sync_interval == 60

    def test_legacy_inbox_poll_interval_takes_precedence(self):
        s = Settings(
            database_url="sqlite:///:memory:", inbox_poll_interval_seconds=30, _env_file=None
        )
        assert s.effective_sync_interval == 30

    def test_default_tasklist_id_new_field(self):
        s = Settings(
            database_url="sqlite:///:memory:",
            google_tasks_default_tasklist_id="new-id",
            _env_file=None,
        )
        assert s.default_tasklist_id == "new-id"

    def test_default_tasklist_id_legacy_fallback(self):
        s = Settings(
            database_url="sqlite:///:memory:",
            google_tasks_inbox_list_id="legacy-id",
            _env_file=None,
        )
        assert s.default_tasklist_id == "legacy-id"


class TestRateLimitConfigValidation:
    def test_zero_capacity_rejected(self):
        import pytest

        with pytest.raises(Exception, match="rate_limit_capacity must be positive"):
            Settings(database_url="sqlite:///:memory:", rate_limit_capacity=0, _env_file=None)

    def test_negative_capacity_rejected(self):
        import pytest

        with pytest.raises(Exception, match="rate_limit_capacity must be positive"):
            Settings(database_url="sqlite:///:memory:", rate_limit_capacity=-5, _env_file=None)

    def test_zero_refill_amount_rejected(self):
        import pytest

        with pytest.raises(Exception, match="rate_limit_refill_amount must be positive"):
            Settings(database_url="sqlite:///:memory:", rate_limit_refill_amount=0, _env_file=None)

    def test_negative_refill_interval_rejected(self):
        import pytest

        with pytest.raises(Exception, match="rate_limit_refill_interval_seconds must be positive"):
            Settings(
                database_url="sqlite:///:memory:",
                rate_limit_refill_interval_seconds=-1,
                _env_file=None,
            )

    def test_valid_rate_limit_config_accepted(self):
        s = Settings(
            database_url="sqlite:///:memory:",
            rate_limit_capacity=5,
            rate_limit_refill_amount=2,
            rate_limit_refill_interval_seconds=15,
            _env_file=None,
        )
        assert s.rate_limit_capacity == 5
        assert s.rate_limit_refill_amount == 2
        assert s.rate_limit_refill_interval_seconds == 15

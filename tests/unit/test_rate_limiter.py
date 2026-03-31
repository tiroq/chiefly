"""Unit tests for the token-bucket rate limiter."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.api.services.rate_limiter import (
    LOCAL_PROVIDERS,
    ProviderRateLimiter,
    RateLimitDecision,
    TokenBucket,
)


class TestTokenBucket:
    def test_bucket_starts_full(self):
        with patch("apps.api.services.rate_limiter.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            bucket = TokenBucket(capacity=10, refill_amount=1, refill_interval=30)

            decisions = [bucket.acquire() for _ in range(10)]

            assert all(d.allowed for d in decisions)

    def test_bucket_denies_after_exhaustion(self):
        with patch("apps.api.services.rate_limiter.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            bucket = TokenBucket(capacity=10, refill_amount=1, refill_interval=30)

            for _ in range(10):
                bucket.acquire()

            denied = bucket.acquire()
            assert not denied.allowed
            assert denied.retry_after_seconds > 0

    def test_token_restored_after_interval(self):
        with patch("apps.api.services.rate_limiter.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            bucket = TokenBucket(capacity=10, refill_amount=1, refill_interval=30)

            for _ in range(10):
                bucket.acquire()

            mock_time.monotonic.return_value = 30.0
            decision = bucket.acquire()
            assert decision.allowed

    def test_full_refill_over_time(self):
        with patch("apps.api.services.rate_limiter.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            bucket = TokenBucket(capacity=10, refill_amount=1, refill_interval=30)

            for _ in range(10):
                bucket.acquire()

            mock_time.monotonic.return_value = 300.0
            decisions = [bucket.acquire() for _ in range(10)]
            assert all(d.allowed for d in decisions)

    def test_partial_refill_still_denied(self):
        with patch("apps.api.services.rate_limiter.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            bucket = TokenBucket(capacity=10, refill_amount=1, refill_interval=30)

            for _ in range(10):
                bucket.acquire()

            mock_time.monotonic.return_value = 15.0
            decision = bucket.acquire()
            assert not decision.allowed

    def test_tokens_capped_at_capacity(self):
        with patch("apps.api.services.rate_limiter.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            bucket = TokenBucket(capacity=10, refill_amount=1, refill_interval=30)

            mock_time.monotonic.return_value = 9999.0
            decisions = [bucket.acquire() for _ in range(11)]
            assert all(d.allowed for d in decisions[:10])
            assert not decisions[10].allowed

    def test_retry_after_seconds_accuracy(self):
        with patch("apps.api.services.rate_limiter.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            bucket = TokenBucket(capacity=10, refill_amount=1, refill_interval=30)

            for _ in range(10):
                bucket.acquire()

            denied = bucket.acquire()
            assert not denied.allowed
            assert 29.0 <= denied.retry_after_seconds <= 30.0


class TestProviderRateLimiter:
    def test_separate_providers_have_separate_buckets(self):
        with patch("apps.api.services.rate_limiter.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            limiter = ProviderRateLimiter(capacity=10, refill_amount=1, refill_interval=30)

            for _ in range(10):
                limiter.check("openai")

            denied = limiter.check("openai")
            assert not denied.allowed

            allowed = limiter.check("github_models")
            assert allowed.allowed

    def test_ollama_bypass(self):
        with patch("apps.api.services.rate_limiter.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            limiter = ProviderRateLimiter(capacity=1, refill_amount=1, refill_interval=30)

            for _ in range(100):
                decision = limiter.check("ollama")
                assert decision.allowed

    def test_disabled_limiter_allows_all(self):
        with patch("apps.api.services.rate_limiter.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            limiter = ProviderRateLimiter(
                capacity=1, refill_amount=1, refill_interval=30, enabled=False
            )

            for _ in range(100):
                decision = limiter.check("openai")
                assert decision.allowed

    def test_unknown_provider_gets_rate_limited(self):
        with patch("apps.api.services.rate_limiter.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            limiter = ProviderRateLimiter(capacity=1, refill_amount=1, refill_interval=30)

            limiter.check("some_new_provider")
            denied = limiter.check("some_new_provider")
            assert not denied.allowed


class TestRateLimitDecision:
    def test_decision_dataclass_fields(self):
        decision = RateLimitDecision(allowed=True, tokens_remaining=5, retry_after_seconds=0.0)
        assert decision.allowed is True
        assert decision.tokens_remaining == 5
        assert decision.retry_after_seconds == 0.0

    def test_decision_is_frozen(self):
        decision = RateLimitDecision(allowed=True, tokens_remaining=5, retry_after_seconds=0.0)
        with pytest.raises(AttributeError):
            decision.allowed = False


class TestLocalProviders:
    def test_ollama_in_local_providers(self):
        assert "ollama" in LOCAL_PROVIDERS

    def test_openai_not_in_local_providers(self):
        assert "openai" not in LOCAL_PROVIDERS


class TestTokenBucketValidation:
    def test_zero_capacity_rejected(self):
        with pytest.raises(ValueError, match="capacity must be positive"):
            TokenBucket(capacity=0, refill_amount=1, refill_interval=30)

    def test_negative_capacity_rejected(self):
        with pytest.raises(ValueError, match="capacity must be positive"):
            TokenBucket(capacity=-1, refill_amount=1, refill_interval=30)

    def test_zero_refill_amount_rejected(self):
        with pytest.raises(ValueError, match="refill_amount must be positive"):
            TokenBucket(capacity=10, refill_amount=0, refill_interval=30)

    def test_zero_refill_interval_rejected(self):
        with pytest.raises(ValueError, match="refill_interval must be positive"):
            TokenBucket(capacity=10, refill_amount=1, refill_interval=0)

    def test_negative_refill_interval_rejected(self):
        with pytest.raises(ValueError, match="refill_interval must be positive"):
            TokenBucket(capacity=10, refill_amount=1, refill_interval=-1)

    def test_negative_refill_amount_rejected(self):
        with pytest.raises(ValueError, match="refill_amount must be positive"):
            TokenBucket(capacity=10, refill_amount=-1, refill_interval=30)


class TestProviderRateLimiterValidation:
    def test_zero_capacity_rejected(self):
        with pytest.raises(ValueError, match="capacity must be positive"):
            ProviderRateLimiter(capacity=0, refill_amount=1, refill_interval=30)

    def test_negative_refill_amount_rejected(self):
        with pytest.raises(ValueError, match="refill_amount must be positive"):
            ProviderRateLimiter(capacity=10, refill_amount=-1, refill_interval=30)

    def test_zero_refill_interval_rejected(self):
        with pytest.raises(ValueError, match="refill_interval must be positive"):
            ProviderRateLimiter(capacity=10, refill_amount=1, refill_interval=0)

    def test_valid_config_accepted(self):
        limiter = ProviderRateLimiter(capacity=10, refill_amount=1, refill_interval=30)
        assert limiter is not None

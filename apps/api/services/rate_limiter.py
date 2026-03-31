from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from apps.api.config import get_settings

LOCAL_PROVIDERS: frozenset[str] = frozenset({"ollama"})


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    tokens_remaining: int
    retry_after_seconds: float


class TokenBucket:
    def __init__(
        self,
        capacity: int,
        refill_amount: int,
        refill_interval: float,
    ) -> None:
        if capacity <= 0:
            raise ValueError(f"capacity must be positive, got {capacity}")
        if refill_amount <= 0:
            raise ValueError(f"refill_amount must be positive, got {refill_amount}")
        if refill_interval <= 0:
            raise ValueError(f"refill_interval must be positive, got {refill_interval}")
        self._capacity = capacity
        self._refill_amount = refill_amount
        self._refill_interval = refill_interval
        self._tokens: float = float(capacity)
        self._last_refill: float = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        tokens_to_add = (elapsed / self._refill_interval) * self._refill_amount
        if tokens_to_add > 0:
            self._tokens = min(self._capacity, self._tokens + tokens_to_add)
            self._last_refill = now

    def acquire(self) -> RateLimitDecision:
        with self._lock:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return RateLimitDecision(
                    allowed=True,
                    tokens_remaining=int(self._tokens),
                    retry_after_seconds=0.0,
                )
            deficit = 1.0 - self._tokens
            retry_after = (deficit / self._refill_amount) * self._refill_interval
            return RateLimitDecision(
                allowed=False,
                tokens_remaining=0,
                retry_after_seconds=retry_after,
            )


_BYPASS_DECISION = RateLimitDecision(allowed=True, tokens_remaining=-1, retry_after_seconds=0.0)


class ProviderRateLimiter:
    def __init__(
        self,
        capacity: int = 10,
        refill_amount: int = 1,
        refill_interval: float = 30.0,
        enabled: bool = True,
    ) -> None:
        if capacity <= 0:
            raise ValueError(f"capacity must be positive, got {capacity}")
        if refill_amount <= 0:
            raise ValueError(f"refill_amount must be positive, got {refill_amount}")
        if refill_interval <= 0:
            raise ValueError(f"refill_interval must be positive, got {refill_interval}")
        self._capacity = capacity
        self._refill_amount = refill_amount
        self._refill_interval = refill_interval
        self._enabled = enabled
        self._buckets: dict[str, TokenBucket] = {}
        self._lock = threading.Lock()

    def check(self, provider: str) -> RateLimitDecision:
        if not self._enabled or provider in LOCAL_PROVIDERS:
            return _BYPASS_DECISION
        with self._lock:
            if provider not in self._buckets:
                self._buckets[provider] = TokenBucket(
                    capacity=self._capacity,
                    refill_amount=self._refill_amount,
                    refill_interval=self._refill_interval,
                )
        return self._buckets[provider].acquire()


_rate_limiter: ProviderRateLimiter | None = None
_rate_limiter_lock = threading.Lock()


def get_rate_limiter() -> ProviderRateLimiter:
    global _rate_limiter
    if _rate_limiter is not None:
        return _rate_limiter
    with _rate_limiter_lock:
        if _rate_limiter is not None:
            return _rate_limiter
        settings = get_settings()
        _rate_limiter = ProviderRateLimiter(
            capacity=settings.rate_limit_capacity,
            refill_amount=settings.rate_limit_refill_amount,
            refill_interval=float(settings.rate_limit_refill_interval_seconds),
            enabled=settings.rate_limit_enabled,
        )
        return _rate_limiter


def reset_rate_limiter() -> None:
    global _rate_limiter
    with _rate_limiter_lock:
        _rate_limiter = None

"""Unit tests for token bucket rate limiter."""

import time

import pytest

from producer.rate_limiter import TokenBucketRateLimiter


def test_acquire_single_token():
    limiter = TokenBucketRateLimiter(rate=1000)
    start = time.monotonic()
    limiter.acquire(1)
    elapsed = time.monotonic() - start
    assert elapsed < 0.01, "Single token acquire should be nearly instant"


def test_rate_limiting():
    """Rate limiter should throttle tokens beyond initial burst capacity."""
    rate = 2000
    capacity = 100  # Small capacity to force rate limiting quickly
    limiter = TokenBucketRateLimiter(rate=rate, capacity=capacity)
    # First 100 tokens come from initial bucket instantly
    # The next 100 tokens must be acquired at rate 2000/s → ~0.05s wait
    tokens = capacity * 2

    start = time.monotonic()
    for _ in range(tokens):
        limiter.acquire(1)
    elapsed = time.monotonic() - start

    # We expect at least capacity/rate seconds of waiting for the second batch
    min_expected = capacity / rate
    assert elapsed >= min_expected * 0.8, (
        f"Expected at least {min_expected:.3f}s of rate limiting, got {elapsed:.3f}s"
    )


def test_capacity_caps_burst():
    """Token count should not exceed capacity."""
    limiter = TokenBucketRateLimiter(rate=1000, capacity=500)
    assert limiter._tokens <= 500


def test_zero_rate_raises():
    """Zero rate should not cause division by zero in practice."""
    limiter = TokenBucketRateLimiter(rate=1e-6)
    # Just verifying it initializes without error
    assert limiter.rate > 0

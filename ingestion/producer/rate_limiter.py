"""Token bucket rate limiter for producer throughput control."""

import time


class TokenBucketRateLimiter:
    """Simple token bucket rate limiter.

    Allows bursting up to `capacity` tokens, then refills at `rate` tokens/second.
    Call `acquire(n)` to consume n tokens; blocks if tokens not yet available.
    """

    def __init__(self, rate: float, capacity: float | None = None) -> None:
        self.rate = rate
        self.capacity = capacity or rate
        self._tokens = float(self.capacity)
        self._last_refill = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
        self._last_refill = now

    def acquire(self, n: int = 1) -> None:
        """Block until n tokens are available, then consume them."""
        while True:
            self._refill()
            if self._tokens >= n:
                self._tokens -= n
                return
            deficit = n - self._tokens
            sleep_time = deficit / self.rate
            time.sleep(min(sleep_time, 0.01))

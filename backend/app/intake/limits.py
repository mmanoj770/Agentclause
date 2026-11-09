"""Request limits for POST /intake/normalize.

Each request can trigger up to 3 model calls (the retry loop in IntakeService.normalize), so the
size cap and the per-user rate limit are the cost controls. The limiter is in memory and
per process: it is only exact while the server runs a single worker (the systemd unit starts uvicorn
without --workers). Recheck that before anyone adds workers or a second server.
"""
import time
from collections import defaultdict, deque
from threading import Lock

from app.config import settings

# Largest accepted contract text, in characters. A setting (INTAKE_MAX_CONTRACT_CHARS), read once at startup.
MAX_CONTRACT_CHARS = settings.intake_max_contract_chars

# (window in seconds, maximum requests in that window) per user. The numbers are settings
# (INTAKE_RATE_LIMIT_PER_MINUTE, INTAKE_RATE_LIMIT_PER_HOUR); defaults 5 and 30.
RATE_LIMITS = ((60, settings.intake_rate_limit_per_minute), (3600, settings.intake_rate_limit_per_hour))


class SlidingWindowLimiter:
    def __init__(self, limits=RATE_LIMITS, clock=time.monotonic):
        self._limits = limits
        self._clock = clock
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        """Record a request and return True, or return False (recording nothing) if over a limit."""
        now = self._clock()
        longest = max(window for window, _ in self._limits)
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= longest:
                hits.popleft()
            for window, maximum in self._limits:
                if sum(1 for t in hits if now - t < window) >= maximum:
                    return False
            hits.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = SlidingWindowLimiter()

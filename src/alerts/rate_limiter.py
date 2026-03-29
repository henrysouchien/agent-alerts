from __future__ import annotations

import time
from collections import defaultdict


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._rate_counts: dict[str, list[float]] = defaultdict(list)
        self._global_rate_counts: list[float] = []
        self._agent_rate_counts: list[float] = []

    def check(self, source_type: str, max_per_hour: int) -> bool:
        cutoff = time.time() - 3600
        recent = [timestamp for timestamp in self._rate_counts[source_type] if timestamp > cutoff]
        self._rate_counts[source_type] = recent
        return len(recent) < max_per_hour

    def check_global(self, max_per_hour: int) -> bool:
        cutoff = time.time() - 3600
        recent = [timestamp for timestamp in self._global_rate_counts if timestamp > cutoff]
        self._global_rate_counts = recent
        return len(recent) < max_per_hour

    def check_agent(self, max_per_hour: int) -> bool:
        cutoff = time.time() - 3600
        recent = [timestamp for timestamp in self._agent_rate_counts if timestamp > cutoff]
        self._agent_rate_counts = recent
        return len(recent) < max_per_hour

    def record(self, source_type: str, *, agent: bool = False) -> None:
        now = time.time()
        self._rate_counts[source_type].append(now)
        self._global_rate_counts.append(now)
        if agent:
            self._agent_rate_counts.append(now)

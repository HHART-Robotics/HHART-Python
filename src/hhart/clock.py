"""Monotonic only, boards without RTC jump wall time at NTP sync"""

from __future__ import annotations

import time


class SystemClock:
    def now_ns(self) -> int:
        return time.monotonic_ns()

    def monotonic(self) -> float:
        return time.monotonic()


class ManualClock:
    def __init__(self, start_ns: int = 0) -> None:
        self._ns = start_ns

    def now_ns(self) -> int:
        return self._ns

    def monotonic(self) -> float:
        return self._ns / 1_000_000_000

    def advance(self, seconds: float) -> None:
        self._ns += int(seconds * 1_000_000_000)

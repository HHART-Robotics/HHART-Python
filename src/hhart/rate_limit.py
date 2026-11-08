from __future__ import annotations

from typing import Any, AsyncIterator

from hhart.ports import Clock, TelemetrySource


class RateLimited:
    def __init__(self, inner: TelemetrySource, *, fps: float, clock: Clock) -> None:
        if fps <= 0:
            raise ValueError(f"fps must be positive, got {fps}")
        self._inner = inner
        # Integer ns, float rounding dropped on-time samples
        self._interval_ns = round(1_000_000_000 / fps)
        self._clock = clock

    @property
    def name(self) -> str:
        return self._inner.name

    async def stream(self) -> AsyncIterator[Any]:
        last_ns: int | None = None
        async for sample in self._inner.stream():
            now_ns = self._clock.now_ns()
            if last_ns is not None and now_ns - last_ns < self._interval_ns:
                continue
            last_ns = now_ns
            yield sample

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator, Awaitable, Callable

from hhart.ports import TelemetrySource

logger = logging.getLogger(__name__)

EXPECTED = (ConnectionError, OSError, asyncio.IncompleteReadError, EOFError)


class Reconnecting:
    """Backoff resets on first sample, not connect, so flapping source doesn't spin"""

    def __init__(
        self,
        inner: TelemetrySource,
        *,
        initial_delay: float = 1.0,
        max_delay: float = 30.0,
        factor: float = 2.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._inner = inner
        self._initial_delay = initial_delay
        self._max_delay = max_delay
        self._factor = factor
        self._sleep = sleep

    @property
    def name(self) -> str:
        return self._inner.name

    async def stream(self) -> AsyncIterator[Any]:
        delay = self._initial_delay
        while True:
            try:
                async for sample in self._inner.stream():
                    delay = self._initial_delay
                    yield sample
                logger.debug("%s: stream ended, reconnecting in %.1fs",
                             self.name, delay)
            except asyncio.CancelledError:
                # Re-raise or SIGTERM is swallowed
                raise
            except EXPECTED as exc:
                logger.debug("%s: not ready (%s), retrying in %.1fs",
                             self.name, exc, delay)
            except Exception as exc:
                logger.warning("%s: %s, retrying in %.1fs", self.name, exc, delay)

            await self._sleep(delay)
            delay = min(delay * self._factor, self._max_delay)

from __future__ import annotations

from typing import Any, AsyncIterator, Protocol, runtime_checkable


@runtime_checkable
class TelemetrySource(Protocol):
    name: str

    def stream(self) -> AsyncIterator[Any]: ...


@runtime_checkable
class Publisher(Protocol):
    async def publish(self, message: dict) -> None: ...


@runtime_checkable
class Clock(Protocol):
    def now_ns(self) -> int: ...
    def monotonic(self) -> float: ...

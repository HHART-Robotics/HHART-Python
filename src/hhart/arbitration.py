from __future__ import annotations

import logging
import math

from hhart.ports import Clock

logger = logging.getLogger(__name__)

OPERATOR = "operator"
ROS = "ros"
TEST = "test"


def admit(latched: bool, source: str, action: str) -> tuple[bool, bool]:
    """(allowed, latched). Operator stop locks out other sources until operator releases"""
    if action == "stop":
        return True, latched or source == OPERATOR
    if action == "release":
        return source == OPERATOR, latched and source != OPERATOR
    return source == OPERATOR or not latched, latched


def deadman(now_s: float, received_s: float, commanding: bool, driving: bool, timeout_s: float) -> str | None:
    """"drive" (resend), "stop" or None. Ticked every P, silent source stops within [T, T + P)"""
    if commanding and now_s - received_s < timeout_s:
        return "drive"
    return "stop" if driving else None


class Arbiter:

    def __init__(self, motors, clock: Clock, *, period_s: float, timeout_s: float) -> None:
        self._motors = motors
        self._clock = clock
        self.period_s = period_s
        self.timeout_s = timeout_s
        self.latched = False
        self.driver: str | None = None
        self._held, self._received_s = None, -math.inf

    async def drive(self, command, source: str) -> None:
        """Ignored while latched out. New command sent at once, repeat only refreshes it"""
        allowed, self.latched = admit(self.latched, source, "drive")
        if not allowed:
            return
        repeat = self.driver is not None and command == self._held
        self._held, self._received_s, self.driver = command, self._clock.monotonic(), source
        if not repeat:
            await self._motors.send(command)

    async def stop(self, source: str) -> None:
        _, self.latched = admit(self.latched, source, "stop")
        self._drop()
        await self._motors.stop()

    def release(self, source: str) -> None:
        _, self.latched = admit(self.latched, source, "release")

    async def run(self, sleep) -> None:
        while True:
            await sleep(self.period_s)
            await self.tick()

    async def tick(self) -> None:
        action = deadman(self._clock.monotonic(), self._received_s, self._held is not None,
                         self.driver is not None, self.timeout_s)
        try:
            if action == "drive":
                await self._motors.send(self._held)
            elif action == "stop":
                self._drop()
                await self._motors.stop()
        except Exception as exc:
            logger.warning("deadman %s failed: %s", action, exc)

    def _drop(self) -> None:
        self._held, self._received_s, self.driver = None, -math.inf, None

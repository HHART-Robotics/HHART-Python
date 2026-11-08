from __future__ import annotations

import asyncio

from hhart.arbitration import OPERATOR, ROS, Arbiter, admit, deadman
from hhart.clock import ManualClock

P, T = 0.2, 0.5  # example P and T, configure appropriate values depending on robot


class Motors:
    def __init__(self):
        self.sent = []

    async def send(self, command):
        self.sent.append(command)

    async def stop(self):
        self.sent.append("stop")


def arbiter():
    clock, motors = ManualClock(), Motors()
    return Arbiter(motors, clock, period_s=P, timeout_s=T), clock, motors


def test_an_operator_stop_latches_out_other_sources_until_the_operator_releases():
    latched = False
    _, latched = admit(latched, OPERATOR, "stop")
    assert admit(latched, ROS, "drive") == (False, True)
    assert admit(latched, ROS, "release") == (False, True)
    assert admit(latched, ROS, "stop") == (True, True)
    assert admit(latched, OPERATOR, "drive") == (True, True)
    _, latched = admit(latched, OPERATOR, "release")
    assert admit(latched, ROS, "drive") == (True, False)


def test_a_ros_stop_does_not_latch():
    assert admit(False, ROS, "stop") == (True, False)


def test_a_stop_goes_out_on_the_next_tick_and_nothing_after_it():
    assert deadman(10.0, 9.9, commanding=False, driving=True, timeout_s=T) == "stop"
    assert deadman(10.0, 9.9, commanding=False, driving=False, timeout_s=T) is None


def test_the_deadman_holds_every_source_and_stops_it_after_silence():
    for source in (OPERATOR, ROS):
        async def run():
            a, clock, motors = arbiter()
            await a.drive("forward", source)
            for _ in range(2):
                clock.advance(P)
                await a.drive("forward", source)
                await a.tick()
            for _ in range(4):
                clock.advance(P)
                await a.tick()
            return motors.sent, a.driver
        # First drive at once, repeats only via deadman, one stop after T
        assert asyncio.run(run()) == (["forward"] * 5 + ["stop"], None), source


def test_a_new_command_goes_out_at_once_and_a_repeat_waits_for_the_tick():
    async def run():
        a, _, motors = arbiter()
        await a.drive("forward", OPERATOR)
        await a.drive("forward", OPERATOR)
        await a.drive("left", ROS)
        return motors.sent, a.driver
    assert asyncio.run(run()) == (["forward", "left"], ROS)


def test_a_resent_ros_drive_is_refused_after_an_operator_stop_until_release():
    async def run():
        a, _, motors = arbiter()
        await a.drive("forward", ROS)
        await a.stop(OPERATOR)
        for _ in range(5):
            await a.drive("forward", ROS)
        await a.tick()
        await a.drive("left", OPERATOR)
        a.release(OPERATOR)
        await a.drive("forward", ROS)
        return motors.sent
    assert asyncio.run(run()) == ["forward", "stop", "left", "forward"]

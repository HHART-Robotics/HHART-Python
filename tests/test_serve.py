from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from hhart.contract import IN, Contract
from hhart.operator import serve

C = Contract(version="1.0.0")


@C.message("drive", direction=IN)
@dataclass(frozen=True)
class Drive:
    direction: str
    pct: int


@C.message("stop", direction=IN)
@dataclass(frozen=True)
class Stop:
    pass


@C.message("error")
@dataclass(frozen=True)
class Error:
    text: str


class Socket:
    def __init__(self, *incoming):
        self.incoming, self.sent = [json.dumps(m) if isinstance(m, dict) else m for m in incoming], []

    async def send(self, text):
        self.sent.append(json.loads(text))

    def __aiter__(self):
        return self._messages()

    async def _messages(self):
        for raw in self.incoming:
            yield raw


class Publisher:
    def __init__(self):
        self.clients = set()

    def add(self, ws):
        self.clients.add(ws)

    def discard(self, ws):
        self.clients.discard(ws)


def run(ws, calls, publisher=None):
    async def drive(m):
        if m.pct > 100:
            raise ValueError("pct over 100")
        calls.append(m)

    async def stop(_):
        calls.append("stop")

    async def leave():
        calls.append("left")

    asyncio.run(serve(ws, C, publisher or Publisher(), {"drive": drive, "stop": stop},
                      reject=lambda text: C.encode(Error(text)), snapshot=lambda: [{"type": "status"}],
                      moves={"drive": True, "stop": False}, on_leave=leave))


def test_describe_then_the_snapshot_then_commands_reach_their_handlers():
    ws, calls = Socket({"type": "drive", "direction": "forward", "pct": 40}, {"type": "stop"}), []
    run(ws, calls)
    assert ws.sent[0] == C.describe() and ws.sent[1] == {"type": "status"}
    assert calls == [Drive("forward", 40), "stop"]


def test_bad_input_is_refused_in_the_contract_s_terms_and_the_rest_still_runs():
    ws, calls = Socket("not json", {"type": "error", "text": "x"}, {"type": "drive", "pct": 1},
                       {"type": "drive", "direction": "left", "pct": 500}, {"type": "stop"}), []
    run(ws, calls)
    errors = [m["text"] for m in ws.sent if m["type"] == "error"]
    assert errors == ["invalid JSON", "not a command this robot accepts: 'error'",
                      "not a command this robot accepts: 'drive'", "pct over 100"]
    assert calls == ["stop"]


def test_a_client_that_leaves_while_driving_stops_the_robot_and_one_that_stopped_does_not():
    moving, calls = Socket({"type": "drive", "direction": "forward", "pct": 40}), []
    run(moving, calls)
    assert calls[-1] == "left"
    stopped, calls = Socket({"type": "drive", "direction": "forward", "pct": 40}, {"type": "stop"}), []
    publisher = Publisher()
    run(stopped, calls, publisher)
    assert calls[-1] == "stop" and not publisher.clients

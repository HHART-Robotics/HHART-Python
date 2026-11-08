from __future__ import annotations

import array
import json
from dataclasses import dataclass, field

import pytest

from hhart.contract import IN, Contract

C = Contract(version="1.2.0")


@dataclass(frozen=True)
class Point:
    angle_deg: float
    range_mm: float


@C.message("scan")
@dataclass(frozen=True)
class Scan:
    points: tuple[Point, ...]
    frame: bytes
    note: str | None
    ok: bool
    count: int = field(metadata={"unit": "items"})


@C.message("drive", direction=IN)
@dataclass(frozen=True)
class Drive:
    direction: str
    pct: int


@C.message("stop", direction=IN)
@dataclass(frozen=True)
class Stop:
    pass


C.passthrough("battery", topic="/battery_state", ros_type="sensor_msgs/msg/BatteryState",
              fields={"voltage_v": "voltage"}, units={"voltage_v": "V"}, max_hz=2.0)
C.passthrough("imu_raw", topic="/imu", ros_type="sensor_msgs/msg/Imu",
              fields=["linear_acceleration.x"])

SCAN = Scan(points=(Point(0.5, 101.25), Point(180.0, 98.75)), frame=b"\xff\xd8",
            note=None, ok=True, count=2)


def test_curated_messages_round_trip_through_json():
    for message in (SCAN, Drive("forward", 40), Stop()):
        wire = json.loads(json.dumps(C.encode(message)))
        assert C.decode(wire) == message


def test_the_wire_format_is_flat_json_with_a_type():
    assert C.encode(Drive("left", 25)) == {"type": "drive", "direction": "left", "pct": 25}
    assert C.encode(Stop()) == {"type": "stop"}
    assert C.encode(SCAN)["frame"] == "/9g="


def test_a_type_outside_the_contract_cannot_be_sent():
    with pytest.raises(KeyError):
        C.encode(Point(0.0, 0.0))


@pytest.mark.parametrize("bad", [
    {"type": "nope"},
    {"type": "drive", "direction": "left"},
    {"type": "drive", "direction": "left", "pct": "fast"},
    {**C.encode(SCAN), "ok": "yes"},
    {**C.encode(SCAN), "frame": "not base64!"},
    "drive",
    None,
])
def test_bad_input_decodes_to_none(bad):
    assert C.decode(bad) is None


def test_names_are_unique_and_describe_is_reserved():
    with pytest.raises(ValueError):
        C.passthrough("drive", topic="/x", ros_type="std_msgs/msg/String", fields=["data"])
    with pytest.raises(ValueError):
        C.message("describe")(Point)
    with pytest.raises(TypeError):
        C.message("plain")(object)


def test_passthrough_picks_declared_fields_from_a_ros_dict():
    ros = {"header": {"frame_id": "base"}, "voltage": 7.4, "cell_voltage": array.array("f", [3.7])}
    assert C.passthrough_payload("battery", ros) == {"type": "battery", "voltage_v": 7.4}
    imu = {"linear_acceleration": {"x": 0.25, "y": 0.0, "z": 9.81}}
    assert C.passthrough_payload("imu_raw", imu) == {"type": "imu_raw", "linear_acceleration_x": 0.25}


def test_array_values_become_lists():
    c = Contract(version="0")
    c.passthrough("cells", topic="/b", ros_type="sensor_msgs/msg/BatteryState",
                  fields={"cells_v": "cell_voltage"})
    assert c.passthrough_payload("cells", {"cell_voltage": array.array("d", [3.5, 3.6])}) == {
        "type": "cells", "cells_v": [3.5, 3.6]}


def test_max_hz_throttles_a_passthrough():
    battery = C.passthroughs[0]
    assert battery.due(None, 10.0)
    assert not battery.due(10.0, 10.4)
    assert battery.due(10.0, 10.5)
    assert C.passthroughs[1].due(10.0, 10.0)


def test_describe_lists_every_message_and_no_ros_names():
    d = C.describe()
    assert d["type"] == "describe" and d["version"] == "1.2.0"
    assert [m["name"] for m in d["messages"]] == ["scan", "drive", "stop", "battery", "imu_raw"]
    scan = d["messages"][0]["fields"]
    assert {"name": "points", "type": "list of object"} in scan
    assert {"name": "note", "type": "str or null"} in scan
    assert {"name": "count", "type": "int", "unit": "items"} in scan
    text = json.dumps(d)
    assert "sensor_msgs" not in text and "/battery_state" not in text


def test_examples_cover_every_type_and_each_curated_one_decodes():
    examples = C.examples()
    assert [m["type"] for m in examples] == ["describe", "scan", "drive", "stop", "battery", "imu_raw"]
    for m in examples[1:4]:
        assert C.decode(m) is not None, m["type"]


def test_the_spec_names_every_message_and_draws_it():
    spec = C.markdown()
    assert "version 1.2.0" in spec and "```mermaid" in spec
    for name in ("scan", "drive", "stop", "battery", "imu_raw", "/battery_state", "sensor_msgs/msg/Imu"):
        assert name in spec

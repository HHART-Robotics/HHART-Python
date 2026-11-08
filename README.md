# hhart

HHART's Python package and CLI. Stdlib only.

## Install

```text
uv pip install "hhart @ git+https://github.com/HHART-Robotics/HHART.git@v0.1.0#subdirectory=python"
```

Or build it with colcon (it has a `package.xml`) and run `ros2 run hhart hhart`.

## Modules

| Module | |
| --- | --- |
| `hhart.ports` | `TelemetrySource`, `Publisher` and `Clock` protocols |
| `hhart.clock` | `SystemClock`, and `ManualClock` for tests |
| `hhart.arbitration` | Operator latch (`admit`), deadman (`deadman`) and `Arbiter` |
| `hhart.rate_limit`, `hhart.retry` | Rate limiting and reconnecting for telemetry sources |
| `hhart.websocket_publisher` | Fan-out to WebSocket clients |
| `hhart.contract` | Contract registry, `describe`, generated spec and golden fixture |
| `hhart.operator` | `serve`, one operator WebSocket connection |
| `hhart.cli` | `hhart new`, `check` and `contract` |
| `hhart.testing.fitness` | Rule checks for a robot's tests |

## Checks

The checks parse source with `ast`, so nothing is imported. Each raises
`AssertionError` listing the offending files.

| Check | Fails when | Rule |
| --- | --- | --- |
| `assert_core_is_pure(core)` | the core imports a device, transport or middleware library | 2 |
| `assert_dependencies_point_inward(package)` | an inner layer imports an outer one (`core`, `adapters`, `apps`) | 2 |
| `assert_middleware_confined(package, "rclpy", to=adapter)` | rclpy is imported outside its adapter | 2, 4 |
| `assert_no_load_time_imports(package, ROS_PACKAGES)` | ROS is imported at module level | 9 |
| `assert_roots_reach_the_core(apps, core)` | an entry point never uses the core | 2 |
| `assert_roots_have_no_import_effects(apps)` | importing an entry point parses args, sets up logging or installs signal handlers | 9 |
| `assert_literals_confined(package, literals, to=module)` | a wire format or message type appears outside the module that owns it | 4, 6 |

`check_all(package)` runs the default set:

```python
from hhart.testing import fitness


def test_architecture():
    failed = [f"Rule {rule}, {check}: {error}" for rule, check, error in fitness.check_all("myrobot") if error]
    assert not failed, "\n".join(failed)
```

The checks expect a package split into `core`, `adapters` and `apps`.

## Contract

```python
from dataclasses import dataclass

from hhart.contract import IN, Contract

CONTRACT = Contract(version="0.1.0")


@CONTRACT.message("drive", direction=IN)
@dataclass(frozen=True)
class Drive:
    direction: str
    pct: int


CONTRACT.passthrough("battery", topic="/battery_state", ros_type="sensor_msgs/msg/BatteryState",
                     fields={"voltage_v": "voltage"}, units={"voltage_v": "V"}, max_hz=1.0)
```

`encode` and `decode` handle tier 1 messages, `passthrough_payload` tier 2.
`describe()` is sent to the UI on connect. `markdown()` and `examples()` give
`CONTRACT.md` and the golden fixture.

## Tests

```text
uv venv && uv pip install -e ".[dev]"
pytest
```

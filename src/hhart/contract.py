from __future__ import annotations

import base64
import binascii
import dataclasses
import types
import typing
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

IN = "in"     # Operator to robot
OUT = "out"   # Robot to operator
DESCRIBE = "describe"
_EXAMPLES = {bool: True, int: 3, float: 1.5, str: "text", bytes: b"\x01\x02"}
_TYPE_NAMES = {bool: "bool", int: "int", float: "float", str: "str", bytes: "base64"}


@dataclass(frozen=True)
class Curated:
    name: str
    cls: type
    direction: str


@dataclass(frozen=True)
class Passthrough:

    name: str
    topic: str
    ros_type: str
    fields: Mapping[str, str]
    units: Mapping[str, str] = field(default_factory=dict)
    max_hz: float | None = None

    def due(self, last_s: float | None, now_s: float) -> bool:
        return self.max_hz is None or last_s is None or now_s - last_s >= 1.0 / self.max_hz


class Contract:

    def __init__(self, version: str) -> None:
        self.version = version
        self._curated: dict[str, Curated] = {}
        self._passthrough: dict[str, Passthrough] = {}
        self._names: dict[type, str] = {}

    def message(self, name: str, *, direction: str = OUT):
        """Units in field name or metadata["unit"]"""
        if direction not in (IN, OUT):
            raise ValueError(f"direction {direction!r}")

        def register(cls):
            if not dataclasses.is_dataclass(cls):
                raise TypeError(f"{cls.__name__} is not a dataclass")
            self._claim(name)
            self._curated[name] = Curated(name, cls, direction)
            self._names[cls] = name
            return cls
        return register

    def passthrough(self, name: str, *, topic: str, ros_type: str,
                    fields: Mapping[str, str] | Sequence[str],
                    units: Mapping[str, str] | None = None, max_hz: float | None = None) -> None:
        """List form: dots in each path become underscores"""
        self._claim(name)
        if not isinstance(fields, Mapping):
            fields = {path.replace(".", "_"): path for path in fields}
        self._passthrough[name] = Passthrough(name, topic, ros_type, dict(fields),
                                              dict(units or {}), max_hz)

    def _claim(self, name: str) -> None:
        if name == DESCRIBE or name in self._curated or name in self._passthrough:
            raise ValueError(f"contract message {name!r} defined twice or reserved")

    @property
    def curated(self) -> tuple[Curated, ...]:
        return tuple(self._curated.values())

    @property
    def passthroughs(self) -> tuple[Passthrough, ...]:
        return tuple(self._passthrough.values())

    def encode(self, message) -> dict:
        return {"type": self._names[type(message)], **_jsonable(dataclasses.asdict(message))}

    def decode(self, data):
        """Tier 1 only. None for unknown type or bad field"""
        entry = self._curated.get(data.get("type")) if isinstance(data, Mapping) else None
        if entry is None:
            return None
        try:
            return _build(entry.cls, data)
        except (KeyError, TypeError, ValueError, binascii.Error):
            return None

    def passthrough_payload(self, name: str, message: Mapping) -> dict:
        entry = self._passthrough[name]
        return {"type": name, **{key: _jsonable(_at(message, path))
                                 for key, path in entry.fields.items()}}

    def describe(self) -> dict:
        messages = [{"name": e.name, "tier": "curated", "direction": e.direction,
                     "fields": _curated_fields(e.cls)} for e in self.curated]
        messages += [{"name": p.name, "tier": "passthrough", "direction": OUT,
                      "fields": [{"name": k, **({"unit": p.units[k]} if k in p.units else {})}
                                 for k in p.fields]} for p in self.passthroughs]
        return {"type": DESCRIBE, "version": self.version, "messages": messages}

    def examples(self) -> list[dict]:
        return ([self.describe()]
                + [self.encode(_example(e.cls)) for e in self.curated]
                + [{"type": p.name, **{k: 1.5 for k in p.fields}} for p in self.passthroughs])

    def markdown(self) -> str:
        out_names = ", ".join(e.name for e in self.curated if e.direction == OUT)
        in_names = ", ".join(e.name for e in self.curated if e.direction == IN)
        lines = [f"# Operator contract, version {self.version}", "",
                 "Generated from the robot's contract registry; edit the registry, not this file.",
                 "", "```mermaid", "flowchart LR"]
        if out_names:
            lines.append(f'  core["robot core"] -- "{out_names}" --> op["operator"]')
        if in_names:
            lines.append(f'  op["operator"] -- "{in_names}" --> core["robot core"]')
        if self._passthrough:
            lines.append(f'  ros["ROS topics"] -- "{", ".join(self._passthrough)}" --> op["operator"]')
        lines += ["```", "",
                  "Every message is a JSON object with a `type`. On connect the robot sends "
                  "`describe`: the version and every message below. Unknown types are ignored.", "",
                  "## Curated (tier 1)", "",
                  "| Message | Direction | Fields |", "| --- | --- | --- |"]
        for e in self.curated:
            fields = ", ".join(f"`{f['name']}` {f['type']}" + (f" ({f['unit']})" if "unit" in f else "")
                               for f in _curated_fields(e.cls)) or "none"
            direction = "robot to operator" if e.direction == OUT else "operator to robot"
            lines.append(f"| `{e.name}` | {direction} | {fields} |")
        if self._passthrough:
            lines += ["", "## Declared ROS topics (tier 2, robot to operator, read-only)", "",
                      "| Message | ROS topic | ROS type | Fields |", "| --- | --- | --- | --- |"]
            for p in self.passthroughs:
                fields = ", ".join(f"`{k}` = `{path}`" + (f" ({p.units[k]})" if k in p.units else "")
                                   for k, path in p.fields.items())
                lines.append(f"| `{p.name}` | `{p.topic}` | `{p.ros_type}` | {fields} |")
        return "\n".join(lines) + "\n"


def _jsonable(value):
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "tolist"):  # numpy and array.array from ROS conversions
        return value.tolist()
    return value


def _at(message: Mapping, path: str):
    value = message
    for part in path.split("."):
        value = value[part]
    return value


def _is_optional(tp) -> bool:
    return typing.get_origin(tp) in (typing.Union, types.UnionType)


def _non_none(tp):
    (inner,) = [a for a in typing.get_args(tp) if a is not type(None)]
    return inner


def _build(cls, data: Mapping):
    hints = typing.get_type_hints(cls)
    return cls(**{f.name: _value(hints[f.name], data[f.name]) for f in dataclasses.fields(cls)})


def _value(tp, raw):
    if _is_optional(tp):
        return None if raw is None else _value(_non_none(tp), raw)
    if typing.get_origin(tp) is tuple:
        return tuple(_value(typing.get_args(tp)[0], item) for item in raw)
    if dataclasses.is_dataclass(tp):
        return _build(tp, raw)
    if tp is bytes:
        return base64.b64decode(raw, validate=True)
    if tp is bool:
        if not isinstance(raw, bool):
            raise TypeError(f"{raw!r} is not a bool")
        return raw
    if tp in (int, float, str):
        return tp(raw)
    return raw


def _type_name(tp) -> str:
    if _is_optional(tp):
        return f"{_type_name(_non_none(tp))} or null"
    if typing.get_origin(tp) is tuple:
        return f"list of {_type_name(typing.get_args(tp)[0])}"
    if dataclasses.is_dataclass(tp):
        return "object"
    return _TYPE_NAMES.get(tp, getattr(tp, "__name__", str(tp)))


def _curated_fields(cls) -> list[dict]:
    hints = typing.get_type_hints(cls)
    return [{"name": f.name, "type": _type_name(hints[f.name]),
             **({"unit": f.metadata["unit"]} if "unit" in f.metadata else {})}
            for f in dataclasses.fields(cls)]


def _example(cls):
    hints = typing.get_type_hints(cls)
    return cls(**{f.name: _example_value(hints[f.name]) for f in dataclasses.fields(cls)})


def _example_value(tp):
    if _is_optional(tp):
        return _example_value(_non_none(tp))
    if typing.get_origin(tp) is tuple:
        return (_example_value(typing.get_args(tp)[0]),)
    if dataclasses.is_dataclass(tp):
        return _example(tp)
    if tp not in _EXAMPLES:
        raise TypeError(f"no example for {tp!r}")
    return _EXAMPLES[tp]

from __future__ import annotations

import ast
import importlib.util
import pathlib
from typing import Iterable

DEFAULT_IO_LIBS = frozenset({
    "asyncio", "cv2", "mcap", "rclpy", "serial", "serial_asyncio", "socket",
    "websockets",
})

ROS_PACKAGES = frozenset({
    "rclpy", "rosidl_runtime_py", "geometry_msgs", "nav_msgs", "sensor_msgs", "std_msgs",
})

# Inner to outer
DEFAULT_LAYERS = ("core", "adapters", "apps")


def package_dir(package: str) -> pathlib.Path:
    try:
        spec = importlib.util.find_spec(package)
    except ModuleNotFoundError:
        spec = None
    if spec is None or not spec.submodule_search_locations:
        raise AssertionError(f"{package} is not an importable package")
    return pathlib.Path(list(spec.submodule_search_locations)[0])


def _parse(path: pathlib.Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))


def _sources(root: pathlib.Path) -> list[pathlib.Path]:
    return sorted(root.rglob("*.py"))


def imported_modules(path: pathlib.Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(_parse(path)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def _top_level(modules: Iterable[str]) -> set[str]:
    return {m.split(".")[0] for m in modules}


def load_time_modules(path: pathlib.Path) -> set[str]:
    """Imports outside functions, incl. under if/try and class bodies"""
    found: set[str] = set()
    stack: list[ast.AST] = [_parse(path)]
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            stack.extend(ast.iter_child_nodes(node))
    return found


def _fail(summary: str, offenders: list[str]) -> None:
    if offenders:
        raise AssertionError(summary + ":\n  " + "\n  ".join(offenders))


def assert_core_is_pure(core_package: str,
                        forbidden: Iterable[str] = DEFAULT_IO_LIBS) -> None:
    root = package_dir(core_package)
    forbidden = set(forbidden)
    offenders = [f"{path.relative_to(root)}: {name}"
                 for path in _sources(root)
                 for name in sorted(_top_level(imported_modules(path)) & forbidden)]
    _fail(f"{core_package} imports I/O libraries", offenders)


def assert_dependencies_point_inward(package: str,
                                     layers: Iterable[str] = DEFAULT_LAYERS) -> None:
    """layers: innermost first"""
    root = package_dir(package)
    layers = list(layers)
    offenders = []
    for depth, layer in enumerate(layers):
        outer = {f"{package}.{name}" for name in layers[depth + 1:]}
        layer_dir = root / layer
        if not layer_dir.is_dir():
            continue
        for path in _sources(layer_dir):
            for module in sorted(imported_modules(path)):
                if any(module == o or module.startswith(o + ".") for o in outer):
                    offenders.append(f"{path.relative_to(root)}: {module}")
    _fail(f"{package} dependencies point outward", offenders)


def assert_middleware_confined(package: str, middleware: str, *, to: str) -> None:
    root = package_dir(package)
    allowed = package_dir(to)
    offenders = []
    for path in _sources(root):
        if path.is_relative_to(allowed):
            continue
        if middleware in _top_level(imported_modules(path)):
            offenders.append(str(path.relative_to(root)))
    _fail(f"{middleware} imported outside {to}", offenders)


def assert_no_load_time_imports(package: str, modules: Iterable[str]) -> None:
    root = package_dir(package)
    modules = set(modules)
    offenders = [f"{path.relative_to(root)}: {name}"
                 for path in _sources(root)
                 for name in sorted(load_time_modules(path) & modules)]
    _fail(f"{sorted(modules)} imported at module level in {package}", offenders)


def assert_roots_reach_the_core(roots_package: str, core_package: str) -> None:
    root = package_dir(roots_package)
    offenders = [path.name for path in _sources(root)
                 if path.name != "__init__.py"
                 and not any(m == core_package or m.startswith(core_package + ".")
                             for m in imported_modules(path))]
    _fail(f"{roots_package} modules that never reach {core_package}", offenders)


def assert_roots_have_no_import_effects(roots_package: str) -> None:
    root = package_dir(roots_package)
    effects = ("parse_args", "basicConfig", "signal.signal")
    offenders = []
    for path in _sources(root):
        for node in _parse(path).body:
            if not isinstance(node, (ast.Expr, ast.Assign)):
                continue
            for call in ast.walk(node):
                if isinstance(call, ast.Call):
                    name = ast.unparse(call.func)
                    if name.endswith(effects):
                        offenders.append(f"{path.name}: {name}() at import")
    _fail(f"{roots_package} acts at import time", offenders)


def assert_literals_confined(package: str, literals: Iterable[str], *,
                             to: str) -> None:
    """Plain text match, skips comment and docstring lines"""
    root = package_dir(package)
    allowed = package_dir(to) if _is_package(to) else _module_path(to)
    offenders = []
    for path in _sources(root):
        if path == allowed or path.is_relative_to(allowed):
            continue
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            stripped = line.strip()
            if stripped.startswith(("#", "*", '"', "'")):
                continue
            for literal in literals:
                if literal in stripped:
                    offenders.append(f"{path.relative_to(root)}: {stripped[:60]}")
    _fail(f"{package} re-encodes literals owned by {to}", offenders)


def check_all(package: str) -> list[tuple[str, str, str | None]]:
    """(rule, check, failure or None) per default check"""
    core, apps, ros = f"{package}.core", f"{package}.apps", f"{package}.adapters.ros"
    checks = [
        ("2", "the core has no I/O or ROS", lambda: assert_core_is_pure(core)),
        ("2", "dependencies point inward", lambda: assert_dependencies_point_inward(package)),
        ("2", "composition roots reach the core", lambda: assert_roots_reach_the_core(apps, core)),
        ("4", "rclpy only in adapters.ros", lambda: assert_middleware_confined(package, "rclpy", to=ros)),
        ("4", "rosidl_runtime_py only in adapters.ros",
         lambda: assert_middleware_confined(package, "rosidl_runtime_py", to=ros)),
        ("9", "no ROS import at load time", lambda: assert_no_load_time_imports(package, ROS_PACKAGES)),
        ("9", "importing a root has no effect", lambda: assert_roots_have_no_import_effects(apps)),
    ]
    if _is_module(f"{core}.contract"):
        checks.append(("6", "messages built only by core.contract",
                       lambda: assert_literals_confined(package, ('"type"', "'type'"), to=f"{core}.contract")))
    results = []
    for rule, name, check in checks:
        try:
            check()
            results.append((rule, name, None))
        except AssertionError as exc:
            results.append((rule, name, str(exc)))
    return results


def _is_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        return False


def _is_package(name: str) -> bool:
    try:
        spec = importlib.util.find_spec(name)
    except ModuleNotFoundError:
        return False
    return bool(spec and spec.submodule_search_locations)


def _module_path(name: str) -> pathlib.Path:
    try:
        spec = importlib.util.find_spec(name)
    except ModuleNotFoundError:
        spec = None
    if spec is None or not spec.origin:
        raise AssertionError(f"{name} is not an importable module")
    return pathlib.Path(spec.origin)

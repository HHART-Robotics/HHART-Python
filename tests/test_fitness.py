"""Unique package names per test, find_spec answers from sys.modules once resolved"""

from __future__ import annotations

import importlib
import sys

import pytest

from hhart.testing import fitness

CLEAN = {
    "__init__.py": "",
    "core/__init__.py": "",
    "core/domain.py": "import math\n",
    "adapters/__init__.py": "",
    "adapters/wire.py": "import socket\nfrom PKG.core import domain\n",
    "adapters/ros/__init__.py": "",
    "adapters/ros/node.py": "def build():\n    import rclpy\n    return rclpy\n",
    "apps/__init__.py": "",
    "apps/main.py": "from PKG.core import domain\n\n\ndef main():\n    pass\n",
}


@pytest.fixture
def package(tmp_path, monkeypatch, request):
    name = "toy_" + request.node.name.replace("test_", "", 1)

    def build(**overrides) -> str:
        files = dict(CLEAN, **overrides)
        for relative, source in files.items():
            path = tmp_path / name / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source.replace("PKG", name), encoding="utf-8")
        monkeypatch.syspath_prepend(str(tmp_path))
        importlib.invalidate_caches()
        for module in [m for m in sys.modules if m == name or m.startswith(name + ".")]:
            del sys.modules[module]
        return name

    return build


def test_core_is_pure_rejects_an_io_import(package):
    name = package(**{"core/domain.py": "import socket\n"})
    with pytest.raises(AssertionError, match="socket"):
        fitness.assert_core_is_pure(f"{name}.core")


def test_core_is_pure_accepts_the_standard_library(package):
    fitness.assert_core_is_pure(f"{package()}.core")


def test_dependencies_point_inward_rejects_core_importing_adapters(package):
    name = package(**{"core/domain.py": "from PKG.adapters import wire\n"})
    with pytest.raises(AssertionError, match="adapters"):
        fitness.assert_dependencies_point_inward(name)


def test_dependencies_point_inward_rejects_adapters_importing_apps(package):
    name = package(**{"adapters/wire.py": "from PKG.apps import main\n"})
    with pytest.raises(AssertionError, match="apps"):
        fitness.assert_dependencies_point_inward(name)


def test_middleware_confined_rejects_a_leak_outside_its_adapter(package):
    name = package(**{"adapters/wire.py": "import rclpy\n"})
    with pytest.raises(AssertionError, match="rclpy"):
        fitness.assert_middleware_confined(name, "rclpy", to=f"{name}.adapters.ros")


def test_middleware_confined_allows_it_inside_its_adapter(package):
    name = package(**{"adapters/ros/node.py": "import rclpy\n"})
    fitness.assert_middleware_confined(name, "rclpy", to=f"{name}.adapters.ros")


def test_no_load_time_imports_rejects_a_module_level_import(package):
    name = package(**{"adapters/ros/node.py": "import rclpy\n"})
    with pytest.raises(AssertionError, match="rclpy"):
        fitness.assert_no_load_time_imports(name, fitness.ROS_PACKAGES)


def test_no_load_time_imports_allows_one_inside_a_function(package):
    fitness.assert_no_load_time_imports(package(), fitness.ROS_PACKAGES)


def test_no_load_time_imports_rejects_an_import_under_try(package):
    name = package(**{"apps/main.py": "try:\n    import rclpy\nexcept ImportError:\n    rclpy = None\n"})
    with pytest.raises(AssertionError, match="rclpy"):
        fitness.assert_no_load_time_imports(name, fitness.ROS_PACKAGES)


def test_roots_reach_the_core_rejects_a_root_that_only_wires_adapters(package):
    name = package(**{"apps/main.py": "from PKG.adapters import wire\n"})
    with pytest.raises(AssertionError, match="main.py"):
        fitness.assert_roots_reach_the_core(f"{name}.apps", f"{name}.core")


def test_roots_have_no_import_effects_rejects_a_call_at_module_level(package):
    name = package(**{"apps/main.py": "import argparse\nargs = argparse.ArgumentParser().parse_args()\n"})
    with pytest.raises(AssertionError, match="parse_args"):
        fitness.assert_roots_have_no_import_effects(f"{name}.apps")


def test_roots_have_no_import_effects_allows_the_call_inside_main(package):
    name = package(**{"apps/main.py": "import argparse\n\n\ndef main():\n    argparse.ArgumentParser().parse_args()\n"})
    fitness.assert_roots_have_no_import_effects(f"{name}.apps")


def test_literals_confined_rejects_a_hand_built_wire_string(package):
    name = package(**{"apps/main.py": "def send():\n    return 'CMD:motor_stop'\n"})
    with pytest.raises(AssertionError, match="CMD:motor_stop"):
        fitness.assert_literals_confined(f"{name}.apps", ("CMD:motor_stop",),
                                         to=f"{name}.core.domain")


def test_literals_confined_allows_the_format_in_a_comment(package):
    name = package(**{"apps/main.py": "# sends CMD:motor_stop through the core\n"})
    fitness.assert_literals_confined(f"{name}.apps", ("CMD:motor_stop",),
                                     to=f"{name}.core.domain")


def test_a_missing_package_is_an_error_not_a_pass(package):
    with pytest.raises(AssertionError, match="not an importable package"):
        fitness.assert_core_is_pure("no_such_robot.core")


def test_check_all_passes_a_clean_package_and_names_the_rule_a_violation_breaks(package):
    assert [error for _, _, error in fitness.check_all(package())] == [None] * 7
    name = package(**{"core/domain.py": "import rclpy\n", "core/contract.py": 'X = {"type": "x"}\n',
                      "apps/main.py": 'X = {"type": "x"}\n'})
    failed = {(rule, check) for rule, check, error in fitness.check_all(name) if error}
    assert failed == {("2", "the core has no I/O or ROS"), ("4", "rclpy only in adapters.ros"),
                      ("9", "no ROS import at load time"), ("2", "composition roots reach the core"),
                      ("6", "messages built only by core.contract")}

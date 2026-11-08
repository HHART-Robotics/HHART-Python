from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys

import pytest

import hhart
from hhart.cli import main, template_dir

SRC = pathlib.Path(hhart.__file__).resolve().parents[1]
REPO = pathlib.Path(__file__).resolve().parents[2]


def test_new_renames_the_template_everywhere_and_pins_this_version(tmp_path):
    assert main(["new", "rover", "--into", str(tmp_path)]) == 0
    robot = tmp_path / "rover"
    paths = [p for p in robot.rglob("*")]
    assert not [p for p in paths if "robot1" in p.name]
    assert not [p for p in paths if p.is_file() and b"robot1" in p.read_bytes()]
    assert (robot / "software" / "python" / "src" / "rover" / "core" / "session.py").is_file()
    assert (robot / "software" / "ros" / "rover_bringup" / "package.xml").is_file()
    assert not (robot / "COLCON_IGNORE").exists()
    assert f"v{hhart.__version__}" in (robot / "software" / "ros" / "rover.repos").read_text(encoding="utf-8")


def test_new_refuses_a_bad_name_and_an_existing_folder(tmp_path):
    for bad in ("Rover", "2wd", "my-robot", "class", "hhart"):
        with pytest.raises(SystemExit):
            main(["new", bad, "--into", str(tmp_path)])
    (tmp_path / "rover").mkdir()
    with pytest.raises(SystemExit, match="exists"):
        main(["new", "rover", "--into", str(tmp_path)])


def test_a_new_robot_passes_its_own_tests_and_hhart_check(tmp_path):
    main(["new", "crawler", "--into", str(tmp_path)])
    python = tmp_path / "crawler" / "software" / "python"
    env = dict(os.environ, PYTHONPATH=str(SRC))
    tests = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=python,
                           env=env, capture_output=True, text=True)
    assert tests.returncode == 0, tests.stdout[-2000:]
    check = subprocess.run([sys.executable, "-m", "hhart", "check", str(tmp_path / "crawler")],
                           env=env, capture_output=True, text=True)
    assert check.returncode == 0 and "8 of 8 checks pass" in check.stdout, check.stdout


@pytest.mark.parametrize("route, gone, kept", [
    ("embedded", ["software/ros", "software/python/src/{n}/apps/robot.py"], ["software/firmware", "software/python/src/{n}/apps/bridge.py"]),
    ("ros", ["software/firmware", "software/python/src/{n}/apps/bridge.py"], ["software/ros", "software/python/src/{n}/apps/robot.py"]),
])
def test_a_one_route_robot_drops_the_other_route_and_still_passes_its_rules(tmp_path, route, gone, kept):
    name = f"solo_{route}"
    main(["new", name, "--into", str(tmp_path), "--route", route])
    robot = tmp_path / name
    assert not [g for g in gone if (robot / g.format(n=name)).exists()]
    assert all((robot / k.format(n=name)).exists() for k in kept)
    env = dict(os.environ, PYTHONPATH=str(SRC))
    tests = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                           cwd=robot / "software" / "python", env=env, capture_output=True, text=True)
    assert tests.returncode == 0, tests.stdout[-2000:]
    assert main(["check", str(robot)]) == 0


def test_a_new_robot_uses_this_repository_s_interface_kit(tmp_path):
    main(["new", "kit", "--into", str(tmp_path)])
    web = (tmp_path / "kit" / "software" / "apps" / "web" / "package.json").read_text(encoding="utf-8")
    assert f'"@hhart/ui": "link:{(REPO / "ui").as_posix()}"' in web


def test_check_fails_on_a_planted_violation(tmp_path):
    main(["new", "digger", "--into", str(tmp_path)])
    session = tmp_path / "digger" / "software" / "python" / "src" / "digger" / "core" / "session.py"
    session.write_text(session.read_text(encoding="utf-8") + "import rclpy\n", encoding="utf-8")
    assert main(["check", str(tmp_path / "digger")]) == 1


def test_contract_writes_the_spec_and_the_golden_fixture(tmp_path):
    main(["new", "probe", "--into", str(tmp_path)])
    software = tmp_path / "probe" / "software"
    (software / "CONTRACT.md").unlink()
    assert main(["contract", str(tmp_path / "probe")]) == 0
    assert (software / "CONTRACT.md").read_text(encoding="utf-8").startswith("# Operator contract")


def test_the_versions_agree():
    found = {
        "hhart": hhart.__version__,
        "pyproject.toml": re.search(r'^version = "(.+)"', (REPO / "python" / "pyproject.toml").read_text(), re.M)[1],
        "package.xml": re.search(r"<version>(.+)</version>", (REPO / "python" / "package.xml").read_text())[1],
        "CITATION.cff": re.search(r"^version: (.+)$", (REPO / "CITATION.cff").read_text(), re.M)[1],
        "ui/package.json": re.search(r'"version": "(.+)"', (REPO / "ui" / "package.json").read_text())[1],
    }
    for readme in ("README.md", "python/README.md", "ui/README.md"):
        for i, pinned in enumerate(re.findall(r"(?:@|--branch |#)v(\d+\.\d+\.\d+)", (REPO / readme).read_text())):
            found[f"{readme} install line {i + 1}"] = pinned
    assert len(set(found.values())) == 1, found


def test_every_copy_of_the_licence_and_the_notice_is_the_same():
    licence = (REPO / "LICENSE").read_bytes()
    assert b"Apache License" in licence and b"Version 2.0, January 2004" in licence
    for copy in ("python/LICENSE", "ui/LICENSE", "template/LICENSES/Apache-2.0.txt"):
        assert (REPO / copy).read_bytes() == licence, copy
    for copy in ("python/NOTICE", "ui/NOTICE"):
        assert (REPO / copy).read_bytes() == (REPO / "NOTICE").read_bytes(), copy


def test_the_template_ships_with_the_package():
    assert (template_dir() / "software" / "python" / "src" / "robot1").is_dir()

"""
Commands:

    new NAME [--into DIR] [--route embedded|ros|both]   new robot from the template
    check [PATH] [--package NAME]                       rules check, exits 1 on a fail
    contract [PATH] [--package NAME]                    regen CONTRACT.md and the golden fixture

PATH: robot root or its software/python. From ROS: ros2 run hhart hhart <command>.
"""

from __future__ import annotations

import argparse
import importlib
import json
import keyword
import pathlib
import re
import shutil
import stat
import sys

import hhart

TOKEN = "robot1"
VERSION_TOKEN = "HHART_VERSION"
NAME = re.compile(r"^[a-z][a-z0-9_]*$")
SKIP = ("__pycache__", "*.pyc", ".pytest_cache", "node_modules", "dist", "build", ".pio", "*.egg-info", "recordings")
UI_DEPENDENCY = '"@hhart/ui": "workspace:*"'
UI_MIRROR = "github:HHART-Robotics/HHART-UI"

SP = "software/python"
ROUTES = {
    "embedded": [f"{SP}/src/robot1/apps/bridge.py", f"{SP}/src/robot1/adapters/firmware_link.py",
                 f"{SP}/src/robot1/adapters/ros/node.py", f"{SP}/src/robot1/core/protocol.py",
                 f"{SP}/tests/test_protocol.py", f"{SP}/tests/test_firmware.py",
                 "software/firmware", "software/deploy/systemd/robot1.service"],
    "ros": [f"{SP}/src/robot1/apps/robot.py", f"{SP}/src/robot1/adapters/ros/devices.py",
            f"{SP}/src/robot1/adapters/ros/passthrough.py", f"{SP}/src/robot1/core/health.py",
            f"{SP}/tests/test_health.py", f"{SP}/tests/ros", "software/ros",
            "software/deploy/systemd/robot1-ros.service"],
}


def template_dir() -> pathlib.Path:
    here = pathlib.Path(hhart.__file__).resolve().parent
    for candidate in (here / "template", here.parents[2] / "template"):
        if (candidate / "software").is_dir():
            return candidate
    raise SystemExit("hhart: this install has no template; install hhart from its repository")


def ui_dependency(template: pathlib.Path) -> str:
    repo_ui = template.parent / "ui"
    if (repo_ui / "package.json").is_file():
        return f'"@hhart/ui": "link:{repo_ui.as_posix()}"'
    return f'"@hhart/ui": "{UI_MIRROR}#v{hhart.__version__}"'


def new(name: str, into: pathlib.Path, route: str = "both") -> int:
    if not NAME.match(name) or keyword.iskeyword(name) or name in ("hhart", "test", "tests"):
        raise SystemExit(f"hhart: {name!r}: lowercase letters, digits and underscores, starting with a letter")
    dest = into / name
    if dest.exists():
        raise SystemExit(f"hhart: {dest} already exists")
    template = template_dir()
    shutil.copytree(template, dest, ignore=shutil.ignore_patterns(*SKIP), copy_function=shutil.copyfile)
    
    for path in [dest, *dest.rglob("*")]:
        path.chmod(path.stat().st_mode | stat.S_IWRITE)
    (dest / "COLCON_IGNORE").unlink(missing_ok=True)  
    for other, paths in ROUTES.items():
        if route not in ("both", other):
            for rel in paths:
                target = dest / rel
                shutil.rmtree(target) if target.is_dir() else target.unlink(missing_ok=True)
    web = dest / "software" / "apps" / "web" / "package.json"
    web.write_text(web.read_text(encoding="utf-8").replace(UI_DEPENDENCY, ui_dependency(template)),
                   encoding="utf-8", newline="\n")
    
    for path in sorted(dest.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if path.is_file():
            data = path.read_bytes()
            renamed = data.replace(TOKEN.encode(), name.encode()).replace(
                VERSION_TOKEN.encode(), hhart.__version__.encode())
            if renamed != data:
                path.write_bytes(renamed)
        if TOKEN in path.name:
            path.rename(path.with_name(path.name.replace(TOKEN, name)))
    print(f"{dest}: robot {name} on hhart {hhart.__version__}, route {route}. Next:\n"
          f"  {dest / 'README.md'}, section Run: a uv venv for software/python, pnpm install at the root,\n"
          f"  then {name}-bridge --port loopback and pnpm dev")
    return 0


def python_dir(path: pathlib.Path) -> pathlib.Path:
    for candidate in (path, path / "software" / "python"):
        if (candidate / "src").is_dir():
            return candidate.resolve()
    raise SystemExit(f"hhart: no src/ in {path} or {path / 'software' / 'python'}")


def package_of(python: pathlib.Path, name: str | None) -> str:
    if name:
        return name
    found = sorted(p.name for p in (python / "src").iterdir() if (p / "__init__.py").is_file())
    if len(found) != 1:
        raise SystemExit(f"hhart: name the package with --package; src/ holds {found or 'none'}")
    return found[0]


def check(path: pathlib.Path, name: str | None) -> int:
    from hhart.testing import fitness

    python = python_dir(path)
    package = package_of(python, name)
    sys.path.insert(0, str(python / "src"))
    results = fitness.check_all(package)
    for rule, what, error in results:
        print(f"{'ok  ' if error is None else 'FAIL'}  Rule {rule}: {what}")
        if error:
            print("        " + error.replace("\n", "\n        "))
    failed = sum(error is not None for _, _, error in results)
    print(f"{package}: {len(results) - failed} of {len(results)} checks pass")
    return 1 if failed else 0


def contract(path: pathlib.Path, name: str | None) -> int:
    python = python_dir(path)
    package = package_of(python, name)
    sys.path.insert(0, str(python / "src"))
    registry = importlib.import_module(f"{package}.core.contract").CONTRACT
    spec = python.parent / "CONTRACT.md"
    golden = python.parent / "apps" / "web" / "src" / "core" / "contract.golden.json"
    spec.write_text(registry.markdown(), encoding="utf-8", newline="\n")
    golden.parent.mkdir(parents=True, exist_ok=True)
    golden.write_text(json.dumps(registry.examples(), indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {spec} and {golden}, contract version {registry.version}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="hhart", description="start a robot, check it, regen its contract")
    p.add_argument("--version", action="version", version=f"hhart {hhart.__version__}")
    sub = p.add_subparsers(dest="command", required=True)
    n = sub.add_parser("new", help="new robot from the template")
    n.add_argument("name")
    n.add_argument("--into", type=pathlib.Path, default=pathlib.Path("."))
    n.add_argument("--route", choices=("embedded", "ros", "both"), default="both",
                   help="keep one route, or both so you can switch on the robot later")
    for command, text in (("check", "check the rules, one line each"),
                          ("contract", "regen CONTRACT.md and the golden fixture")):
        c = sub.add_parser(command, help=text)
        c.add_argument("path", nargs="?", type=pathlib.Path, default=pathlib.Path("."))
        c.add_argument("--package", help="which package, if src/ has more than one")
    args = p.parse_args(argv)
    if args.command == "new":
        return new(args.name, args.into, args.route)
    return {"check": check, "contract": contract}[args.command](args.path, args.package)

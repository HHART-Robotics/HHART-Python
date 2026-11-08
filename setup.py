"""For colcon, pip uses pyproject.toml. Both bundle ../template for hhart new"""

import pathlib
import shutil

from setuptools import setup
from setuptools.command.build_py import build_py

TEMPLATE = pathlib.Path(__file__).resolve().parent.parent / "template"
SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", "node_modules", "dist", "build",
                              ".pio", "*.egg-info", "recordings")


class BuildPy(build_py):
    def run(self):
        super().run()
        if TEMPLATE.is_dir():  # Missing in sdist builds
            shutil.copytree(TEMPLATE, pathlib.Path(self.build_lib) / "hhart" / "template",
                            ignore=SKIP, dirs_exist_ok=True)


setup(
    python_requires=">=3.10",
    cmdclass={"build_py": BuildPy},
    data_files=[("share/ament_index/resource_index/packages", ["resource/hhart"]),
                ("share/hhart", ["package.xml"])],
)

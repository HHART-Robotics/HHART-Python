from __future__ import annotations

import sys

from hhart.testing import fitness


def test_hhart_depends_on_nothing_outside_the_standard_library():
    root = fitness.package_dir("hhart")
    allowed = set(sys.stdlib_module_names) | {"hhart", "__future__"}
    offenders = [f"{path.relative_to(root)}: {name}"
                 for path in sorted(root.rglob("*.py"))
                 for name in sorted({m.split(".")[0] for m in fitness.imported_modules(path)} - allowed)]
    assert not offenders, "hhart imports outside the standard library:\n  " + "\n  ".join(offenders)

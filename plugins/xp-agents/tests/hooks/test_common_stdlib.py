#!/usr/bin/env python3
"""Tests for _common.py — stdlib-only import policy (AC M1).

Split from test_common.py (pure move, no test-body edits). Scans all
scripts/*.py and smm/*.py for non-stdlib imports.
Sibling groups: hook I/O (test_common_io.py), persistence
(test_common_persistence.py), event/arg bookkeeping (test_common_events.py).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))


# Explicit `from event_schema import EVENT_TYPE_*` so a future constant rename
# fails at test collection (NameError) instead of silently changing a
# make_event(...) call's behavior.


class TestStdlibOnly(unittest.TestCase):
    """AC (M1): Python stdlib only — no external packages."""

    def test_no_external_imports(self):
        """Scan all .py files for non-stdlib imports."""
        import pkgutil

        project_modules = frozenset(
            {
                "_common",
                "_append_impl",
                "read_delta",
                "materialize",
                "pre_tool_use",
                "post_tool_use",
                "lint_check",
                "bash_post_tool",
                "session_start",
                "session_end",
                "pre_compact",
                "subagent_start",
                "subagent_stop",
                "user_prompt_log",
                "retrospective",
            }
        )

        stdlib_names = {m.name for m in pkgutil.iter_modules()}
        stdlib_names |= set(sys.stdlib_module_names)

        project_root = Path(__file__).parent.parent.parent
        py_files = list(project_root.glob("scripts/*.py")) + list(
            project_root.glob("smm/*.py")
        )

        violations = []
        for py_file in py_files:
            if py_file.name.startswith("test_"):
                continue
            source = py_file.read_text()
            in_docstring = False
            for line in source.splitlines():
                stripped = line.strip()
                if '"""' in stripped or "'''" in stripped:
                    count = stripped.count('"""') + stripped.count("'''")
                    if count == 1:
                        in_docstring = not in_docstring
                    continue
                if in_docstring or stripped.startswith("#"):
                    continue
                if not (stripped.startswith("import ") or stripped.startswith("from ")):
                    continue
                if stripped.startswith("from "):
                    module = stripped.split()[1].split(".")[0]
                else:
                    module = stripped.split()[1].split(".")[0]
                if module not in stdlib_names and module not in project_modules:
                    violations.append(f"{py_file.name}: {stripped}")

        msg = "Non-stdlib imports found:\n" + "\n".join(violations)
        self.assertEqual(violations, [], msg)


if __name__ == "__main__":
    unittest.main()

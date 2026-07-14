#!/usr/bin/env python3
"""Shared fixture for the lint suites that ask the REAL linter binaries.

Extracted from test_lint_polyglot at the commit that pushed it past the 500-line cap.
The split is by QUESTION, not by line count. Two different things are being proved:

  * test_lint_polyglot  — what the BINARIES do (the facts our tables encode).
  * test_lint_compile_db — what OUR GATE does with a compile database, against those
    same binaries (coverage, and the base the paths resolve against).

Both need the same probe, the same config, and the same throwaway project, and neither
may fake them: a hand-written stub encodes the AUTHOR'S MODEL of the CLI, so it cannot
fail in the one way that matters — the model being wrong. See test_lint_polyglot's
docstring for why that is the whole point of these suites.
"""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


def _usable(binary: str) -> str | None:
    """The path to `binary`, but ONLY if it actually runs.

    On PATH is not the same as functional, and the difference is not academic:
    checkstyle is a JVM launcher, and under a too-old JDK it is on PATH and throws
    `LinkageError` before it can lint a thing. A guard that asked only `which` would
    have run these tests against a binary that cannot start — and, worse, the same
    confusion lives in PRODUCTION: a crashing checkstyle exits non-zero WITH output,
    which the gate's contract reads as FINDINGS. "Cannot start" and "found
    violations" are indistinguishable by exit code alone.
    """
    path = shutil.which(binary)
    if not path:
        return None
    try:
        probe = subprocess.run(
            [path, "--version"], capture_output=True, text=True, timeout=60
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return path if probe.returncode == 0 else None


_CLANG_TIDY = _usable("clang-tidy")
_CHECKSTYLE = _usable("checkstyle")
_CLANG_FORMAT = _usable("clang-format")

# `skipUnless` guards every use at runtime, but pyright cannot see through a class
# decorator — so narrow to `str` here. The fallback name is never invoked: the class
# is skipped whenever the probe above came back None.
CLANG_TIDY: str = _CLANG_TIDY or "clang-tidy"
CHECKSTYLE: str = _CHECKSTYLE or "checkstyle"
CLANG_FORMAT: str = _CLANG_FORMAT or "clang-format"

# A check with no compiler-flag dependency, so the finding is about the CODE and not
# about the build. Braces-around-statements fires on a one-line `if`.
_CLANG_TIDY_CONFIG = "Checks: '-*,readability-braces-around-statements'\n"
_DIRTY_C = "int main(void) {\n    if (1) return 0;\n    return 1;\n}\n"
_CLEAN_C = "int main(void) {\n    return 0;\n}\n"


def _run(argv: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv, cwd=str(cwd), capture_output=True, text=True, timeout=60
    )


class _TmpProject(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.d = Path(self._tmp.name)

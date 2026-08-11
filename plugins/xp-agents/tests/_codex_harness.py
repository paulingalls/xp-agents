#!/usr/bin/env python3
"""Plumbing for tests that shell out to the second harness's CLI.

Three suites need it: `test_marketplace_install.py`, which proves the catalog is
a shape the harness accepts, `test_install_docs.py`, which drives the documented
install sequence, and `integration/test_dual_packaging_e2e.py`, which installs
from that catalog and reads the version back out of the copy. Each docstring
below records something that was MEASURED, and a second copy of those lessons
would be a second thing to keep true — which is the whole reason this module
exists rather than the plumbing being duplicated.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _paths import _PLUGIN_ROOT

_HARNESS = "codex"
_PLUGIN_ID = "xp-agents@xp-agents"

_REPO_ROOT = _PLUGIN_ROOT.parents[1]

# Every harness call is bounded. An unbounded one already cost a 600s run once
# (the skip probe, before its recursion guard): with no timeout a wedged child
# hangs the whole suite instead of failing one row.
_HARNESS_TIMEOUT = 120
_INNER_RUN_TIMEOUT = 300


def _isolated_home() -> tuple[dict, Path]:
    """An environment whose harness state is a fresh temp directory.

    Every harness invocation runs under one of these. The user's real config
    already carries a marketplace registered against this very repo (left by the
    packaging spike), so without isolation a passing install could be satisfied
    by that standing registration instead of by the catalog under test — and
    worse, the suite would mutate the developer's own state.
    """
    home = Path(tempfile.mkdtemp())
    env = os.environ.copy()
    env["CODEX_HOME"] = str(home)
    return env, home


def _harness(env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [_HARNESS, "plugin", *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=_HARNESS_TIMEOUT,
    )


def _installed_entry(listed: subprocess.CompletedProcess) -> dict:
    """The plugin's record in a `--json` listing, or fail loudly.

    `next(...)` over the list would raise StopIteration on an empty install,
    which surfaces as an opaque error rather than as the assertion the row is
    actually making.
    """
    installed = json.loads(listed.stdout)["installed"]
    for entry in installed:
        if entry.get("pluginId") == _PLUGIN_ID:
            return entry
    raise AssertionError(f"nothing installed under that id: {installed}")


def _installed_root(add_stdout: str) -> Path:
    """The tree the harness COPIED the plugin into, taken from its own report.

    Not the listing's `source.path`: that is where the plugin was read FROM (the
    live repo), so a row comparing it against the repo compares a directory with
    itself and holds whatever the install did. The copy under the temp home is
    the only tree an install actually produces, and this line is where the
    harness names it.
    """
    match = re.search(r"^Installed plugin root: (.+)$", add_stdout, re.MULTILINE)
    if not match:
        raise AssertionError(f"install reported no plugin root: {add_stdout!r}")
    return Path(match.group(1).strip())


def assert_module_skips_without_harness(
    case: unittest.TestCase,
    module_path: Path,
    gated_classes: tuple[type, ...],
) -> None:
    """Re-run *module_path* with no harness on PATH; its gated rows must SKIP.

    The claim needs its own check because a developer machine HAS the harness, so
    the skip branch never runs there. A decorator that silently took the pass
    branch would look identical in a green suite; running the module with the
    harness stripped from PATH is what tells the two apart.

    The inner run DESELECTS the calling probe class, whose name is taken from
    *case* rather than passed in — a caller naming the wrong class gets a probe
    that re-enters its own module and recurses until the timeout kills it, so
    deriving it removes the only way to misuse this helper. Without the deselect
    at all, that recursion already killed one run: the guard is load-bearing, not
    tidiness. It rides on the spawn ARGUMENTS rather than on an environment
    sentinel deliberately: a sentinel is inherited, so an outer shell that
    happened to export it would make this whole probe vanish silently instead of
    failing.

    Parameterized on `gated_classes` rather than copied because those classes are
    local to each consuming module; the floor is derived from them via
    `getTestCaseNames`, so a row added to any consumer raises the bar without
    anyone remembering to.
    """
    probe_class_name = type(case).__name__
    empty = Path(tempfile.mkdtemp())
    case.addCleanup(shutil.rmtree, empty, ignore_errors=True)

    env = os.environ.copy()
    # An EMPTY PATH rather than one filtered of directories containing the
    # harness: the harness shares a directory with the test runner here, so
    # filtering would strip the runner too. The inner run needs no PATH at all —
    # it is launched through the interpreter running this test.
    env["PATH"] = str(empty)
    case.assertIsNone(
        shutil.which(_HARNESS, path=env["PATH"]),
        "the harness is still reachable, so the inner run would take the RUN "
        "branch and prove nothing about skipping",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(module_path),
            "-q",
            "--no-header",
            "-k",
            f"not {probe_class_name}",
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=_REPO_ROOT,
        check=False,
        timeout=_INNER_RUN_TIMEOUT,
    )
    tail = result.stdout[-2000:]

    case.assertEqual(result.returncode, 0, tail)
    # Counted, not merely matched: `\d+ skipped` also matches "0 skipped", so the
    # number has to be compared against the rows that MUST skip.
    gated = sum(
        len(unittest.defaultTestLoader.getTestCaseNames(cls)) for cls in gated_classes
    )
    reported = re.findall(r"(\d+) skipped", result.stdout)
    case.assertTrue(
        reported, f"a harness-free run reported no skips at all. stdout: {tail}"
    )
    case.assertGreaterEqual(
        int(reported[0]),
        gated,
        f"fewer than the {gated} harness-gated rows reported as skipped — a "
        f"harness-free run must skip them, never quietly pass. stdout: {tail}",
    )

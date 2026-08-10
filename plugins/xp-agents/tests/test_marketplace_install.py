#!/usr/bin/env python3
"""The second harness really registers this repo and installs the plugin.

The sibling `test_marketplace_catalogs` pins the two catalogs' SHAPE by reading
JSON — hermetic, always runs. This file proves the shape is the one the harness
actually accepts, by shelling out to it. That split is why the two are separate
modules: everything here needs the CLI on PATH and skips without it, and every
row writes to a throwaway home.

Schema pins alone would not carry the claim. `marketplace add` was measured
returning zero against this repo while the catalog did not exist at all, so
registration proves nothing on its own — the load is asserted from the listing,
and the install from reading the plugin back out of the tree it produced.
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

sys.path.insert(0, str(Path(__file__).parent))

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

    Every harness invocation in this file runs under one of these. The user's
    real config already carries a marketplace registered against this very repo
    (left by the packaging spike), so without isolation a passing install could
    be satisfied by that standing registration instead of by the catalog under
    test — and worse, the suite would mutate the developer's own state.
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


@unittest.skipUnless(
    shutil.which(_HARNESS), f"{_HARNESS} not on PATH — install-dependent rows skip"
)
class TestRealRegistrationAndInstall(unittest.TestCase):
    """Register the repo as a marketplace, install from it, read the result."""

    def _registered_home(self) -> dict:
        """A fresh home with this repo registered, cleaned up with the test."""
        env, home = _isolated_home()
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        added = _harness(env, "marketplace", "add", str(_REPO_ROOT))
        self.assertEqual(added.returncode, 0, added.stderr)
        return env

    def test_the_temp_home_starts_with_no_marketplace_in_scope(self):
        """Isolation is asserted, not assumed.

        Without this, every row below could be satisfied by the developer's
        pre-existing registration against this repo rather than by the catalog.
        The exit code is asserted first: a listing that FAILED also prints no
        marketplace, and would pass an absence check while proving nothing.
        """
        env, home = _isolated_home()
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)

        listed = _harness(env, "marketplace", "list")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertNotIn("xp-agents", listed.stdout)

    def test_registering_this_repo_surfaces_the_plugin_from_the_catalog(self):
        listed = _harness(self._registered_home(), "list")

        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertIn(
            _PLUGIN_ID,
            listed.stdout,
            "the catalog did not surface the plugin — registration alone is not "
            f"proof of a load. stdout: {listed.stdout}",
        )

    def test_installing_reports_the_version_from_the_manifest_it_pointed_at(self):
        """Install, then read the record back.

        The installed record is read as JSON, which carries the resolved source
        path and the version. Note the listing is only rich AFTER an install —
        before one, `--json` reports empty lists on a home whose text output
        already names the plugin, so this asserts post-install state.
        """
        env = self._registered_home()
        added = _harness(env, "add", _PLUGIN_ID)
        self.assertEqual(added.returncode, 0, added.stderr)

        listed = _harness(env, "list", "--json")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        entry = _installed_entry(listed)

        manifest = json.loads(
            (_PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        self.assertEqual(entry["version"], manifest["version"])
        self.assertEqual(
            Path(entry["source"]["path"]).resolve(), _PLUGIN_ROOT.resolve()
        )

    def test_every_shipped_skill_is_discoverable_in_the_installed_tree(self):
        """The COPY, not the source. An install materialises a tree under the
        home; reading the listing's `source.path` back would name the live repo
        and compare it with itself.
        """
        env = self._registered_home()
        added = _harness(env, "add", _PLUGIN_ID)
        self.assertEqual(added.returncode, 0, added.stderr)

        installed_root = _installed_root(added.stdout)
        self.assertTrue(
            installed_root.is_relative_to(Path(env["CODEX_HOME"]).resolve()),
            f"install landed outside the isolated home: {installed_root}",
        )
        skills_dir = installed_root / "skills"
        self.assertTrue(skills_dir.is_dir(), f"install copied no skills: {skills_dir}")

        installed_skills = sorted(p.name for p in skills_dir.iterdir())
        shipped_skills = sorted(p.name for p in (_PLUGIN_ROOT / "skills").iterdir())

        self.assertTrue(shipped_skills, "no skills shipped to compare against")
        self.assertEqual(installed_skills, shipped_skills)


@unittest.skipUnless(
    shutil.which(_HARNESS), f"{_HARNESS} not on PATH — install-dependent rows skip"
)
class TestWrongSourceFailsTheInstall(unittest.TestCase):
    """The negative that gives the install rows their meaning.

    Built in a throwaway fixture root rather than by editing the shipped catalog:
    registering a local marketplace was measured reporting the live directory as
    its root, so the CATALOG is read in place with no snapshot copy (the plugin
    tree, by contrast, IS copied into the home at install). Mutating the real
    catalog to prove a failure would therefore write to a tracked file, and could
    leave the tree dirty on a crash.
    """

    def test_a_source_path_naming_no_directory_fails_rather_than_installs(self):
        env, home = _isolated_home()
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        fixture = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, fixture, ignore_errors=True)

        catalog_dir = fixture / ".agents" / "plugins"
        catalog_dir.mkdir(parents=True)
        (catalog_dir / "marketplace.json").write_text(
            json.dumps(
                {
                    "name": "wrong-source",
                    "interface": {"displayName": "Wrong source"},
                    "plugins": [
                        {
                            "name": "xp-agents",
                            "source": {"source": "local", "path": "./nowhere"},
                            "policy": {"installation": "AVAILABLE"},
                            "category": "Developer Tools",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        self.assertEqual(
            _harness(env, "marketplace", "add", str(fixture)).returncode,
            0,
            "registration is expected to succeed — it does not read the source",
        )
        added = _harness(env, "add", "xp-agents@wrong-source")

        self.assertNotEqual(
            added.returncode, 0, f"install should have failed: {added.stdout}"
        )
        self.assertIn("not a directory", (added.stderr + added.stdout).lower())


_GATED_CLASSES = (TestRealRegistrationAndInstall, TestWrongSourceFailsTheInstall)


class TestTheSkipPathIsClean(unittest.TestCase):
    """With no harness on PATH the rows above SKIP — they do not pass.

    The claim needs its own check because this machine has the harness, so the
    skip branch never runs here. A decorator that silently took the pass branch
    would look identical in a green suite; running the module with the harness
    stripped from PATH is what tells the two apart.

    The inner run DESELECTS this class by name. Written without that, the probe
    re-entered its own module and recursed until the run was killed — the guard
    is load-bearing, not tidiness. It rides on the spawn arguments rather than on
    an environment sentinel deliberately: a sentinel is inherited, so an outer
    shell that happened to export it would make this whole probe vanish silently
    instead of failing.
    """

    def test_the_module_skips_cleanly_without_the_harness(self):
        empty = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)

        env = os.environ.copy()
        # An EMPTY PATH rather than one filtered of directories containing the
        # harness: the harness shares a directory with the test runner here, so
        # filtering would strip the runner too. The inner run needs no PATH at
        # all — it is launched through sys.executable.
        env["PATH"] = str(empty)
        self.assertIsNone(
            shutil.which(_HARNESS, path=env["PATH"]),
            "the harness is still reachable, so the inner run would take the "
            "RUN branch and prove nothing about skipping",
        )

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                str(Path(__file__)),
                "-q",
                "--no-header",
                "-k",
                f"not {type(self).__name__}",
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=_REPO_ROOT,
            check=False,
            timeout=_INNER_RUN_TIMEOUT,
        )
        tail = result.stdout[-2000:]

        self.assertEqual(result.returncode, 0, tail)
        # Counted, not merely matched: `\d+ skipped` also matches "0 skipped",
        # so the number has to be compared against the rows that MUST skip.
        # Derived from the classes rather than written down, so a row added to
        # either one raises the bar without anyone remembering to.
        gated = sum(
            len(unittest.defaultTestLoader.getTestCaseNames(cls))
            for cls in _GATED_CLASSES
        )
        reported = re.findall(r"(\d+) skipped", result.stdout)
        self.assertTrue(
            reported, f"a harness-free run reported no skips at all. stdout: {tail}"
        )
        self.assertGreaterEqual(
            int(reported[0]),
            gated,
            f"fewer than the {gated} harness-gated rows reported as skipped — a "
            f"harness-free run must skip them, never quietly pass. stdout: {tail}",
        )


if __name__ == "__main__":
    unittest.main()

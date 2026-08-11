#!/usr/bin/env python3
"""Milestone 8 capstone: the second catalog installs, and the copy names itself.

Six stories shipped Milestone 8. Each proves its own half; the milestone's done
clause names a chain none of them owns: *a generated variant that the second
manifest actually names, a catalog that installs that manifest, and a version
read that reports the copy so installed.* This module carries the second and
third links — the ones needing the harness CLI, which skip without it. The first
link (the manifest naming what the emitter wrote) is hermetic and lives in
`test_dual_packaging_manifest_chain.py`; the two were split when the combined
file reached three lines below the per-file band floor, since sitting just under
a limit is the shape that produced the same debt four times here.

Not to be confused with `test_milestone_08_capstone.py`, which belongs to
sprint-062's DIFFERENT "M-8" (close-cycle frictions) under an older milestone
numbering. This file is named for its content precisely so the two do not
collide.

## What this file deliberately does NOT re-run

Story-005 (README install and trust prose) and story-006 (the shipped-prose
harness-leak pin) ship no behaviour to drive through this chain. Each is held by
its own suite — `tests/test_install_docs.py` and
`tests/test_shipped_prose_harness_agnostic.py`, whose existence is asserted below
so this carve-out cannot end up naming a deleted file. Re-running them here would
duplicate assertions already in the same suite run and buy nothing. The sibling
capstone carves out its doc-only story the same way, for the same reason.
"""

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import plugin_loader
from _bases import _PLUGIN_ROOT, _AssertNotNoneMixin
from _codex_harness import (
    _HARNESS,
    _PLUGIN_ID,
    _REPO_ROOT,
    _harness,
    _installed_root,
    _isolated_home,
    assert_module_skips_without_harness,
)

# The version read is a bounded subprocess like every harness call: an unbounded
# child hangs the whole suite instead of failing one row.
_VERSION_READ_TIMEOUT = 60

# The suites holding the two prose surfaces this chain carves out. Named here so
# the docstring's claim is checked rather than asserted in prose alone.
_PROSE_PIN_SUITES = (
    _PLUGIN_ROOT / "tests" / "test_install_docs.py",
    _PLUGIN_ROOT / "tests" / "test_shipped_prose_harness_agnostic.py",
)


def _version_from_inside(installed_root: Path, env: dict) -> str:
    """What the INSTALLED COPY says its own version is.

    Runs the copy's own `scripts/plugin_loader.py`, not the repo's. The whole
    point of that read is to name the copy that is executing, so asking the
    repo's loader about the install would answer a different question — and would
    still pass if the install were empty.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import plugin_loader; print(plugin_loader.plugin_version())",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=_VERSION_READ_TIMEOUT,
        env={
            **env,
            "CLAUDE_PLUGIN_ROOT": str(installed_root),
            "PYTHONPATH": str(installed_root / "scripts"),
        },
    )
    assert result.returncode == 0, f"the copy's loader failed: {result.stderr}"
    return result.stdout.strip()


@unittest.skipUnless(
    shutil.which(_HARNESS), f"{_HARNESS} not on PATH — install-dependent rows skip"
)
class TestTheInstalledCopyReportsItsOwnVersion(_AssertNotNoneMixin, unittest.TestCase):
    """Links two and three: the catalog installs, and the copy names itself.

    Installed in setUpClass rather than per row — an install is a real subprocess
    that copies a tree, and every row below reads the same result. Not once per
    RUN: the suite runs under `-n auto`, whose default distribution hands
    individual rows to different workers, so each worker that draws one pays its
    own install into its own isolated home.
    """

    @classmethod
    def setUpClass(cls):
        cls.env = env = _isolated_home(cls.addClassCleanup)

        registered = _harness(env, "marketplace", "add", str(_REPO_ROOT))
        assert registered.returncode == 0, registered.stderr
        added = _harness(env, "add", _PLUGIN_ID)
        assert added.returncode == 0, added.stderr

        cls.installed_root = _installed_root(added.stdout)
        cls.reported = _version_from_inside(cls.installed_root, env)

    def test_the_install_landed_inside_the_isolated_home(self):
        """An install that landed elsewhere proves nothing about this catalog —
        it could be the developer's own standing registration answering."""
        self.assertTrue(
            self.installed_root.is_relative_to(Path(self.env["CODEX_HOME"]).resolve()),
            f"install landed outside the isolated home: {self.installed_root}",
        )

    def test_the_installed_manifest_names_a_hooks_file_inside_the_copy(self):
        """Link one, re-asked of the INSTALLED tree rather than of a fixture.

        The hermetic half proves the manifest and the hooks emitter agree on a
        name; it proves that in a temp root the harness never touched. Nothing
        else asks whether an INSTALL carries the file that agreement names, and
        the two are different questions: a copy that skipped `hooks/` would leave
        the manifest naming a path that resolves to nothing, with the version read
        above still green because it reads `.codex-plugin/` instead.

        `is_relative_to` is asserted too, not only `is_file`: a manifest hook path
        resolves against the plugin root and must stay inside it, so a declared
        `../` would be a real escape rather than a missing file.
        """
        manifest = self.installed_root / ".codex-plugin" / "plugin.json"
        declared = json.loads(manifest.read_text(encoding="utf-8"))["hooks"]
        resolved = (self.installed_root / declared).resolve()

        self.assertTrue(
            resolved.is_relative_to(self.installed_root.resolve()),
            f"the installed manifest's hooks path escapes the plugin root: "
            f"{declared!r} resolved to {resolved}",
        )
        self.assertTrue(
            resolved.is_file(),
            f"the installed manifest names {declared!r}, which the install did "
            f"not put at {resolved}",
        )

    def test_the_copy_reports_the_version_the_catalog_pointed_at(self):
        expected = json.loads(
            (_PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )["version"]

        self.assertNotEqual(
            self.reported,
            "?",
            "the installed copy could not name its own version — either the path "
            "it executes from names a version no manifest in it declares (the "
            "cache-bumped-in-place state), or no manifest could be read at all. "
            "Note a mere DISAGREEMENT between the two manifests would not land "
            "here: with a version-keyed path the component matches one of them "
            "and that one is returned, which is story-002's drift pins to catch, "
            "not this row's",
        )
        self.assertEqual(self.reported, expected)

    def test_the_path_attribution_branch_is_what_answered(self):
        """Which code path produced the answer, not just whether it was right.

        The version read has a weaker fallback: with no version-shaped path
        component it agrees two manifests against each other. Install roots were
        measured as version-keyed (`.../xp-agents/<version>/`), so the branch that
        should answer here is path attribution — the one whose absence was the
        original defect, where a session reported one number while executing from
        a directory keyed to another. If the install layout ever stopped carrying
        that component, the row above would keep passing on the weaker branch and
        nobody would know.
        """
        key = self._assert_not_none(
            plugin_loader._version_key_component(self.installed_root),
            f"{self.installed_root} is not a version-keyed directory, so the "
            "weaker agreement branch answered and this chain no longer covers "
            "path attribution",
        )

        self.assertEqual(
            self.reported,
            key.removeprefix("v"),
            "the reported version is not the one the executing path names",
        )


class TestTheProseCarveOutNamesLiveSuites(unittest.TestCase):
    """The carve-out in this module's docstring must not name a deleted file.

    Stories 005 and 006 are deliberately not re-run here. That is only honest
    while the suites said to hold them exist.
    """

    def test_both_carved_out_suites_exist(self):
        for suite in _PROSE_PIN_SUITES:
            self.assertTrue(
                suite.is_file(),
                f"this module's docstring defers story coverage to {suite}, "
                "which does not exist",
            )


_GATED_CLASSES = (TestTheInstalledCopyReportsItsOwnVersion,)


class TestTheSkipPathIsClean(unittest.TestCase):
    """AC#3's second clause: with no harness on PATH the install rows SKIP.

    A developer machine HAS the harness, so the skip branch never runs here and a
    decorator that silently took the PASS branch would look identical in a green
    suite. The probe is shared with story-004's suite and parameterized, because
    `_GATED_CLASSES` names a class local to this module — the skip floor can only
    be derived from what is passed, never shared as a constant.
    """

    def test_the_module_skips_cleanly_without_the_harness(self):
        assert_module_skips_without_harness(
            self,
            module_path=Path(__file__),
            gated_classes=_GATED_CLASSES,
        )


if __name__ == "__main__":
    unittest.main()

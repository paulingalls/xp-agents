#!/usr/bin/env python3
"""The close diff must be captured in a form the relevance rule can match.

The merge gate judges an UNTAGGED concern by intersecting its recorded `files`
with the close diff, and every producer captured that diff with a bare
`--name-only`. Git quotes a path containing non-ASCII bytes, `"` or `\\`, so a
concern naming the real path matched nothing in the diff and read as "provably
about other code" — and was DROPPED. Measured end to end below: one high concern
about a file the close genuinely touched counts 0 under the old capture and 1
under `-z`. That is a merge gate discarding the exact finding it exists to catch.

`-z` closes all three quoting classes; `-c core.quotepath=false` (what the story
record originally prescribed) closes only the non-ASCII one — pinned here so the
cheaper-looking substitution cannot be made later by someone reading the flags
and assuming they are interchangeable.

WHAT `--no-renames` DOES AND DOES NOT DO. It genuinely restores a renamed file's
OLD path to the diff, which `test_no_renames_lists_both_paths` proves against
real git. It does NOT change this gate's count: the relevance rule only drops a
concern whose files ALL EXIST in the working tree, and a renamed file's old path
does not exist, so such a concern already counts fail-closed. The flag is
defence-in-depth for a future rule that stops requiring existence — not a fix for
a live escape, and `test_old_path_counts_under_both_captures` holds that honest
rather than letting a tautology read as a proof.

A prose pin alone would pass while the shipped command was wrong — the exact
fail-open class this story closes — so every behavioural claim here runs real
git, and the pin only guards against a later edit dropping a flag from one site.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from _repo_fixtures import init_repo
from conftest import _PLUGIN_ROOT, _SMMTestCase, run_cli
from event_schema import EVENT_TYPE_CONCERN

_CLI = _PLUGIN_ROOT / "smm" / "smm_cli.py"

# The three shipped sites that capture the close diff. All must carry both flags:
# a future edit that drops one from a single site re-opens the escape there only,
# which is the shape a per-site pin exists to catch.
_CAPTURE_SITES = (
    _PLUGIN_ROOT / "scripts" / "_close_pipeline_shared.md",
    _PLUGIN_ROOT / "skills" / "xp-story-close" / "SKILL.md",
    _PLUGIN_ROOT / "skills" / "xp-free-close" / "SKILL.md",
)

# Paths exercising each class of git path-quoting. The backslash and quote cases
# are what `-c core.quotepath=false` leaves quoted, so they are what make `-z`
# the necessary choice rather than a stylistic one.
_NON_ASCII = "d/café.txt"
_WITH_QUOTE = 'd/we"ird.txt'
_WITH_BACKSLASH = "d/back\\slash.txt"

_CYCLE = "ffff00001111"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout


def _seed_repo(repo: Path) -> None:
    """A base commit plus a `feat` branch touching all three quoting classes."""
    init_repo(str(repo))
    (repo / "d").mkdir()
    for name in (_NON_ASCII, _WITH_QUOTE, _WITH_BACKSLASH):
        (repo / name).write_text("x\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    _git(repo, "checkout", "-b", "feat")
    for name in (_NON_ASCII, _WITH_QUOTE, _WITH_BACKSLASH):
        with (repo / name).open("a") as fh:
            fh.write("y\n")
    _git(repo, "commit", "-am", "touch every quoting class")


def _capture(repo: Path, *flags: str) -> str:
    """The diff as a producer would capture it, with whichever flags are given."""
    return _git(repo, "diff", *flags, "--name-only", "main...feat")


class TestQuotingEscapeIsClosed(unittest.TestCase):
    """`-z` is the only separator under which git never quotes a path."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.repo = Path(self._td.name)
        _seed_repo(self.repo)

    def test_bare_capture_quotes_every_class(self):
        out = _capture(self.repo)
        for name in (_NON_ASCII, _WITH_QUOTE, _WITH_BACKSLASH):
            self.assertNotIn(name, out, f"{name} unexpectedly raw without -z")

    def test_quotepath_false_still_quotes_backslash_and_quote(self):
        """The originally-prescribed flag is a PARTIAL fix. Pinned so nobody
        swaps `-z` back out for it on the assumption they are equivalent."""
        out = _git(
            self.repo,
            "-c",
            "core.quotepath=false",
            "diff",
            "--name-only",
            "main...feat",
        )
        self.assertIn(_NON_ASCII, out, "quotepath=false should fix the non-ASCII case")
        self.assertNotIn(_WITH_QUOTE, out)
        self.assertNotIn(_WITH_BACKSLASH, out)

    def test_z_returns_every_class_raw(self):
        paths = set(_capture(self.repo, "--no-renames", "-z").split("\0")) - {""}
        for name in (_NON_ASCII, _WITH_QUOTE, _WITH_BACKSLASH):
            self.assertIn(name, paths)


class TestNoRenamesRestoresTheOldPath(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.repo = Path(self._td.name)
        init_repo(str(self.repo))
        (self.repo / "d").mkdir()
        (self.repo / "d/old.py").write_text("x\n")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-m", "base")
        _git(self.repo, "checkout", "-b", "feat")
        _git(self.repo, "mv", "d/old.py", "d/new.py")
        with (self.repo / "d/new.py").open("a") as fh:
            fh.write("y\n")
        _git(self.repo, "commit", "-am", "rename")

    def test_bare_capture_hides_the_old_path(self):
        out = _capture(self.repo)
        self.assertIn("d/new.py", out)
        self.assertNotIn("d/old.py", out)

    def test_no_renames_lists_both_paths(self):
        paths = set(_capture(self.repo, "--no-renames", "-z").split("\0")) - {""}
        self.assertIn("d/old.py", paths)
        self.assertIn("d/new.py", paths)


class TestGateCountsThroughTheRealCli(_SMMTestCase):
    """End to end through `count-concerns --diff-paths -`, which is what the
    close skills actually pipe into."""

    def setUp(self):
        super().setUp()
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.repo = Path(self._td.name)
        _seed_repo(self.repo)

    def _count(self, diff: str) -> int:
        result = run_cli(
            _CLI,
            [
                "count-concerns",
                "--diff-paths",
                "-",
                "--severity",
                "high",
                "--cycle-id",
                _CYCLE,
                "--repo-root",
                str(self.repo),
            ],
            self.smm_dir,
            stdin_data=diff,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return int(result.stdout.strip())

    def _write_concern(self, path: str) -> None:
        self.events_file.write_text(
            json.dumps(
                {
                    "id": "aaaabbbbcccc",
                    "ts": "2020-01-01T00:00:00+00:00",
                    "type": EVENT_TYPE_CONCERN,
                    "agent_id": "t",
                    "content": "about a file this close touched",
                    "severity": "high",
                    "files": [path],
                    "schema_version": 1,
                }
            )
            + "\n"
        )

    def test_bare_capture_drops_a_concern_about_a_touched_file(self):
        """The fail-open, demonstrated: the file EXISTS and IS in the diff, but
        the quoted form matches no `files` entry, so the rule reads it as
        provably-other-code and drops it."""
        self._write_concern(_NON_ASCII)
        self.assertEqual(self._count(_capture(self.repo)), 0)

    def test_z_capture_counts_it(self):
        self._write_concern(_NON_ASCII)
        self.assertEqual(self._count(_capture(self.repo, "--no-renames", "-z")), 1)

    def test_quote_and_backslash_paths_also_count_only_under_z(self):
        for path in (_WITH_QUOTE, _WITH_BACKSLASH):
            with self.subTest(path=path):
                self._write_concern(path)
                self.assertEqual(self._count(_capture(self.repo)), 0)
                self.assertEqual(
                    self._count(_capture(self.repo, "--no-renames", "-z")), 1
                )


class TestOldPathCountsUnderBothCaptures(_SMMTestCase):
    """Honesty pin. `--no-renames` does NOT change this gate's verdict, and the
    story's AC implying it does is a tautology: the relevance rule drops only a
    concern whose files all EXIST, and a renamed file's old path does not, so it
    counts fail-closed either way. If a future change makes the rule stop
    requiring existence, this test flips and the flag starts earning its keep.
    """

    def setUp(self):
        super().setUp()
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.repo = Path(self._td.name)
        init_repo(str(self.repo))
        (self.repo / "d").mkdir()
        (self.repo / "d/old.py").write_text("x\n")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-m", "base")
        _git(self.repo, "checkout", "-b", "feat")
        _git(self.repo, "mv", "d/old.py", "d/new.py")
        with (self.repo / "d/new.py").open("a") as fh:
            fh.write("y\n")
        _git(self.repo, "commit", "-am", "rename")
        self.events_file.write_text(
            json.dumps(
                {
                    "id": "aaaabbbbcccc",
                    "ts": "2020-01-01T00:00:00+00:00",
                    "type": EVENT_TYPE_CONCERN,
                    "agent_id": "t",
                    "content": "about the pre-rename path",
                    "severity": "high",
                    "files": ["d/old.py"],
                    "schema_version": 1,
                }
            )
            + "\n"
        )

    def _count(self, diff: str) -> int:
        result = run_cli(
            _CLI,
            [
                "count-concerns",
                "--diff-paths",
                "-",
                "--severity",
                "high",
                "--cycle-id",
                _CYCLE,
                "--repo-root",
                str(self.repo),
            ],
            self.smm_dir,
            stdin_data=diff,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return int(result.stdout.strip())

    def test_counts_one_either_way(self):
        self.assertEqual(self._count(_capture(self.repo)), 1)
        self.assertEqual(self._count(_capture(self.repo, "--no-renames", "-z")), 1)


class TestEveryCaptureSiteCarriesBothFlags(unittest.TestCase):
    """The pin. Behaviour above proves the flags work; this proves all three
    shipped sites use them, so a later edit cannot silently drop one."""

    def test_all_three_sites_carry_no_renames_and_z(self):
        missing = []
        for site in _CAPTURE_SITES:
            text = site.read_text(encoding="utf-8")
            for line in text.splitlines():
                if not ("git diff" in line and "--name-only" in line):
                    continue
                if "--no-renames" not in line or " -z " not in line:
                    missing.append(f"{site.name}: {line.strip()}")
        self.assertFalse(
            missing,
            "close-diff capture site(s) missing --no-renames and/or -z:\n"
            + "\n".join(missing),
        )

    def test_the_pin_is_not_vacuous(self):
        """A pin that finds no capture line passes forever."""
        found = sum(
            1
            for site in _CAPTURE_SITES
            for line in site.read_text(encoding="utf-8").splitlines()
            if "git diff" in line and "--name-only" in line
        )
        self.assertGreaterEqual(found, len(_CAPTURE_SITES), f"only {found} sites found")


if __name__ == "__main__":
    unittest.main()

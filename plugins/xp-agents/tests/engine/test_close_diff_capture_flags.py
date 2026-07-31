#!/usr/bin/env python3
"""The close diff must be captured in a form the relevance rule can match.

The merge gate judges an UNTAGGED concern by intersecting its recorded `files`
with the close diff, and every producer captured that diff with a bare
`--name-only`. Git quotes a path containing non-ASCII bytes, `"` or `\\`, so a
concern naming the real path matched nothing in the diff and read as "provably
about other code" — and was DROPPED. Measured end to end below: one high concern
about a file the close genuinely touched counts 0 under the old capture and 1
under `-z`. That is a merge gate discarding the exact finding it exists to catch.

`-z` closes every quoting class; `-c core.quotepath=false` (what the story record
originally prescribed) closes only the non-ASCII one — pinned here so the
cheaper-looking substitution cannot be made later by someone reading the flags
and assuming they are interchangeable.

A fourth class, the CONTROL bytes, only `-z` can deliver raw at all — a newline
is legal in a POSIX path — and delivering it raw moves the burden to the reader,
which must then not re-split on it. `TestNewlineInPathSurvivesTheReader` covers
that end of the same escape.

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
git. The pin guards only the sweep: a later edit dropping a flag from one site,
or a new site shipping without them.
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

# The three shipped sites that capture the close diff today. Named for the
# vacuity floor only — the pin below SCANS rather than reads this list, because a
# hard-coded list cannot fail on the case that matters most: a FOURTH site added
# later, shipping bare and unpinned. (Same shape as the preload-budget suite's
# on-disk surface scan, which exists for exactly that gap.)
_KNOWN_CAPTURE_SITES = (
    _PLUGIN_ROOT / "scripts" / "_close_pipeline_shared.md",
    _PLUGIN_ROOT / "skills" / "xp-story-close" / "SKILL.md",
    _PLUGIN_ROOT / "skills" / "xp-free-close" / "SKILL.md",
)

_SHIPPED_PROSE_DIRS = (
    _PLUGIN_ROOT / "scripts",
    _PLUGIN_ROOT / "skills",
    _PLUGIN_ROOT / "agents",
)


def _capture_lines() -> list[tuple[Path, str]]:
    """Every shipped-prose line that captures a diff AND pipes it into the gate.

    Keyed on the `count-concerns` consumer within the next few lines, not on
    `git diff --name-only` alone: only a capture feeding THIS gate needs these
    flags, and an unrelated capture documented elsewhere must not go red.
    """
    hits: list[tuple[Path, str]] = []
    for directory in _SHIPPED_PROSE_DIRS:
        for path in sorted(directory.rglob("*.md")):
            lines = path.read_text(encoding="utf-8").splitlines()
            for index, line in enumerate(lines):
                if "git diff" not in line or "--name-only" not in line:
                    continue
                if any("count-concerns" in nxt for nxt in lines[index : index + 4]):
                    hits.append((path, line))
    return hits


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


def _init_repo_with_pinned_diff_defaults(repo: Path) -> None:
    """`init_repo`, plus LOCAL pins for the two git defaults this file contrasts
    the fixed capture against.

    The bare-capture cases assert what git does WITHOUT the flags, and both of
    those behaviours are user-configurable: `core.quotepath=false` is a common
    ergonomics setting for non-ASCII filenames, and `diff.renames` can be turned
    off globally. `init_repo` inherits the developer's global config, so without
    these pins the baseline is whatever the machine says — the bare-capture
    tests go red on a perfectly healthy checkout, and the escape they document
    stops being reproducible. Local config outranks global, so pinning here is
    enough.
    """
    init_repo(str(repo))
    _git(repo, "config", "core.quotepath", "true")
    _git(repo, "config", "diff.renames", "true")


def _seed_repo(repo: Path) -> None:
    """A base commit plus a `feat` branch touching all three quoting classes."""
    _init_repo_with_pinned_diff_defaults(repo)
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


def _seed_rename_repo(repo: Path) -> None:
    """A base commit plus a `feat` branch that renames `d/old.py` to `d/new.py`
    and edits it — enough similarity for git's rename detection to fire."""
    _init_repo_with_pinned_diff_defaults(repo)
    (repo / "d").mkdir()
    (repo / "d/old.py").write_text("x\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    _git(repo, "checkout", "-b", "feat")
    _git(repo, "mv", "d/old.py", "d/new.py")
    with (repo / "d/new.py").open("a") as fh:
        fh.write("y\n")
    _git(repo, "commit", "-am", "rename")


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
        _seed_rename_repo(self.repo)

    def test_bare_capture_hides_the_old_path(self):
        out = _capture(self.repo)
        self.assertIn("d/new.py", out)
        self.assertNotIn("d/old.py", out)

    def test_no_renames_lists_both_paths(self):
        paths = set(_capture(self.repo, "--no-renames", "-z").split("\0")) - {""}
        self.assertIn("d/old.py", paths)
        self.assertIn("d/new.py", paths)


class _GateCountTestCase(_SMMTestCase):
    """Shared plumbing: one untagged high concern, counted through the real CLI
    with a captured diff on stdin — the exact shape the close skills pipe."""

    def setUp(self):
        super().setUp()
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.repo = Path(self._td.name)

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


class TestGateCountsThroughTheRealCli(_GateCountTestCase):
    """End to end through `count-concerns --diff-paths -`, which is what the
    close skills actually pipe into."""

    def setUp(self):
        super().setUp()
        _seed_repo(self.repo)

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


class TestNewlineInPathSurvivesTheReader(_GateCountTestCase):
    """A newline is legal in a POSIX path, and `-z` is the ONLY capture that
    delivers it raw — the bare capture C-quotes it to `\\n`. That makes the
    reader the last line of defence: if it also splits `-z` records on newlines
    the path shatters into fragments, matches nothing, and the concern about a
    file this close touched is dropped — the same fail-open, one class deeper.
    """

    def setUp(self):
        super().setUp()
        _init_repo_with_pinned_diff_defaults(self.repo)
        (self.repo / "d").mkdir()
        (self.repo / self._PATH).write_text("x\n")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-m", "base")
        _git(self.repo, "checkout", "-b", "feat")
        with (self.repo / self._PATH).open("a") as fh:
            fh.write("y\n")
        _git(self.repo, "commit", "-am", "touch the newline path")

    _PATH = "d/we\nird.txt"

    def test_z_capture_delivers_the_newline_path_raw(self):
        paths = set(_capture(self.repo, "--no-renames", "-z").split("\0")) - {""}
        self.assertIn(self._PATH, paths)

    def test_z_capture_counts_a_concern_about_it(self):
        self._write_concern(self._PATH)
        self.assertEqual(self._count(_capture(self.repo, "--no-renames", "-z")), 1)


class TestOldPathCountsUnderBothCaptures(_GateCountTestCase):
    """Honesty pin. `--no-renames` does NOT change this gate's verdict, and the
    story's AC implying it does is a tautology: the relevance rule drops only a
    concern whose files all EXIST, and a renamed file's old path does not, so it
    counts fail-closed either way. If a future change makes the rule stop
    requiring existence, this test flips and the flag starts earning its keep.
    """

    def setUp(self):
        super().setUp()
        _seed_rename_repo(self.repo)
        self._write_concern("d/old.py")

    def test_counts_one_either_way(self):
        self.assertEqual(self._count(_capture(self.repo)), 1)
        self.assertEqual(self._count(_capture(self.repo, "--no-renames", "-z")), 1)


class TestEveryCaptureSiteCarriesBothFlags(unittest.TestCase):
    """The pin. Behaviour above proves the flags work; this proves every shipped
    site that feeds the gate uses them — including one added after this story."""

    def test_every_capture_line_carries_no_renames_and_z(self):
        missing = [
            f"{path.name}: {line.strip()}"
            for path, line in _capture_lines()
            if "--no-renames" not in line or " -z " not in line
        ]
        self.assertFalse(
            missing,
            "close-diff capture site(s) missing --no-renames and/or -z:\n"
            + "\n".join(missing),
        )

    def test_the_scan_still_finds_every_known_site(self):
        """A scan that matches nothing passes forever. Asserted PER SITE: a bare
        total would stay green with one file holding two capture lines and
        another holding none — the drop above then has nothing left to look at
        in the silent file."""
        found = {path for path, _ in _capture_lines()}
        self.assertFalse(
            set(_KNOWN_CAPTURE_SITES) - found,
            "no close-diff capture line found in: "
            f"{sorted(p.name for p in set(_KNOWN_CAPTURE_SITES) - found)}",
        )


if __name__ == "__main__":
    unittest.main()

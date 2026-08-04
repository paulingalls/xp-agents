#!/usr/bin/env python3
"""Which paths the close gate narrows FROM — the input to every other rule.

The veto, the collapse rule and the digest all reason about a changed-path set
`close_gate_commands.changed_paths` derives from git. Every safety property
downstream is only as true as that set: a path missing from it is a path no
selected command has to cover, and the block that follows MERGES WITHOUT
ASKING.

Two ways the set can be wrong, both fail-OPEN, both exercised here:

1. IT CAN BE PARTIAL RATHER THAN EMPTY. The set is the committed range UNION
   the working tree. Both preloads pass `git merge-base "$TARGET_BRANCH" HEAD`
   with stderr suppressed, so a base that will not resolve arrives as an EMPTY
   STRING — and `git diff "...HEAD"` answers an empty diff with exit 0 for it.
   The union then still produces paths, from the working tree alone, so the
   gate narrows to whatever is dirty while the branch's committed work goes
   unseen. "No committed range" and "an empty committed range" have to be
   different answers.

2. IT CAN BE MIS-SPELLED. `git status --porcelain` quotes a path holding a
   space and reports a rename's DESTINATION only. A quoted path matches no
   glob (fail-closed, but narrowing then never fires at all); a dropped rename
   SOURCE silently removes that surface's command from the selection, which is
   fail-open. `-z` answers both, and `--untracked-files=all` names the files in
   a new directory rather than the directory.

THE DEAD-TEST TRAP: no project declares surface `paths`, so an assertion that
forgets to seed one runs against an empty selection and passes vacuously. The
fixture here declares THREE commanded surfaces and every case touches at most
two, so the collapse rule cannot produce the expected answer for the wrong
reason either.
"""

import subprocess
import sys
import unittest
from pathlib import Path
from typing import ClassVar

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from _bases import _PLUGIN_ROOT
from _gate_harness import FULL, GateHarness

sys.path.insert(0, str(_PLUGIN_ROOT / "smm"))
sys.path.insert(0, str(_PLUGIN_ROOT / "scripts"))

import close_gate_commands

_CLI = "pytest tests/cli"
_API = "pytest tests/api"


def _surface(name: str, glob: str, command: str | None = None) -> dict:
    entry: dict = {
        "name": name,
        "signals": ["x"],
        "status": "covered",
        "paths": [glob],
    }
    if command is not None:
        entry["command"] = command
    return entry


class _ChangedSetCase(GateHarness):
    """Drives the real resolver against a real git repo.

    `GateHarness.repo_with` already builds "a repo whose committed diff since
    `base` is exactly these paths", which is every fixture here — so it is
    reused rather than re-grown. The only thing added is a `git` escape hatch,
    because these cases need the base and the WORKING TREE to disagree, and
    that is what the shared helper deliberately does not express.
    """

    SURFACES: ClassVar[list[dict]] = [
        _surface("cli", "src/cli/**", _CLI),
        _surface("api", "src/api/**", _API),
        _surface("web", "src/web/**", "pytest tests/web"),
        _surface("residue", "README", None),
    ]

    def git(self, repo: Path, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            capture_output=True,
            text=True,
        ).stdout

    def write(self, repo: Path, rel: str) -> None:
        """An UNCOMMITTED file — the leg `repo_with` does not build."""
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x")

    def run_resolver(self, repo: Path, base: str) -> tuple[str, list[str]]:
        """(scope, selected commands) from the real CLI, as the preload calls it."""
        out = subprocess.run(
            [
                "python3",
                str(_PLUGIN_ROOT / "scripts" / "close_gate_commands.py"),
                "--smm-dir",
                str(self.seed(self.SURFACES)),
                "--base",
                base,
                "--cwd",
                str(repo),
                "--full-command",
                FULL,
            ],
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        scope = next(ln.split("=", 1)[1] for ln in out if ln.startswith("SCOPE="))
        commands = out[out.index("--") + 1 :] if "--" in out else []
        return scope, commands


class TestAnUnreadableBaseNeverNarrows(_ChangedSetCase):
    """Concern class: the gate narrowing on a PARTIAL view of the branch.

    `git diff "...HEAD"` — the empty base both preloads can pass — exits 0 with
    an empty diff, so the committed leg goes silently missing while the
    working-tree leg still supplies paths.
    """

    def _split_branch(self) -> tuple[Path, str]:
        """Committed work in `api`, an uncommitted review fix in `cli`."""
        repo, base = self.repo_with("src/api/routes.py")
        self.write(repo, "src/cli/main.py")
        return repo, base

    def test_a_real_base_sees_both_legs(self) -> None:
        """The refutation partner. Without it, "always full" would pass every
        other case here and narrowing would be inert. Mutation: drop the
        working-tree union -> red on the missing cli command."""
        repo, base = self._split_branch()
        scope, commands = self.run_resolver(repo, base)
        self.assertEqual(scope, "surface")
        self.assertEqual(commands, [_CLI, _API])

    def test_an_empty_base_falls_back_to_the_full_command(self) -> None:
        """THE case. An empty base is what `merge-base ... 2>/dev/null` yields
        on any failure, and `git diff "...HEAD"` answers it with an empty diff
        and exit 0 — so the committed leg goes missing without failing.

        Mutation: drop the blank-base guard (measured red) -> the gate
        auto-merges having run `pytest tests/cli` while the branch's committed
        `src/api` work was tested by nothing.
        """
        repo, _ = self._split_branch()
        scope, commands = self.run_resolver(repo, "")
        self.assertEqual(scope, "full")
        self.assertEqual(commands, [FULL])

    def test_an_unresolvable_base_falls_back_to_the_full_command(self) -> None:
        """Same shape by the other door: a base that names a ref this checkout
        does not have (a deleted plan branch, a shallow clone). Here the read
        FAILS rather than returning empty.

        Mutation: have `_git` swallow failure to `""` — its shape before this
        review — (measured red) -> the working-tree leg alone selects.
        """
        repo, _ = self._split_branch()
        scope, commands = self.run_resolver(repo, "no-such-ref-anywhere")
        self.assertEqual(scope, "full")
        self.assertEqual(commands, [FULL])


class TestTheWorkingTreeLegSpellsPathsGitsWay(_ChangedSetCase):
    """`git status --porcelain` is not a path list — it is a status format with
    quoting, rename pairs and directory folding. Each of those changes which
    surfaces the veto sees."""

    def test_a_rename_keeps_the_SOURCE_surface_selected(self) -> None:
        """A file renamed OUT of a surface still changes that surface. Keeping
        only the destination drops `api` from the selection while `src/api`
        lost a module — fail-open, before an unattended merge.

        Mutation: keep only the destination path -> red, and only
        `pytest tests/cli` runs.

        The base is re-taken AFTER the file exists, so `base...HEAD` is empty
        and the status leg is the only thing under test. Taking the earlier
        base would have let the committed range supply `src/api/routes.py` and
        the assertion would pass with the rename half dropped — measured, it
        did.
        """
        repo, _ = self.repo_with("src/api/routes.py")
        base = self.git(repo, "rev-parse", "HEAD").strip()
        (repo / "src" / "cli").mkdir(parents=True, exist_ok=True)
        self.git(repo, "mv", "src/api/routes.py", "src/cli/routes.py")
        scope, commands = self.run_resolver(repo, base)
        self.assertEqual(scope, "surface")
        self.assertEqual(commands, [_CLI, _API])

    def test_a_path_holding_a_space_still_matches_its_surface(self) -> None:
        """`--porcelain` quotes it as `"src/cli/a b.py"`, which fullmatches no
        glob — so the veto fires and narrowing never happens for any project
        with a space in a changed filename. Fail-closed, but the feature is
        inert, which is the failure this repo keeps paying for.

        Mutation: drop `-z` -> red (scope becomes `full`).
        """
        repo, base = self.repo_with("")
        self.write(repo, "src/cli/a b.py")
        scope, commands = self.run_resolver(repo, base)
        self.assertEqual(scope, "surface")
        self.assertEqual(commands, [_CLI])

    def test_a_new_untracked_directory_reports_its_FILES(self) -> None:
        """Default `--porcelain` folds a wholly-untracked directory to
        `src/web/`. Surface globs in the wild are file-shaped
        (`src/**/*.py`), so the folded entry matches nothing and vetoes.

        Mutation: drop `--untracked-files=all` -> red.
        """
        repo, base = self.repo_with("")
        self.write(repo, "src/web/app.js")
        self.assertIn(
            "src/web/app.js", close_gate_commands.changed_paths(base, repo) or []
        )


class TestTheChangedSetIsAnOptionNotAList(_ChangedSetCase):
    """The seam that makes the fall-back above structural rather than incidental:
    `changed_paths` answers None for "could not be read" and a list for "read
    it", so a caller cannot confuse the two by accident."""

    def test_a_blank_base_answers_none(self) -> None:
        repo, _ = self.repo_with("")
        self.assertIsNone(close_gate_commands.changed_paths("", repo))

    def test_a_readable_range_answers_a_list(self) -> None:
        """Refutation partner: None must not be the answer to everything."""
        repo, base = self.repo_with("src/api/routes.py")
        self.assertEqual(
            close_gate_commands.changed_paths(base, repo), ["src/api/routes.py"]
        )

    def test_resolve_refuses_to_narrow_on_none(self) -> None:
        """The pure half, asserted directly: an unknown changed set is not an
        empty one. Mutation: fall through to surface selection -> red."""
        from _gate_harness import system_context as _ctx

        scope, commands, reason = close_gate_commands.resolve(
            _ctx(self.SURFACES), None, FULL
        )
        self.assertEqual((scope, commands, reason), ("full", [FULL], None))


if __name__ == "__main__":
    unittest.main()

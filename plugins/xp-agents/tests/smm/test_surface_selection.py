#!/usr/bin/env python3
"""Tests for surface_selection.py and the `surface-commands` CLI seam.

Module and CLI live in one file deliberately. Most `system_context_cli`
tests sit in tests/engine/, but tests/smm/test_system_context_cli.py set
the precedent that a story's OWN new CLI surface keeps its tests with its
feature, and surface_selection's two dependencies (test_glob_translator,
test_triage) are both here.

The load-bearing tests are the two glob discriminators in
`TestGlobSemanticsDiscriminateFromFnmatch`. Every other test in this file
passes under a `fnmatch.translate` implementation, because fnmatch's `*`
crosses slashes and is therefore MORE permissive than glob_to_regex, not
less. A "`**` matches a nested path" assertion — the obvious shape, and
the one this story's AC first named — proves nothing at all.
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import surface_selection
import system_context_surface_cli
from _system_context_fixtures import valid_doc, write_doc
from conftest import _SMMTestCase, run_cli

_CLI = Path(__file__).parent.parent.parent / "smm" / "system_context_cli.py"


def _surface(name: str, **overrides: object) -> dict:
    base: dict = {"name": name, "signals": ["detected"], "status": "covered"}
    base.update(overrides)
    return base


class TestCommandsForPaths(unittest.TestCase):
    def test_single_surface_returns_only_its_command(self) -> None:
        surfaces = [
            _surface("cli", paths=["src/cli/**"], command="pytest tests/cli"),
            _surface("api", paths=["src/api/**"], command="pytest tests/api"),
        ]
        self.assertEqual(
            surface_selection.commands_for_paths(surfaces, {"src/cli/main.py"}),
            ["pytest tests/cli"],
        )

    def test_two_surfaces_return_both_in_declaration_order(self) -> None:
        surfaces = [
            _surface("cli", paths=["src/cli/**"], command="pytest tests/cli"),
            _surface("api", paths=["src/api/**"], command="pytest tests/api"),
        ]
        self.assertEqual(
            surface_selection.commands_for_paths(
                surfaces, {"src/api/routes.py", "src/cli/main.py"}
            ),
            ["pytest tests/cli", "pytest tests/api"],
        )

    def test_two_surfaces_sharing_a_command_de_duplicate(self) -> None:
        surfaces = [
            _surface("cli", paths=["src/cli/**"], command="pytest tests/unit"),
            _surface("api", paths=["src/api/**"], command="pytest tests/unit"),
        ]
        self.assertEqual(
            surface_selection.commands_for_paths(
                surfaces, {"src/cli/main.py", "src/api/routes.py"}
            ),
            ["pytest tests/unit"],
        )

    def test_no_match_returns_empty(self) -> None:
        surfaces = [_surface("cli", paths=["src/cli/**"], command="pytest tests/cli")]
        self.assertEqual(
            surface_selection.commands_for_paths(surfaces, {"docs/README.md"}), []
        )

    def test_surface_declaring_no_paths_never_matches(self) -> None:
        """Today's real state: this repo's surfaces predate the fields, so
        every one of them declares neither. The whole seam must degrade to
        empty rather than match everything."""
        surfaces = [_surface("cli"), _surface("automation")]
        self.assertEqual(
            surface_selection.commands_for_paths(surfaces, {"src/cli/main.py"}), []
        )

    def test_matched_surface_without_a_command_contributes_nothing(self) -> None:
        surfaces = [
            _surface("cli", paths=["src/cli/**"]),
            _surface("api", paths=["src/api/**"], command="pytest tests/api"),
        ]
        self.assertEqual(
            surface_selection.commands_for_paths(
                surfaces, {"src/cli/main.py", "src/api/routes.py"}
            ),
            ["pytest tests/api"],
        )

    def test_a_gap_surface_declaring_a_command_is_still_selected(self) -> None:
        """`status` is deliberately not consulted: nothing in the schema
        couples it to `command`, and dropping a command the author explicitly
        wrote would be a rule invented here."""
        surfaces = [
            _surface(
                "cli",
                status="gap",
                paths=["src/cli/**"],
                command="pytest tests/cli",
            )
        ]
        self.assertEqual(
            surface_selection.commands_for_paths(surfaces, {"src/cli/main.py"}),
            ["pytest tests/cli"],
        )


class TestSurfacesForPaths(unittest.TestCase):
    def test_returns_the_surface_entries_not_just_commands(self) -> None:
        """story-017 needs surface IDENTITY to judge whether the selected set
        covers all-or-nearly-all surfaces, which a command list cannot answer."""
        cli = _surface("cli", paths=["src/cli/**"], command="pytest tests/cli")
        api = _surface("api", paths=["src/api/**"], command="pytest tests/api")
        matched = surface_selection.surfaces_for_paths([cli, api], {"src/cli/main.py"})
        self.assertEqual([s["name"] for s in matched], ["cli"])


class TestUnclaimedPaths(unittest.TestCase):
    """The residue a caller must see before it dares narrow anything."""

    def test_paths_no_surface_claims_are_returned_sorted(self) -> None:
        self.assertEqual(
            surface_selection.unclaimed_paths(
                [_surface("cli", paths=["src/cli/**"])],
                {"src/cli/main.py", "src/db/schema.py", "README.md"},
            ),
            ["README.md", "src/db/schema.py"],
        )

    def test_total_coverage_leaves_no_residue(self) -> None:
        surfaces = [_surface("cli", paths=["src/**"]), _surface("d", paths=["*.md"])]
        self.assertEqual(
            surface_selection.unclaimed_paths(surfaces, {"src/cli/main.py", "a.md"}), []
        )

    def test_a_surface_declaring_no_paths_claims_nothing(self) -> None:
        self.assertEqual(
            surface_selection.unclaimed_paths([_surface("cli")], {"src/cli/main.py"}),
            ["src/cli/main.py"],
        )


class TestGlobSemanticsDiscriminateFromFnmatch(unittest.TestCase):
    """Two shapes where glob_to_regex and fnmatch.translate actually disagree.
    Swap `triage.compile_glob` for `fnmatch.translate` in the implementation
    and BOTH of these go red while every other test in this file stays green —
    that asymmetry is the proof the mandate is real.

    Measured:
      tests/**/*.py  vs tests/a.py            -> ours True,  fnmatch False
      smm/*.py       vs smm/sub/a.py          -> ours False, fnmatch True
      (and `**` vs a nested path agrees, which is why it proves nothing)

    Not the only two: `?` also crosses a slash under fnmatch and not under
    ours. That third shape is pinned on the primitive, in test_glob_translator.
    """

    def test_zero_segment_recursion_matches(self) -> None:
        surfaces = [_surface("t", paths=["tests/**/*.py"], command="pytest tests")]
        self.assertEqual(
            surface_selection.commands_for_paths(surfaces, {"tests/a.py"}),
            ["pytest tests"],
        )

    def test_star_does_not_cross_slashes(self) -> None:
        surfaces = [_surface("s", paths=["smm/*.py"], command="pytest smm")]
        self.assertEqual(
            surface_selection.commands_for_paths(surfaces, {"smm/sub/a.py"}), []
        )

    def test_a_malformed_glob_does_not_raise(self) -> None:
        """`compile_glob` absorbs the re.error an unterminated class raises;
        an inline re.compile(glob_to_regex(...)) would crash the caller."""
        surfaces = [_surface("bad", paths=["src/[]*.py"], command="pytest x")]
        self.assertEqual(
            surface_selection.commands_for_paths(surfaces, {"src/a.py"}), []
        )


class TestCommandsForChangedPaths(unittest.TestCase):
    """The ONE door now, and the one place the coverage veto lives.

    story-017 replaced the story-id door with a paths door, because free close
    has no story and story close must see DRIFTED files (Step 1b tolerates
    drift, so the declared domain is not what changed). Plan review caught that
    the paths door as first drafted would have called `commands_for_paths`,
    which has NO veto — narrowing while an unclaimed file is tested by nothing,
    the exact fail-open shape story-015's close review fixed.

    Inputs here are LITERAL (`git diff --name-only`), never re-expanded: a
    deleted file must stay in the residue, or the veto weakens fail-open.
    """

    @staticmethod
    def _context(*extra: dict) -> dict:
        return {
            "acceptance_surfaces": [
                _surface(
                    "engine",
                    paths=["plugins/xp-agents/smm/**"],
                    command="pytest tests/smm",
                ),
                *extra,
            ]
        }

    def test_a_fully_claimed_path_set_selects_its_command(self) -> None:
        self.assertEqual(
            surface_selection.commands_for_changed_paths(
                self._context(), ["plugins/xp-agents/smm/surface_selection.py"]
            ),
            ["pytest tests/smm"],
        )

    def test_a_partly_claimed_path_set_selects_nothing(self) -> None:
        """Mutation: have the paths door call commands_for_paths (no veto)
        -> red. This is the row my first plan draft was missing entirely."""
        self.assertEqual(
            surface_selection.commands_for_changed_paths(
                self._context(),
                ["plugins/xp-agents/smm/surface_selection.py", "docs/ARCH.md"],
            ),
            [],
        )

    def test_a_deleted_path_still_counts_against_coverage(self) -> None:
        """Diff paths are literal and must NOT be re-expanded over disk: a
        deleted file matches no glob on the filesystem, so expansion would
        drop it from the residue and weaken the veto fail-open."""
        self.assertEqual(
            surface_selection.commands_for_changed_paths(
                self._context(),
                ["plugins/xp-agents/smm/surface_selection.py", "docs/DELETED.md"],
            ),
            [],
        )

    def test_a_claiming_surface_without_a_command_still_earns_coverage(self) -> None:
        """The escape hatch that keeps the rule usable."""
        self.assertEqual(
            surface_selection.commands_for_changed_paths(
                self._context(_surface("docs", paths=["docs/**"])),
                ["plugins/xp-agents/smm/surface_selection.py", "docs/ARCH.md"],
            ),
            ["pytest tests/smm"],
        )

    def test_no_surfaces_declared_selects_nothing(self) -> None:
        self.assertEqual(surface_selection.commands_for_changed_paths({}, ["a.py"]), [])

    def test_an_empty_path_set_selects_nothing(self) -> None:
        """An empty diff must not read as 'everything is covered'."""
        self.assertEqual(
            surface_selection.commands_for_changed_paths(self._context(), []), []
        )


class TestShouldCollapse(unittest.TestCase):
    """Collapse = every DISTINCT declared command is selected, and there are
    at least two of them.

    The >=2 floor is arithmetic, not an invented threshold: the AC's whole
    motivation is "N runs are slower than the one full command". With N=1 a
    narrowed run is never slower than the full one, so collapsing there would
    make narrowing never fire in the commonest case — the feature inert.
    """

    def test_all_commanded_surfaces_selected_collapses(self) -> None:
        a = _surface("a", paths=["a/**"], command="pytest a")
        b = _surface("b", paths=["b/**"], command="pytest b")
        self.assertTrue(surface_selection.should_collapse([a, b], [a, b]))

    def test_a_subset_does_not_collapse(self) -> None:
        a = _surface("a", paths=["a/**"], command="pytest a")
        b = _surface("b", paths=["b/**"], command="pytest b")
        self.assertFalse(surface_selection.should_collapse([a, b], [a]))

    def test_a_single_commanded_surface_never_collapses(self) -> None:
        """Mutation: drop the >=2 floor -> red, and narrowing dies."""
        a = _surface("a", paths=["a/**"], command="pytest a")
        self.assertFalse(surface_selection.should_collapse([a], [a]))

    def test_surfaces_sharing_one_command_count_once(self) -> None:
        a = _surface("a", paths=["a/**"], command="pytest all")
        b = _surface("b", paths=["b/**"], command="pytest all")
        self.assertFalse(surface_selection.should_collapse([a, b], [a, b]))

    def test_command_less_surfaces_are_ignored(self) -> None:
        a = _surface("a", paths=["a/**"], command="pytest a")
        b = _surface("b", paths=["b/**"], command="pytest b")
        docs = _surface("docs", paths=["docs/**"])
        self.assertTrue(surface_selection.should_collapse([a, b, docs], [a, b]))


class TestSurfaceCommandsCli(_SMMTestCase):
    """The read seam, now paths-only. `--smm-dir` is a GLOBAL argument declared
    before the subparsers, so it precedes the subcommand — `run_cli` builds it
    that way. Changed paths arrive newline-separated on stdin.
    """

    #: Seeded into every case so the no-match assertions DISCRIMINATE.
    #: valid_doc()'s stack carries no test_command, and without one a CLI
    #: mutated to substitute the full suite prints nothing anyway — the
    #: assertion would pass and prove nothing. Measured on story-015: the
    #: mutation went 24-passed until this line existed.
    FULL_SUITE = "pytest -n auto THE-WHOLE-SUITE"

    def _seed(self, surfaces: list[dict]) -> None:
        doc = valid_doc()
        doc["stack"] = {"languages": ["Python"], "test_command": self.FULL_SUITE}
        doc["acceptance_surfaces"] = surfaces
        write_doc(self.smm_dir, doc)

    def _run(self, *paths: str) -> subprocess.CompletedProcess:
        return run_cli(
            _CLI,
            ["surface-commands", "--paths-from", "-"],
            self.smm_dir,
            stdin_data="\n".join(paths) + "\n",
        )

    def test_prints_one_command_per_line(self) -> None:
        self._seed(
            [
                _surface("cli", paths=["src/cli/**"], command="pytest tests/cli"),
                _surface("api", paths=["src/api/**"], command="pytest tests/api"),
            ]
        )
        result = self._run("src/cli/main.py", "src/api/routes.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(), ["pytest tests/cli", "pytest tests/api"]
        )

    def test_partial_coverage_prints_nothing_and_exits_zero(self) -> None:
        """The veto, through the door callers actually use. Mutation: have the
        CLI call commands_for_paths (no veto) -> red."""
        self._seed([_surface("cli", paths=["src/cli/**"], command="pytest tests/cli")])
        result = self._run("src/cli/main.py", "src/db/schema.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertNotIn(self.FULL_SUITE, result.stdout)

    def test_surfaces_declaring_no_paths_yield_nothing(self) -> None:
        """Every project's state today — the fields postdate their documents."""
        self._seed([_surface("cli"), _surface("automation")])
        result = self._run("src/cli/main.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertNotIn(self.FULL_SUITE, result.stdout)

    def test_the_cli_never_substitutes_the_full_command(self) -> None:
        """Empty must mean 'no narrowing available', so the CALLER owns the
        fallback. A CLI that printed the full suite here would make narrowing
        indistinguishable from no selection."""
        self._seed([_surface("cli", paths=["src/cli/**"], command="pytest x")])
        result = self._run("docs/README.md")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_missing_system_context_exits_one(self) -> None:
        result = self._run("src/cli/main.py")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")


class TestSurfaceCliExports(unittest.TestCase):
    """Sibling of test_system_context_field_cli / _nested_field_cli / _caps_cli:
    the extraction convention pins the extracted module's export surface AND
    the aggregator's re-import shim, so a `mock.patch` on either path bites the
    one object the dispatch table holds.
    """

    def test_command_is_callable(self) -> None:
        self.assertTrue(callable(system_context_surface_cli.cmd_surface_commands))

    def test_cli_module_reimports_the_same_object(self) -> None:
        import system_context_cli

        self.assertIs(
            system_context_cli._cmd_surface_commands,
            system_context_surface_cli.cmd_surface_commands,
        )

    def test_shim_name_is_declared_in_all(self) -> None:
        import system_context_cli

        self.assertIn("_cmd_surface_commands", system_context_cli.__all__)


if __name__ == "__main__":
    unittest.main()

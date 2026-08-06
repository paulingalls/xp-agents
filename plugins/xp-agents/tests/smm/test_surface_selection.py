#!/usr/bin/env python3
"""Tests for surface_selection.py, plus a guard that `surface-commands`
stays gone from the CLI dispatch table.

The CLI subcommand was deleted outright — it had no production caller;
`close_gate_commands.resolve` already answers the same question through
`surface_selection.commands_for_changed_paths`, with the exit-status
refusal the CLI never carried. surface_selection's two dependencies
(test_glob_translator, test_triage) live here too.

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

    def test_a_blank_command_is_not_a_command(self) -> None:
        """One predicate with the collapse rule, which already stripped — a
        surface must not be commanded for one and uncommanded for the other."""
        surfaces = [_surface("cli", paths=["src/cli/**"], command="  ")]
        self.assertEqual(
            surface_selection.commands_for_paths(surfaces, {"src/cli/main.py"}), []
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


class TestTheDoorCollapsesWhenItWouldSelectEverything(unittest.TestCase):
    """Collapse is expressed as "no narrowing available", not as a separate
    signal: a selection covering every declared command is not cheaper than
    the one full command it replaces, so the door returns EMPTY and the
    caller's existing fallback runs the full suite once instead of N times.
    """

    @staticmethod
    def _ctx() -> dict:
        return {
            "acceptance_surfaces": [
                _surface("a", paths=["a/**"], command="pytest a"),
                _surface("b", paths=["b/**"], command="pytest b"),
            ]
        }

    def test_selecting_every_command_returns_empty(self) -> None:
        """Mutation: drop the collapse check from the door -> red, and a broad
        branch runs N commands where 1 was cheaper."""
        self.assertEqual(
            surface_selection.commands_for_changed_paths(
                self._ctx(), ["a/x.py", "b/y.py"]
            ),
            [],
        )

    def test_selecting_a_subset_still_narrows(self) -> None:
        """Mutation: collapse unconditionally -> red, and narrowing never
        fires at all."""
        self.assertEqual(
            surface_selection.commands_for_changed_paths(self._ctx(), ["a/x.py"]),
            ["pytest a"],
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


class TestSurfaceCommandsCliRemoved(_SMMTestCase):
    """`surface-commands` had no production caller — `close_gate_commands`
    already answers the same question through `commands_for_changed_paths`,
    with the exit-status veto this CLI never carried. Deleted outright."""

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return run_cli(_CLI, list(args), self.smm_dir)

    def test_surface_commands_is_not_a_recognized_subcommand(self) -> None:
        result = self._run("surface-commands")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid choice", result.stderr)


if __name__ == "__main__":
    unittest.main()

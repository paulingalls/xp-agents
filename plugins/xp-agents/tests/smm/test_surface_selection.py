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

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import surface_selection


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


class TestGlobSemanticsDiscriminateFromFnmatch(unittest.TestCase):
    """The two measured shapes where glob_to_regex and fnmatch.translate
    actually disagree. Swap `triage.compile_glob` for `fnmatch.translate` in
    the implementation and BOTH of these go red while every other test in this
    file stays green — that asymmetry is the proof the mandate is real.

    Measured:
      tests/**/*.py  vs tests/a.py            -> ours True,  fnmatch False
      smm/*.py       vs smm/sub/a.py          -> ours False, fnmatch True
      (and `**` vs a nested path agrees, which is why it proves nothing)
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


class TestCommandsForStory(unittest.TestCase):
    def _tree(self) -> Path:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        (root / "plugins" / "xp-agents" / "smm").mkdir(parents=True)
        (root / "plugins" / "xp-agents" / "smm" / "surface_selection.py").write_text("")
        return root

    @staticmethod
    def _sprint(*entries: str) -> dict:
        return {"stories": [{"id": "story-015", "file_domain": list(entries)}]}

    @staticmethod
    def _context(**overrides: object) -> dict:
        return {
            "acceptance_surfaces": [
                _surface(
                    "engine",
                    paths=["plugins/xp-agents/smm/**"],
                    command="pytest tests/smm",
                    **overrides,
                )
            ]
        }

    def test_a_glob_file_domain_is_expanded_before_matching(self) -> None:
        """THE discriminator for `extract_file_domain_paths` over
        `entry_to_paths`. Unexpanded, the raw string
        `plugins/**/surface_selection.py` cannot fullmatch the surface regex
        `plugins/xp\\-agents/smm(?:/.*)?` — the literal `xp-agents/smm`
        segments simply are not in it. Expanded against a real tree it
        becomes `plugins/xp-agents/smm/surface_selection.py`, which does.
        """
        self.assertEqual(
            surface_selection.commands_for_story(
                self._context(),
                self._sprint("plugins/**/surface_selection.py — new: the matcher"),
                "story-015",
                cwd=str(self._tree()),
            ),
            ["pytest tests/smm"],
        )

    def test_a_literal_file_domain_entry_keeps_its_description_stripped(self) -> None:
        self.assertEqual(
            surface_selection.commands_for_story(
                self._context(),
                self._sprint(
                    "plugins/xp-agents/smm/surface_selection.py — new: the matcher"
                ),
                "story-015",
                cwd=str(self._tree()),
            ),
            ["pytest tests/smm"],
        )

    def test_a_story_outside_every_surface_selects_nothing(self) -> None:
        self.assertEqual(
            surface_selection.commands_for_story(
                self._context(),
                self._sprint("docs/ARCHITECTURE.md — prose only"),
                "story-015",
                cwd=str(self._tree()),
            ),
            [],
        )

    def test_a_context_declaring_no_surfaces_selects_nothing(self) -> None:
        self.assertEqual(
            surface_selection.commands_for_story(
                {},
                self._sprint("plugins/xp-agents/smm/surface_selection.py"),
                "story-015",
                cwd=str(self._tree()),
            ),
            [],
        )

    def test_an_unknown_story_raises_rather_than_returning_empty(self) -> None:
        """Empty would be indistinguishable from a real no-match, which reads
        as 'no narrowing available' instead of 'you named the wrong story'."""
        with self.assertRaises(ValueError) as ctx:
            surface_selection.commands_for_story(
                self._context(), self._sprint("a.py"), "story-999", cwd="."
            )
        self.assertIn("story-999", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

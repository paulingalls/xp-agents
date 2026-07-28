#!/usr/bin/env python3
"""Mutation proof for the two matchers in `test_shipped_prose_language_agnostic`.

Split from that module (which owns the tree-wide assertions) when the two
features together crowded the file-size cap. The seam: this file exercises the
matchers on SYNTHETIC text, the sibling asserts the real tree complies. Both
legs are green over the real tree once a leak is fixed, so a synthetic offender
is the only thing that can prove the matchers fire at all — and four vacuous
pins were found in a single sprint, which is what happens when nothing does.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from test_shipped_prose_language_agnostic import (
    find_offending_grants,
    find_prose_tool_names,
)


class TestProseMatcherDetects(unittest.TestCase):
    def test_a_single_tool_instruction_is_flagged(self) -> None:
        hits = find_prose_tool_names("- `ruff format` before staging\n")
        self.assertEqual(hits, [(1, "ruff")])

    def test_a_multi_word_tool_is_matched_whole(self) -> None:
        self.assertEqual(
            find_prose_tool_names("run `cargo fmt` first\n"), [(1, "cargo fmt")]
        )

    def test_a_tool_inside_a_longer_word_is_not_flagged(self) -> None:
        """`ruff` must not fire on `scruffy`, or the pin gets disabled."""
        self.assertEqual(find_prose_tool_names("a scruffy diff, blackened\n"), [])

    def test_agnostic_prose_is_not_flagged(self) -> None:
        self.assertEqual(
            find_prose_tool_names("- Run the project's formatter before staging\n"),
            [],
        )

    def test_an_undetected_checker_is_flagged(self) -> None:
        """`pylint` is in no detection table, and was invisible until it was
        added to the vocabulary."""
        self.assertEqual(
            find_prose_tool_names("- `lint` -> run `pylint --fix`\n"), [(1, "pylint")]
        )


class TestHatchBehaviour(unittest.TestCase):
    def test_the_hatch_exempts_a_named_tool(self) -> None:
        text = "listing linters <!-- lang-ok: documents the detection table -->\n"
        self.assertEqual(find_prose_tool_names(text), [])

    def test_the_hatch_on_the_line_above_exempts(self) -> None:
        text = "<!-- lang-ok: table of every detected linter -->\n| `ruff` | .py |\n"
        self.assertEqual(find_prose_tool_names(text), [])

    def test_an_empty_hatch_reason_does_not_exempt(self) -> None:
        """A bare marker is a shrug, not a justification."""
        self.assertEqual(
            find_prose_tool_names("`ruff` <!-- lang-ok: -->\n"), [(1, "ruff")]
        )


class TestGrantMatcherDetects(unittest.TestCase):
    def test_a_user_runner_grant_is_flagged(self) -> None:
        self.assertEqual(
            find_offending_grants("  - Bash(python3 -m unittest *)\n"),
            [(1, "python3 -m unittest *")],
        )

    def test_a_plugin_path_as_an_argument_does_not_launder_a_runner(self) -> None:
        """The permit-list matches the grant's TARGET, not any substring: a
        plugin path in an ARGUMENT position must not bless the runner in front
        of it."""
        self.assertEqual(
            find_offending_grants("  - Bash(python3 -m pytest */skills/*/scripts/*)\n"),
            [(1, "python3 -m pytest */skills/*/scripts/*")],
        )

    def test_a_commented_grant_is_still_read(self) -> None:
        """An inline annotation must not hide a grant from leg 2."""
        self.assertEqual(
            find_offending_grants("  - Bash(python3 -m unittest *)  # our tests\n"),
            [(1, "python3 -m unittest *")],
        )

    def test_plugin_owned_and_host_grants_are_exempt(self) -> None:
        text = (
            "  - Bash(python3 */smm/sprint_cli.py *)\n"
            "  - Bash(*/append.sh *)\n"
            "  - Bash(*/init.sh)\n"
            "  - Bash(*/skills/*/scripts/*)\n"
            "  - Bash(git push *)\n"
            "  - Bash(gh pr *)\n"
            "  - Bash(printf *)\n"
        )
        self.assertEqual(find_offending_grants(text), [])

    def test_the_plugins_own_inline_runtime_is_exempt_but_dash_m_is_not(self) -> None:
        """`python3` is not the signal — `-m` is. `-c` runs the plugin's own code;
        `-m` resolves a module from the environment, which is the user's project.
        Both were live in the tree, and conflating them would have forced a real
        grant to be deleted or a real leak to be tolerated."""
        self.assertEqual(find_offending_grants("  - Bash(python3 -c *datetime*)\n"), [])
        self.assertEqual(
            find_offending_grants("  - Bash(python3 -m pytest *)\n"),
            [(1, "python3 -m pytest *")],
        )


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Module docstrings that reach a user through `--help`, pinned as such.

`_ast_identity.code_shape` strips docstrings from both trees before comparing,
so a prose pass that empties one of these reads perfectly clean there — the
guard is blind to it by construction, and says so. This is the check that is
not blind.

THREE shipped modules pass `__doc__` to `argparse`, and they split into two
shapes. `close_gate_commands` and `review_flag_cli` pass the WHOLE docstring;
`worktree_differential` passes only its FIRST LINE, so for that one every line
below the first is ordinary prose and only the opening sentence is user-facing.

What this deliberately does NOT pin is wording. Narrowing a claim to what is
true is the fix this repo asks for, and a test asserting exact help text would
block it. The failure it catches is the one narrowing cannot cause: a docstring
emptied, deleted, or reduced to something that is no longer a summary, which
silently strips a CLI's `--help` description.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import close_gate_commands
import review_flag_cli
import worktree_differential

# (module, passes_whole_docstring). The flag is the difference that matters: a
# first-line consumer only exposes its opening sentence, so the rest of its
# docstring is not user-facing and is free to change.
_CONSUMERS = (
    (worktree_differential, False),
    (close_gate_commands, True),
    (review_flag_cli, True),
)


class TestRuntimeDocstringConsumers(unittest.TestCase):
    def test_every_consumer_still_has_a_docstring_to_pass(self):
        for module, _ in _CONSUMERS:
            with self.subTest(module=module.__name__):
                self.assertTrue(
                    (module.__doc__ or "").strip(),
                    f"{module.__name__} passes __doc__ to argparse as its "
                    "--help description; emptying it strips that description "
                    "with nothing else to catch it",
                )

    def test_the_first_line_is_a_usable_one_line_summary(self):
        """The first line is what a `--help` reader sees first, and for
        `worktree_differential` it is ALL they see."""
        for module, _ in _CONSUMERS:
            with self.subTest(module=module.__name__):
                first = (module.__doc__ or "").strip().splitlines()[0].strip()
                self.assertTrue(
                    first, f"{module.__name__}'s docstring opens with a blank line"
                )
                self.assertFalse(
                    first.endswith(":"),
                    f"{module.__name__}'s first line reads as a heading, not a "
                    "summary — argparse shows it as the command's description",
                )

    def test_the_first_line_only_consumer_is_named_as_such(self):
        """`worktree_differential` takes `(__doc__ or "").split(chr(10))[0]`.
        Pinning that it is the odd one out keeps the two shapes from being
        conflated by a reader who checks only one call site."""
        first_line_only = [m.__name__ for m, whole in _CONSUMERS if not whole]
        self.assertEqual(first_line_only, ["worktree_differential"])


if __name__ == "__main__":
    unittest.main()

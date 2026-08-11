#!/usr/bin/env python3
"""Shipped prose must not name one harness as though it were the only one.

Milestone 8 asks for prose audited for harness leaks the way it is already
audited for language leaks, and the sibling
`test_shipped_prose_language_agnostic.py` establishes that way: an AT-SITE
`<!-- lang-ok: reason -->` marker, chosen because "an allowlist in another file
drifts away from" the thing it excuses. This pin mirrors it with its own keyword,
`harness-ok`, so the two guardrails cannot silence each other.

At-site is what makes a stale excuse impossible rather than policed. A marker
lives on the line it excuses, so deleting the sentence deletes the marker with
it. A separate registry keyed on a line number would instead red-light any commit
that merely inserted a paragraph above a site — and a guardrail that fires on
unrelated edits gets blanket-updated, which is the same as deleted.

These fixture rows come first because the scanner's exclusions are the whole
design: 216 of ~230 harness mentions in shipped prose are excluded structurally,
so an exclusion even slightly too greedy produces a green pin over a leaky tree.
The positive controls exist to make that failure loud.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import _harness_leak_scan as scan


class TestProseIsFound(unittest.TestCase):
    """Positive controls. Without these, over-broad exclusions read as clean."""

    def test_a_plain_markdown_prose_mention_is_reported(self):
        found = scan.find_harness_mentions("Run this under Claude Code.\n", ".md")
        self.assertEqual(found, [(1, "claude")])

    def test_a_shell_echo_body_is_prose(self):
        """The measured leak's own shape: advice inside an echoed string."""
        text = 'echo "Run the test command (look in CLAUDE.md)"\n'
        self.assertEqual(scan.find_harness_mentions(text, ".sh"), [(1, "claude")])

    def test_a_shell_comment_body_is_prose(self):
        self.assertEqual(
            scan.find_harness_mentions("# Codex reads a different file\n", ".sh"),
            [(1, "codex")],
        )

    def test_the_other_harness_is_caught_too(self):
        """The pin is not one-sided: naming only the second harness is the same
        leak, and a rule that watched one name would pass the mirror image."""
        found = scan.find_harness_mentions("This only works on Codex.\n", ".md")
        self.assertEqual(found, [(1, "codex")])


class TestIdentifiersAreExcluded(unittest.TestCase):
    """Each exclusion class, PAIRED with a prose mention on the same line.

    The pairing is the point. Excluding the identifier must not amnesty its whole
    line, or `${CLAUDE_PLUGIN_ROOT}` becomes a licence to say anything after it.
    """

    def test_the_plugin_root_variable_is_not_a_mention(self):
        text = "Resolve via `${CLAUDE_PLUGIN_ROOT}/smm/init.sh`.\n"
        self.assertEqual(scan.find_harness_mentions(text, ".md"), [])

    def test_but_prose_beside_that_variable_is_still_caught(self):
        text = "Set ${CLAUDE_PLUGIN_ROOT}, which only Claude Code defines.\n"
        self.assertEqual(scan.find_harness_mentions(text, ".md"), [(1, "claude")])

    def test_a_dot_path_is_not_a_mention(self):
        text = "Do not browse `.claude/` or the transcripts.\n"
        self.assertEqual(scan.find_harness_mentions(text, ".md"), [])

    def test_but_prose_beside_a_path_is_still_caught(self):
        text = "Files land in ~/.claude/plugins, because Claude puts them there.\n"
        self.assertEqual(scan.find_harness_mentions(text, ".md"), [(1, "claude")])

    def test_a_fenced_command_block_is_not_prose(self):
        text = "Install it:\n\n```bash\ncodex plugin add xp-agents@xp-agents\n```\n"
        self.assertEqual(scan.find_harness_mentions(text, ".md"), [])

    def test_but_prose_after_a_fence_closes_is_still_caught(self):
        text = "```bash\ncodex plugin add x\n```\n\nCodex is the only harness.\n"
        self.assertEqual(scan.find_harness_mentions(text, ".md"), [(5, "codex")])

    def test_a_multi_line_fence_does_not_leak_its_middle(self):
        """A fence opening and closing many lines apart must stay closed
        throughout — line-by-line blanking would read its body as prose."""
        text = "```bash\ncodex a\ncodex b\ncodex c\n```\n"
        self.assertEqual(scan.find_harness_mentions(text, ".md"), [])


class TestTheHatch(unittest.TestCase):
    """A marker excuses its line; an empty one excuses nothing."""

    def test_a_markdown_hatch_with_a_reason_excuses_the_line(self):
        text = "A Claude Code setting. <!-- harness-ok: only there -->\n"
        self.assertEqual(scan.find_harness_mentions(text, ".md"), [])

    def test_a_hatch_on_the_line_above_excuses_it(self):
        text = "<!-- harness-ok: that knob exists only there -->\nA Claude setting.\n"
        self.assertEqual(scan.find_harness_mentions(text, ".md"), [])

    def test_an_empty_reason_is_not_a_hatch(self):
        """An excuse that says nothing is not an excuse — the sibling pin treats
        a blank marker as absent, and a silencer is what this would become."""
        text = "A Claude Code setting. <!-- harness-ok: -->\n"
        self.assertEqual(scan.find_harness_mentions(text, ".md"), [(1, "claude")])

    def test_a_shell_hatch_uses_the_comment_form(self):
        text = '# harness-ok: that flag is only on that CLI\necho "Claude only"\n'
        self.assertEqual(scan.find_harness_mentions(text, ".sh"), [])


class TestAHatchCannotOutliveItsProse(unittest.TestCase):
    """The property that made at-site the right choice.

    A registry keyed on a line number needs machinery to notice that the prose it
    excused was reworded away. Here the marker sits on the line, so the residue
    is visible directly — and the pin reports it rather than letting a stale
    excuse accumulate.
    """

    def test_a_hatch_with_no_mention_beside_it_is_reported(self):
        text = "<!-- harness-ok: stale reason -->\nThis text no longer names one.\n"
        self.assertEqual(scan.hatches_without_mentions(text, ".md"), [1])

    def test_a_hatch_doing_real_work_is_not_reported(self):
        text = "<!-- harness-ok: a live reason -->\nA Claude Code setting.\n"
        self.assertEqual(scan.hatches_without_mentions(text, ".md"), [])


if __name__ == "__main__":
    unittest.main()

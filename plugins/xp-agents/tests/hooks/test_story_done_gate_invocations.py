#!/usr/bin/env python3
"""Command-parsing half of the mark-done gate (split from test_story_done_gate.py
per the max-500 rule).

`mark_done_invocations` reads EVERY `(story_id, force_overridden)` a Bash command
marks `done` — across chained invocations, quoted ids, and the `update-story-if`
CAS. This suite pins that parsing; the merge-proof gate (branch absence / ancestry /
force-drop records) stays in test_story_done_gate.py. Both reuse `_GateCase`.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
from test_story_done_gate import _STORY_BRANCH, _done_cmd, _GateCase


class TestTheGateReadsEveryMarkDoneInTheCommand(_GateCase):
    """One regex `search` per command was three holes wearing one bug.

    The gate read the FIRST match, took the id EXACTLY as the shell wrote it, and
    knew only one of the two subcommands that write `done`. Each hole is silent: a
    story slips past a gate that reports nothing, which is the same failure the
    gate exists to stop, one layer up.
    """

    def test_the_SECOND_mark_done_in_one_command_is_gated_too(self):
        """`... update-story story-001 done && ... update-story story-002 done` —
        `search` stops at the first match, so story-002 was marked done with no
        merge proof at all. Chaining the two is the natural shape when a close
        wraps up several stories."""
        self._unmerged_story_branch()
        self._seed_stories(
            self._story("story-001", branch=None),  # nothing to prove — passes
            self._story("story-002", branch=_STORY_BRANCH),  # unmerged — must block
        )

        with self.assertRaises(_common.BlockedError) as caught:
            self._run(f"{_done_cmd('story-001')} && {_done_cmd('story-002')}")

        self.assertIn("story-002", str(caught.exception))

    def test_a_QUOTED_story_id_is_still_gated(self):
        """`\\S+` swallowed the shell's own quotes, so the gate looked up the story
        `'story-001'` — which does not exist — and `merged_block` read the resulting
        ValueError as "no such story", i.e. nothing to check, i.e. ALLOW. The shell
        strips the quotes before the CLI sees them, so the forged `done` lands.

        Quoting an id is not exotic: /xp-schedule quotes `"$FIRST"` two steps
        earlier in the very same pipeline.
        """
        self._unmerged_story_branch()
        self._seed_sprint()

        with self.assertRaises(_common.BlockedError):
            self._run(_done_cmd('"story-001"'))

        with self.assertRaises(_common.BlockedError):
            self._run(_done_cmd("'story-001'"))

    def test_update_story_if_new_done_is_gated(self):
        """The OTHER writer of `done`. `update-story-if <id> --expected X --new done`
        is a compare-and-swap onto the same field, and the gate's pattern did not
        know the subcommand existed — so the whole merge proof was one flag away."""
        self._unmerged_story_branch()
        self._seed_sprint()
        cmd = (
            "python3 /path/to/sprint_cli.py --smm-dir /tmp/smm "
            "update-story-if story-001 --expected closing --new done"
        )

        with self.assertRaises(_common.BlockedError) as caught:
            self._run(cmd)

        self.assertIn("story-001", str(caught.exception))

    def test_an_override_waives_only_the_invocation_that_TYPED_it(self):
        """`--force-unmerged` was matched against the WHOLE command, so one override
        waived every mark-done chained after it — including stories whose bypass no
        debt event ever paid for. The flag belongs to its own invocation."""
        self._unmerged_story_branch()
        self._seed_stories(
            self._story("story-001", branch=_STORY_BRANCH),
            self._story("story-002", branch=_STORY_BRANCH),
        )
        overridden = _done_cmd("story-001", extra=' --force-unmerged "on the record"')
        cmd = overridden + " && " + _done_cmd("story-002")

        with self.assertRaises(_common.BlockedError) as caught:
            self._run(cmd)

        self.assertIn("story-002", str(caught.exception), "the UNoverridden one")

    def test_update_story_if_to_a_non_done_status_is_not_gated(self):
        """The control — /xp-accept's real CAS is `--new closing`, and it must pass."""
        self._unmerged_story_branch()
        self._seed_sprint()
        cmd = (
            "python3 /path/to/sprint_cli.py --smm-dir /tmp/smm "
            "update-story-if story-001 --expected reviewing --new closing"
        )

        self.assertIsNone(self._run(cmd))


if __name__ == "__main__":
    unittest.main()

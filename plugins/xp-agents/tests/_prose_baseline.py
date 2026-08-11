#!/usr/bin/env python3
"""What the `scripts/` prose ratchet measures, and what it tolerates.

PER FILE, IN ABSOLUTE LINES. The ratchet this replaced compared one whole-root
RATIO against a number recorded on an earlier tree, and that shape fired twice
on work that rotted nothing:

  EXTRACTION. Splitting a file, which CLAUDE.md's 500-line rule demands, adds a
  module docstring and a header without adding the code they describe, so the
  extracted module raises the ratio purely by existing.

  CLAIM-NARROWING. A true claim is usually longer than the false short one it
  replaces, so correcting prose RAISED the number — the ratio moved against
  exactly the work milestones 1 and 3 exist to produce.

EXTRACTION is gone: an extracted file is measured on its own terms, so it
cannot move a number recorded on anything else.

CLAIM-NARROWING is NOT gone. Any line-counting measure moves against it, and
this one still does — it is only localised, to the one governed file the
correction lands in, and bounded there by the slack below. A correction longer
than that slack still reads as a regression, and the pressure to golf out
accurate rationale to get green survives with it. That gap is smaller than the
ratio's, not closed.

A per-file measure does close the defect the named-set fix left behind: a sum
let one file's honest shrink pay for another's regrowth, which no per-file
comparison can express.

WHO IS GOVERNED. The pin walks the TREE and reads this table for numbers, so a
file above the floor with no entry here is a violation, not an exemption. That
is the reverse direction (concern 469b5b0a87a5) by construction rather than as
a separate leg — under the old named set, a file the tree gained afterwards was
unmeasured for as long as the set stood, and two were.

Below the floor a file is ungoverned, but by a uniform rule rather than by
omission, and it becomes a violation the moment it crosses. So the floor sets
where explicit ceilings begin, not where enforcement does.
"""

# Prose lines per file as measured on 2026-08-10, at the open of sprint-003.
# Recorded separately from the allowance below so a reader sees the observation
# and the tolerance as two numbers, not one fudged one. GENERATED from
# `_prose_scan`, never hand-typed: a hand-edited number is indistinguishable
# from a raised one.
PROSE_MEASURED: dict[str, int] = {
    "plugins/xp-agents/scripts/_common.py": 164,
    "plugins/xp-agents/scripts/bash_post_tool.py": 123,
    "plugins/xp-agents/scripts/branch_lifecycle.py": 149,
    "plugins/xp-agents/scripts/branch_resolution.py": 207,
    "plugins/xp-agents/scripts/branching.py": 180,
    "plugins/xp-agents/scripts/close_cycle_abandonment.py": 137,
    "plugins/xp-agents/scripts/close_cycle_stop_gate.py": 160,
    "plugins/xp-agents/scripts/close_gate_commands.py": 149,
    "plugins/xp-agents/scripts/commit_command.py": 272,
    "plugins/xp-agents/scripts/commit_emit.py": 169,
    "plugins/xp-agents/scripts/commit_event.py": 167,
    "plugins/xp-agents/scripts/commit_handling.py": 157,
    "plugins/xp-agents/scripts/commits.py": 175,
    "plugins/xp-agents/scripts/concern_conflicts.py": 161,
    "plugins/xp-agents/scripts/coordination.py": 145,
    "plugins/xp-agents/scripts/dash_c_tokens.py": 129,
    "plugins/xp-agents/scripts/framework_detect.py": 122,
    "plugins/xp-agents/scripts/hook_liveness.py": 196,
    "plugins/xp-agents/scripts/identity.py": 209,
    "plugins/xp-agents/scripts/in_place_marker.py": 291,
    "plugins/xp-agents/scripts/lead_gates.py": 166,
    "plugins/xp-agents/scripts/lint_runners.py": 177,
    "plugins/xp-agents/scripts/linter_invocation.py": 201,
    "plugins/xp-agents/scripts/linter_tables.py": 290,
    "plugins/xp-agents/scripts/markers.py": 143,
    "plugins/xp-agents/scripts/migration_lock.py": 121,
    "plugins/xp-agents/scripts/result_counts.py": 126,
    "plugins/xp-agents/scripts/retro_metrics.py": 130,
    "plugins/xp-agents/scripts/scaffold_apply.py": 128,
    "plugins/xp-agents/scripts/session_start.py": 164,
    "plugins/xp-agents/scripts/shell_exit_structure.py": 257,
    "plugins/xp-agents/scripts/spawn_teammate.py": 271,
    "plugins/xp-agents/scripts/staged_lint.py": 226,
    "plugins/xp-agents/scripts/tdd_check.py": 133,
    "plugins/xp-agents/scripts/teammate_runner.py": 182,
    "plugins/xp-agents/scripts/test_attribution.py": 151,
    "plugins/xp-agents/scripts/test_parsing.py": 151,
    "plugins/xp-agents/scripts/verify_acceptance.py": 159,
    "plugins/xp-agents/scripts/verify_acceptance_record.py": 129,
    "plugins/xp-agents/scripts/verify_paths.py": 156,
    "plugins/xp-agents/scripts/worktree.py": 197,
    "plugins/xp-agents/scripts/worktree_differential.py": 211,
}

# Growth this pin deliberately tolerates, per file, in prose lines.
#
# WHY THERE IS ANY. Recorded at the measurement exactly, every one of these
# files would have zero headroom, so a single added rationale line reddens at
# `git push`, after the commits exist. A gate that cheap to trip is cheapest to
# satisfy by DELETING accurate rationale — the opposite of what this milestone
# produces, and something that already happened once when a clause saying how
# long a gate stays quiet was golfed out purely to get green. The band ratchet
# hit the identical wall; see `_pin_ceilings.py`'s own docstring.
#
# WHY 5. One rationale comment is one to three lines. Five absorbs that without
# absorbing a paragraph, and it is per FILE rather than pooled, so it cannot be
# spent all in one place the way a single tree-wide allowance could.
#
# The date is here because the allowance is spent, not renewed: re-measuring is
# a deliberate, reviewable act.
PROSE_SLACK_LINES = 5


def prose_ceilings() -> dict[str, int]:
    """Path -> the number the tree is compared against: measurement + slack.

    A function rather than a fourth constant so no caller can compare against
    the raw measurement and rediscover the zero-headroom ceiling.
    """
    return {path: n + PROSE_SLACK_LINES for path, n in PROSE_MEASURED.items()}

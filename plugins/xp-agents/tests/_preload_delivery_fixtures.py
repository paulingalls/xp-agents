#!/usr/bin/env python3
"""Recorded delivery table + term list for `test_preload_delivery_contract.py`.

The table is RECORDED, not derived. Nothing here reads a preload's current
output: a pin whose expectation comes from the thing under test regenerates
its own oracle and passes forever, which is exactly the "a preload silently
lost a state marker" case the pin exists to catch.

**How an entry was seeded.** Each preload was run once under the pinned
harness (`_bootstrap_seeded_smm` — see the suite's docstring for why that
harness and not a real checkout), its emitted markers collected, and the set
intersected with what that skill's INSTRUCTIONS dereference. Instructions
means `skills/<name>/SKILL.md`, plus the agent definition for a `context:
fork` skill (its SKILL.md is a four-line handoff; the agent is the body that
reads the markers), plus `scripts/_close_pipeline_review.md` and
`scripts/_close_pipeline_shared.md` for the close skills — that prose was
factored OUT of the four close SKILL.md bodies and is appended by their
preloads, so it is those skills' instructions living in another file.

Deliberately NOT recorded, though delivered:
- Values a scrape would pick up that no instruction reads — `PLUGIN_ROOT=`
  (`xp-assign`, `xp-schedule`; both SKILL.md bodies resolve the plugin root
  from the environment instead), `SMM_FILE=` from `xp-assign`,
  `PLAN_FILE_ERROR=` from `xp-review-plan`, `TEAMMATE_CWD=` from
  `xp-quality-review`, `CLOSE_CODE_FILE_COUNT=` from the close preloads.
- `HIGH_CONCERN_COUNT=$(git diff ...)` — a shell assignment inside a fenced
  example in the shared close reference, not a delivered value. Recording it
  would pin reference prose as if it were state.
- The shared close reference's own `### Step N` headings. That block is
  instruction prose delivered wholesale; `tests/test_close_pipeline_review_
  bounds_prose.py`, `tests/test_close_step_6b_enumerated.py` and the preload
  byte budgets already hold it. This table records state markers.

`Marker.why` is REQUIRED for `KEY_PRESENT` and the suite enforces it —
"the value is legitimately empty" is the one rule that can be used to wave
a genuinely-lost value through, so every use argues for itself.
"""

from enum import Enum
from typing import NamedTuple


class Rule(str, Enum):
    """How a recorded marker is matched against a line of delivered output.

    Substring containment is NOT one of them, and that is the point:
    `_preload_base.sh` emits `## XP Values` on success and `## XP Values: not
    found` on failure, so `assertIn` passes on precisely the degraded branch
    this pin exists to catch.
    """

    EXACT_LINE = "exact-line"  # some stripped output line EQUALS the marker
    VALUE_NONEMPTY = "value-nonempty"  # a `KEY=` line whose value is non-empty
    KEY_PRESENT = "key-present"  # a `KEY=` line; an empty value is allowed


class Marker(NamedTuple):
    text: str
    rule: Rule
    why: str = ""


def _line(text: str) -> Marker:
    return Marker(text, Rule.EXACT_LINE)


def _val(key: str) -> Marker:
    return Marker(key, Rule.VALUE_NONEMPTY)


def _key(key: str, why: str) -> Marker:
    return Marker(key, Rule.KEY_PRESENT, why)


# Every preload emits this first; every skill body dereferences it.
_SMM_DIR = _val("SMM_DIR")

# `TEST_COMMAND=` is empty whenever system_context declares no test command,
# which is the plugin's shipped-to-any-project default. Shared reason.
_NO_TEST_COMMAND = "empty when the project declares no test command"

# The four close preloads share `_preload_base.sh`'s close helpers, so they
# share a core. `### HOOK_GUIDANCE` is why the harness is pinned: it is emitted
# only when the pre-commit hook is ABSENT, which is true in a fresh temp repo
# and false in a checkout after `make setup`. `PRE_COMMIT_HOOK` is deliberately
# VALUE_NONEMPTY rather than a literal `absent` — the value comes from the
# runner's repo state, so a literal would pin the harness, not the delivery.
_CLOSE_CORE: tuple[Marker, ...] = (
    _SMM_DIR,
    _val("CURRENT_BRANCH"),
    _val("TARGET_BRANCH"),
    _val("GH_AVAILABLE"),
    _val("WORKTREE_CLEAN"),
    _val("PRE_COMMIT_HOOK"),
    _val("CLOSE_START_TS"),
    _val("CLOSE_CYCLE_ID"),
    _line("### HOOK_GUIDANCE"),
)

# free/plan/sprint-close append `_close_pipeline_review.md`, whose Step 4b is
# gated on this value. story-close does not append it and does not emit it.
_RUN_FULL_CODE_REVIEW = _val("RUN_FULL_CODE_REVIEW")

# free-close and story-close both drive the Step 6 test gate from these two.
_GATE_VARS: tuple[Marker, ...] = (
    _val("GATE_SCOPE"),
    _val("GATE_DISABLED_REASON"),
)


PRELOAD_DELIVERY_MARKERS: dict[str, tuple[Marker, ...]] = {
    "xp-accept": (
        _SMM_DIR,
        _line("### ERROR"),
    ),
    "xp-assign": (
        _SMM_DIR,
        _key("TEAMMATE_STORY_IDS", "empty when no story is batched to a teammate"),
        _key("SOLO_TARGET", "empty unless one story routes to solo delegation"),
        _key("RECOMMENDED_TIER_STORY", "empty when RECOMMENDED_TIER is none"),
        _val("RECOMMENDED_TIER"),
        _key("RECOMMENDED_EFFORT", "empty when no tier is recommended"),
        _val("TEAMMATE_DEFAULT"),
    ),
    "xp-end-session": (
        _SMM_DIR,
        _line("### CANDIDATES"),
        _line("### OPEN_QUESTIONS"),
        _line("### MAYBE_ADDRESSED"),
        _line("### UNCOMMITTED"),
    ),
    "xp-free-close": (
        *_CLOSE_CORE,
        _RUN_FULL_CODE_REVIEW,
        _key("TEST_COMMAND", _NO_TEST_COMMAND),
        *_GATE_VARS,
    ),
    "xp-kickoff": (
        _SMM_DIR,
        # The whole line, arrow and target skill included: the SKILL.md acts on
        # the heading and the arrow names what it must invoke.
        _line("### NEEDS_SYSTEM_CONTEXT → invoke /xp-system-context"),
        _line("### NEEDS_EXECUTION_PLAN → invoke /xp-plan"),
        _line("### NEEDS_SPRINT → invoke /xp-sprint-start"),
    ),
    "xp-plan": (
        _SMM_DIR,
        _line("## No execution plan found"),
        _val("NEEDS_SYSTEM_CONTEXT"),
    ),
    "xp-plan-close": (
        *_CLOSE_CORE,
        _RUN_FULL_CODE_REVIEW,
    ),
    "xp-quality-review": (
        _SMM_DIR,
        _val("MODE"),
        _key("TEST_COMMAND", _NO_TEST_COMMAND),
        _line("## Debt for Changed Files"),
        # Unconditional, and a whole SKILL.md step ("For each concern...")
        # is driven by it. `## Changed Files` is unconditional too but no
        # instruction dereferences the heading, so it stays unrecorded.
        _line("## Open Plan Concerns"),
    ),
    # Forks to xp-plan-reviewer, whose definition reads SMM_DIR. The preload's
    # other line, `PLAN_FILE_ERROR=`, is read by nothing.
    "xp-review-plan": (_SMM_DIR,),
    "xp-scaffold-worktree": (
        _SMM_DIR,
        _val("REPO_ROOT"),
        _val("CURRENT_BOOTSTRAP"),
        # Unlike the close preloads, this one emits the literal sentinel `none`
        # for an undeclared test command, so an empty value here IS a loss.
        _val("TEST_COMMAND"),
        _val("NONE_DECLARED"),
        _val("WORKTREE_CLEAN"),
    ),
    "xp-schedule": (
        _SMM_DIR,
        _val("FRONTIER_COUNT"),
        _val("PARALLELIZABLE"),
        _val("GLOB_FORCED"),
        _key("FRONTIER_IDS", "empty when the ready frontier is empty"),
        _key("OVERLAP_DETAIL", "empty when no two frontier stories share files"),
        _key("UNSCOPED_IDS", "empty when every frontier story declares a domain"),
        _val("TEAMMATE_ENABLED"),
    ),
    "xp-sprint-close": (
        *_CLOSE_CORE,
        _RUN_FULL_CODE_REVIEW,
        _val("VERIFY_STATUS"),
    ),
    # Forks to xp-sprint-reviewer; the preload delivers SMM_DIR and nothing else.
    "xp-sprint-review": (_SMM_DIR,),
    "xp-sprint-start": (
        _SMM_DIR,
        _line("## ERROR: No execution plan — run /xp-plan."),
    ),
    "xp-story-close": (
        *_CLOSE_CORE,
        _key("TEAMMATE_CWD", "empty in solo mode — no teammate worktree to enter"),
        _val("STORY_BASE_UNRESOLVED"),
        _key("TEST_COMMAND", _NO_TEST_COMMAND),
        _key("VERIFY_UNTOUCHED", "empty when no acceptance path is left untouched"),
        _val("VERIFY_DEFERRED"),
        _val("REVIEW_PATH"),
        *_GATE_VARS,
    ),
    # Forks to xp-system-analyzer, whose definition reads both.
    "xp-system-context": (
        _SMM_DIR,
        _val("MODE"),
    ),
    "xp-work-selection": (_SMM_DIR,),
}


# --- Term list for the mechanism scan -------------------------------------
#
# Lives HERE, not in the file being scanned: a term list inside the scanned
# file matches itself and the scan is red by construction.
#
# The list covers the mechanism in force TODAY as well as its replacement.
# Pinning only the replacement would let the pin quietly assert the current
# delivery path — which is the thing the milestone is about to swap out.
#
# `hook` alone is deliberately NOT a term, and tightening it into one would
# break this suite for the wrong reason: `### HOOK_GUIDANCE` and
# `PRE_COMMIT_HOOK=` are genuine DELIVERED CONTENT that contain it, and the
# harness assertion legitimately names `will_fire_hook`. The terms below are
# narrow enough to name a delivery mechanism and nothing else.
#
# `!`` (bang-backtick) is the instruction-time execution shape; it is two
# characters rather than the whole preload line so that a docstring
# explaining which skill body dereferences a marker cannot trip it.
MECHANISM_TERMS: tuple[tuple[str, str], ...] = (
    ("PreToolUse", "hook-side event name"),
    ("UserPromptSubmit", "hook-side event name"),
    ("SubagentStart", "hook-side event name"),
    ("hookSpecificOutput", "hook-side output envelope"),
    ("additionalContext", "hook-side delivery field"),
    ("hooks.json", "hook registration file"),
    ("inject", "hook-side delivery verb"),
    ("!`", "instruction-time execution shape"),
    ("CLAUDE_SKILL_DIR", "the variable the instruction-time line resolves"),
)

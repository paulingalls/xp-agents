#!/usr/bin/env python3
"""Each close-skill preload appends the shared close-pipeline reference.

After commit 2a of the spike-008 follow-up, all four close skills source
their Step 5 / 5b / 6 prose from a single file at
`scripts/_close_pipeline_shared.md`. Each preload `cat`s that file at the
end of its output so the LLM running the skill sees one consistent set of
shared instructions instead of four near-duplicate copies.

These tests assert the preload-side mechanic: when a close-skill preload
runs, its stdout contains the shared content's marker headings and key
phrases. Subsequent commits add Step 5c (commit 3) and tighten Step 6
(commit 4); those tests live alongside these and reuse the same fixture
pattern.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import markers
from _bases import _PLUGIN_ROOT
from _close_fixtures import (
    _ClosePreloadCommonTests,
    _record_quality_block,
    _record_security_block,
)
from conftest import _IntegrationTestCase, run_cli
from event_helpers import events_of_type
from event_schema import EVENT_TYPE_CONCERN

_SMM_CLI = _PLUGIN_ROOT / "smm" / "smm_cli.py"


class _SharedPreloadAssertions(_ClosePreloadCommonTests):
    """Mixin asserting the shared close-pipeline content appears in stdout.

    Subclasses extend this PLUS _IntegrationTestCase (same pattern as
    _ClosePreloadCommonTests). The assertions check for marker phrases
    that are present in `scripts/_close_pipeline_shared.md` from
    commit 2a onward — the heading and at least one phrase per
    extracted step (5, 5b, 6).
    """

    def test_emits_shared_pipeline_heading(self):
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "## Shared close-pipeline reference",
            result.stdout,
            "preload must emit the shared close-pipeline heading",
        )

    def test_emits_step5_present_findings_marker(self):
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "### Step 5: Present findings",
            result.stdout,
            "preload must emit Step 5 (Present findings) heading",
        )

    def test_emits_step5b_resolve_addressed_marker(self):
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "### Step 5b: Resolve Addressed Concerns",
            result.stdout,
            "preload must emit Step 5b (Resolve Addressed Concerns) heading",
        )
        self.assertIn(
            "LIKELY ADDRESSED",
            result.stdout,
            "Step 5b body must mention the LIKELY ADDRESSED annotation",
        )

    def test_emits_step6_confirm_merge_marker(self):
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "### Step 6: Confirm the merge",
            result.stdout,
            "preload must emit Step 6 (Confirm the merge) heading",
        )
        self.assertIn(
            "AskUserQuestion",
            result.stdout,
            "Step 6 body must mention AskUserQuestion (merge-confirm prompt)",
        )

    def test_emits_step6_count_concerns_invocation(self):
        # Step 6 abort-default uses count-concerns deterministically — single
        # source of truth for both quality blocks (xp-close-reviewer) and
        # security blocks (each close skill's Step 4.5). Replaces the prior
        # text-keyword prose-match check per the canonical-event constraint.
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "count-concerns",
            result.stdout,
            "Step 6 must invoke smm_cli.py count-concerns to compute the "
            "abort-default flag deterministically",
        )
        self.assertIn(
            "--severity high",
            result.stdout,
            "Step 6 count-concerns invocation must filter --severity high "
            "(both quality and security blocks land at severity=high)",
        )
        self.assertIn(
            "--cycle-id",
            result.stdout,
            "Step 6 count-concerns invocation must scope by --cycle-id "
            "<CLOSE_CYCLE_ID> so concurrent close-cycles in other "
            "worktrees don't leak in",
        )
        self.assertIn(
            "(Recommended)",
            result.stdout,
            "Step 6 must instruct marking the Abort option '(Recommended)' "
            "when the count is > 0",
        )

    def test_step6_does_not_keep_prose_match_check(self):
        # count-concerns is the deterministic single source of truth;
        # the prose-match check would diverge from the structured count
        # (xp-close-reviewer records every Block as severity=high already).
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(
            "prose summary above contains any Block",
            result.stdout,
            "Step 6 must NOT keep the prose-match fallback",
        )

    def test_emits_step4_security_review_skill_invocation(self):
        # M-2 step-order swap: Security Review is now Step 4 (was 4.5),
        # close-reviewer fork is now Step 4.5 (was 4). Pin the new
        # heading + the exact Skill-tool invocation shape — args MUST
        # name "cumulative diff" so /security-review scopes correctly.
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "### Step 4: Security Review",
            result.stdout,
            "preload must emit the shared Step 4 (Security Review) heading "
            "(M-2 step-order swap)",
        )
        self.assertNotIn(
            "### Step 4.5: Security Review",
            result.stdout,
            "shared file must NOT carry the old `### Step 4.5: Security Review` "
            "heading post-swap",
        )
        self.assertIn(
            'Skill(skill: "security-review"',
            result.stdout,
            "Step 4 must invoke Skill(skill: 'security-review', args: ...)",
        )
        self.assertIn(
            "cumulative diff",
            result.stdout,
            "Step 4 args must scope to the cumulative diff",
        )

    def test_emits_step4_close_cycle_active_marker_write(self):
        # The close-cycle marker MUST be written by the preload script
        # itself (not LLM prose), so the Stop hook arms regardless of
        # what the LLM does next. Pin two halves:
        #  (a) the preload source calls `write_marker CLOSE_CYCLE_ACTIVE`
        #      BEFORE its `cat _close_pipeline_shared.md` line
        #      (text inspection — write_marker runs silently, no stdout).
        #  (b) the marker file actually appears on disk after the
        #      preload runs (behavioral effect).
        # Story-close overrides this test with an inverse-pin
        # (no marker write) — see TestStoryClosePreloadEmitsShared.
        source = self._PRELOAD.read_text()
        write_call = "write_marker CLOSE_CYCLE_ACTIVE"
        cat_call = 'cat "${PLUGIN_ROOT}/scripts/_close_pipeline_shared.md"'
        write_idx = source.find(write_call)
        cat_idx = source.find(cat_call)
        self.assertGreater(
            write_idx,
            -1,
            f"preload must invoke `{write_call}` to arm the close-cycle gate",
        )
        self.assertGreater(
            cat_idx,
            -1,
            f"preload must `{cat_call}` to append the shared pipeline",
        )
        self.assertLess(
            write_idx,
            cat_idx,
            "preload must arm the marker BEFORE cat'ing the shared "
            "pipeline (prose-driven marker write was the failure mode)",
        )

        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        marker_path = markers.marker_path(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE)
        self.assertTrue(
            marker_path.is_file(),
            f"preload must actually write the marker file at {marker_path}",
        )

    def test_emits_step4_5_security_concern_metadata_kind(self):
        # Security findings file as concerns with metadata.kind=security
        # so the structural commit-link probe AND any future "filter by
        # source" query can distinguish them from quality blocks.
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            '"kind":"security"',
            result.stdout,
            "Step 4.5 append.sh templates must include metadata.kind=security",
        )
        self.assertIn(
            '"close_cycle_id":',
            result.stdout,
            "Step 4.5 append.sh templates must include metadata.close_cycle_id "
            "(scopes the Step 6 count to this close cycle only)",
        )
        self.assertIn(
            '"close_mode":',
            result.stdout,
            "Step 4.5 append.sh templates must include metadata.close_mode "
            "(free|sprint|plan substituted by each close skill)",
        )

    def test_emits_step4_5_clean_separation_note(self):
        # Constraint: don't pass security findings to close-reviewer.
        # The shared template must explicitly tell the close skill not
        # to fold security into the reviewer prompt — security and
        # quality are independent review streams.
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "clean separation",
            result.stdout,
            "Step 4.5 must explicitly call out clean-separation from "
            "xp-close-reviewer (M-8 constraint)",
        )

    def test_emits_step5c_classify_and_act_marker(self):
        # Commit 3: Step 5c — fix-or-ask classifier (spike-008 Path 2,
        # LLM-side, no Python regex). Each NEW concern/block from the
        # reviewer gets sorted into "fix it now" or "defer to user".
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "### Step 5c: Classify and act on reviewer findings",
            result.stdout,
            "preload must emit Step 5c (Classify and act) heading",
        )

    def test_emits_step5c_code_fixable_categories(self):
        # The seven Class-A/B categories the LLM should fix inline
        # (per spike-008 §3 vocabulary). Pin each so a future edit
        # that drops one fails loudly instead of silently routing the
        # dropped category to "ask user". subTest reports each missing
        # category individually rather than masking after the first.
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        for category in (
            "lint",
            "test_failure",
            "ac_coverage",
            "file_domain_drift",
            "honesty_gap",
            "file_split",
            "spec_drift",
        ):
            with self.subTest(category=category):
                self.assertIn(
                    f"`{category}`",
                    result.stdout,
                    f"Step 5c code-fixable bucket must list `{category}`",
                )

    def test_emits_step5c_ask_user_categories(self):
        # The three Class-C categories that require user judgment
        # (per spike-008 §3 vocabulary). subTest gives per-category
        # failure visibility, same as the code-fixable test above.
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        for category in ("design_decision", "ac_amendment", "plan_discipline"):
            with self.subTest(category=category):
                self.assertIn(
                    f"`{category}`",
                    result.stdout,
                    f"Step 5c ask-user bucket must list `{category}`",
                )

    def test_step5c_lint_action_pins_ruff_command(self):
        # Per concern af53fd5e37d0: category names are pinned but action
        # verbs aren't. A silent rewrite of `ruff format && ruff check
        # --fix` to something different (e.g., dropping --fix or swapping
        # to a different formatter) would never fail a test. Pin both
        # halves of the lint verb so any rewrite forces a deliberate
        # test edit.
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "ruff format",
            result.stdout,
            "Step 5c lint action must pin `ruff format` (concern af53fd5e37d0)",
        )
        self.assertIn(
            "ruff check --fix",
            result.stdout,
            "Step 5c lint action must pin `ruff check --fix` (concern af53fd5e37d0)",
        )

    def test_step5c_test_failure_action_pins_runner_output_phrase(self):
        # The test_failure verb walks the LLM through "read the test
        # runner output, edit code at file:line, re-run". Pin the
        # generic "test runner output" phrase — NOT a runner-specific
        # name like "pytest" — because the shared file ships to every
        # project. The complementary test_step5c_does_not_leak_project
        # _internal_refs guards the negative side; this guards the
        # positive side that the verb stays meaningful.
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "test runner output",
            result.stdout,
            "Step 5c test_failure verb must pin generic 'test runner output' "
            "(concern af53fd5e37d0); naming a specific runner would break "
            "plugin-genericness",
        )

    def test_emits_step5c_default_to_ask(self):
        # Safety: when the LLM can't classify, default to ASK rather
        # than silently auto-fixing something it doesn't understand.
        # Case-insensitive — markdown bolding may capitalize the leading
        # word; what matters is that the policy is stated.
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "default to ask",
            result.stdout.lower(),
            "Step 5c must instruct default-to-ASK on uncertain classification",
        )

    def test_emits_step5c_resolves_event_trailer_hook(self):
        # Each LLM fix must commit with a Resolves-Event trailer so
        # the auto-link hook closes the concern. Without this guidance
        # the LLM might leave concerns open after fixing them.
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "Resolves-Event:",
            result.stdout,
            "Step 5c must instruct adding Resolves-Event: trailer to fix commits",
        )

    def test_emits_step5c_audit_trail_append_template(self):
        # Each classification appends a status event so retrospective
        # tooling can sample classifications to measure rule precision.
        # Pin the canonical content prefix + append.sh invocation. The
        # prefix must be plugin-generic (no spike-NNN names) since the
        # plugin ships to projects that have no notion of spike-008.
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "concern-classify",
            result.stdout,
            "Step 5c audit trail must use the plugin-generic "
            "'concern-classify' status content prefix",
        )
        self.assertIn(
            "append.sh",
            result.stdout,
            "Step 5c audit trail must reference append.sh to record the event",
        )

    def test_emits_step5c_audit_metadata_action(self):
        # Per concern cd3b361020ca: the canonical signal for retro/gate
        # consumers is metadata.action, not content-prefix regex. The
        # Step 5c append.sh template must set metadata.action +
        # route + category + concern_id so the count-classifications
        # subcommand can filter on structured fields. Content prefix
        # stays for human readability (covered by the test above).
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "--metadata",
            result.stdout,
            "Step 5c append.sh template must include --metadata flag "
            "for the canonical structured signal",
        )
        for marker in (
            '"action"',
            "concern_classify",  # the STATUS_ACTION_CONCERN_CLASSIFY value
            '"route"',
            '"category"',
            '"concern_id"',
            '"close_cycle_id"',  # per concern 1cf66a58205d: cycle scoper
        ):
            with self.subTest(marker=marker):
                self.assertIn(
                    marker,
                    result.stdout,
                    f"Step 5c metadata block must include `{marker}` so the "
                    f"count-classifications subcommand can filter on it",
                )

    def test_step5c_does_not_leak_project_internal_refs(self):
        # The shared file ships to other projects; it must not mention
        # project-internal naming (spike numbers, sprint numbers, SMM
        # event hex IDs) that would be meaningless out-of-context.
        # Tests under tests/ and docs/ may freely reference spike-008
        # — those don't ship.
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(
            "spike-008",
            result.stdout.lower(),
            "Shared close-pipeline content must not name 'spike-008' — "
            "the plugin ships to other projects",
        )

    def test_emits_close_cycle_id_12_hex(self):
        # Per concern 1cf66a58205d: every close preload emits
        # CLOSE_CYCLE_ID=<12-hex>. Story+free use it as the strict
        # scoper for the auto-merge gate's count-classifications query;
        # sprint+plan write it into Step 5c metadata so downstream
        # retrospective queries can slice classifications by cycle.
        # Pin all 4 so a future preload edit can't silently drop the
        # emission for one mode.
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(
            result.stdout,
            re.compile(r"^CLOSE_CYCLE_ID=[0-9a-f]{12}$", re.MULTILINE),
            "preload must emit CLOSE_CYCLE_ID=<12-hex> for the Step 5c "
            "audit-trail close_cycle_id metadata field "
            "(concern 1cf66a58205d)",
        )


class TestStoryClosePreloadEmitsShared(_SharedPreloadAssertions, _IntegrationTestCase):
    _PRELOAD = _PLUGIN_ROOT / "skills" / "xp-story-close" / "scripts" / "preload.sh"

    def test_emits_step4_close_cycle_active_marker_write(self):
        # Inverse-pin: story-close NEVER runs Step 4 (Security Review) —
        # the enclosing sprint-close covers it. So the preload source
        # must NOT invoke `write_marker CLOSE_CYCLE_ACTIVE`, and after
        # running, no marker file must land on disk.
        source = self._PRELOAD.read_text()
        self.assertNotIn(
            "write_marker CLOSE_CYCLE_ACTIVE",
            source,
            "story-close preload must NOT arm the close-cycle marker "
            "(no security-review, no marker arming)",
        )
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        marker_path = markers.marker_path(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE)
        self.assertFalse(
            marker_path.is_file(),
            f"story-close preload must not create marker at {marker_path}",
        )


class TestSprintClosePreloadEmitsShared(_SharedPreloadAssertions, _IntegrationTestCase):
    _PRELOAD = _PLUGIN_ROOT / "skills" / "xp-sprint-close" / "scripts" / "preload.sh"


class TestPlanClosePreloadEmitsShared(_SharedPreloadAssertions, _IntegrationTestCase):
    """Commit 2b: plan-close preload now emits the shared content too.

    Step 5b previously skipped on the rationale that story+sprint close
    already auto-resolved everything resolvable. Multi-sprint plans
    break that assumption — concerns from sprint N can be LIKELY-
    ADDRESSED by commits in sprint N+1, but sprint N's close window has
    already passed when those commits land. Plan-close is the last
    chance to catch slipped-through matches.
    """

    _PRELOAD = _PLUGIN_ROOT / "skills" / "xp-plan-close" / "scripts" / "preload.sh"


class TestFreeClosePreloadEmitsShared(_SharedPreloadAssertions, _IntegrationTestCase):
    """Commit 2b: free-close preload now emits the shared content too.

    Step 5b previously skipped on the (incorrect) rationale that free
    branches don't carry sprint/plan-tracked concerns. Demonstrably
    wrong — free branches routinely fix tracked concerns when used for
    follow-up work (cleanup, docs, fixes). The triage_preload helper
    looks for files-touched overlap with open concerns and is mode-
    agnostic; nothing about free-mode justifies the skip.
    """

    _PRELOAD = _PLUGIN_ROOT / "skills" / "xp-free-close" / "scripts" / "preload.sh"


_SKIP_NOTE_TARGETS = {
    "plan": _PLUGIN_ROOT / "skills" / "xp-plan-close" / "SKILL.md",
    "free": _PLUGIN_ROOT / "skills" / "xp-free-close" / "SKILL.md",
}

_TEST_COMMAND_PRELOADS = {
    "story": _PLUGIN_ROOT / "skills" / "xp-story-close" / "scripts" / "preload.sh",
    "free": _PLUGIN_ROOT / "skills" / "xp-free-close" / "scripts" / "preload.sh",
}


class TestStoryFreePreloadEmitsTestCommand(unittest.TestCase):
    """Story-close + free-close preloads emit a `TEST_COMMAND=...` line
    sourced from `system_context.stack.test_command`. The auto-merge
    override (Step 6) reads this to decide whether the deterministic
    test gate can fire — empty TEST_COMMAND means fall through to the
    confirm prompt.

    Tests use _IntegrationTestCase fixtures (fresh tmp SMM per test)
    to control whether system_context.json exists and what it contains.
    """

    def _run_preload(self, preload_path: Path, smm_dir: Path) -> str:
        env = dict(os.environ)
        env["CLAUDE_PLUGIN_DATA"] = str(smm_dir.parent.parent)
        env["SMM_DIR"] = str(smm_dir)
        result = subprocess.run(
            ["bash", str(preload_path)],
            cwd=smm_dir,
            capture_output=True,
            text=True,
            env=env,
        )
        return result.stdout

    def _make_smm(self, sc_data: dict | None) -> Path:
        # Mirror _IntegrationTestCase's SMM-dir convention: deep nested
        # path under a tmp root so init.sh resolves it cleanly.
        tmp = Path(tempfile.mkdtemp())
        smm_dir = tmp / "data" / "proj" / "smm"
        smm_dir.mkdir(parents=True)
        (smm_dir / "events.jsonl").write_text("")
        if sc_data is not None:
            (smm_dir / "system_context.json").write_text(json.dumps(sc_data))
        return smm_dir

    def test_emits_test_command_when_set(self):
        # When system_context.stack.test_command is set, the preload
        # surfaces it verbatim so the auto-merge override can run it.
        sc = {
            "product": "x",
            "architecture_overview": "x",
            "stack": {"languages": ["Python"], "test_command": "pytest -n auto"},
            "modules": [],
            "conventions": [],
            "key_decisions": [],
            "sources": [],
            "project_specific": [],
        }
        for mode, preload in _TEST_COMMAND_PRELOADS.items():
            with self.subTest(mode=mode):
                smm = self._make_smm(sc)
                stdout = self._run_preload(preload, smm)
                self.assertIn(
                    "TEST_COMMAND=pytest -n auto",
                    stdout,
                    f"{mode}-close preload must emit TEST_COMMAND=<stack.test_command>",
                )

    def test_emits_empty_test_command_when_unset(self):
        # When stack.test_command is absent, TEST_COMMAND= is empty.
        # The auto-merge override falls through to confirm prompt on
        # empty — never guesses pytest/npm/cargo.
        sc = {
            "product": "x",
            "architecture_overview": "x",
            "stack": {"languages": ["Python"]},
            "modules": [],
            "conventions": [],
            "key_decisions": [],
            "sources": [],
            "project_specific": [],
        }
        for mode, preload in _TEST_COMMAND_PRELOADS.items():
            with self.subTest(mode=mode):
                smm = self._make_smm(sc)
                stdout = self._run_preload(preload, smm)
                self.assertIn(
                    "TEST_COMMAND=\n",
                    stdout,
                    f"{mode}-close preload must emit empty TEST_COMMAND= "
                    f"when stack.test_command is unset",
                )

    def test_emits_empty_test_command_when_no_system_context(self):
        # Graceful: missing system_context.json → empty TEST_COMMAND.
        # Plugins ship to repos that may not have run /xp-system-context
        # yet; preload must not fail, just emit empty.
        for mode, preload in _TEST_COMMAND_PRELOADS.items():
            with self.subTest(mode=mode):
                smm = self._make_smm(sc_data=None)
                stdout = self._run_preload(preload, smm)
                self.assertIn(
                    "TEST_COMMAND=\n",
                    stdout,
                    f"{mode}-close preload must emit empty TEST_COMMAND= "
                    f"when system_context.json is missing",
                )

    def test_emits_close_start_ts_iso_timestamp(self):
        # The auto-merge override's count-classifications invocation
        # bounds events by --since-ts <CLOSE_START_TS>. Pin that the
        # preload emits a CLOSE_START_TS line with an ISO 8601-shaped
        # value (YYYY-MM-DDTHH:MM:SS...) so lexicographic comparison
        # against event ts values works. Format match doesn't need to
        # be exact: assert leading 4-digit year, T separator, and a
        # +00:00 / Z trailer.
        iso_pattern = re.compile(
            r"^CLOSE_START_TS=\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.*(\+00:00|Z)$",
            re.MULTILINE,
        )
        for mode, preload in _TEST_COMMAND_PRELOADS.items():
            with self.subTest(mode=mode):
                smm = self._make_smm(sc_data=None)
                stdout = self._run_preload(preload, smm)
                self.assertRegex(
                    stdout,
                    iso_pattern,
                    f"{mode}-close preload must emit CLOSE_START_TS=<ISO 8601 "
                    f"UTC timestamp> for the auto-merge gate's --since-ts "
                    f"bound",
                )


_ALL_CLOSE_PRELOADS = {
    "story": _PLUGIN_ROOT / "skills" / "xp-story-close" / "scripts" / "preload.sh",
    "sprint": _PLUGIN_ROOT / "skills" / "xp-sprint-close" / "scripts" / "preload.sh",
    "plan": _PLUGIN_ROOT / "skills" / "xp-plan-close" / "scripts" / "preload.sh",
    "free": _PLUGIN_ROOT / "skills" / "xp-free-close" / "scripts" / "preload.sh",
}


class TestAllClosePreloadsEmitCloseStartTs(unittest.TestCase):
    """Every close-skill preload must emit CLOSE_START_TS=<ISO 8601>.

    The shared Step 6 abort-default count-concerns invocation references
    `<CLOSE_START_TS>` as a value "from the preload values at the top of
    this context" — for that promise to hold, every close preload (not
    just story/free) must emit it. Sprint/plan-close hit the same Step 6
    block in the shared pipeline AND apply Step 4.5 (Security Review),
    which writes concerns the Step 6 count then filters by since-ts.
    """

    def _run_preload(self, preload_path: Path, smm_dir: Path) -> str:
        env = dict(os.environ)
        env["CLAUDE_PLUGIN_DATA"] = str(smm_dir.parent.parent)
        env["SMM_DIR"] = str(smm_dir)
        result = subprocess.run(
            ["bash", str(preload_path)],
            cwd=smm_dir,
            capture_output=True,
            text=True,
            env=env,
        )
        return result.stdout

    def _make_smm(self) -> Path:
        tmp = Path(tempfile.mkdtemp())
        smm_dir = tmp / "data" / "proj" / "smm"
        smm_dir.mkdir(parents=True)
        (smm_dir / "events.jsonl").write_text("")
        return smm_dir

    def test_every_close_preload_emits_iso_close_start_ts(self):
        iso_pattern = re.compile(
            r"^CLOSE_START_TS=\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.*(\+00:00|Z)$",
            re.MULTILINE,
        )
        for mode, preload in _ALL_CLOSE_PRELOADS.items():
            with self.subTest(mode=mode):
                smm = self._make_smm()
                stdout = self._run_preload(preload, smm)
                self.assertRegex(
                    stdout,
                    iso_pattern,
                    f"{mode}-close preload must emit CLOSE_START_TS=<ISO 8601 "
                    f"UTC timestamp> for the shared Step 6 abort-default "
                    f"count-concerns --since-ts bound",
                )


# Commit 4: auto-merge override lives in mode-specific SKILL.md files,
# NOT in the shared file (per plan-reviewer concern fdcf62462321 —
# asymmetric mode logic should not pollute the shared file all 4
# skills consume).
_AUTO_MERGE_SKILL_MDS = {
    "story": _PLUGIN_ROOT / "skills" / "xp-story-close" / "SKILL.md",
    "free": _PLUGIN_ROOT / "skills" / "xp-free-close" / "SKILL.md",
}
_NO_AUTO_MERGE_SKILL_MDS = {
    "sprint": _PLUGIN_ROOT / "skills" / "xp-sprint-close" / "SKILL.md",
    "plan": _PLUGIN_ROOT / "skills" / "xp-plan-close" / "SKILL.md",
}
_SHARED_CLOSE_PIPELINE = _PLUGIN_ROOT / "scripts" / "_close_pipeline_shared.md"


class TestPlanFreeCloseSkillMDDropsSkipNote(unittest.TestCase):
    """Commit 2b removes the 'skip LIKELY ADDRESSED' notes from
    xp-plan-close + xp-free-close SKILL.md. The shared file's Step 5b
    now applies uniformly across all 4 close skills; leaving the skip
    notes inline would contradict the preload-injected guidance.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.skill_lower = {
            mode: path.read_text().lower() for mode, path in _SKIP_NOTE_TARGETS.items()
        }

    def test_close_skills_drop_skip_likely_addressed_note(self):
        for mode in _SKIP_NOTE_TARGETS:
            with self.subTest(mode=mode):
                self.assertNotIn(
                    "does not run the likely addressed",
                    self.skill_lower[mode],
                    f"{mode}-close SKILL.md must drop the 'skip LIKELY "
                    f"ADDRESSED' note in commit 2b — it now contradicts "
                    f"the shared Step 5b",
                )


class TestStoryFreeAutoMergeOverride(unittest.TestCase):
    """Commit 4: story-close + free-close add a Step 6 override that
    auto-merges when (no Step 5c ask-user items queued) AND (no Block)
    AND (automated tests green). Sprint-close + plan-close do NOT —
    those are terminal merges into primary with bigger blast radius
    where the user expects to confirm.

    Per plan-reviewer concern ecc57a98b410: gating on green automated
    tests (deterministic, like v2.37.4 xp-accept) — not just LLM
    judgment from Step 5c — is what makes the auto-merge safe for the
    free-close primary-merge case.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.auto_merge_text = {
            mode: path.read_text() for mode, path in _AUTO_MERGE_SKILL_MDS.items()
        }
        cls.no_auto_merge_text = {
            mode: path.read_text() for mode, path in _NO_AUTO_MERGE_SKILL_MDS.items()
        }

    def test_story_free_skills_carry_auto_merge_override(self):
        # Pin the structural marker, not the literal keyword: the override
        # section opens with `override for Step 6 (auto-merge gate)` in both
        # story+free SKILL.md. Sprint+plan close test the absence of the
        # same marker (test_sprint_plan_skills_lack_auto_merge_override),
        # so a header rename cannot silently pass both halves.
        for mode in _AUTO_MERGE_SKILL_MDS:
            with self.subTest(mode=mode):
                text = self.auto_merge_text[mode]
                self.assertIn(
                    "override for Step 6 (auto-merge gate)",
                    text,
                    f"{mode}-close SKILL.md must add an auto-merge "
                    f"override section (commit 4)",
                )

    def test_story_free_auto_merge_gates_on_tests_green(self):
        # Per concern ecc57a98b410: auto-merge must require deterministic
        # green-tests signal, not just LLM judgment from Step 5c. Pin
        # the gate so a future edit can't drop the deterministic check
        # and silently widen the blast radius.
        for mode in _AUTO_MERGE_SKILL_MDS:
            with self.subTest(mode=mode):
                lower = self.auto_merge_text[mode].lower()
                self.assertIn(
                    "tests",
                    lower,
                    f"{mode}-close auto-merge override must mention tests",
                )
                self.assertIn(
                    "green",
                    lower,
                    f"{mode}-close auto-merge override must require green tests",
                )

    def test_story_free_auto_merge_uses_test_command_var_not_hardcoded_runner(
        self,
    ):
        # Per concern e343377dab19: the plugin ships to repos that may
        # use any test runner (pytest, npm, cargo, mix, …) or none.
        # The auto-merge gate must read TEST_COMMAND from the preload
        # (sourced from system_context.stack.test_command), NOT
        # hardcode `pytest -n auto`. Pin both halves so a future edit
        # can't silently revert to a project-specific runner name.
        for mode in _AUTO_MERGE_SKILL_MDS:
            with self.subTest(mode=mode):
                text = self.auto_merge_text[mode]
                self.assertIn(
                    "TEST_COMMAND",
                    text,
                    f"{mode}-close auto-merge override must reference "
                    f"TEST_COMMAND env var (sourced from "
                    f"system_context.stack.test_command)",
                )
                self.assertNotIn(
                    "pytest",
                    text.lower(),
                    f"{mode}-close auto-merge override must not hardcode "
                    f"`pytest` — the plugin is project-generic; the test "
                    f"runner comes from TEST_COMMAND",
                )

    def test_story_free_auto_merge_surfaces_discovery_hint_when_unset(self):
        # Per plan-reviewer concern 4246adeaa521 + concern e343377dab19's
        # hint-discoverability requirement: when TEST_COMMAND is empty,
        # the override must NOT silently fall through — it must print a
        # discoverable nudge naming the WHAT to set
        # (system_context.stack.test_command) AND the actionable CLI
        # invocation (edit-stack-field). Otherwise a plugin user in
        # another repo never knows why auto-merge isn't firing.
        for mode in _AUTO_MERGE_SKILL_MDS:
            with self.subTest(mode=mode):
                text = self.auto_merge_text[mode]
                self.assertIn(
                    "stack.test_command",
                    text,
                    f"{mode}-close override must name "
                    f"`stack.test_command` so the user knows WHAT to set",
                )
                self.assertIn(
                    "edit-stack-field",
                    text,
                    f"{mode}-close override must reference the "
                    f"`edit-stack-field` CLI subcommand so the user has "
                    f"a runnable invocation to enable the gate",
                )

    def test_story_free_auto_merge_uses_count_classifications_not_grep(self):
        # Per concern cd3b361020ca: the verification recipe for
        # condition 1 must use the structured count-classifications
        # CLI (filtering on metadata.action + route + ts), NOT a
        # grep over event content. Pin both halves: the new CLI is
        # mentioned, AND the legacy grep recipe is gone.
        for mode in _AUTO_MERGE_SKILL_MDS:
            with self.subTest(mode=mode):
                text = self.auto_merge_text[mode]
                self.assertIn(
                    "count-classifications",
                    text,
                    f"{mode}-close auto-merge override must invoke the "
                    f"`count-classifications` CLI subcommand for "
                    f"structured verification",
                )
                self.assertIn(
                    "--route ask",
                    text,
                    f"{mode}-close override must filter the count to "
                    f"--route ask (the auto-merge gate cares about "
                    f"ask-routed items, not fix-routed)",
                )
                self.assertIn(
                    "CLOSE_START_TS",
                    text,
                    f"{mode}-close override must scope the count to events "
                    f"since CLOSE_START_TS (from the preload) so prior "
                    f"close cycles' classifications don't leak in",
                )
                self.assertNotIn(
                    "grep 'concern-classify",
                    text,
                    f"{mode}-close override must NOT grep event content "
                    f"prefix anymore — count-classifications is the "
                    f"canonical structured replacement",
                )

    def test_sprint_plan_skills_lack_auto_merge_override(self):
        # Sprint+plan close into primary as terminal merges. The user
        # confirms there. Auto-merge in those modes would be a
        # behavior regression.
        #
        # Test the structural marker, not the literal word: the
        # override section in story/free-close opens with the exact
        # header `override for Step 6 (auto-merge gate)`. Sprint+plan
        # close are free to mention "auto-merge" in prose explaining
        # the absence (per concern a4e03dbeefcb) — what they must not
        # carry is the override section itself.
        for mode in _NO_AUTO_MERGE_SKILL_MDS:
            with self.subTest(mode=mode):
                text = self.no_auto_merge_text[mode]
                self.assertNotIn(
                    "override for Step 6 (auto-merge gate)",
                    text,
                    f"{mode}-close SKILL.md must NOT carry an auto-merge "
                    f"override section — terminal merges keep explicit confirm",
                )

    def test_free_close_auto_merge_blocks_on_design_decision(self):
        # Per concern 28f5e1b919d6: free-close merges to primary, so
        # any design_decision finding deserves a human checkpoint —
        # even if the Step 5c classifier routed it to `fix`. Pin both
        # the CLI invocation (--category design_decision) and the
        # numeric guard so a future edit can't silently drop the check.
        free_text = self.auto_merge_text["free"]
        self.assertIn(
            "--category design_decision",
            free_text,
            "free-close auto-merge must invoke count-classifications "
            "with --category design_decision (concern 28f5e1b919d6)",
        )
        self.assertIn(
            "DESIGN_DECISION_COUNT",
            free_text,
            "free-close auto-merge must capture DESIGN_DECISION_COUNT "
            "and gate on it (concern 28f5e1b919d6)",
        )

    def test_story_free_auto_merge_uses_cycle_id(self):
        # Per concern 1cf66a58205d: since-ts is time-scoped, not
        # cycle-scoped — concurrent close-cycles in other teammate
        # worktrees could leak concern_classify events into this
        # cycle's count. The auto-merge gate must invoke
        # count-classifications with --cycle-id <CLOSE_CYCLE_ID> so
        # the close_cycle_id metadata field strict-scopes the count.
        # --since-ts stays as belt-and-suspenders defense.
        for mode in _AUTO_MERGE_SKILL_MDS:
            with self.subTest(mode=mode):
                text = self.auto_merge_text[mode]
                self.assertIn(
                    "--cycle-id <CLOSE_CYCLE_ID>",
                    text,
                    f"{mode}-close auto-merge must invoke "
                    f"count-classifications with --cycle-id "
                    f"<CLOSE_CYCLE_ID> (concern 1cf66a58205d)",
                )

    def test_story_close_auto_merge_lacks_design_decision_guard(self):
        # Story-close merges into the sprint branch (not primary), so
        # the design_decision guard isn't load-bearing there — sprint+plan
        # close pick up the human checkpoint at the next boundary. Pin
        # the absence so a future copy-paste from free-close doesn't
        # silently widen the guard's blast radius.
        story_text = self.auto_merge_text["story"]
        self.assertNotIn(
            "--category design_decision",
            story_text,
            "story-close auto-merge must NOT carry the design_decision "
            "guard — that's free-close-only (merges to primary)",
        )


class TestSharedPipelineCoherence(unittest.TestCase):
    """Per plan-reviewer concern ee1db2bd2f8a: each preceding commit's
    smoke test only checks that commit's marker text. After commits 2,
    3, AND 4 land, the shared file's section ordering should still
    flow: Step 5 → Step 5b → Step 5c → Step 6. A scrambled or
    duplicated heading would break LLM execution but no per-commit
    smoke test would catch it.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.shared_text = _SHARED_CLOSE_PIPELINE.read_text()

    def test_step_headings_appear_in_expected_order(self):
        expected = [
            "### Step 5: Present findings",
            "### Step 5b: Resolve Addressed Concerns",
            "### Step 5c: Classify and act on reviewer findings",
            "### Step 6: Confirm the merge",
        ]
        positions = [self.shared_text.find(heading) for heading in expected]
        for heading, pos in zip(expected, positions, strict=True):
            self.assertNotEqual(
                pos,
                -1,
                f"Shared close-pipeline file missing required heading: {heading}",
            )
        self.assertEqual(
            positions,
            sorted(positions),
            f"Shared close-pipeline headings out of order. "
            f"Expected {expected}; got positions {positions}",
        )

    def test_each_step_heading_appears_exactly_once(self):
        # Duplicate headings would confuse the LLM about which body
        # block to follow. Pin uniqueness alongside ordering.
        for heading in (
            "### Step 5: Present findings",
            "### Step 5b: Resolve Addressed Concerns",
            "### Step 5c: Classify and act on reviewer findings",
            "### Step 6: Confirm the merge",
        ):
            with self.subTest(heading=heading):
                self.assertEqual(
                    self.shared_text.count(heading),
                    1,
                    f"Heading must appear exactly once: {heading}",
                )


class TestShippedFilesAreProjectGeneric(unittest.TestCase):
    """Regression guard: shipped plugin files (skills, agents, the
    shared close-pipeline reference) must not name project-internal
    SMM event IDs (12-hex hashes wrapped in `(decision <id>)` or
    `(Constraints \\`<id>\\`)` / `(Wisdom \\`<id>\\`)` patterns) or
    spike-NNN names. Those are meaningful only inside the xp-agents
    repo's own SMM event log; they're noise-or-worse to a plugin user
    in another project.

    Resolves-Event trailers in commit messages are fine (they're git
    trailer syntax, not in shipped runtime instructions). Tests under
    tests/ and docs under docs/ may freely reference internal IDs —
    those don't ship.
    """

    # Walks every markdown file the plugin ships at runtime: SKILL.md
    # bodies (skills/), agent prompts (agents/), and the shared
    # close-pipeline reference. _preload_base.sh is shell, not LLM-
    # facing prose, so excluded.
    _SHIPPED_MARKDOWN_ROOTS = (
        _PLUGIN_ROOT / "skills",
        _PLUGIN_ROOT / "agents",
        _PLUGIN_ROOT / "scripts" / "_close_pipeline_shared.md",
    )

    # Match the parenthetical patterns that wrap an internal event ID.
    # We deliberately don't ban bare 12-hex strings — git short-hashes
    # and example placeholders use that shape too. The parenthetical
    # framing is what marks the project-internal reference.
    #
    # `M-N` matches project-internal milestone labels (M-1, M-2, …)
    # which only make sense inside this repo's execution_plan.json
    # phasing. Word-boundary anchored so it doesn't false-positive on
    # tokens like "M-Audit" or "M-x".
    _BANNED_PATTERNS = (
        re.compile(r"\(decision\s+[0-9a-f]{12}\b", re.IGNORECASE),
        re.compile(r"\(Constraints\s+`[0-9a-f]{12}`", re.IGNORECASE),
        re.compile(r"\(Wisdom\s+`[0-9a-f]{12}`", re.IGNORECASE),
        re.compile(r"\(Risks\s+`[0-9a-f]{12}`", re.IGNORECASE),
        re.compile(r"\bspike-\d{3}\b", re.IGNORECASE),
        re.compile(r"\bM-\d+\b"),
    )

    @classmethod
    def _shipped_md_files(cls):
        files = []
        for root in cls._SHIPPED_MARKDOWN_ROOTS:
            if root.is_file():
                files.append(root)
            elif root.is_dir():
                files.extend(root.rglob("*.md"))
        return files

    def test_no_internal_smm_id_or_spike_refs_in_shipped_md(self):
        for md_path in self._shipped_md_files():
            text = md_path.read_text()
            for pattern in self._BANNED_PATTERNS:
                with self.subTest(file=str(md_path), pattern=pattern.pattern):
                    match = pattern.search(text)
                    self.assertIsNone(
                        match,
                        f"{md_path.relative_to(_PLUGIN_ROOT)} contains "
                        f"project-internal reference matching "
                        f"{pattern.pattern!r}: {match.group(0) if match else ''!r}. "
                        f"Shipped files must be plugin-generic — no SMM "
                        f"event hex IDs or spike-NNN names. Move the "
                        f"reference to docs/ or replace with a self-"
                        f"contained explanation.",
                    )


# Realistic close-cycle ids — distinct 12-hex values so cross-cycle
# leakage is visually obvious if a query mis-scopes.
_CYCLE_A = "aaaa11112222"
_CYCLE_B = "bbbb33334444"


class TestStep6CountConcernsRealisticE2E(_IntegrationTestCase):
    """End-to-end: synthesize a real close cycle by writing concerns
    through `append.sh` (no mocks, no JSON forgery), then drive
    `smm_cli count-concerns` through the same CLI surface the shared
    Step 6 abort-default invokes. The combined contract — append.sh
    metadata shape ⇄ count-concerns filter — is what regressed at
    sprint-055 (concern 0825da9526de): the close-reviewer wrote
    quality blocks lacking `close_cycle_id`, so Step 6's count-concerns
    --cycle-id query silently dropped them.

    Realistic event shapes (xp-close-reviewer quality blocks: full
    metadata block per agents/xp-close-reviewer.md; security blocks:
    metadata.kind=security per scripts/_close_pipeline_shared.md
    Step 4.5) are written via real append.sh subprocess calls — the
    only way to catch a future drift between what the appender accepts
    and what the counter filters on.
    """

    def _count_high_concerns_for(self, cycle_id: str) -> int:
        result = run_cli(
            _SMM_CLI,
            ["count-concerns", "--severity", "high", "--cycle-id", cycle_id],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return int(result.stdout.strip())

    def test_high_concern_count_scopes_to_cycle_a_excluding_cycle_b(self) -> None:
        # Cycle A: two reviewer Blocks + one security Block — three high
        # severity concerns total under cycle id A.
        for content, path in [
            ("Block: foo helper duplicates bar helper", "scripts/foo.py"),
            ("Block: missing test for edge case", "scripts/bar.py"),
        ]:
            r = _record_quality_block(self, _CYCLE_A, content, path)
            self.assertEqual(r.returncode, 0, r.stderr)
        r = _record_security_block(
            self,
            _CYCLE_A,
            "Security Block: hardcoded credential in fixture",
            "scripts/sec.py",
        )
        self.assertEqual(r.returncode, 0, r.stderr)

        # Cycle B noise: a medium-severity quality concern (wrong severity
        # for the count) and a status event (wrong type for the count). No
        # high-severity concern under B, so the cycle-B count is zero.
        r = _record_quality_block(
            self,
            _CYCLE_B,
            "Concern: noise from a parallel close",
            "scripts/noise.py",
            severity="medium",
            source_branch="other-branch",
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self._run_append(
            "--type", "status",
            "--agent", "xp-sprint-close",
            "--content", "preload: gathered context",
            "--working-on", "[]",
            "--metadata", json.dumps({"close_cycle_id": _CYCLE_B}),
        )  # fmt: skip
        self.assertEqual(r.returncode, 0, r.stderr)

        # Sanity: the four concern writes landed as concern events with
        # the metadata we synthesized — guards against a silent append.sh
        # contract change masking a real bug.
        events = self._read_events()
        concerns = events_of_type(events, EVENT_TYPE_CONCERN)
        self.assertEqual(
            len(concerns), 4, f"expected 4 concern events; got {len(concerns)}"
        )
        a_high_concerns = [
            e
            for e in concerns
            if e.get("severity") == "high"
            and e.get("metadata", {}).get("close_cycle_id") == _CYCLE_A
        ]
        self.assertEqual(len(a_high_concerns), 3)
        kinds = sorted(c.get("metadata", {}).get("kind", "") for c in a_high_concerns)
        self.assertEqual(
            kinds,
            ["", "", "security"],
            "cycle A's three high concerns must include exactly one "
            "kind=security (Step 4.5) and two un-kinded quality blocks "
            "(xp-close-reviewer Step 4)",
        )

        # The load-bearing assertion: the deterministic Step 6
        # abort-default count must equal 3 for cycle A and 0 for cycle B,
        # via the same `smm_cli count-concerns` CLI the shared template
        # invokes — no in-process shortcuts.
        self.assertEqual(self._count_high_concerns_for(_CYCLE_A), 3)
        self.assertEqual(self._count_high_concerns_for(_CYCLE_B), 0)

    def test_concurrent_high_concerns_in_two_cycles_stay_isolated(self) -> None:
        # Both cycles file high-severity concerns. The cycle-id filter
        # must isolate them — a leak here is exactly the sprint-055
        # regression class (concern 0825da9526de).
        for content, path in [
            ("Block: cycle A first", "scripts/a1.py"),
            ("Block: cycle A second", "scripts/a2.py"),
        ]:
            r = _record_quality_block(self, _CYCLE_A, content, path)
            self.assertEqual(r.returncode, 0, r.stderr)
        for content, path in [
            ("Block: cycle B first", "scripts/b1.py"),
            ("Block: cycle B second", "scripts/b2.py"),
            ("Block: cycle B third", "scripts/b3.py"),
        ]:
            r = _record_quality_block(self, _CYCLE_B, content, path)
            self.assertEqual(r.returncode, 0, r.stderr)
        r = _record_security_block(
            self,
            _CYCLE_B,
            "Security Block: cycle B hardcoded secret",
            "scripts/b_sec.py",
        )
        self.assertEqual(r.returncode, 0, r.stderr)

        self.assertEqual(self._count_high_concerns_for(_CYCLE_A), 2)
        self.assertEqual(self._count_high_concerns_for(_CYCLE_B), 4)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Shared helpers for the close-preload "emits shared content" test family.

Split out of `test_close_preloads_emit_shared.py` (which grew past the
500-line cap) so the `_SharedPreloadAssertions` mixin and the
`_close_started_events` helper have exactly one home instead of being
duplicated across sibling test modules. Not `test_`-prefixed, so
pytest/unittest discovery does not collect it directly — it is only
ever imported by the `test_close_preloads_emit_shared*.py` siblings.
"""

import json as _json
import re
from pathlib import Path

import markers
from _close_fixtures import _ClosePreloadCommonTests
from conftest import _extract_preload_var
from event_metadata import STATUS_ACTION_CLOSE_STARTED


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

    def test_emits_step4b_full_code_review_heading(self):
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "### Step 4b: Full code review (conditional)",
            result.stdout,
            "preload must emit the shared Step 4b (full code review) heading",
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
            "MAYBE ADDRESSED",
            result.stdout,
            "Step 5b body must mention the MAYBE ADDRESSED annotation",
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

    def test_step5c_lint_action_pins_project_agnostic_verb(self):
        # Category names are pinned but action verbs aren't, so a silent rewrite
        # of the lint verb would never fail a test. That reasoning still holds —
        # only the verb being pinned changed.
        #
        # This pin used to require the literal `ruff format` and `ruff check
        # --fix`. Naming ONE language's formatter in a file all four close skills
        # emit told every project, whatever it is written in, to run a Python
        # tool — and the pin is what held it there. The verb now names the
        # project's own formatter and linter, matching the register of the
        # test_failure row below, which had this right all along.
        #
        # Both halves are still pinned (formatter AND linter, plus the fix
        # intent), so dropping one still forces a deliberate test edit.
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        for phrase in ("the project's formatter and linter", "fix mode"):
            with self.subTest(phrase=phrase):
                self.assertIn(
                    phrase,
                    result.stdout,
                    f"Step 5c lint action must pin {phrase!r} — a language-"
                    "specific tool name here ships a Python assumption to every "
                    "project (see tests/test_shipped_prose_language_agnostic.py)",
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
            "Step 5c test_failure verb must pin generic 'test runner output'; "
            "naming a specific runner would break plugin-genericness",
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

    def test_persists_the_close_cycle_id_to_its_marker(self):
        # Emitting the id into stdout tells the LLM what this cycle is called;
        # it tells the APPENDER nothing. A concern raised mid-close is written
        # by a separate process, so the id has to reach disk — otherwise the
        # merge gate is back to inferring relevance from the `files` a concern
        # happened to record. All four modes, since all four gate on the count.
        #
        # The write happens in the preload SCRIPT, not in prose: a prose-driven
        # marker write was already the observed failure mode for
        # CLOSE_CYCLE_ACTIVE (the LLM skipped or reordered it).
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        emitted = _extract_preload_var(result.stdout, "CLOSE_CYCLE_ID")
        self.assertIsNotNone(emitted, "preload must emit CLOSE_CYCLE_ID")
        stored = markers.marker_read(self.smm_dir, markers.CLOSE_CYCLE_ID)
        self.assertEqual(
            stored,
            emitted,
            "the id on disk must be the SAME id the preload emitted — the "
            "close skill stamps reviewer findings with the emitted value and "
            "the appender stamps everything else with the stored one, so two "
            "ids would split one close cycle into two the gate cannot join",
        )


def _close_started_events(smm_dir: Path) -> list[dict]:
    """Return all close_started status events in events.jsonl."""
    events_file = smm_dir / "events.jsonl"
    if not events_file.is_file():
        return []
    out: list[dict] = []
    for line in events_file.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = _json.loads(line)
        except _json.JSONDecodeError:
            continue
        md = e.get("metadata") or {}
        if md.get("action") == STATUS_ACTION_CLOSE_STARTED:
            out.append(e)
    return out

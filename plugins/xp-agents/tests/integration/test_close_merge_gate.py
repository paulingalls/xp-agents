#!/usr/bin/env python3
"""Close-pipeline auto-merge gate, TEST_COMMAND wiring, and Step 6 count-concerns.

Three cohesive classes cover the story-/free-close auto-merge
decision: TEST_COMMAND preload emission (story+free preloads surface
`system_context.stack.test_command`), the SKILL.md auto-merge override
section itself (story+free carry it, sprint+plan do not), and the
deterministic Step 6 count-concerns CLI scoped by `--cycle-id` (the
abort-default that isolates concurrent close cycles).

Per-mode shared-content preload emission tests live in
test_close_preloads_emit_shared.py.
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

from _bases import _PLUGIN_ROOT
from _close_fixtures import _record_quality_block, _record_security_block
from conftest import _IntegrationTestCase, run_cli
from event_helpers import events_of_type
from event_schema import EVENT_TYPE_CONCERN

_SMM_CLI = _PLUGIN_ROOT / "smm" / "smm_cli.py"

_TEST_COMMAND_PRELOADS = {
    "story": _PLUGIN_ROOT / "skills" / "xp-story-close" / "scripts" / "preload.sh",
    "free": _PLUGIN_ROOT / "skills" / "xp-free-close" / "scripts" / "preload.sh",
}

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

# Realistic close-cycle ids — distinct 12-hex values so cross-cycle
# leakage is visually obvious if a query mis-scopes.
_CYCLE_A = "aaaa11112222"
_CYCLE_B = "bbbb33334444"


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

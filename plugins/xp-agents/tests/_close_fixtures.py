#!/usr/bin/env python3
"""Shared test fixtures for the close-skill family preload tests.

`_ClosePreloadCommonTests` covers the assertions every close-skill
preload must satisfy: it emits SMM_DIR, CURRENT_BRANCH, GH_AVAILABLE,
WORKTREE_CLEAN, and exits 0 even with a fresh CLAUDE_PLUGIN_DATA.
Subclasses inherit the mixin plus `_IntegrationTestCase` and supply
`_PRELOAD`. The TARGET_BRANCH assertion is skill-specific (sprint-close
uses get-target, plan-close uses get-primary, free-close mirrors
plan-close), so subclasses own that test individually.

`_CloseSkillTextCommonTests` covers the SKILL.md guard assertions
shared across sprint/plan/free close skills: each SKILL.md must
invoke close_common.py's four subcommands (preflight, push,
create-pr, merge) with the right args, embed the close-reviewer
prompt sections inline, fork the reviewer before the merge, and
prompt the user via AskUserQuestion. Subclasses supply `_SKILL_MD:
Path` and `_MODE: str` ("sprint" | "plan" | "free" | "story");
mode-specific tail tests (plan-archive, sprint→plan-close chain,
plan/free same-branch refusal nuance) stay on the subclasses.
"""

import json
import os
import re
import shlex
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING

from conftest import _extract_preload_var

# Static-only base for the mixin classes below: pyright sees
# unittest.TestCase (so self.assertEqual / self.smm_dir / etc are known
# attributes), but at runtime the mixin is plain `object` so pytest
# doesn't try to collect the mixin's test methods in isolation. The
# real subclasses inherit from _IntegrationTestCase / unittest.TestCase
# alongside the mixin and supply the actual TestCase machinery.
if TYPE_CHECKING:
    _MixinBase = unittest.TestCase
else:
    _MixinBase = object


def _quality_meta(
    cycle_id: str,
    *,
    close_mode: str = "sprint",
    source_branch: str = "sprint-058",
    target_branch: str = "main",
) -> dict:
    """xp-close-reviewer quality-block metadata shape (no `kind` field).

    Single source of truth for the close_mode/source_branch/target_branch/
    close_cycle_id metadata block xp-close-reviewer.md documents. Used by
    both the count-concerns CLI tests and the realistic e2e tests so a
    contract change here surfaces in both surfaces at once.
    """
    return {
        "close_mode": close_mode,
        "source_branch": source_branch,
        "target_branch": target_branch,
        "close_cycle_id": cycle_id,
    }


def _security_meta(cycle_id: str, *, close_mode: str = "sprint") -> dict:
    """Step 4.5 security-block metadata shape (kind=security).

    Single source of truth for the kind=security/close_cycle_id/close_mode
    block scripts/_close_pipeline_shared.md Step 4.5 documents.
    """
    return {
        "kind": "security",
        "close_cycle_id": cycle_id,
        "close_mode": close_mode,
    }


def _record_quality_block(
    test,
    cycle_id: str,
    content: str,
    file_path: str,
    *,
    severity: str = "high",
    source_branch: str = "sprint-058",
) -> subprocess.CompletedProcess:
    """File a quality concern via the test's `_run_append`.

    Uses `_quality_meta` so the metadata shape stays in lockstep with the
    unit-level count-concerns tests. `severity` and `source_branch` are
    overridable for noise/cross-cycle fixtures that exercise the same
    metadata contract under different filter inputs.
    """
    return test._run_append(
        "--type", "concern",
        "--agent", "xp-close-reviewer",
        "--severity", severity,
        "--content", content,
        "--files", json.dumps([file_path]),
        "--metadata", json.dumps(_quality_meta(cycle_id, source_branch=source_branch)),
    )  # fmt: skip


def _record_security_block(
    test, cycle_id: str, content: str, file_path: str
) -> subprocess.CompletedProcess:
    """File a high-severity Step 4.5 security concern via `_run_append`.

    Uses `_security_meta` for the same single-source-of-truth reason.
    """
    return test._run_append(
        "--type", "concern",
        "--agent", "xp-sprint-close",
        "--severity", "high",
        "--content", content,
        "--files", json.dumps([file_path]),
        "--metadata", json.dumps(_security_meta(cycle_id)),
    )  # fmt: skip


def stub_gh(stub_dir: str, stdout: str, exit_code: int = 0) -> dict:
    """Write a fake `gh` script that prints `stdout` and exits `exit_code`.

    Returns env dict with PATH prefixed by stub_dir. Used by close_common
    tests (and future close-family tests) to exercise the gh-available
    path without depending on a real `gh` binary or live GitHub.
    """
    gh_path = Path(stub_dir) / "gh"
    # shlex.quote prevents callers' stdout containing $/`/quotes from
    # injecting into the sh script. Today's callers pass URL literals,
    # but the helper outlives its first user.
    gh_path.write_text(
        f"#!/bin/sh\nprintf '%s' {shlex.quote(stdout)}\nexit {exit_code}\n"
    )
    gh_path.chmod(gh_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    env = dict(os.environ)
    env["PATH"] = f"{stub_dir}:{env.get('PATH', '')}"
    return env


def stub_no_gh(stub_dir: str) -> dict:
    """Return env with PATH scoped to `stub_dir` so no real `gh` is found.

    `stub_dir` should be empty (no gh script). Used by close-family tests
    to exercise the gh-not-available skip path.
    """
    env = dict(os.environ)
    env["PATH"] = stub_dir
    return env


class _ClosePreloadCommonTests(_MixinBase):
    """Mixin asserting the shared preload contract.

    Subclasses inherit this mixin PLUS _IntegrationTestCase (which
    supplies smm_dir / tmpdir / _run_preload). At runtime _MixinBase
    is `object` so pytest doesn't auto-collect the mixin's tests in
    isolation. Statically pyright sees unittest.TestCase, so
    self.assertEqual / etc type-check cleanly.

    Subclasses must define:
        _PRELOAD: Path — absolute path to the preload.sh under test.
    """

    _PRELOAD: Path
    # Forward-declared fixture attrs from _IntegrationTestCase — pyright
    # sees them via this mixin (under TYPE_CHECKING), real values come
    # from the subclass's _IntegrationTestCase parent at setUp/setUpClass.
    # Placed inside TYPE_CHECKING so they don't shadow the parent's real
    # methods/attrs at runtime via Python's MRO lookup.
    if TYPE_CHECKING:
        smm_dir: Path
        tmpdir: Path

        def _run_preload(
            self,
            script_path: Path,
            extra_env: dict | None = None,
        ) -> subprocess.CompletedProcess: ...

    def setUp(self) -> None:
        super().setUp()
        # Assert the script exists — no silent skipTest while we're red.
        self.assertTrue(
            self._PRELOAD.is_file(), f"Preload script missing: {self._PRELOAD}"
        )

    def _preload(self) -> subprocess.CompletedProcess:
        return self._run_preload(self._PRELOAD)

    def test_emits_smm_dir(self):
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            _extract_preload_var(result.stdout, "SMM_DIR"), str(self.smm_dir)
        )

    def test_emits_current_branch(self):
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        actual_branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertEqual(
            _extract_preload_var(result.stdout, "CURRENT_BRANCH"), actual_branch
        )

    def test_emits_gh_available_boolean(self):
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        gh = _extract_preload_var(result.stdout, "GH_AVAILABLE")
        self.assertIn(gh, ("true", "false"))

    def test_emits_worktree_clean_true_on_clean(self):
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_extract_preload_var(result.stdout, "WORKTREE_CLEAN"), "true")

    def test_emits_worktree_clean_false_when_dirty(self):
        # _IntegrationTestCase tearDown removes tmpdir, so no manual cleanup.
        (self.tmpdir / "dirty.txt").write_text("uncommitted")
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_extract_preload_var(result.stdout, "WORKTREE_CLEAN"), "false")

    def test_emits_pre_commit_hook_present_or_absent(self):
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        hook = _extract_preload_var(result.stdout, "PRE_COMMIT_HOOK")
        self.assertIn(hook, ("present", "absent"))

    def test_does_not_emit_review_input(self):
        # The close skill no longer creates a tempfile or echoes a
        # REVIEW_INPUT line — the four close-review fields are now passed
        # inline in the Agent prompt as ## Source Branch / Target Branch /
        # Diff Command sections, with the mode literal already in the prompt.
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(
            _extract_preload_var(result.stdout, "REVIEW_INPUT"),
            "preload must not emit REVIEW_INPUT (file pattern removed)",
        )

    def test_exits_zero_with_unwritable_smm(self):
        # Override CLAUDE_PLUGIN_DATA to a fresh empty dir so init.sh
        # produces a different SMM path with no shared_mental_model.json.
        # Preload should still emit its five lines and exit 0.
        with tempfile.TemporaryDirectory() as fresh_data:
            result = self._run_preload(
                self._PRELOAD, extra_env={"CLAUDE_PLUGIN_DATA": fresh_data}
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        for key in (
            "SMM_DIR",
            "CURRENT_BRANCH",
            "TARGET_BRANCH",
            "GH_AVAILABLE",
            "WORKTREE_CLEAN",
            "PRE_COMMIT_HOOK",
        ):
            self.assertIsNotNone(
                _extract_preload_var(result.stdout, key),
                f"Missing key in preload output: {key}",
            )


class _CloseSkillTextCommonTests(_MixinBase):
    """Mixin asserting the shared SKILL.md guard contract.

    Same TYPE_CHECKING pattern as _ClosePreloadCommonTests above.
    Subclasses inherit this mixin PLUS unittest.TestCase.

    Subclasses must define:
        _SKILL_MD: Path — absolute path to the close skill's SKILL.md
        _MODE: str    — "sprint" | "plan" | "free" | "story"; used by
                        the Agent-prompt-mode assertion.

    The shared close pipeline (preflight, push, create-pr, merge) lives
    in scripts/close_common.py — these tests assert each SKILL.md
    invokes the four subcommands instead of asserting the pipeline's
    inline bash literals (which are now hidden inside close_common.py).
    Mode-specific tail tests (plan-archive, sprint→plan-close chain,
    current==target refusal) live on the subclasses.
    """

    _SKILL_MD: Path
    _MODE: str
    text: str  # set by setUpClass — SKILL.md text + shared close-pipeline reference
    # Subclasses set False when current==target is impossible by design
    # (e.g. sprint-close uses the get-target lookup which returns a
    # different branch when on the sprint branch).
    _ASSERT_REFUSES_SAME_BRANCH: bool = True

    # The shared close-pipeline reference (Steps 5, 5b, 6) was lifted
    # out of each SKILL.md into one file each preload `cat`s. The
    # LLM-visible context for any close skill is the union of its
    # SKILL.md and that shared reference; assertions about the close
    # pipeline must check the union, not just the SKILL.md.
    _SHARED_PIPELINE: Path = (
        Path(__file__).parent.parent / "scripts" / "_close_pipeline_shared.md"
    )

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Fail-fast on missing shared file — silently falling back to
        # SKILL.md alone would let receiver-side prose assertions
        # (Step 4.5 / Block finding / Recommended) appear to pass while
        # the actual close pipeline is missing the shared content.
        skill_text = cls._SKILL_MD.read_text()
        shared_text = cls._SHARED_PIPELINE.read_text()
        # Concatenated with a separator so headings from each don't run
        # together in regex/index lookups; assertions don't care about the
        # separator itself.
        cls.text = skill_text + "\n\n" + shared_text

    def _merge_invocation(self) -> "re.Match[str]":
        """Locate the close_common.py merge invocation. Asserts presence."""
        m = re.search(r"close_common\.py\s+merge", self.text)
        assert m is not None, "close_common.py merge invocation not found"
        return m

    def test_invokes_close_common_preflight(self):
        # SKILL.md must invoke close_common.py preflight with the three
        # required args. close_common.py owns the dirty/same-branch
        # refusal logic — SKILL.md just calls it and bails on non-zero.
        self.assertRegex(
            self.text,
            r"close_common\.py\s+preflight",
            "SKILL.md must invoke close_common.py preflight",
        )
        for arg in ("--cwd", "--current", "--target"):
            self.assertIn(arg, self.text, f"preflight invocation must pass {arg}")

    def test_invokes_close_common_push(self):
        # SKILL.md must invoke close_common.py push. The script handles
        # the no-remote skip internally, so SKILL.md no longer branches.
        self.assertRegex(
            self.text,
            r"close_common\.py\s+push",
            "SKILL.md must invoke close_common.py push",
        )
        self.assertIn("--branch", self.text)

    def test_invokes_close_common_create_pr(self):
        # SKILL.md must invoke close_common.py create-pr. The script
        # handles the no-gh skip internally; SKILL.md captures stdout
        # (PR_NUMBER or skip message) for the diff-command decision.
        self.assertRegex(
            self.text,
            r"close_common\.py\s+create-pr",
            "SKILL.md must invoke close_common.py create-pr",
        )
        for arg in ("--base", "--head", "--title", "--body"):
            self.assertIn(arg, self.text, f"create-pr invocation must pass {arg}")

    def test_invokes_close_common_merge(self):
        # SKILL.md must invoke close_common.py merge. The script does
        # the chained merge --no-ff + push target (if remote) + delete
        # source — SKILL.md no longer inlines the && chain.
        self.assertRegex(
            self.text,
            r"close_common\.py\s+merge",
            "SKILL.md must invoke close_common.py merge",
        )
        for arg in ("--source", "--target"):
            self.assertIn(arg, self.text, f"merge invocation must pass {arg}")

    def test_prompt_template_carries_close_review_fields(self):
        # The Agent prompt template still embeds the four close-review
        # sections inline — that's the close-reviewer's prompt contract,
        # which is orchestrator-side (close_common.py doesn't touch it).
        self.assertNotIn(
            "REVIEW_INPUT",
            self.text,
            "REVIEW_INPUT pattern was removed; SKILL.md must not reference it",
        )
        for section in (
            "## Mode",
            "## Source Branch",
            "## Target Branch",
            "## Diff Command",
        ):
            self.assertIn(
                section, self.text, f"Missing prompt section heading: {section}"
            )

    def test_agent_prompt_carries_smm_dir_and_mode(self):
        # The Agent prompt must literally embed SMM_DIR= and the mode
        # literal under the ## Mode section — the close-reviewer reads
        # them from the prompt now that SubagentStart no longer injects
        # anything for it.
        self.assertIn("SMM_DIR=", self.text)
        self.assertIn(f"## Mode\\n{self._MODE}", self.text)

    def test_invokes_close_reviewer_via_agent_tool(self):
        # The body must instruct forking xp-close-reviewer via the Agent
        # tool — orchestrator step, can't be in close_common.py.
        self.assertIn("xp-agents:xp-close-reviewer", self.text)
        self.assertIn("subagent_type", self.text)

    def test_reviewer_prompt_passes_close_cycle_id(self):
        # Critical: xp-close-reviewer's append.sh templates set
        # metadata.close_cycle_id from the prompt's `## Close Cycle ID`
        # section. Without that section in the Agent prompt, every
        # reviewer-filed Block has no close_cycle_id and is silently
        # invisible to the shared Step 6 count-concerns query — which
        # scopes by --cycle-id. This test pins the section so a future
        # edit can't quietly delete it and re-introduce the same
        # silent-drop bug the sprint-close reviewer caught at sprint-055.
        self.assertIn(
            "## Close Cycle ID",
            self.text,
            f"{self._MODE}-close Agent prompt must include "
            "'## Close Cycle ID\\n<CLOSE_CYCLE_ID>' so xp-close-reviewer "
            "can substitute the cycle id into its append.sh metadata; "
            "without it, severity=high quality Blocks never reach the "
            "Step 6 abort-default count-concerns query.",
        )
        self.assertIn(
            "<CLOSE_CYCLE_ID>",
            self.text,
            f"{self._MODE}-close Agent prompt must reference "
            "<CLOSE_CYCLE_ID> placeholder so the LLM substitutes the "
            "actual cycle id from the preload.",
        )

    def test_merge_invocation_appears_after_review(self):
        # The merge step must run AFTER the close-reviewer fork — never
        # before — so the user has the reviewer's findings before
        # merging. Catches a regression that reorders the pipeline.
        agent_idx = self.text.index("xp-agents:xp-close-reviewer")
        self.assertLess(
            agent_idx,
            self._merge_invocation().start(),
            "close_common.py merge must appear AFTER the reviewer fork",
        )

    def test_asks_user_before_merging(self):
        # Per design, the close skill must ask the user to confirm the
        # merge after presenting the reviewer's findings — orchestrator
        # step (AskUserQuestion is not a script-callable tool).
        self.assertIn("AskUserQuestion", self.text)

    def test_defaults_to_abort_on_block_finding(self):
        # Step 6 abort-default contract (post-Commit-B of M-8 sprint-055):
        # the close pipeline counts severity=high concerns deterministically
        # via smm_cli count-concerns scoped to this close-cycle, and flips
        # the AskUserQuestion default to "Abort (Recommended)" when count > 0.
        # Both quality blocks (xp-close-reviewer Step 4) and security blocks
        # (Step 4.5) land at severity=high, so a single count covers both.
        self.assertIn(
            "count-concerns",
            self.text,
            "close pipeline must invoke smm_cli count-concerns to compute "
            "the abort-default flag (deterministic, single source of truth "
            "for both quality and security blocks)",
        )
        self.assertIn(
            "--severity high",
            self.text,
            "count-concerns must filter --severity high (both quality and "
            "security blocks land at severity=high)",
        )
        self.assertIn(
            "--cycle-id",
            self.text,
            "count-concerns must scope by --cycle-id <CLOSE_CYCLE_ID> so "
            "concurrent close-cycles in other worktrees don't leak in",
        )
        lower = self.text.lower()
        self.assertIn(
            "recommended",
            lower,
            "close pipeline must instruct the orchestrator to mark the "
            "Abort option '(Recommended)' so AskUserQuestion's first-option "
            "default surfaces as Abort to the user",
        )

    def test_documents_no_gh_skip_breadcrumb(self):
        # Operator-facing breadcrumb: SKILL.md must mention "skipped:"
        # so the human reading the skill sees what create-pr's
        # gh-not-available output looks like. Without this line the
        # operator might think a missing PR_NUMBER is a bug.
        self.assertIn(
            "skipped:",
            self.text,
            "SKILL.md must document close_common.py skip-message prose "
            "so the operator recognizes the no-gh / no-remote path",
        )

    def test_refuses_when_current_equals_target(self):
        # Pulled from the plan/free subclasses: SKILL.md must name both
        # branch vars (so the operator sees what preflight checks) and
        # describe the stop-on-failure path. Sprint-close opts out via
        # _ASSERT_REFUSES_SAME_BRANCH = False because its get-target
        # lookup always returns a different branch from the sprint
        # branch — the same-branch case is not reachable.
        if not self._ASSERT_REFUSES_SAME_BRANCH:
            self.skipTest(
                "this skill's preload guarantees current != target; "
                "no same-branch refusal to assert"
            )
        self.assertIn("CURRENT_BRANCH", self.text)
        self.assertIn("TARGET_BRANCH", self.text)
        lower = self.text.lower()
        self.assertTrue(
            "stop" in lower or "preflight" in lower or "refuse" in lower,
            "SKILL.md must describe stopping/refusing on preflight failure",
        )


# Synthetic 12-hex cycle id used by close-skill Step 4.5 runtime tests.
# Repeated across free/sprint/plan integration tests; named so a future
# reader sees "fixture, not real" without grepping.
_FAKE_CLOSE_CYCLE_ID = "abcd1234abcd"


class _Step4_5SecurityIncludeTests(_MixinBase):
    """Mixin asserting Step 4.5 (Security Review) is wired into a close skill.

    The shared template lives in scripts/_close_pipeline_shared.md (covered
    by test_close_preloads_emit_shared.py). Each close skill that runs
    security review (free/sprint/plan, NOT story) must add a one-line
    reference instructing the LLM to apply the shared block with its own
    close-mode and close-skill-name substituted in.

    Subclasses inherit this mixin PLUS _IntegrationTestCase. Subclasses
    must define:
        _SKILL_MD: Path — absolute path to the close skill's SKILL.md
        _MODE: str    — "free" | "sprint" | "plan"
        _SKILL_NAME: str — "xp-free-close" | "xp-sprint-close" | "xp-plan-close"
    """

    _SKILL_MD: Path
    _MODE: str
    _SKILL_NAME: str
    skill_text: str  # set by setUpClass — SKILL.md text only (not concatenated)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.skill_text = cls._SKILL_MD.read_text()

    def test_references_shared_step_4_5_with_per_skill_substitutions(self):
        self.assertIn(
            "Step 4.5",
            self.skill_text,
            f"{self._SKILL_NAME} SKILL.md must reference the shared Step 4.5",
        )
        # Per-skill must specify the two substitutions that distinguish
        # this skill from its peers; both `<close-mode>` and the literal
        # mode/name must appear in the same skill text. The exact prose
        # shape (whether arrow notation or `key = value`) is flexible —
        # what's load-bearing is that both ends of each substitution are
        # named so the LLM can apply them.
        self.assertIn("<close-mode>", self.skill_text)
        self.assertIn(
            f"`{self._MODE}`",
            self.skill_text,
            f"Step 4.5 reference must name `{self._MODE}` as the close-mode value",
        )
        self.assertIn("<close-skill-name>", self.skill_text)
        self.assertIn(
            f"`{self._SKILL_NAME}`",
            self.skill_text,
            (
                f"Step 4.5 reference must name `{self._SKILL_NAME}` "
                "as the close-skill value"
            ),
        )

    def test_step_4_5_reference_appears_between_step4_and_steps5_6(self):
        # Order matters: Step 4 (Fork close-reviewer) -> Step 4.5
        # (Security Review) -> Steps 5/6 (shared findings + merge).
        step4_idx = self.skill_text.find("## Step 4: Fork the close-reviewer")
        step4_5_idx = self.skill_text.find("Step 4.5")
        # Substring chosen to avoid the EN DASH in the actual heading.
        step5_6_idx = self.skill_text.find("Apply shared close-pipeline reference")
        self.assertGreater(step4_idx, -1, "Step 4 heading must exist")
        self.assertGreater(step4_5_idx, -1, "Step 4.5 reference must exist")
        self.assertGreater(step5_6_idx, -1, "Steps 5/6 heading must exist")
        self.assertLess(
            step4_idx,
            step4_5_idx,
            "Step 4.5 reference must appear after Step 4 (Fork close-reviewer)",
        )
        self.assertLess(
            step4_5_idx,
            step5_6_idx,
            "Step 4.5 reference must appear before Steps 5/6 (shared)",
        )

    def test_close_reviewer_prompt_does_not_mention_security(self):
        # Clean separation: security and quality are independent review
        # streams that converge only at the Step 6 abort-default count.
        # The Step 4 reviewer Agent prompt template must not mention security.
        # Scope: from the literal `Agent(` open-paren to its MATCHING close-
        # paren (paren-depth walk). A naive `find(")", start)` truncates at
        # the first `)` inside the prompt body — e.g. `(no gh)` — and silently
        # skips the `## Instructions` section where a leak would most likely
        # land, defeating the whole point of this test.
        agent_open = self.skill_text.find("Agent(")
        self.assertGreater(agent_open, -1, "reviewer Agent( call must exist")
        depth = 0
        agent_close = -1
        for i in range(agent_open, len(self.skill_text)):
            ch = self.skill_text[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    agent_close = i
                    break
        self.assertGreater(agent_close, agent_open, "Agent( has no matching ')'")
        prompt_block = self.skill_text[agent_open : agent_close + 1]
        self.assertIn(
            "Instructions",
            prompt_block,
            "captured Agent block must include the Instructions section "
            "(otherwise the security-mention check is scanning a stub)",
        )
        self.assertNotIn(
            "security",
            prompt_block.lower(),
            f"{self._SKILL_NAME} Step 4 reviewer prompt must NOT mention security",
        )

    def _record_security_concern(self, severity: str, content: str, file_path: str):
        """File a security concern via append.sh with the close-skill metadata
        shape Step 4.5 documents. Pins the contract at the script boundary.

        Metadata shape comes from `_security_meta` (single source of truth
        with `_record_security_block` and the count-concerns CLI tests).
        """
        return self._run_append(  # type: ignore[attr-defined]
            "--type",
            "concern",
            "--agent",
            self._SKILL_NAME,
            "--severity",
            severity,
            "--content",
            content,
            "--files",
            json.dumps([file_path]),
            "--metadata",
            json.dumps(_security_meta(_FAKE_CLOSE_CYCLE_ID, close_mode=self._MODE)),
        )

    def test_block_recording_emits_high_severity_kind_security(self) -> None:
        result = self._record_security_concern(
            "high", "Security Block: hardcoded credential", "scripts/foo.py"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        events = self._read_events()  # type: ignore[attr-defined]
        highs = [
            e
            for e in events
            if e.get("type") == "concern" and e.get("severity") == "high"
        ]
        self.assertEqual(len(highs), 1)
        meta = highs[0]["metadata"]
        self.assertEqual(meta.get("kind"), "security")
        self.assertEqual(meta.get("close_mode"), self._MODE)
        self.assertEqual(meta.get("close_cycle_id"), _FAKE_CLOSE_CYCLE_ID)
        self.assertEqual(highs[0]["files"], ["scripts/foo.py"])

    def test_concern_recording_emits_medium_severity(self) -> None:
        result = self._record_security_concern(
            "medium", "Security Concern: weak input validation", "scripts/bar.py"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        events = self._read_events()  # type: ignore[attr-defined]
        mediums = [
            e
            for e in events
            if e.get("type") == "concern" and e.get("severity") == "medium"
        ]
        self.assertEqual(len(mediums), 1)
        self.assertEqual(mediums[0]["metadata"].get("kind"), "security")

#!/usr/bin/env python3
"""Shared test fixtures for the close-skill family: metadata helpers, gh
stubs, and the Step 4 (Security Review) inclusion mixin.

Split out of `_close_fixtures.py` to keep both files under the 500-line
cap. This module is a LEAF — it must not import from `_close_fixtures`
(that file imports back from here) to avoid a circular import.

`_quality_meta` / `_security_meta` are the single source of truth for
the close-reviewer / Step 4.5 metadata shapes documented in
xp-close-reviewer.md and scripts/_close_pipeline_shared.md; used by
both the count-concerns CLI tests and the realistic e2e tests so a
contract change here surfaces in both surfaces at once.

`_Step4SecurityIncludeTests` covers the shared Step 4 (Security Review)
wiring contract: each close skill that runs security review must
reference the shared block with per-skill substitutions, order Step 4
before the Step 4.5 reviewer fork, keep the reviewer prompt
security-free, and record security concerns with the right metadata
shape.
"""

import json
import os
import shlex
import stat
import subprocess
import unittest
from pathlib import Path

from conftest import _MixinBase
from event_schema import EVENT_TYPE_CONCERN


def _assert_text_ordering(
    test: unittest.TestCase, text: str, *markers: str, msg: str | None = None
) -> list[int]:
    """Assert each marker appears in `text` in the given order.

    Each marker must be present (text.find > -1) and each must appear
    before the next. On failure the error message names the offending
    marker (missing) or pair (out of order) so the diagnostic points
    at the actual contract that broke. Returns the per-marker indices
    so callers can reuse them for slicing without a second `text.find`.
    """
    if len(markers) < 2:
        raise ValueError("_assert_text_ordering needs at least 2 markers")
    suffix = f" ({msg})" if msg else ""
    indices: list[int] = []
    for marker in markers:
        idx = text.find(marker)
        test.assertGreater(idx, -1, f"marker {marker!r} not found in text{suffix}")
        indices.append(idx)
    for i in range(len(markers) - 1):
        test.assertLess(
            indices[i],
            indices[i + 1],
            f"marker {markers[i]!r} must appear before {markers[i + 1]!r}{suffix}",
        )
    return indices


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


# Synthetic 12-hex cycle id used by close-skill Step 4.5 runtime tests.
# Repeated across free/sprint/plan integration tests; named so a future
# reader sees "fixture, not real" without grepping.
_FAKE_CLOSE_CYCLE_ID = "abcd1234abcd"


class _Step4SecurityIncludeTests(_MixinBase):
    """Mixin asserting Step 4 (Security Review) is wired into a close skill.

    Post-M-2 (sprint-063) the Security Review runs at Step 4 (was Step 4.5
    pre-M-2). Mixin name reflects the current numbering; the in-prose
    `Step 4.5` references that remain in this file refer to the *Fork
    close-reviewer* step that now lives at 4.5.

    The shared template lives in scripts/_close_pipeline_shared.md (covered
    by test_close_preloads_emit_shared.py). Each close skill that runs
    security review (free/sprint/plan unconditionally) must add a
    reference instructing the LLM to apply the shared block with its own
    close-mode and close-skill-name substituted in. xp-story-close never
    runs security-review (defers to its enclosing sprint-close) and is
    not a subclass of this mixin.

    Subclasses inherit this mixin PLUS _IntegrationTestCase. Subclasses
    must define:
        _SKILL_MD: Path — absolute path to the close skill's SKILL.md
        _MODE: str    — "free" | "sprint" | "plan"
        _SKILL_NAME: str — "xp-free-close" | "xp-sprint-close" |
                           "xp-plan-close"
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

    def test_step_4_security_before_step_4_5_fork_before_steps_5_6(self):
        # M-2 step-order swap: Step 4 (Security Review) -> Step 4.5
        # (Fork close-reviewer) -> Steps 5/6 (shared findings + merge).
        # Substring for Steps 5/6 chosen to avoid the EN DASH in the heading.
        _assert_text_ordering(
            self,
            self.skill_text,
            "### Step 4: Security Review",
            "## Step 4.5: Fork the close-reviewer",
            "Apply shared close-pipeline reference",
            msg="M-2 step-order swap: Step 4 (Security) → Step 4.5 (Fork) → Steps 5/6",
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
            if e.get("type") == EVENT_TYPE_CONCERN and e.get("severity") == "high"
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
            if e.get("type") == EVENT_TYPE_CONCERN and e.get("severity") == "medium"
        ]
        self.assertEqual(len(mediums), 1)
        self.assertEqual(mediums[0]["metadata"].get("kind"), "security")

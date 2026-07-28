#!/usr/bin/env python3
"""story-006: the three refresh sources that keep the heartbeat alive past a
single UserPromptSubmit.

`user_prompt_log.py` (story-002) is the only writer a headless teammate gets
from its own prompt loop — it fires once. Past `STALE_AFTER_SECONDS` the
preload check (story-003) refuses every skill. This suite pins the three
call sites that refresh the marker from INSIDE later tool use, so a
long-running teammate keeps a live verdict:

- `bash_post_tool.py`   — PostToolUse:Bash, every test run / git command
- `post_tool_use.py`    — PostToolUse:Write|Edit|MultiEdit, every edit
- `pre_tool_skill.py`   — PreToolUse:Skill, before the skill's own preload

Marker mechanics are tested in test_hook_heartbeat_marker.py /
test_hook_heartbeat_liveness.py; the writer PATTERN is tested in
test_heartbeat_writers.py. This suite is about PLACEMENT: each write must
sit on a code path every invocation reaches, ahead of that hook's own early
returns — a write that records "this event mattered" would miss the cases
that matter most (a dead-site bug review already caught once for the
dropped review_cycle_done.py candidate).
"""

import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import bash_post_tool
import hook_liveness
import markers
import post_tool_use
import pre_tool_skill
from _heartbeat_fixtures import env as _env
from _heartbeat_fixtures import heartbeat_payload
from conftest import (
    _HookTestCase,
    _IntegrationTestCase,
    _make_bash_input,
    _make_skill_input,
    _make_write_input,
)


class _RefreshTestCase(_HookTestCase):
    """Shared reads/writes against this session's own heartbeat marker."""

    SESSION = "sess-refresh"
    # Deliberately near-epoch, not "now minus a delta": mirrors
    # test_heartbeat_writers.py's STALE_AT — any age computed against it is
    # far past STALE_AFTER_SECONDS without needing time.time() at seed time.
    STALE_AT = 1_000.0

    def _seed_stale(self, session_id: str | None = None) -> None:
        with patch.dict(os.environ, _env()):
            hook_liveness.write_heartbeat(
                self.smm_dir,
                session_id=session_id or self.SESSION,
                now=self.STALE_AT,
            )

    def _wrote(self, session_id: str | None = None) -> bool:
        return markers.marker_exists(
            self.smm_dir, hook_liveness.heartbeat_marker(session_id or self.SESSION)
        )

    def _payload(self, session_id: str | None = None) -> dict | None:
        return heartbeat_payload(self.smm_dir, session_id or self.SESSION)


class TestBashPostToolRefreshesHeartbeat(_RefreshTestCase):
    """AC#1, AC#4 for the PostToolUse:Bash site."""

    def test_stale_heartbeat_is_refreshed_to_current(self):
        self._seed_stale()
        before = time.time()
        with patch.dict(os.environ, _env()):
            bash_post_tool.run(
                _make_bash_input("echo hi", session_id=self.SESSION),
                smm_dir=self.smm_dir,
            )
        data = self._payload()
        assert isinstance(data, dict)
        self.assertGreaterEqual(data["written_at"], before)

    def test_xp_agent_writes_no_heartbeat(self):
        """AC#3. Paired with the positive case above — alone this would also
        pass against a do-nothing implementation."""
        with patch.dict(os.environ, _env()):
            bash_post_tool.run(
                _make_bash_input(
                    "echo hi",
                    session_id=self.SESSION,
                    agent_type="xp-code-reviewer",
                ),
                smm_dir=self.smm_dir,
            )
        self.assertFalse(self._wrote())

    def test_a_command_that_is_neither_commit_nor_test_run_still_writes(self):
        """AC#4, the dead-site guard for this file. Apart from the heartbeat's
        own guard, `is_xp_agent` is computed only inside the commit branch and
        again just below it, ahead of test-run detection — a write reusing
        either would never run for an ordinary command like this one. This is
        the case that goes red if the write moves below either branch."""
        with patch.dict(os.environ, _env()):
            bash_post_tool.run(
                _make_bash_input("ls -la", session_id=self.SESSION),
                smm_dir=self.smm_dir,
            )
        self.assertTrue(self._wrote())


class TestPostToolUseRefreshesHeartbeat(_RefreshTestCase):
    """AC#1, AC#4 for the PostToolUse:Write|Edit|MultiEdit site."""

    def test_stale_heartbeat_is_refreshed_to_current(self):
        self._seed_stale()
        before = time.time()
        with patch.dict(os.environ, _env()):
            post_tool_use.run(
                _make_write_input(session_id=self.SESSION), smm_dir=self.smm_dir
            )
        data = self._payload()
        assert isinstance(data, dict)
        self.assertGreaterEqual(data["written_at"], before)

    def test_xp_agent_writes_no_heartbeat(self):
        """AC#3. This hook already returns early on is_xp_agent, ahead of the
        write, so the write inherits the guard for free — asserted here rather
        than left implicit."""
        with patch.dict(os.environ, _env()):
            post_tool_use.run(
                _make_write_input(
                    session_id=self.SESSION, agent_type="xp-code-reviewer"
                ),
                smm_dir=self.smm_dir,
            )
        self.assertFalse(self._wrote())

    def test_a_file_path_that_yields_no_status_event_still_writes(self):
        """AC#4. `run()` returns early when `extract_file_path` finds
        nothing worth logging — that decides whether THIS event is worth
        recording, not whether the hook ran. Passing an unsupported
        tool_name reaches that early return without ever reaching the
        status-append code, so the write must sit ahead of it."""
        with patch.dict(os.environ, _env()):
            post_tool_use.run(
                _make_write_input(
                    session_id=self.SESSION,
                    tool_name="SomeOtherTool",
                    tool_input={},
                ),
                smm_dir=self.smm_dir,
            )
        self.assertTrue(self._wrote())


class TestPreToolSkillRefreshesHeartbeat(_RefreshTestCase):
    """AC#1 for the PreToolUse:Skill site, at the `refresh_heartbeat` unit."""

    def test_stale_heartbeat_is_refreshed_to_current(self):
        self._seed_stale()
        before = time.time()
        with patch.dict(os.environ, _env()):
            pre_tool_skill.refresh_heartbeat(
                _make_skill_input("xp-sprint-start", session_id=self.SESSION),
                smm_dir=self.smm_dir,
            )
        data = self._payload()
        assert isinstance(data, dict)
        self.assertGreaterEqual(data["written_at"], before)

    def test_xp_agent_writes_no_heartbeat(self):
        """AC#3."""
        with patch.dict(os.environ, _env()):
            pre_tool_skill.refresh_heartbeat(
                _make_skill_input(
                    "xp-sprint-start",
                    session_id=self.SESSION,
                    agent_type="xp-retrospective",
                ),
                smm_dir=self.smm_dir,
            )
        self.assertFalse(self._wrote())


class TestSkillPathSelfRescues(_RefreshTestCase):
    """AC#2, with the ordering trap called out: the refusal fires in the
    skill's OWN preload, which now runs after PreToolUse:Skill, so a skill
    invocation genuinely self-rescues a stale heartbeat. The precondition
    (marker verified stale first) is asserted, not assumed — without it this
    test would pass trivially against a do-nothing implementation too."""

    def test_stale_marker_then_skill_invocation_reads_back_live(self):
        self._seed_stale()
        with patch.dict(os.environ, _env(CLAUDE_CODE_SESSION_ID=self.SESSION)):
            before = hook_liveness.check_liveness(self.smm_dir)
            self.assertFalse(before.live, "precondition: marker must start stale")

            pre_tool_skill.refresh_heartbeat(
                _make_skill_input("xp-sprint-start", session_id=self.SESSION),
                smm_dir=self.smm_dir,
            )

            after = hook_liveness.check_liveness(self.smm_dir)
        self.assertTrue(after.live, after.reason)


class TestPreToolSkillWritesOnBlockPaths(_IntegrationTestCase):
    """AC#4, the dead-site guard this story exists to prevent regressing.

    `pre_tool_skill.py`'s `__main__` can `sys.exit(0)` on the teammate-block
    path WITHOUT ever calling `run()`. A write placed inside `run()` — the
    obvious spot — would silently miss every teammate invocation, which is
    exactly the population this refresh source exists to serve. Driven as a
    real subprocess because the bug lives in `__main__`'s call ORDER, which an
    in-process call to `refresh_heartbeat` alone can't exercise.
    """

    SESSION = "sess-block-path"

    def _run_pre_tool_skill(self, payload: dict) -> subprocess.CompletedProcess:
        return self._run_script_with_env(
            "pre_tool_skill.py", payload, {**self._env_with_plugin_root(), **_env()}
        )

    def test_teammate_block_path_still_writes_a_heartbeat(self):
        result = self._run_pre_tool_skill(
            {
                "session_id": self.SESSION,
                "tool_name": "Skill",
                "tool_input": {"skill": "xp-accept"},
                "cwd": str(
                    self.tmpdir / ".claude" / "worktrees" / "worktree-story-001"
                ),
            }
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("decision", result.stdout)  # sanity: the block did fire

        data = markers.marker_read(
            self.smm_dir, hook_liveness.heartbeat_marker(self.SESSION)
        )
        self.assertIsInstance(data, dict)


class TestE2ELivenessAfterToolUseFollowingStale(_RefreshTestCase):
    """AC#5. Full-pipeline proof: a stale heartbeat, followed by an ordinary
    tool use through each of the three sites, reads back live through the
    shipped CLI status verdict — not just through the marker file."""

    def test_bash_post_tool_then_status_reports_live(self):
        self._seed_stale()
        with patch.dict(os.environ, _env(CLAUDE_CODE_SESSION_ID=self.SESSION)):
            bash_post_tool.run(
                _make_bash_input("echo hi", session_id=self.SESSION),
                smm_dir=self.smm_dir,
            )
            result = hook_liveness.check_liveness(self.smm_dir)
        self.assertTrue(result.live, result.reason)
        self.assertEqual(hook_liveness.EXIT_LIVE, 0)

    def test_post_tool_use_then_status_reports_live(self):
        self._seed_stale()
        with patch.dict(os.environ, _env(CLAUDE_CODE_SESSION_ID=self.SESSION)):
            post_tool_use.run(
                _make_write_input(session_id=self.SESSION), smm_dir=self.smm_dir
            )
            result = hook_liveness.check_liveness(self.smm_dir)
        self.assertTrue(result.live, result.reason)

    def test_pre_tool_skill_then_status_reports_live(self):
        self._seed_stale()
        with patch.dict(os.environ, _env(CLAUDE_CODE_SESSION_ID=self.SESSION)):
            pre_tool_skill.refresh_heartbeat(
                _make_skill_input("xp-sprint-start", session_id=self.SESSION),
                smm_dir=self.smm_dir,
            )
            result = hook_liveness.check_liveness(self.smm_dir)
        self.assertTrue(result.live, result.reason)

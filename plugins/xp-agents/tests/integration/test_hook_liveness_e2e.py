#!/usr/bin/env python3
"""Milestone 1 capstone: the hook-liveness seams compose across a session.

Each Milestone 1 story is green on its own — the marker primitive
(story-001), the two session-boundary writers (story-002), the shell-side
preload check (story-003), the three tool-use refresh sites (story-006).
Every one of those tests seeds one marker and asks one question. The seam
none of them owns is the writer CADENCE clearing the staleness THRESHOLD
across a working session: nothing drives the real hook entry points in
sequence and checks that a live session never refuses.

What is deliberately NOT re-authored here, and where it already ships
(`tests/skills/test_preload_liveness.py`, driving real preloads):

- a stale heartbeat refuses ...... test_a_stale_heartbeat_refuses_the_same_way
- a fresh one does not ..... test_output_is_identical_with_the_check_active
- the banner replaces the preload's own output
  ................... test_the_banner_replaces_the_preload_output_entirely
- the documented escape hatch ......................... TestTheEscapeHatch
- the two refusal kinds land on different exit codes
  ........... test_the_two_refusal_kinds_arrive_on_different_exit_codes

Duplicating a shipped pin would give one contract two homes, so those are
cited rather than repeated. This file adds the two things no story owns:
the cross-turn composition proof, and the completion-hook write site.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _env_hygiene
import hook_liveness
import marker_names
import markers
from _heartbeat_fixtures import heartbeat_payload
from _preload_fixtures import PRELOAD_FIXTURES
from conftest import (
    _IntegrationTestCase,
    _make_bash_input,
    _make_write_input,
    _preload_script_path,
    discover_preload_scripts,
)

# The refusal heading is story-003's constant, imported rather than spelled
# again: a hardcoded prefix here would silently stop matching the day the
# banner is reworded, and the assertions below would pass by never matching.
from skills.test_preload_liveness import REFUSAL_HEADER

# One preload stands in for the whole set. "every preload inherits the check"
# is story-003's claim (TestEveryPreloadInheritsTheCheck) and is not restated
# here; this file's claim is about the WRITERS feeding it.
_PRELOAD_SKILL = "xp-accept"


class _LivenessE2ECase(_IntegrationTestCase):
    """Real hook entry points and a real preload, one SMM, one session.

    `_env_hygiene` pins the liveness bypass ON for every other runner. This
    suite unsets it, which is the only way the behaviour under test is
    reachable at all — see that module for why the pin exists.
    """

    SESSION = "capstone-e2e-session"

    def _env(self, **extra: str) -> dict:
        env = self._env_with_plugin_root()
        env.update(PRELOAD_FIXTURES[_PRELOAD_SKILL]())
        env[_env_hygiene.PINNED_SESSION_ID_VAR] = self.SESSION
        env.pop(_env_hygiene.SKIP_LIVENESS_ENV, None)
        env.update(extra)
        return env

    def _preload(self) -> str:
        """Drive the REAL preload, the way story-003 does.

        Not `bash _preload_liveness.sh`: that is a sourced fragment with no
        shebang and a bare `exit 0`, so standalone it emits the banner and
        nothing else — every "the normal output survived" assertion against
        it would be vacuous by construction.
        """
        result = subprocess.run(
            ["bash", str(_preload_script_path(_PRELOAD_SKILL))],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
            env=self._env(),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def _hook(self, script: str, payload: dict) -> subprocess.CompletedProcess:
        """Run a hook entry point as the platform does: own process, JSON in."""
        result = subprocess.run(
            ["python3", str(self.scripts_dir / script)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            cwd=self.tmpdir,
            env=self._env(),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def _our_marker_name(self) -> str:
        return markers.marker_path(
            self.smm_dir, hook_liveness.heartbeat_marker(self.SESSION)
        ).name

    def _assert_only_our_marker(self, when: str) -> None:
        """The SMM under test holds this session's heartbeat and no other.

        `check_liveness` has sibling logic — `_freshest_sibling`,
        `_live_on_freshness_alone`, `_no_heartbeat_of_our_own` — so ANOTHER
        session's fresh heartbeat can produce a live verdict while our own
        marker is stale. Without this guard a future concurrent-story seed
        would turn the whole suite green for the wrong reason. This repo has
        shipped vacuous pins twice; assert the premise instead of assuming it.
        """
        glob = f"{marker_names.HOOK_HEARTBEAT}*"
        found = sorted(p.name for p in self.smm_dir.glob(glob))
        self.assertEqual(
            found,
            [self._our_marker_name()],
            f"{when}: a heartbeat this test did not write could carry the verdict",
        )

    def _written_at(self) -> float:
        data = heartbeat_payload(self.smm_dir, self.SESSION)
        self.assertIsInstance(data, dict, "no heartbeat for the session under test")
        assert isinstance(data, dict)
        return data["written_at"]


class TestTheWriterCadenceClearsTheThreshold(_LivenessE2ECase):
    """AC#3 + AC#4 — the seam no single Milestone 1 story owns.

    ONE test method on purpose. It mutates a single SMM across a sequence of
    subprocesses; split across methods, xdist is free to interleave the steps
    and the sequence stops being one.
    """

    # Deliberately near-epoch rather than "now minus a delta", mirroring the
    # STALE_AT in test_heartbeat_writers.py / test_heartbeat_refresh.py. Any
    # age computed against it is far past STALE_AFTER_SECONDS. Never `sleep`:
    # the threshold is four hours, so a timing-based test is a flake at best.
    STALE_AT = 1_000.0

    def _turns(self) -> tuple[tuple[str, dict], ...]:
        """The hook entry points a working session actually reaches, in order.

        A prompt, then a bash tool use, then a file edit — the three writers
        that must between them keep a session's verdict live between prompts.
        """
        return (
            (
                "user_prompt_log.py",
                {"session_id": self.SESSION, "prompt": "carry on"},
            ),
            (
                "bash_post_tool.py",
                _make_bash_input(
                    "ls -la", session_id=self.SESSION, cwd=str(self.tmpdir)
                ),
            ),
            (
                "post_tool_use.py",
                _make_write_input(session_id=self.SESSION, cwd=str(self.tmpdir)),
            ),
        )

    def test_a_stale_session_recovers_and_then_never_refuses_again(self):
        self.assertIn(
            _PRELOAD_SKILL,
            discover_preload_scripts(),
            "the representative preload was renamed; this suite would skip silently",
        )

        hook_liveness.write_heartbeat(
            self.smm_dir, session_id=self.SESSION, now=self.STALE_AT
        )
        self._assert_only_our_marker("after seeding the stale heartbeat")

        # AC#3: the runtime stopped, the threshold elapsed, the preload refuses.
        # Also the control that makes everything below non-vacuous — without a
        # demonstrated refusal, "never refuses" is a claim about a check that
        # might simply never fire.
        self.assertTrue(
            self._preload().startswith(REFUSAL_HEADER),
            "a heartbeat older than the threshold must refuse",
        )

        # AC#4: hooks live throughout, preloads run between every turn, and
        # none of them refuses.
        last = self.STALE_AT
        for script, payload in self._turns():
            with self.subTest(turn=script):
                self._hook(script, payload)

                # A writer that did nothing would still read live off the
                # PREVIOUS turn's write. Monotonicity is what makes each turn
                # in the cadence carry its own weight.
                written = self._written_at()
                self.assertGreater(
                    written, last, f"{script} left the heartbeat where it was"
                )
                self.assertLessEqual(written, time.time())
                last = written

                out = self._preload()
                self.assertNotIn(REFUSAL_HEADER, out, f"{script}: preload refused")
                self.assertTrue(out.strip(), f"{script}: preload emitted nothing")
                self._assert_only_our_marker(f"after {script}")

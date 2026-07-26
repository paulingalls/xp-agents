#!/usr/bin/env python3
"""The shared preload base refuses when the hook runtime is not live.

When the hook runtime fails to load, every gate it enforces disappears and the
session looks normal. A preload is an instruction-time load rather than a hook,
so it still executes when the thing it tests is broken — which makes it the one
place the check can live.

A preload cannot BLOCK. It has no decision channel: its stdout becomes context.
"Refuse" here means an unmistakable banner plus suppression of the preload's
normal output, so the skill has nothing to work with. Starvation plus
instruction, not enforcement. These tests assert exactly that and no more.
"""

import os
import re
import subprocess
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import _env_hygiene
import hook_liveness
from _preload_fixtures import PRELOAD_FIXTURES
from conftest import (
    _PLUGIN_ROOT,
    _IntegrationTestCase,
    _preload_script_path,
    discover_preload_scripts,
)

# Fields that differ between two runs of the SAME preload for reasons that have
# nothing to do with the liveness check: `generate_id` mints a fresh close-cycle
# id, `now_iso` stamps the wall clock, and `mktemp` picks a fresh suffix for each
# render tempfile. Normalized on BOTH sides of every comparison, so anything the
# check itself adds still shows up.
_VOLATILE: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"(\.(?:smm|sprint|sprint-review-input|system-context)"
            r"-?(?:rendered)?\.)[A-Za-z0-9]{6}"
        ),
        r"\1XXXXXX",
    ),
    (re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?\+00:00"), "<ts>"),
    (re.compile(r"\b[0-9a-f]{12}\b"), "<id>"),
)


def _normalize(text: str) -> str:
    for pattern, replacement in _VOLATILE:
        text = pattern.sub(replacement, text)
    return text


class _PreloadLivenessCase(_IntegrationTestCase):
    """Drives real preload scripts with the suite-wide bypass explicitly OFF.

    `_env_hygiene` pins the bypass ON for every other runner. This is the one
    place that opts back out, which is what keeps the pin from hollowing out the
    behavior it exists to contain.
    """

    def _env(self, skill: str, *, bypass: bool, **extra: str) -> dict[str, str]:
        env = dict(self._test_env)
        env.update(PRELOAD_FIXTURES[skill]())
        if bypass:
            env[_env_hygiene.SKIP_LIVENESS_ENV] = "1"
        else:
            env.pop(_env_hygiene.SKIP_LIVENESS_ENV, None)
        env.update(extra)
        return env

    def _beat(self, *, age_seconds: float = 0.0) -> None:
        """Record a heartbeat for the session the preload subprocess resolves."""
        hook_liveness.write_heartbeat(
            self.smm_dir,
            session_id=_env_hygiene.TEST_SESSION_ID,
            now=time.time() - age_seconds,
        )

    def _run(self, skill: str, env: dict[str, str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(_preload_script_path(skill))],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
            env=env,
        )


class TestSessionIdContainment(unittest.TestCase):
    """A test run must never resolve the developer's REAL session id.

    Nothing stripped a session id before this suite existed, so a preload
    subprocess inherited whichever id the surrounding harness exported and the
    per-session marker under test moved with it. Containment is pinned once in
    `_env_hygiene`, for every runner that exists or ever will.
    """

    def test_the_pinned_variable_is_the_top_preference_candidate(self):
        """A pin anything can outrank is not containment.

        Fails loudly if a new candidate is ever inserted ABOVE the pinned one —
        at which point the pin silently stops containing anything.
        """
        self.assertEqual(
            _env_hygiene.PINNED_SESSION_ID_VAR,
            hook_liveness.SESSION_ID_ENV_CANDIDATES[0],
            "the pin must sit on the candidate production consults FIRST",
        )

    def test_every_candidate_is_accounted_for(self):
        """The strip list must cover the whole chain, not the part we knew about."""
        self.assertEqual(
            (
                _env_hygiene.PINNED_SESSION_ID_VAR,
                *_env_hygiene.STRIPPED_SESSION_ID_VARS,
            ),
            hook_liveness.SESSION_ID_ENV_CANDIDATES,
        )

    def test_lower_preference_candidates_are_stripped(self):
        for name in _env_hygiene.STRIPPED_SESSION_ID_VARS:
            with self.subTest(var=name):
                self.assertNotIn(name, os.environ)

    def test_resolution_yields_the_pinned_value(self):
        self.assertEqual(
            hook_liveness.resolve_session_id(),
            _env_hygiene.TEST_SESSION_ID,
        )

    def test_a_child_process_inherits_the_pin(self):
        """Preloads are SUBPROCESSES — an in-process patch would not reach them."""
        proc = subprocess.run(
            [
                "bash",
                "-c",
                'printf "%s|%s" "${XP_SESSION_ID-unset}" '
                '"${CLAUDE_CODE_SESSION_ID-unset}"',
            ],
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )
        self.assertEqual(proc.stdout, f"{_env_hygiene.TEST_SESSION_ID}|unset")

    def test_the_bypass_is_pinned_on(self):
        """One bypass pin covers all six `_run_preload` definitions.

        Seeding a heartbeat per runner would cover a sixth of the surface, and a
        seventh runner would opt out by simply not knowing. The dedicated
        liveness suites below unset it explicitly — that is where the real
        behavior is exercised.
        """
        self.assertEqual(os.environ.get(_env_hygiene.SKIP_LIVENESS_ENV), "1")


class TestALiveHeartbeatChangesNothing(_PreloadLivenessCase):
    """The happy path must be byte-for-byte what it was before the check.

    A gate on the shared base runs ahead of all 16 preloads, so a stray line on
    the LIVE path is 16 regressions at once, in context windows the check has no
    business touching. Every preload is compared, not a representative.
    """

    def test_output_is_identical_with_the_check_active(self):
        for skill in discover_preload_scripts():
            with self.subTest(skill=skill):
                self._beat()
                baseline = self._run(skill, self._env(skill, bypass=True))
                checked = self._run(skill, self._env(skill, bypass=False))
                self.assertEqual(
                    _normalize(checked.stdout),
                    _normalize(baseline.stdout),
                    "a live heartbeat must leave preload stdout untouched",
                )
                self.assertEqual(checked.returncode, baseline.returncode)


class TestLefthookMirrorsTheStrip(unittest.TestCase):
    """CLAUDE.md's two-place convention: `env -u` in lefthook.yml must match.

    lefthook runs pytest through `env -u ...` so the vars are gone before the
    interpreter starts. The conftest-side strip cannot cover a var the shell
    exported into pytest's own process for code that reads it at import time,
    and a var added to only one of the two places has already shipped once.
    """

    def test_session_id_candidates_are_stripped_in_lefthook(self):
        lefthook = (_PLUGIN_ROOT.parents[1] / "lefthook.yml").read_text(
            encoding="utf-8"
        )
        for line in lefthook.splitlines():
            if "pytest" not in line or "env -u" not in line:
                continue
            for name in hook_liveness.SESSION_ID_ENV_CANDIDATES:
                with self.subTest(var=name, line=line.strip()[:40]):
                    self.assertIn(f"-u {name}", line)


if __name__ == "__main__":
    unittest.main()

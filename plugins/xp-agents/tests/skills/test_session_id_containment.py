#!/usr/bin/env python3
"""The session-id candidate chain, and the two places that must contain it.

Session-scoped markers fold a session id into their filename, so whichever id
a process resolves decides which marker it addresses. Two separate contracts
follow from that, and both live here rather than beside the liveness-refusal
behaviour they used to share a module with:

- **Containment.** A test run must never resolve the developer's REAL id.
  Nothing stripped one before this suite existed, so a preload subprocess
  inherited whatever the surrounding harness exported and the marker under test
  moved with it. Pinned once in `_env_hygiene`, for every runner that exists or
  ever will — plus `lefthook.yml`, which strips them before the interpreter
  starts and so cannot be covered from inside it.

- **Ordering.** The chain is ordered by OWNERSHIP, not arrival: one host
  launched from another inherits the launcher's variable, so several can be set
  at once and preference alone picks the marker.
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import _env_hygiene
import hook_liveness
from conftest import _PLUGIN_ROOT


class TestSessionIdContainment(unittest.TestCase):
    """A test run must never resolve the developer's REAL session id."""

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

    def test_a_hosts_own_id_outranks_one_leaked_from_its_parent(self):
        """Measured: one host's id reaches a child host's processes.

        A session launched from another agent inherits that agent's session-id
        variable, so both are set at once and preference alone decides which
        heartbeat the preload addresses. Getting this backwards is silent and
        total: hooks scope their heartbeat by the id the HOST handed them, the
        preload resolves a DIFFERENT id from the inherited variable, finds no
        heartbeat under it and withholds every skill's context — while the
        runtime it is testing is running perfectly.

        So a variable naming the session actually in charge must outrank one
        that merely leaked into it.
        """
        candidates = hook_liveness.SESSION_ID_ENV_CANDIDATES
        env = {name: f"id-from-{name}" for name in candidates}
        env[_env_hygiene.PINNED_SESSION_ID_VAR] = ""

        with patch.dict(os.environ, env):
            resolved = hook_liveness.resolve_session_id()

        leaked = candidates[-1]
        self.assertNotEqual(
            resolved,
            f"id-from-{leaked}",
            f"{leaked} leaks into child sessions, so it must rank LAST",
        )

    def test_a_child_process_inherits_the_pin(self):
        """Preloads are SUBPROCESSES — an in-process patch would not reach them.

        Derives the probed names from the production chain rather than naming
        one: a hardcoded list keeps passing for the candidate it knows while a
        newly added sibling goes unchecked.
        """
        probes = " ".join(
            f'"${{{name}-unset}}"' for name in _env_hygiene.STRIPPED_SESSION_ID_VARS
        )
        proc = subprocess.run(
            [
                "bash",
                "-c",
                f'printf "%s" "${{{_env_hygiene.PINNED_SESSION_ID_VAR}-unset}}"; '
                f'printf "|%s" {probes}',
            ],
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )
        stripped = "|".join(["unset"] * len(_env_hygiene.STRIPPED_SESSION_ID_VARS))
        self.assertEqual(proc.stdout, f"{_env_hygiene.TEST_SESSION_ID}|{stripped}")

    def test_the_bypass_is_pinned_on(self):
        """One bypass pin covers all six `_run_preload` definitions.

        Seeding a heartbeat per runner would cover a sixth of the surface, and a
        seventh runner would opt out by simply not knowing. The dedicated
        liveness suites unset it explicitly — that is where the real behavior is
        exercised.
        """
        self.assertEqual(os.environ.get(_env_hygiene.SKIP_LIVENESS_ENV), "1")


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
        pytest_lines = [
            line
            for line in lefthook.splitlines()
            if "pytest" in line and "env -u" in line
        ]
        # Without this the loop below is vacuous: reword the `run:` lines and
        # the agreement check silently stops checking anything. Three today —
        # pre-commit `tests`, pre-push `integration`, pre-push `perf`.
        self.assertEqual(len(pytest_lines), 3, lefthook)
        for line in pytest_lines:
            for name in hook_liveness.SESSION_ID_ENV_CANDIDATES:
                with self.subTest(var=name, line=line.strip()[:40]):
                    self.assertIn(f"-u {name}", line)


if __name__ == "__main__":
    unittest.main()

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

- **Refusal, not preference.** One host launched from another inherits the
  launcher's variable, so two can be set at once — and which one this host owns
  depends on which launched which, runtime state the environment does not
  record. Disagreement therefore resolves to None rather than to whichever the
  chain lists first, which makes ORDER irrelevant to correctness. Guessing
  would address the launcher's heartbeat and read as live for a session whose
  own hooks never loaded.
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
import session_scope
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

    def test_two_disagreeing_ids_resolve_to_none_rather_than_a_guess(self):
        """Nesting direction is runtime state, so preference cannot decide.

        A session launched from another agent inherits that agent's session-id
        variable, so two are set at once. Which one the host actually owns
        depends on WHICH launched WHICH — unknowable from the environment, in
        which both are just strings. Any fixed preference is therefore right in
        one nesting direction and silently wrong in the mirrored one.

        Wrong is not a weaker check, it is a dangerous one: hooks scope their
        heartbeat by the id the HOST handed them, so resolving the other id
        addresses the LAUNCHER's heartbeat. That reads as live when this
        session's hook runtime never loaded — a fail-open in the check whose
        entire job is to detect exactly that.

        So disagreement resolves to None: unresolvable evidence refuses. That
        is the same direction as every other gate here, and it makes ordering
        irrelevant to correctness rather than load-bearing in one direction.
        """
        env = dict.fromkeys(hook_liveness.SESSION_ID_ENV_CANDIDATES, "")
        env["CODEX_THREAD_ID"] = "an-id-this-host-owns"
        env["CLAUDE_CODE_SESSION_ID"] = "an-id-leaked-from-the-launcher"

        with patch.dict(os.environ, env):
            resolved = hook_liveness.resolve_session_id()
            conflict = session_scope.conflicting_session_ids()

        self.assertIsNone(
            resolved,
            "two disagreeing ids are unresolvable — refuse rather than pick "
            "one, which would address the launcher's heartbeat",
        )
        self.assertEqual(
            conflict,
            ("CODEX_THREAD_ID", "CLAUDE_CODE_SESSION_ID"),
            "the conflicting names must be reportable, so the refusal can say "
            "which two disagree and which variable settles it",
        )

    def test_agreeing_duplicates_are_not_a_conflict(self):
        """One id exported under two names is not ambiguous — it is one id.

        A host that sets its own variable AND the neutral override to the same
        value must not be refused; only DISAGREEMENT is unresolvable.
        """
        env = dict.fromkeys(hook_liveness.SESSION_ID_ENV_CANDIDATES, "")
        env[_env_hygiene.PINNED_SESSION_ID_VAR] = "one-id"
        env["CODEX_THREAD_ID"] = "one-id"

        with patch.dict(os.environ, env):
            self.assertEqual(hook_liveness.resolve_session_id(), "one-id")
            self.assertEqual(session_scope.conflicting_session_ids(), ())

    def test_the_two_functions_normalise_a_value_identically(self):
        """One emptiness-and-padding rule, or the pair disagrees about reality.

        `conflicting_session_ids` decides WHETHER there is an answer and
        `resolve_session_id` decides WHAT it is, from the same environment. Each
        strips before comparing, and neither can be the one that stops: padding
        read as significant turns one id under two names into a refusal, while a
        whitespace-only value read as set turns a single-host session into one.
        Both are false refusals of a working runtime, so the agreement is pinned
        rather than left to the two implementations happening to match.
        """
        one_id = "an-id-with-padding"
        for other in (f"  {one_id}", f"{one_id}\n", f"\t{one_id} "):
            with self.subTest(padded=other):
                env = dict.fromkeys(hook_liveness.SESSION_ID_ENV_CANDIDATES, "")
                env[_env_hygiene.PINNED_SESSION_ID_VAR] = one_id
                env["CODEX_THREAD_ID"] = other
                with patch.dict(os.environ, env):
                    self.assertEqual(session_scope.conflicting_session_ids(), ())
                    self.assertEqual(hook_liveness.resolve_session_id(), one_id)

        for blank in ("   ", "\t", "\n"):
            with self.subTest(whitespace_only=blank):
                env = dict.fromkeys(hook_liveness.SESSION_ID_ENV_CANDIDATES, "")
                env[_env_hygiene.PINNED_SESSION_ID_VAR] = one_id
                env["CODEX_THREAD_ID"] = blank
                with patch.dict(os.environ, env):
                    self.assertEqual(session_scope.conflicting_session_ids(), ())
                    self.assertEqual(hook_liveness.resolve_session_id(), one_id)

    def test_a_single_candidate_still_resolves(self):
        """The ordinary single-host case must be untouched by the refusal."""
        for name in hook_liveness.SESSION_ID_ENV_CANDIDATES:
            with self.subTest(var=name):
                env = dict.fromkeys(hook_liveness.SESSION_ID_ENV_CANDIDATES, "")
                env[name] = f"only-{name}"
                with patch.dict(os.environ, env):
                    self.assertEqual(hook_liveness.resolve_session_id(), f"only-{name}")
                    self.assertEqual(session_scope.conflicting_session_ids(), ())

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
        # the agreement check silently stops checking anything. Two today —
        # pre-push `all-tests` and pre-push `perf`. Was three until the full
        # suite moved off the commit gate; pre-commit no longer runs pytest at
        # all, and pre-push `integration` was subsumed by `all-tests` rather
        # than kept alongside it, which would have run tests/integration twice.
        self.assertEqual(len(pytest_lines), 2, lefthook)
        for line in pytest_lines:
            for name in hook_liveness.SESSION_ID_ENV_CANDIDATES:
                with self.subTest(var=name, line=line.strip()[:40]):
                    self.assertIn(f"-u {name}", line)


if __name__ == "__main__":
    unittest.main()

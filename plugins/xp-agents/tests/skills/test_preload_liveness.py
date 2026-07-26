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
import markers
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


# The refusal's own heading. It must not be confusable with the base's
# pre-existing no-SMM-at-all exit: "there is no shared model here" and "the
# shared model is here but the runtime maintaining it is dead" are different
# failures with different fixes.
REFUSAL_HEADER = "## Hook Runtime: not live"
SMM_UNAVAILABLE = "## SMM State: unavailable"

# One preload stands in for the shape assertions; the set-wide inheritance
# assertion is its own test below, because "some preload refuses" and "every
# preload refuses" are different claims.
_REP = "xp-accept"


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


class TestRefusalWhenNoHeartbeatExists(_PreloadLivenessCase):
    """The failure the whole milestone exists for: gates absent, nothing said."""

    def test_the_banner_replaces_the_preload_output_entirely(self):
        """Refusal is starvation plus instruction — the skill gets nothing."""
        normal = self._run(_REP, self._env(_REP, bypass=True)).stdout
        refusal = self._run(_REP, self._env(_REP, bypass=False)).stdout

        self.assertTrue(refusal.startswith(REFUSAL_HEADER), refusal[:200])
        survivors = [
            line
            for line in normal.splitlines()
            if len(line.strip()) > 5 and line in refusal
        ]
        self.assertEqual(survivors, [], "the preload's normal output must be gone")

    def test_the_message_names_the_likely_cause(self):
        """Not "a file is missing" — the diagnosis a reader can act on.

        Taken verbatim from the CLI, which already owns the verdict and its
        wording. The shell must not re-derive either.
        """
        refusal = self._run(_REP, self._env(_REP, bypass=False)).stdout
        verdict = hook_liveness.check_liveness(self.smm_dir)

        self.assertEqual(verdict.code, hook_liveness.CODE_NO_MARKER)
        self.assertIn(verdict.reason, refusal)
        self.assertIn("not loaded", refusal)

    def test_the_banner_names_the_escape_hatch(self):
        """An opt-out the refusal does not name is not an opt-out."""
        refusal = self._run(_REP, self._env(_REP, bypass=False)).stdout
        self.assertIn(_env_hygiene.SKIP_LIVENESS_ENV, refusal)

    def test_refusal_is_not_confusable_with_an_unresolvable_smm(self):
        refusal = self._run(_REP, self._env(_REP, bypass=False)).stdout
        self.assertNotIn(SMM_UNAVAILABLE, refusal)

    def test_the_preload_still_exits_zero(self):
        """A preload's channel is stdout; a non-zero exit is a different failure
        for the caller to handle, and would mask the banner it needs to read."""
        self.assertEqual(self._run(_REP, self._env(_REP, bypass=False)).returncode, 0)


class TestStaleAndUndeterminedRefuseToo(_PreloadLivenessCase):
    """Absence is not the only way a runtime is untrustworthy.

    A heartbeat can be too old (the runtime died partway through the session) or
    unreadable (whether it is running cannot be determined). A check that cannot
    see is not a check that passed, so both refuse — but they are different
    diagnoses and must read differently.
    """

    def _heartbeat_path(self) -> Path:
        return markers.marker_path(
            self.smm_dir,
            hook_liveness.heartbeat_marker(_env_hygiene.TEST_SESSION_ID),
        )

    def test_a_stale_heartbeat_refuses_the_same_way(self):
        self._beat(age_seconds=hook_liveness.STALE_AFTER_SECONDS + 60)
        verdict = hook_liveness.check_liveness(self.smm_dir)
        refusal = self._run(_REP, self._env(_REP, bypass=False)).stdout

        self.assertEqual(verdict.code, hook_liveness.CODE_STALE)
        self.assertTrue(refusal.startswith(REFUSAL_HEADER), refusal[:200])
        self.assertIn(verdict.reason, refusal)

    def test_an_unreadable_heartbeat_refuses_with_its_own_message(self):
        """Could-not-determine keeps its own wording — it supports no diagnosis."""
        self._beat()
        self._heartbeat_path().write_text("not json at all", encoding="utf-8")
        verdict = hook_liveness.check_liveness(self.smm_dir)
        refusal = self._run(_REP, self._env(_REP, bypass=False)).stdout

        self.assertEqual(verdict.code, hook_liveness.CODE_UNREADABLE)
        self.assertTrue(refusal.startswith(REFUSAL_HEADER), refusal[:200])
        self.assertIn(verdict.reason, refusal)
        self.assertIn("cannot be determined", refusal)
        # It must NOT claim the runtime is absent — nothing established that.
        self.assertNotIn("has been recorded", refusal)

    def test_the_two_refusal_kinds_arrive_on_different_exit_codes(self):
        """Why the shell refuses on every non-zero status, not just on 1."""
        self._beat(age_seconds=hook_liveness.STALE_AFTER_SECONDS + 60)
        self.assertEqual(self._status_exit_code(), hook_liveness.EXIT_NOT_LIVE)

        self._heartbeat_path().write_text("not json at all", encoding="utf-8")
        self.assertEqual(self._status_exit_code(), hook_liveness.EXIT_UNDETERMINED)

    def _status_exit_code(self) -> int:
        return subprocess.run(
            [
                "python3",
                str(_PLUGIN_ROOT / "scripts" / "hook_liveness.py"),
                "--smm-dir",
                str(self.smm_dir),
                "status",
            ],
            capture_output=True,
            text=True,
            env=self._test_env,
        ).returncode

    def test_an_unresolvable_smm_still_takes_the_existing_path(self):
        """A different failure, and it must stay legible as one.

        No shared model AT ALL is not a dead runtime, and the two have different
        fixes. The base's own exit runs before this check and must keep winning.
        """
        blocker = self.tmpdir / "not-a-directory"
        blocker.write_text("", encoding="utf-8")
        env = self._env(_REP, bypass=False)
        env.pop("SMM_DIR", None)
        env["XP_AGENTS_DATA"] = str(blocker)

        out = self._run(_REP, env).stdout
        self.assertIn(SMM_UNAVAILABLE, out)
        self.assertNotIn(REFUSAL_HEADER, out)


class TestTheEscapeHatch(_PreloadLivenessCase):
    """A deliberate, self-advertised opt-out.

    This does not reintroduce the failure the milestone is about. That failure
    is enforcement vanishing SILENTLY; this vanishes only when someone sets a
    variable the refusal itself named. It exists because of a known
    false-refusal path: a headless teammate submits one prompt, so its
    heartbeat is written once and it self-refuses past the staleness threshold
    mid-run with no in-session recovery.
    """

    def test_the_bypass_produces_the_normal_output_with_no_heartbeat(self):
        refusal = self._run(_REP, self._env(_REP, bypass=False)).stdout
        bypassed = self._run(_REP, self._env(_REP, bypass=True)).stdout

        self.assertTrue(refusal.startswith(REFUSAL_HEADER))
        self.assertNotIn(REFUSAL_HEADER, bypassed)
        self.assertNotEqual(bypassed, refusal)

    def test_only_the_documented_value_bypasses(self):
        """Fail closed on anything else — including the near-misses.

        The banner names `=1`, so a reader who set something else is told the
        exact form. Treating every non-empty value as truthy would let a
        leftover `=0` disable the check silently.
        """
        for value in ("0", "", "true", "yes", "2", " 1"):
            with self.subTest(value=value):
                env = self._env(_REP, bypass=False)
                env[_env_hygiene.SKIP_LIVENESS_ENV] = value
                out = self._run(_REP, env).stdout
                self.assertTrue(
                    out.startswith(REFUSAL_HEADER), f"{value!r}: {out[:80]}"
                )


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

#!/usr/bin/env python3
"""Volume budgets — what each injected surface costs against a POPULATED SMM.

Sister to the SHAPE families (`hooks/test_injection_budgets.py`,
`hooks/test_preload_budgets.py`), not a replacement for them. Those measure
`_bootstrap_seeded_smm` — an SMM with an empty `events.jsonl`, no `sprint.json`
and no `system_context.json` — so they bound the *prose* a surface emits and are
structurally blind to the *data* it renders. Both fixture modules say so:
`_preload_fixtures._no_env` records that its preloads "route to their no-state
branch", which is why two of them are budgeted at 100 chars while emitting tens
of thousands in production.

Measured live before this module existed: `.retro-input.json` 204,224 chars with
no bound at all, the `xp-quality-review` preload 196,066 against a budget of 300,
`triage_preload` 42,864 against 100.

Two independent axes make a surface quiet, and BOTH have to be driven:

  1. data volume — the SMM is empty
  2. input shape — the fixture picks the cheap branch (`session_start` at
     `source: "startup"`, never `"compact"`; `subagent_start` at
     `general-purpose`, the cheapest of five tiers)

Phase 0 measured which axis each emitter sits on: 3 of 15 flip on volume alone,
8 stay at 0 until given a loud input, and `session_start`/`subagent_start` move
on NEITHER events volume nor sprint state — they render
`shared_mental_model.json`, which `seed_smm.py` already writes.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _emitter_fixtures import EMITTER_BUDGETS, EMITTER_LOUD_FIXTURES
from _preload_fixtures import PRELOAD_BUDGETS
from _volume_fixture import (
    assert_volume_under_budgets,
    bootstrap_populated_smm,
    emitter_runner,
)
from conftest import _SCRIPTS_DIR, _bootstrap_seeded_smm, _run_emitter

# ratchet(measured, current, 100, rounding=ceil) — measured against
# `_volume_fixture.bootstrap_populated_smm`, calibrated at 1.125 so a fresh
# surface lands near 89% rather than inside the 98% band.
#
# These read roughly 2x the same surface against a copied real log (105,454 vs
# 52,674 for xp-work-selection). The generator emits every concern UNRESOLVED,
# where a real log resolves most of them — 223 open here against 91 open of 223
# raised in production. Deliberate: a bound wants the pessimistic end, and the
# open-concern count is the very thing a downstream story has to vary.
PRELOAD_VOLUME_BUDGETS: dict[str, int] = {
    "xp-work-selection": 118700,
}

# Same calibration, measured at each emitter's LOUD input (see
# `_emitter_fixtures.EMITTER_LOUD_FIXTURES`) against the populated SMM.
EMITTER_VOLUME_BUDGETS: dict[str, int] = {
    "post_tool_exit_plan.py": 400,
    "pre_tool_skill.py": 400,
    "prompt_nugget.py": 600,
    "retrospective.py": 600,
    "session_end_warning.py": 200,
    "session_start.py": 20300,
    "subagent_start.py": 12100,
}

_LABEL = "skills/*/scripts/preload.sh"
_EMITTER_LABEL = "scripts/*.py emitter"


class TestRunEmitterAcceptsFixtureOverride(unittest.TestCase):
    """`_run_emitter` must accept the stdin builder as an argument.

    It resolves the builder from the module-global `EMITTER_FIXTURES` registry,
    so without a parameter there is no way to drive an emitter at a LOUDER
    branch than the shape family's entry — the volume family would silently
    measure the same quiet input and every budget it derived would be wrong in
    the direction that still looks green.
    """

    def test_run_emitter_uses_the_supplied_builder(self):
        def loud() -> dict:
            return {"session_id": "t", "agent_id": "main", "source": "compact"}

        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            repo, smm = _bootstrap_seeded_smm(Path(tmp))
            quiet_out, _, quiet_rc = _run_emitter(
                "session_start.py", _SCRIPTS_DIR, smm, repo
            )
            loud_out, _, loud_rc = _run_emitter(
                "session_start.py",
                _SCRIPTS_DIR,
                smm,
                repo,
                fixtures={"session_start.py": loud},
            )

        self.assertEqual(quiet_rc, 0, "quiet run should succeed")
        self.assertEqual(loud_rc, 0, "loud run should succeed")
        self.assertGreater(
            len(loud_out),
            len(quiet_out),
            "the supplied builder was ignored: `source: compact` injects "
            "PROCESS_GUIDE and must measure larger than `source: startup`",
        )


class TestPreloadVolumeBudgets(unittest.TestCase):
    def test_no_preload_exceeds_its_volume_budget(self):
        assert_volume_under_budgets(
            self, PRELOAD_VOLUME_BUDGETS, PRELOAD_BUDGETS, _LABEL
        )

    def test_the_fixture_is_what_makes_these_surfaces_loud(self):
        """Point the assert at the SHAPE bootstrap and it must fail.

        This is the mutation the family exists to survive, kept as a test
        rather than a one-off procedure. Every volume budget is derived from
        the populated fixture's own measurement, so a fixture that silently
        stopped driving surfaces loud would derive small budgets and stay green
        forever. Here the same surfaces, measured against the empty SMM, must
        fall back under their shape budgets and be reported by name.
        """
        with self.assertRaises(AssertionError) as caught:
            assert_volume_under_budgets(
                self,
                PRELOAD_VOLUME_BUDGETS,
                PRELOAD_BUDGETS,
                _LABEL,
                bootstrap=_bootstrap_seeded_smm,
            )
        message = str(caught.exception)
        for surface in PRELOAD_VOLUME_BUDGETS:
            self.assertIn(surface, message)
        self.assertIn("does not exceed its shape budget", message)
        self.assertNotIn("subprocess rc=", message)

    def test_the_generator_is_deterministic(self):
        """Two bootstraps must measure identically, or the 2% band flakes."""
        import tempfile

        from _budget_helpers import _PLUGIN_ROOT, _measured_len, _run_preload

        measurements = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as tmp:
                repo, smm = bootstrap_populated_smm(Path(tmp))
                out, _err, rc = _run_preload("xp-work-selection", smm, repo)
                self.assertEqual(rc, 0)
                measurements.append(
                    _measured_len(
                        out,
                        normalize_paths=(str(_PLUGIN_ROOT), str(smm), str(repo)),
                    )
                )
        self.assertEqual(
            measurements[0],
            measurements[1],
            "the volume fixture is not deterministic; a drifting measurement "
            "inside a 2%-wide band will flake in CI",
        )


class TestEmitterVolumeBudgets(unittest.TestCase):
    def test_no_emitter_exceeds_its_volume_budget(self):
        assert_volume_under_budgets(
            self,
            EMITTER_VOLUME_BUDGETS,
            EMITTER_BUDGETS,
            _EMITTER_LABEL,
            runner=emitter_runner(EMITTER_LOUD_FIXTURES),
        )

    def test_the_fixture_is_what_makes_these_emitters_loud(self):
        """The same mutation, over the emitter path."""
        with self.assertRaises(AssertionError) as caught:
            assert_volume_under_budgets(
                self,
                EMITTER_VOLUME_BUDGETS,
                EMITTER_BUDGETS,
                _EMITTER_LABEL,
                bootstrap=_bootstrap_seeded_smm,
                runner=emitter_runner(EMITTER_LOUD_FIXTURES),
            )
        message = str(caught.exception)
        self.assertIn("does not exceed its shape budget", message)
        self.assertNotIn("subprocess rc=", message)

    def test_every_loud_fixture_has_a_volume_budget(self):
        self.assertEqual(
            set(EMITTER_LOUD_FIXTURES),
            set(EMITTER_VOLUME_BUDGETS),
            "a loud builder without a volume budget measures nothing, and a "
            "volume budget without a loud builder bounds the quiet branch",
        )


if __name__ == "__main__":
    unittest.main()

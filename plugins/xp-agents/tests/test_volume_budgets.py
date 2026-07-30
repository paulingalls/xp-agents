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
  2. input shape — the fixture picks the cheap branch, e.g. `session_start` at
     `source: "startup"`, never `"compact"`, which is the branch that also
     injects PROCESS_GUIDE (1,264 chars against 17,962)

Measured, not assumed: 3 of 15 emitters flip on events volume alone, 8 stay at
0 until given a loud input, and `session_start`/`subagent_start` move on
NEITHER events volume nor sprint state — their cost is
`shared_mental_model.json`, which `seed_smm.py` already writes, so the fixture
has to overwrite that file specifically. "Populate the SMM" turned out to be
seven artifacts.

`subagent_start` is worth knowing about: its shape builder passes
`subagent_type` inside `tool_input`, while the hook reads a TOP-LEVEL
`agent_type`. The lookup therefore sees `""` and falls through `_resolve_tier`
to `_inject_full` — the most expensive tier, not the cheapest. The shape family
measures the right tier against the wrong data.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _emitter_fixtures import EMITTER_BUDGETS, EMITTER_LOUD_FIXTURES
from _preload_fixtures import PRELOAD_BUDGETS
from _volume_fixture import (
    ARTIFACT_MEASURERS,
    assert_artifacts_under_budgets,
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
    "xp-accept": 45600,
    "xp-end-session": 2300,
    "xp-kickoff": 400,
    "xp-plan": 200,
    "xp-sprint-start": 300,
    "xp-work-selection": 119000,
}

# Surfaces whose size does NOT track SMM data, with the reason. This is a
# CLAIM, not an exemption: `test_prose_dominated_surfaces_really_are` measures
# each one and fails if it ever climbs above its shape budget, which would mean
# it had become volume-sensitive and needs a real entry here instead.
_PRELOAD_PROSE_DOMINATED: dict[str, str] = {
    "xp-free-close": "static shared close reference dominates (8,721 of 8,900)",
    "xp-plan-close": "same shared reference",
    "xp-sprint-close": "same shared reference",
    "xp-story-close": "same reference, mode-scoped subset",
    "xp-assign": "emits computed vars, not rendered SMM content",
    "xp-schedule": "frontier ids only",
    "xp-sprint-review": "counts only",
    "xp-system-context": "a path and a flag",
}

# Surfaces that need a trigger this fixture does not build. Each names what is
# missing so the gap is a to-do with an owner, not an unexplained absence.
_PRELOAD_NEEDS_TRIGGER: dict[str, str] = {
    "xp-quality-review": "needs a real git diff — its 196,066 chars in "
    "production are the diff, not the SMM",
    "xp-review-plan": "keyed on a `.plan-awaiting-review` marker that "
    "populating the SMM does not create",
}

# Same calibration, measured at each emitter's LOUD input (see
# `_emitter_fixtures.EMITTER_LOUD_FIXTURES`) against the populated SMM.
_EMITTER_PROSE_DOMINATED: dict[str, str] = {
    "lint_check.py": "a fixed warning string",
    "review_cycle_done.py": "a fixed follow-up string",
}

_EMITTER_NEEDS_TRIGGER: dict[str, str] = {
    "bash_post_tool.py": "needs a command whose result it records",
    "kickoff_gate.py": "needs an un-kicked-off session",
    "pre_tool_bash.py": "needs a gated command",
    "pre_tool_write.py": "needs a write that trips the TDD gate",
    "subagent_stop.py": "needs a live plan-review marker",
}

# Cannot emit AT ALL: `user_prompt_log.run()` returns None on all six of its
# paths, so its `_common.hook_output` call is unreachable. Its 100-char shape
# budget bounds a surface that structurally cannot produce output.
_EMITTER_STRUCTURALLY_SILENT: dict[str, str] = {
    "user_prompt_log.py": "run() returns None on every path; hook_output is "
    "unreachable",
}

EMITTER_VOLUME_BUDGETS: dict[str, int] = {
    "post_tool_exit_plan.py": 400,
    "pre_tool_skill.py": 400,
    "prompt_nugget.py": 600,
    "retrospective.py": 600,
    "session_end_warning.py": 200,
    "session_start.py": 20300,
    "subagent_start.py": 12100,
}

# Disk artifacts handed to a subagent by path. Neither carried ANY bound
# before this module: `.retro-input.json` is written on every session start and
# measured 204,224 chars in production, `.curation-input.json` 79,068. They are
# the two largest injected surfaces in the plugin.
ARTIFACT_VOLUME_BUDGETS: dict[str, int] = {
    ".retro-input.json": 264100,
    ".curation-input.json": 249600,
}

_LABEL = "skills/*/scripts/preload.sh"
_EMITTER_LABEL = "scripts/*.py emitter"
_ARTIFACT_LABEL = "smm/.*-input.json artifact"


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


class TestArtifactVolumeBudgets(unittest.TestCase):
    """The two biggest injected surfaces, neither of which had any bound."""

    def test_no_artifact_exceeds_its_volume_budget(self):
        assert_artifacts_under_budgets(self, ARTIFACT_VOLUME_BUDGETS, _ARTIFACT_LABEL)

    def test_every_artifact_measurer_has_a_budget(self):
        self.assertEqual(
            set(ARTIFACT_MEASURERS),
            set(ARTIFACT_VOLUME_BUDGETS),
            "an artifact measured with no budget bounds nothing; a budget with "
            "no measurer is never checked",
        )


class TestVolumeCoverageIsComplete(unittest.TestCase):
    """Every surface the shape families bound must be CLASSIFIED here.

    Written last, deliberately. An allowlist that retires itself is the
    gate-that-does-nothing shape story-007's contract forbids, so there is no
    pending set: a surface is either bounded at volume, or carries a written
    reason why it cannot be, and anything else fails by name.
    """

    def test_every_preload_is_classified(self):
        classified = (
            set(PRELOAD_VOLUME_BUDGETS)
            | set(_PRELOAD_PROSE_DOMINATED)
            | set(_PRELOAD_NEEDS_TRIGGER)
        )
        self.assertEqual(
            set(PRELOAD_BUDGETS) - classified,
            set(),
            "preloads with a shape budget and no volume classification. Add a "
            "volume budget, or record why the surface has no volume dimension.",
        )

    def test_every_emitter_is_classified(self):
        classified = (
            set(EMITTER_VOLUME_BUDGETS)
            | set(_EMITTER_PROSE_DOMINATED)
            | set(_EMITTER_NEEDS_TRIGGER)
            | set(_EMITTER_STRUCTURALLY_SILENT)
        )
        self.assertEqual(
            set(EMITTER_BUDGETS) - classified,
            set(),
            "emitters with a shape budget and no volume classification.",
        )

    def test_no_surface_is_classified_twice(self):
        for label, groups in (
            (
                "preload",
                [
                    PRELOAD_VOLUME_BUDGETS,
                    _PRELOAD_PROSE_DOMINATED,
                    _PRELOAD_NEEDS_TRIGGER,
                ],
            ),
            (
                "emitter",
                [
                    EMITTER_VOLUME_BUDGETS,
                    _EMITTER_PROSE_DOMINATED,
                    _EMITTER_NEEDS_TRIGGER,
                    _EMITTER_STRUCTURALLY_SILENT,
                ],
            ),
        ):
            seen: set[str] = set()
            for group in groups:
                overlap = seen & set(group)
                self.assertEqual(overlap, set(), f"{label} classified twice: {overlap}")
                seen |= set(group)

    def test_prose_dominated_surfaces_really_are(self):
        """The claim is measured, not taken on trust.

        A surface parked in `_PROSE_DOMINATED` because its size does not track
        SMM data must keep measuring at or below its shape budget against the
        POPULATED fixture. One that climbs past it has grown a volume dimension
        and needs a real budget — this is what stops the category becoming a
        quiet exemption.
        """
        import tempfile

        from _budget_helpers import _PLUGIN_ROOT, _measured_len, _run_preload

        offenders = []
        with tempfile.TemporaryDirectory() as tmp:
            repo, smm = bootstrap_populated_smm(Path(tmp))
            for name, reason in sorted(_PRELOAD_PROSE_DOMINATED.items()):
                out, err, rc = _run_preload(name, smm, repo)
                self.assertEqual(rc, 0, f"{name}: {err[:200]}")
                actual = _measured_len(
                    out, normalize_paths=(str(_PLUGIN_ROOT), str(smm), str(repo))
                )
                if actual > PRELOAD_BUDGETS[name]:
                    offenders.append(
                        f"{name}: {actual} chars at volume, above its shape "
                        f"budget of {PRELOAD_BUDGETS[name]} — no longer "
                        f"prose-dominated ({reason})"
                    )
        self.assertFalse(offenders, "\n".join(offenders))


if __name__ == "__main__":
    unittest.main()

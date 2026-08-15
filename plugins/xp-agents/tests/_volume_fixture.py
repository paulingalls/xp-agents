#!/usr/bin/env python3
"""An SMM seeded to realistic volume, for `tests/test_volume_budgets.py`.

`_budget_helpers._bootstrap_seeded_smm` builds an SMM with an empty
`events.jsonl`, no `sprint.json` and no `system_context.json`. That is the right
fixture for bounding PROSE, and the wrong one for bounding DATA: measured
against it, `xp-work-selection`'s preload emits 32 chars and carries a budget of
100, while the same preload against a populated SMM emits 52,674.

Distributions below are measured from real event logs (2,038 events), not
invented. A generator rather than a committed log because the family must be
able to VARY volume — a downstream story has to seed past an overflow cap to
test it, which a frozen blob cannot do — and because `tests/` holds no data
fixtures, while the raw logs carry absolute home paths and literal prompt text.

**Determinism.** Content lengths, ids (constant-width) and timestamps are all
fixed; nothing reads the wall clock. Timestamps are therefore absolute, so a
reader that filters on recency will eventually see this fixture as stale and go
quiet. That failure is LOUD by construction, on two guards that between them
cover every surface: `assert_volume_under_budgets` requires each one to
out-measure its own shape budget, and — for the emitters whose loud input
already clears that budget on its own —
`test_every_emitter_volume_entry_moves_with_data` requires the populated
bootstrap to out-measure the empty one. A fixture that ages into silence fails
rather than passing with a wrong number.
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
# `_event_fixtures` imports `event_schema` from smm/ at module scope, and this
# module is imported BEFORE `conftest` (alphabetically) by the suite that uses
# it — so it cannot rely on conftest having put smm/ on the path.
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

from _bases import _SCRIPTS_DIR
from _budget_helpers import (
    _PLUGIN_ROOT,
    _bootstrap_seeded_smm,
    _measured_len,
    _run_emitter,
    _run_preload,
    band_offender,
    scrub_close_cycle_marker,
)
from _event_fixtures import make_event, write_events

# Measured over a real 2,038-event log. Proportions of the whole, rounded to
# whole events by the generator; the long tail (question/convention/discovery/
# sprint/goal/retrospective, ~1% combined) is dropped rather than modelled — it
# does not move a byte budget and each carries its own required-field shape.
_TYPE_MIX: dict[str, float] = {
    "status": 0.693,
    "concern": 0.109,
    "decision": 0.069,
    "commit": 0.048,
    "assumption": 0.030,
    "debt": 0.011,
}

# Median content length per type from the same log. Medians, not means: the
# means are pulled by a small number of very long commit bodies (mean 1,297 vs
# median 1,202) and the median is the more faithful "typical event".
_CONTENT_LEN: dict[str, int] = {
    "status": 41,
    "concern": 402,
    "decision": 318,
    "commit": 1202,
    "assumption": 289,
    "debt": 474,
}

# 15% of events carry a `files` list, mean 3.67 entries, mean path 49 chars.
_FILES_EVERY = 7
_FILES_PER_EVENT = 4
_FILE_PATHS = [
    "plugins/xp-agents/smm/sprint_store.py",
    "plugins/xp-agents/scripts/pre_tool_bash.py",
    "plugins/xp-agents/tests/hooks/test_session_start_core.py",
    "plugins/xp-agents/skills/xp-accept/scripts/preload.sh",
]

_TS = "2026-07-20T09:00:00+00:00"


def generate_events(total: int = 2000) -> list[dict]:
    """Event list matching the measured distribution, at a fixed SIZE.

    Round-robin by integer count rather than sampling. Not byte-identical
    across runs — `make_event` mints a random id — but every id is the same
    12 hex chars wide and every other field is fixed, so the measured length
    is stable and the 2%-wide budget band does not flake.
    `test_the_generator_is_deterministic` holds that.
    """
    events: list[dict] = []
    for event_type, share in _TYPE_MIX.items():
        length = _CONTENT_LEN[event_type]
        for i in range(int(total * share)):
            kwargs: dict = {"ts": _TS, "content": "x" * length}
            if event_type == "debt" or i % _FILES_EVERY == 0:
                kwargs["files"] = _FILE_PATHS[:_FILES_PER_EVENT]
            if event_type == "decision":
                kwargs["topic"] = f"topic-{i}"
            events.append(make_event(event_type, **kwargs))
    return events


def bootstrap_populated_smm(tmp: Path, *, total_events: int = 2000):
    """`_bootstrap_seeded_smm` plus realistic data. Returns (repo, smm).

    Layered on the shape bootstrap rather than replacing it, so the git repo,
    the env hygiene and `seed_smm.py`'s `shared_mental_model.json` all stay
    exactly as the shape family builds them and the only difference between the
    two fixtures is the data.
    """
    repo, smm = _bootstrap_seeded_smm(tmp)
    write_events(smm / "events.jsonl", generate_events(total_events))
    (smm / "sprint.json").write_text(json.dumps(_sprint_doc()))
    (smm / "shared_mental_model.json").write_text(json.dumps(_curated_pillars()))
    (smm / "system_context.json").write_text(json.dumps(_system_context_doc()))
    (smm / "execution_plan.json").write_text(json.dumps(_plan_doc()))
    return repo, smm


def _system_context_doc() -> dict:
    """System context at its schema SOFT caps — 20 conventions, 15 principles,
    10 modules, 10 project-specific entries, each field at its length cap.

    The caps are real: `system_context_schema` enforces them at write time, so
    this is the largest document the pillar can legally hold and therefore the
    honest worst case for anything that renders it.
    """
    return {
        "product": "p" * 400,
        "architecture_overview": "a" * 750,
        "stack": {"languages": ["python"], "test_command": "pytest"},
        "modules": [
            {"name": f"module-{i}", "purpose": "u" * 100, "path": "src/" + "d" * 60}
            for i in range(10)
        ],
        "conventions": ["c" * 150 for _ in range(20)],
        "principles": [
            {"topic": f"topic-{i}", "decision": "d" * 200, "rationale": "r" * 200}
            for i in range(15)
        ],
        "project_specific": [
            {"name": f"section-{i}", "content": "s" * 400} for i in range(10)
        ],
    }


def _plan_doc() -> dict:
    """An execution plan with one in-progress milestone."""
    return {
        "title": "t" * 60,
        "sources": [],
        "overview": "o" * 300,
        "milestones": [
            {
                "number": 1,
                "name": "n" * 60,
                "status": "in-progress",
                "delivered_sprint": None,
                "goal": "g" * 200,
                "done": "Given x, When y, Then z",
                "sources": "s" * 100,
                "design_details": "d" * 800,
                "constraints": ["c" * 150 for _ in range(4)],
                "change_zones": [{"path": p, "note": "n" * 100} for p in _FILE_PATHS],
                "impact_zones": [{"path": _FILE_PATHS[0], "note": "n" * 100}],
            }
        ],
    }


# Pillar counts and per-entry length from a real curated SMM: 1 intent, 20
# constraints, 5 risks, 10 wisdom. The `type` per pillar is not decorative —
# smm_schema pins a distinct enum for each (intent: goal/customer_intent,
# constraints: decision/convention, risks: concern/assumption/debt/question,
# wisdom: unconstrained), and load_smm raises on a mismatch.
_PILLAR_SIZES = {
    "intent": (1, 250, "goal"),
    "constraints": (20, 250, "convention"),
    "risks": (5, 330, "concern"),
    "wisdom": (10, 210, "convention"),
}


def _curated_pillars() -> dict:
    """The curated four pillars, populated.

    `seed_smm.py` already writes this file, so the shape bootstrap has a
    non-empty version of it — which is why `subagent_start` and `session_start`
    move on NEITHER events volume nor sprint state. Their cost is this file,
    and nothing else. Overwriting it is the only thing that drives the
    `_inject_full` subagent tier or the session-start SMM render loud.
    """
    pillars: dict[str, list[dict]] = {}
    next_id = 0
    for pillar, (count, length, entry_type) in _PILLAR_SIZES.items():
        entries = []
        for _ in range(count):
            # Ids are unique across ALL pillars, not per pillar — smm_schema
            # rejects a collision between e.g. constraints[3] and wisdom[3].
            entries.append(
                {
                    "id": f"{next_id:012x}",
                    "content": "c" * length,
                    "source": "seed",
                    "ts": _TS,
                    "type": entry_type,
                    # Risk severity is its own enum, NOT the event severities
                    # (high/medium/low) — debt/problem/uncertainty.
                    **({"severity": "problem"} if pillar == "risks" else {}),
                }
            )
            next_id += 1
        pillars[pillar] = entries
    return pillars


def _sprint_doc() -> dict:
    """A sprint with in-motion stories — what flips the accept/close preloads."""
    return {
        "sprint_id": "sprint-001",
        "goal": "g" * 80,
        "started": _TS,
        "milestone": "execution_plan.json §Milestone 1",
        "branch_name": "main",
        "stories": [
            {
                "id": f"story-{i:03d}",
                "title": "t" * 60,
                "status": status,
                "dependencies": [],
                "milestone_ref": "execution_plan.json §Milestone 1",
                "design_sources": "s" * 40,
                "context": "c" * 400,
                "file_domain": [p + " — owned" for p in _FILE_PATHS],
                "interface_contracts": ["i" * 150],
                "acceptance_criteria": ["Given x, When y, Then z"],
            }
            for i, status in enumerate(
                ["done", "done", "in-progress", "reviewing", "scheduled"], start=1
            )
        ],
    }


def measure_retro_input(smm_dir: Path, repo: Path) -> int:
    """Bytes of `.retro-input.json`, the file handed to xp-retrospective.

    Measured on DISK, not from stdout: `retrospective.py`'s stdout is a ~500
    char pointer and already carries an emitter budget, while the artifact that
    pointer names is the thing the subagent actually reads.
    """
    _, stderr, rc = _run_emitter("retrospective.py", _SCRIPTS_DIR, smm_dir, repo)
    if rc != 0:
        # Otherwise a crashed emitter writes no artifact, measures 0, and is
        # reported as "the fixture did not drive this" — the wrong diagnosis.
        raise RuntimeError(f"retrospective.py: rc={rc} stderr={stderr[:200]!r}")
    artifact = smm_dir / ".retro-input.json"
    return artifact.stat().st_size if artifact.exists() else 0


def measure_curation_input(smm_dir: Path, repo: Path) -> int:
    """Bytes of the housekeeper's curation payload.

    Serialized from `materialize.prepare_curation_data`, matching how
    `engine/test_curation_retro_bounds` measures it — that suite pins a
    duplication regression at 20 items and says so; this bounds the same
    payload at realistic volume, which nothing did.

    `repo` is unused — the signature is the one `ARTIFACT_MEASURERS` calls.
    """
    import materialize  # smm/ is on sys.path from this module's import

    return len(json.dumps(materialize.prepare_curation_data(smm_dir)).encode("utf-8"))


ARTIFACT_MEASURERS = {
    ".retro-input.json": measure_retro_input,
    ".curation-input.json": measure_curation_input,
}


def assert_artifacts_under_budgets(
    testcase, budgets: dict[str, int], label: str
) -> None:
    """Disk artifacts: bounded at volume, and proved to grow with data.

    These carry no shape budget — no family ever measured them — so the margin
    check compares the two bootstraps directly rather than against a pinned
    constant.
    """
    offenders: list[str] = []
    with tempfile.TemporaryDirectory() as tmp_s, tempfile.TemporaryDirectory() as tmp_v:
        shape_repo, shape_smm = _bootstrap_seeded_smm(Path(tmp_s))
        vol_repo, vol_smm = bootstrap_populated_smm(Path(tmp_v))
        for name, budget in sorted(budgets.items()):
            measurer = ARTIFACT_MEASURERS[name]
            shape = measurer(shape_smm, shape_repo)
            actual = measurer(vol_smm, vol_repo)
            if actual <= shape:
                offenders.append(
                    f"{name}: {actual} bytes at volume vs {shape} at shape — "
                    f"the fixture did not drive this artifact, so its budget "
                    f"bounds nothing"
                )
                continue
            offender = band_offender(name, actual, budget)
            if offender:
                offenders.append(offender)
    testcase.assertFalse(
        offenders, f"{label} volume measurement failed:\n" + "\n".join(offenders)
    )


def _preload_runner(name, smm_dir, repo):
    result = _run_preload(name, smm_dir, repo)
    # The close preloads arm a marker the NEXT close preload reads as an
    # abandoned cycle, recording a concern that a concern-rendering sibling
    # would then measure. Same class of leak as `_MARKER_WRITERS` below, but
    # ordering cannot fix this one — the readers are the writers.
    scrub_close_cycle_marker(smm_dir)
    return result


# Surfaces that leave state behind in the SMM they run against:
# `post_tool_exit_plan` writes a `.plan-awaiting-review` marker, and a later
# surface reads it — `session_end_warning` measures 0 chars alone and 81 after
# it. Every helper below shares one bootstrap across a whole set, so these go
# LAST and no sibling measures a marker it did not trigger. Same guard, same
# reason, as `_budget_helpers.assert_emitter_under_budgets`'s subagent_stop
# ordering; an unlisted marker-writer makes measurements order-dependent.
#
# `preload_injection` writes through whatever preload its fixture names, so it
# inherits that preload's side effects: the loud fixture's `xp-work-selection`
# arms NEEDS_HOUSEKEEPING and HOUSEKEEPING_ARMED. It sorts before every
# `s`-named sibling by default, so it is listed here rather than left to be
# discovered by the first sibling that starts reading those markers.
_MARKER_WRITERS = frozenset({"post_tool_exit_plan.py", "preload_injection.py"})


def _measurement_order(names) -> list[str]:
    return sorted(names, key=lambda name: (name in _MARKER_WRITERS, name))


def measure_surfaces(names, *, bootstrap, runner) -> dict[str, int]:
    """{surface: measured chars} for a whole set, against one bootstrap.

    Fails loud on a non-zero exit: a crashed surface measures 0, and 0 read as
    a measurement is exactly the vacuous-green shape this family exists to
    prevent.
    """
    measured: dict[str, int] = {}
    with tempfile.TemporaryDirectory() as tmp:
        repo, smm_dir = bootstrap(Path(tmp))
        for name in _measurement_order(names):
            stdout_bytes, stderr, rc = runner(name, smm_dir, repo)
            if rc != 0:
                raise RuntimeError(
                    f"{name}: subprocess rc={rc} stderr={stderr[:200]!r}"
                )
            measured[name] = _measured_len(
                stdout_bytes,
                normalize_paths=(str(_PLUGIN_ROOT), str(smm_dir), str(repo)),
            )
    return measured


def emitter_runner(loud_fixtures: dict):
    """Runner that drives each emitter at its LOUD input."""

    def run(name, smm_dir, repo):
        return _run_emitter(
            name, _SCRIPTS_DIR, smm_dir, repo, fixtures={name: loud_fixtures[name]}
        )

    return run


def assert_volume_under_budgets(
    testcase,
    budgets: dict[str, int],
    shape_budgets: dict[str, int],
    label: str,
    *,
    bootstrap=bootstrap_populated_smm,
    runner=_preload_runner,
) -> None:
    """Every surface stays clear of its volume band AND out-measures shape.

    The second half is the load-bearing one. Each volume budget is derived from
    this fixture's own measurement, so a fixture that fails to drive a surface
    loud yields a small measurement, a small derived budget, and an entry that
    is green forever — indistinguishable from a correct one. Requiring the
    volume measurement to exceed that surface's SHAPE budget (a constant the
    other family already pins) catches that, with no second bootstrap.

    It does NOT catch it for an emitter whose loud INPUT alone clears the shape
    budget — the margin is already satisfied before the SMM is read, so data
    contributing nothing still passes. `session_start` measures 10,372 of its
    17,854 that way. `test_every_emitter_volume_entry_moves_with_data` is the
    guard for that half; this one cannot be.

    `bootstrap` is injectable so the mutation is a permanent test rather than a
    manual procedure: point it at `_bootstrap_seeded_smm` and every surface
    must fall back under its shape budget.
    """
    offenders: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        repo, smm_dir = bootstrap(Path(tmp))
        for name in _measurement_order(budgets):
            budget = budgets[name]
            stdout_bytes, stderr, rc = runner(name, smm_dir, repo)
            if rc != 0:
                offenders.append(f"{name}: subprocess rc={rc} stderr={stderr[:200]!r}")
                continue
            actual = _measured_len(
                stdout_bytes,
                normalize_paths=(str(_PLUGIN_ROOT), str(smm_dir), str(repo)),
            )
            shape = shape_budgets[name]
            if actual <= shape:
                offenders.append(
                    f"{name}: {actual} chars at volume does not exceed its shape "
                    f"budget of {shape} — the fixture did not drive this surface "
                    f"loud, so its volume budget bounds nothing"
                )
                continue
            offender = band_offender(name, actual, budget)
            if offender:
                offenders.append(offender)
    testcase.assertFalse(
        offenders,
        f"{label} volume measurement failed:\n" + "\n".join(offenders),
    )

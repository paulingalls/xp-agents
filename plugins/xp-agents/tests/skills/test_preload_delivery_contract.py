#!/usr/bin/env python3
"""Every preload still delivers the state markers its skill reads.

This suite pins preload delivery BY CONTENT. The milestone's original
protection for the working harness was a byte-identical pin on the delivery
mechanism — worthless the moment the mechanism is deliberately replaced, which
is what the milestone does. This is the replacement protection, and it ships
before the mechanism change so a regression meets a test that predates it.

**It makes no assertion about how the content arrives.** Swap the delivery
path while preserving content and this stays green; that is the contract, and
`TestNoMechanismAssertions` below is the gate that keeps it true.

**The expectation is recorded, not derived.** `_preload_delivery_fixtures.
PRELOAD_DELIVERY_MARKERS` is a hand-seeded table; see that module for how each
entry was seeded and what was deliberately left out. Deriving it from current
output would make the pin regenerate its own oracle.

**Matching is never substring containment.** `_preload_base.sh` emits
`## XP Values` on success and `## XP Values: not found` on failure, so the
failure string CONTAINS the success string and `assertIn` passes on exactly
the branch worth catching. Each marker carries one of three rules instead —
see `Rule`.

**The harness is pinned too, because presence varies as well as value.** The
close preloads emit `### HOOK_GUIDANCE` only when the project's pre-commit
hook is absent, resolved per-cwd-repo. Those four entries are green in a fresh
temp repo and red in a checkout after `make setup`. So every run bootstraps
its own `(repo, smm_dir)` via `_bootstrap_seeded_smm`, every recorded marker
is unconditional under THAT harness, and `collect_preload_outputs` asserts the
harness assumption up front — a machine whose global git config installs hooks
into every `git init` fails once, with a diagnostic, instead of four times
with none.

Known limits, recorded rather than fixed:

- `PRELOAD_FIXTURES` drives each preload's REPRESENTATIVE branch only, so this
  pin is per-branch, not per-skill-exhaustive. A marker only reachable on
  another branch is not covered here.
- `_budget_helpers._preload_script_name` is a third skill-to-script resolution
  site alongside `skill_preload_map` and `test_preload_wiring`'s glob — this
  suite consumes it and so extends concern f81a974e98e8. Out of scope.
- A sibling story changes the four close skills' preloads. When it lands their
  recorded markers change and going red here is CORRECT, not a regression:
  re-seed the table from the new output, do not loosen the rules.
- No heartbeat machinery. `_env_hygiene` pins `XP_SKIP_LIVENESS_CHECK=1` at
  import and `_run_preload` copies `os.environ`, so no preload driven by this
  runner can refuse; `test_preload_liveness.py` owns that behaviour. The one
  `REFUSAL_HEADER` tripwire below exists to catch that pin coming undone.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from _budget_helpers import scrub_close_cycle_marker
from _preload_delivery_fixtures import (
    MARKERLESS_BY_DESIGN,
    MECHANISM_TERMS,
    PRELOAD_DELIVERY_MARKERS,
    Marker,
    Rule,
)
from _preload_fixtures import REFUSAL_HEADER
from conftest import (
    _bootstrap_seeded_smm,
    _run_preload,
    discover_preload_scripts,
)

_SUITE_PATH = Path(__file__)
_TABLE_PATH = _SUITE_PATH.parent.parent / "_preload_delivery_fixtures.py"

_HARNESS_BROKEN = (
    "pinned harness broken: git will fire a hook in the fresh temp repo at "
    "{repo}. `resolved_hooks_dir` honours a GLOBAL core.hooksPath, and a "
    "global init.templateDir can populate a fresh `git init` — either flips "
    "the close preloads off their recorded branch. Fix the machine's global "
    "git config; do not re-seed the table against it."
)


def match_marker(marker: Marker, lines: list[str]) -> bool:
    """Does any stripped output line satisfy this marker under its own rule?"""
    match marker.rule:
        case Rule.EXACT_LINE:
            return any(line == marker.text for line in lines)
        case Rule.VALUE_NONEMPTY:
            prefix = f"{marker.text}="
            return any(
                line.startswith(prefix) and line[len(prefix) :].strip()
                for line in lines
            )
        case Rule.KEY_PRESENT:
            return any(line.startswith(f"{marker.text}=") for line in lines)
    raise ValueError(f"unknown match rule: {marker.rule!r}")


def delivery_failures(outputs: dict[str, str]) -> list[str]:
    """One offender line per recorded marker absent from its skill's output.

    Names the skill AND the marker (AC3) — "a preload lost a marker" is not
    actionable without both.
    """
    failures: list[str] = []
    for skill, markers in PRELOAD_DELIVERY_MARKERS.items():
        if skill not in outputs:
            continue
        lines = [line.strip() for line in outputs[skill].splitlines()]
        for marker in markers:
            if not match_marker(marker, lines):
                failures.append(
                    f"{skill}: delivered output is missing the "
                    f"{marker.rule.value} marker {marker.text!r}"
                )
    return failures


def empty_marker_sets() -> list[str]:
    """Table entries recording no marker at all — vacuous unless declared."""
    return sorted(
        skill
        for skill, markers in PRELOAD_DELIVERY_MARKERS.items()
        if not markers and skill not in MARKERLESS_BY_DESIGN
    )


def mechanism_references(text: str) -> list[str]:
    """Delivery-mechanism terms found in `text`, each with why it is a term."""
    lowered = text.lower()
    return [
        f"{term!r} ({why})" for term, why in MECHANISM_TERMS if term.lower() in lowered
    ]


def collect_preload_outputs(skills: tuple[str, ...] | None = None) -> dict[str, str]:
    """Run preloads under the pinned harness; return {skill: stdout text}.

    Raises AssertionError (not a test-case assertion — this is also called
    from the vacuity proofs) when the harness assumption or a preload's exit
    status is wrong, so those fail once with a diagnostic.
    """
    # Function-local, like `scrub_close_cycle_marker`'s own `import markers`:
    # `git_hooks` lives under smm/ and only conftest puts that on sys.path, so
    # a module-scope import here resolves under pytest (which loads conftest
    # first) and NOT under the documented `unittest discover` fallback.
    import git_hooks

    names = tuple(PRELOAD_DELIVERY_MARKERS) if skills is None else skills
    outputs: dict[str, str] = {}
    with tempfile.TemporaryDirectory() as tmp:
        repo, smm_dir = _bootstrap_seeded_smm(Path(tmp))
        if git_hooks.will_fire_hook(str(repo)):
            raise AssertionError(_HARNESS_BROKEN.format(repo=repo))
        for name in names:
            stdout, stderr, rc = _run_preload(name, smm_dir, repo)
            # Four close preloads arm a close cycle merely by running; a
            # survivor makes the next one record an abandoned-cycle concern,
            # and an orphaned cycle leaves a Stop gate demanding a full close.
            scrub_close_cycle_marker(smm_dir)
            if rc != 0:
                raise AssertionError(f"{name}: preload rc={rc} stderr={stderr[:300]!r}")
            outputs[name] = stdout.decode("utf-8", errors="replace")
    return outputs


class TestTableCoverage(unittest.TestCase):
    """The three cheap vacuity doors: entry, content, and the reason for KEY_PRESENT."""

    def test_every_preload_bearing_skill_has_a_table_entry(self):
        """Superset guard, mirroring the budget suite's: a new preload must not
        ship un-pinned, and a stale entry must not linger as dead weight."""
        on_disk = set(discover_preload_scripts())
        recorded = set(PRELOAD_DELIVERY_MARKERS)
        self.assertFalse(
            on_disk - recorded,
            "preload-bearing skills with no delivery-table entry: "
            f"{sorted(on_disk - recorded)}",
        )
        self.assertFalse(
            recorded - on_disk,
            f"table entries with no preload on disk: {sorted(recorded - on_disk)}",
        )

    def test_no_entry_records_an_empty_marker_set(self):
        """An entry that records nothing passes for any output whatsoever."""
        self.assertFalse(
            empty_marker_sets(),
            "delivery-table entries recording no marker (a vacuous entry — "
            "seed it, or declare it in MARKERLESS_BY_DESIGN with a reason): "
            f"{empty_marker_sets()}",
        )

    def test_every_key_present_marker_carries_a_reason(self):
        """KEY_PRESENT is the vacuity door in miniature — it tolerates the empty
        value that a silently-lost value also produces. Every use argues for
        itself in writing, or it is not allowed."""
        unreasoned = sorted(
            f"{skill}:{marker.text}"
            for skill, markers in PRELOAD_DELIVERY_MARKERS.items()
            for marker in markers
            if marker.rule is Rule.KEY_PRESENT and not marker.why.strip()
        )
        self.assertFalse(
            unreasoned,
            f"KEY_PRESENT markers with no recorded reason: {unreasoned}",
        )

    def test_no_recorded_marker_names_a_delivery_mechanism(self):
        """AC2 reaches the table too: a marker text naming a mechanism would
        smuggle a mechanism assertion past the scan of the suite file."""
        offenders = sorted(
            f"{skill}:{marker.text} -> {hit}"
            for skill, markers in PRELOAD_DELIVERY_MARKERS.items()
            for marker in markers
            for hit in mechanism_references(marker.text)
        )
        self.assertFalse(offenders, f"marker texts naming a mechanism: {offenders}")


class TestDeliveredMarkers(unittest.TestCase):
    """AC1: run every preload once under the pinned harness, then match."""

    outputs: dict[str, str]

    @classmethod
    def setUpClass(cls):
        cls.outputs = collect_preload_outputs()

    def test_every_recorded_marker_is_delivered(self):
        failures = delivery_failures(self.outputs)
        self.assertFalse(
            failures,
            "recorded state markers missing from delivered preload output:\n"
            + "\n".join(failures),
        )

    def test_no_output_is_a_liveness_refusal(self):
        """Tripwire only. A refusal here means `_env_hygiene`'s skip pin came
        undone and every marker above was matched against a banner."""
        refusing = sorted(s for s, out in self.outputs.items() if REFUSAL_HEADER in out)
        self.assertFalse(
            refusing, f"preloads that refused instead of running: {refusing}"
        )


class TestNoMechanismAssertions(unittest.TestCase):
    """AC2: this file asserts content, never the path the content took."""

    def test_suite_names_no_delivery_mechanism(self):
        hits = mechanism_references(_SUITE_PATH.read_text(encoding="utf-8"))
        self.assertFalse(
            hits,
            "this suite names a delivery mechanism, so swapping the mechanism "
            f"could turn it red on content it still receives: {hits}",
        )

    def test_the_scan_would_be_red_on_the_module_holding_the_terms(self):
        """The scan above is worth nothing if the terms cannot match anything.
        The term list lives in a sibling module precisely because a list inside
        the scanned file is red by construction — so scanning THAT module is
        the demonstration that the separation is load-bearing, and that the
        terms are live strings rather than decoration."""
        hits = mechanism_references(_TABLE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            len(hits),
            len(MECHANISM_TERMS),
            "every term should match the module that spells it; the scan of "
            f"the suite is only meaningful because they do. Matched: {hits}",
        )


class TestThePinIsNotVacuous(unittest.TestCase):
    """Demonstrations, not TDD-red: against a correct pin each passes first run.

    Each was proved by TEMPORARILY loosening the pin — `EXACT_LINE` swapped for
    containment, a marker set emptied — watching the case go red, and
    reverting. They live here permanently so the loosening cannot come back
    unnoticed.

    They assert on the failure MESSAGE, never on an exception type: the guards
    are pure functions returning offender lists, so a pin that silently stopped
    resolving anything shows up as an empty list rather than passing under an
    `assertRaises(AssertionError)` that the suite's own asserts would satisfy.
    """

    def test_suppressing_one_skills_delivery_names_that_skill(self):
        """AC4, and the only case here that proves the pin watches DELIVERY.
        Emptying a marker set and loosening a rule both mutate the pin; this
        mutates what the preload hands back."""
        target = "xp-schedule"
        expected = PRELOAD_DELIVERY_MARKERS[target]
        with patch.object(
            sys.modules[__name__], "_run_preload", return_value=(b"", "", 0)
        ):
            outputs = collect_preload_outputs(skills=(target,))
        self.assertEqual(outputs, {target: ""})

        failures = delivery_failures(outputs)
        self.assertEqual(
            len(failures),
            len(expected),
            f"suppressed delivery should fail every recorded marker: {failures}",
        )
        joined = "\n".join(failures)
        self.assertIn(target, joined)
        for marker in expected:
            self.assertIn(repr(marker.text), joined)

    def test_the_match_rules_reject_what_containment_would_wave_through(self):
        """`## XP Values: not found` is `_preload_base.sh`'s FAILURE branch and
        it contains its own success string, so `assertIn` passes on it. Same
        shape one level down: a `KEY=` line survives with its value gone.

        This case pins the MATCH RULE, not delivery. Pointing PLUGIN_ROOT at a
        tree with no XP_VALUES.md is a no-op — `_preload_base.sh` derives that
        path from BASH_SOURCE and ignores the environment — so no preload run
        can produce the degraded line here, and building a copied-tree harness
        to force one would test the copy.
        """
        heading = Marker("## XP Values", Rule.EXACT_LINE)
        degraded = "## XP Values: not found"
        self.assertIn(heading.text, degraded)  # what containment would accept
        self.assertFalse(match_marker(heading, [degraded]))
        self.assertTrue(match_marker(heading, [heading.text]))

        value = Marker("FRONTIER_COUNT", Rule.VALUE_NONEMPTY)
        tolerated = Marker("FRONTIER_COUNT", Rule.KEY_PRESENT, why="proof")
        self.assertFalse(match_marker(value, ["FRONTIER_COUNT="]))
        self.assertTrue(match_marker(value, ["FRONTIER_COUNT=0"]))
        self.assertTrue(match_marker(tolerated, ["FRONTIER_COUNT="]))

    def test_emptying_a_marker_set_trips_the_content_guard(self):
        """An entry recording nothing matches any output, including none."""
        self.assertEqual(empty_marker_sets(), [])
        with patch.dict(PRELOAD_DELIVERY_MARKERS, {"xp-plan": ()}):
            self.assertEqual(empty_marker_sets(), ["xp-plan"])
        self.assertEqual(empty_marker_sets(), [])


if __name__ == "__main__":
    unittest.main()

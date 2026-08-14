#!/usr/bin/env python3
"""Does `lefthook.yml` actually strip what `_env_hygiene.py` says it must?

CLAUDE.md names `tests/_env_hygiene.py` the single registry of leaky env vars and
says lefthook must mirror its strip list. Nothing checked that, and it was false:
lefthook omitted `SMM_DIR`, `XP_AGENTS_DATA`, `XP_FILE_DOMAIN_DRIFT_TOLERANCE`,
`XP_LOCK_TIMEOUT_SECONDS` and `XP_SMM_MIGRATE` — five of eleven — while the doc
asserted an invariant. A documented invariant with no test is a claim.

THE RULE IS NOT SET EQUALITY, and getting that wrong is the trap here. lefthook
also strips two vars the registry deliberately does not, so the containment runs
one way: every registry-stripped var must appear in every `env -u` run, and
anything extra lefthook strips must be declared below with a reason. Demanding
equality would force `XP_SESSION_ID` into the registry, where it must NOT be —
`_env_hygiene` PINS that one to a fixed value instead, and stripping a var it
pins would fight itself.

THE SCAN IS THE POINT. This DISCOVERS every `env -u` occurrence by reading
lefthook.yml, rather than naming the three runs that exist today. Enumerating
locations is precisely the failure being fixed: a fourth run added later would be
unmirrored and unnoticed, which is how the first three drifted. It reproduces the
gap it closes. (The same reasoning rebuilt the per-file prose ratchet around a
tree walk instead of a named set.)

No YAML parser ships here, so it is a text scan — but over `_uncommented` text,
borrowed with the block helpers from `test_lefthook_perf_gate`. A commented-out
`env -u` line would otherwise satisfy the pin while stripping nothing, and reusing
those helpers is what stops a change to the parser making one file's pins
silently vacuous while the other's still bite.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _env_hygiene import PINNED_SESSION_ID_VAR, STRIPPED_VARS
from test_lefthook_perf_gate import LEFTHOOK, _uncommented

# Vars lefthook strips that the registry does not, each with the reason it is not
# a registry entry. An undeclared extra fails the test rather than being tolerated:
# the point is that every asymmetry is a decision somebody wrote down.
_LEFTHOOK_ONLY_STRIPS = {
    # The registry PINS this to a fixed test session id rather than stripping it,
    # so it cannot appear there. lefthook strips it so the pin is what every
    # pytest process sees, not a dev shell's value.
    PINNED_SESSION_ID_VAR: "pinned by the registry, not stripped",
    # Arms the wall-clock perf tier. Not a correctness leak — a leaked XP_PERF
    # makes benchmarks run where they were not asked for, and they fail on timing
    # noise. Stripped at the gate; irrelevant in-process.
    "XP_PERF": "arms the perf tier; a gate concern, not an import-time one",
}


def _env_u_runs() -> list[str]:
    """Every uncommented line in lefthook.yml that invokes `env -u`.

    A LIST, deliberately not a set: two runs stripping identical var sets are
    still two runs to check, and de-duplicating them would let one silently stop
    being verified.
    """
    return [
        line
        for line in _uncommented(LEFTHOOK.read_text(encoding="utf-8")).splitlines()
        if "env -u" in line
    ]


def _stripped_in(run: str) -> set[str]:
    """The var names this run passes to `env -u`.

    Reads the `-u <NAME>` pairs rather than splitting on whitespace and guessing:
    the same line also carries `XP_PERF=1` assignments and the pytest invocation,
    and neither is a strip.
    """
    tokens = run.split()
    return {
        tokens[i + 1]
        for i, tok in enumerate(tokens)
        if tok == "-u" and i + 1 < len(tokens)
    }


class TestTheScanFindsSomethingToCheck(unittest.TestCase):
    """A vacuity guard. Every assertion below is over the scan's output, so a
    scan that silently found nothing would make the whole file pass while
    checking nothing — the exact shape of a test that cannot fail."""

    def test_lefthook_declares_env_stripped_runs(self):
        self.assertGreaterEqual(
            len(_env_u_runs()), 3, "the scan found no `env -u` runs to verify"
        )

    def test_the_registry_is_not_empty(self):
        self.assertGreaterEqual(len(STRIPPED_VARS), 5)


class TestEveryRunMirrorsTheRegistry(unittest.TestCase):
    def test_no_run_omits_a_registry_var(self):
        missing = {
            run.strip()[:60]: sorted(set(STRIPPED_VARS) - _stripped_in(run))
            for run in _env_u_runs()
            if set(STRIPPED_VARS) - _stripped_in(run)
        }
        self.assertEqual(
            missing,
            {},
            "these `env -u` runs do not strip every var _env_hygiene.py strips: "
            f"{missing}",
        )

    def test_every_extra_strip_is_declared_with_a_reason(self):
        undeclared = {
            run.strip()[:60]: sorted(
                _stripped_in(run) - set(STRIPPED_VARS) - set(_LEFTHOOK_ONLY_STRIPS)
            )
            for run in _env_u_runs()
            if _stripped_in(run) - set(STRIPPED_VARS) - set(_LEFTHOOK_ONLY_STRIPS)
        }
        self.assertEqual(
            undeclared,
            {},
            "lefthook strips vars that are neither in the registry nor declared "
            f"in _LEFTHOOK_ONLY_STRIPS with a reason: {undeclared}",
        )

    def test_a_declared_extra_is_not_silently_also_a_registry_var(self):
        """`_LEFTHOOK_ONLY_STRIPS` records asymmetries. An entry that IS in the
        registry is a stale note, and a stale note is what this file exists to
        stop — it would excuse a real omission somewhere else."""
        overlap = sorted(set(_LEFTHOOK_ONLY_STRIPS) & set(STRIPPED_VARS))
        self.assertEqual(
            overlap, [], f"declared as lefthook-only but in the registry: {overlap}"
        )


class TestThePinnedVarIsNotStrippedInProcess(unittest.TestCase):
    def test_the_registry_pins_rather_than_strips_the_session_id(self):
        """The reason the rule is containment and not equality, asserted rather
        than only explained above."""
        self.assertNotIn(PINNED_SESSION_ID_VAR, STRIPPED_VARS)


if __name__ == "__main__":
    unittest.main()

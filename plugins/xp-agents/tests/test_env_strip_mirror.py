#!/usr/bin/env python3
"""Does `lefthook.yml` actually strip what `_env_hygiene.py` says it must?

CLAUDE.md names `tests/_env_hygiene.py` the single registry of leaky env vars and
says lefthook must mirror its strip list. Nothing checked that, and it was false:
lefthook omitted `SMM_DIR`, `XP_AGENTS_DATA`, `XP_FILE_DOMAIN_DRIFT_TOLERANCE`,
`XP_LOCK_TIMEOUT_SECONDS` and `XP_SMM_MIGRATE` — five of twelve — while the doc
asserted an invariant. A documented invariant with no test is a claim.

THE RULE IS NOT SET EQUALITY, and getting that wrong is the trap here. lefthook
also strips a var the registry deliberately does not, so the containment runs
one way: every registry-stripped var must appear in every `env -u` run, and
anything extra lefthook strips must be declared below with a reason. Demanding
equality would force `XP_SESSION_ID` into the registry, where it must NOT be —
`_env_hygiene` PINS that one to a fixed value instead, and stripping a var it
pins would fight itself.

THE SCAN IS THE POINT. This DISCOVERS every pytest run by reading
lefthook.yml, rather than naming the runs that exist today. Enumerating
locations is precisely the failure being fixed: a run added later would be
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
    # The capstone's live rows put a REAL model in the loop on two harnesses.
    # The registry cannot strip these two: it strips at IMPORT time, which would
    # make a deliberate live run impossible to perform at all. Stripping them
    # here instead is what makes "the commit and push gates never pay for a
    # model call" an assertion rather than a hope — the gates run this suite on
    # every commit and every push.
    "XP_CAPSTONE_LIVE": "would bill a model call on every commit and push",
    # Worse than billing: this is the spawn guard's own escape hatch. Inherited
    # into a gate run it would disarm the backstop that exists because ~20 real
    # recursive agents once escaped, one alive 22 minutes.
    "XP_ALLOW_REAL_AGENT_SPAWN": "inheriting it disarms the spawn backstop",
}


def _pytest_runs() -> list[str]:
    """Every uncommented lefthook line that invokes pytest.

    DISCOVERED ON `pytest`, NOT ON `env -u`, and that distinction is the whole
    value of the scan. Filtering on `env -u` — the first version of this — could
    only ever find runs that already comply, so the drift it claimed to catch (a
    new job added WITHOUT the prefix) was exactly the case it could not see. A
    population defined by the property under test is not a test.

    A LIST, deliberately not a set: two runs stripping identical var sets are
    still two runs to check, and de-duplicating them would let one silently stop
    being verified.
    """
    return [
        line
        for line in _uncommented(LEFTHOOK.read_text(encoding="utf-8")).splitlines()
        if "pytest" in line
    ]


def _stripped_in(run: str) -> set[str]:
    """The var names this run passes to `env -u`.

    Reads the `-u <NAME>` pairs rather than splitting on whitespace and guessing:
    a run line can also carry bare `NAME=value` assignments and the pytest
    invocation itself, and neither is a strip.
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

    def test_lefthook_declares_pytest_runs(self):
        self.assertGreaterEqual(
            len(_pytest_runs()), 2, "the scan found no pytest runs to verify"
        )

    def test_the_registry_is_not_empty(self):
        self.assertGreaterEqual(len(STRIPPED_VARS), 5)

    def test_the_registry_size_matches_what_the_prose_claims(self):
        """This file's docstring and the release notes both say "five of twelve".
        The twelve was wrong once — written as eleven, because the two session-id
        vars come in via a splat and are easy to miscount by hand — so the number
        is asserted rather than trusted. A count in prose with nothing checking it
        is the same species of claim this whole file exists to stop."""
        self.assertEqual(
            len(STRIPPED_VARS),
            12,
            "the registry size changed; update the counts in this file's docstring "
            "and in the CHANGELOG entry that quotes them",
        )


class TestEveryRunMirrorsTheRegistry(unittest.TestCase):
    def test_no_run_omits_a_registry_var(self):
        """Every pytest run, whether or not it strips anything today. A run with
        no `env -u` at all reports the whole registry as missing, which is the
        drift the previous discovery predicate could not see."""
        missing = {
            run.strip()[:60]: sorted(set(STRIPPED_VARS) - _stripped_in(run))
            for run in _pytest_runs()
            if set(STRIPPED_VARS) - _stripped_in(run)
        }
        self.assertEqual(
            missing,
            {},
            "these pytest runs do not strip every var _env_hygiene.py strips: "
            f"{missing}",
        )

    def test_every_extra_strip_is_declared_with_a_reason(self):
        undeclared = {
            run.strip()[:60]: sorted(
                _stripped_in(run) - set(STRIPPED_VARS) - set(_LEFTHOOK_ONLY_STRIPS)
            )
            for run in _pytest_runs()
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

    def test_a_declared_extra_is_still_stripped_somewhere(self):
        """The other direction of the same staleness rule, and the one that was
        missing: an entry lefthook has STOPPED stripping is a note describing
        machinery that no longer exists, and it goes on excusing whatever else
        lands under that name. Retiring `XP_PERF` proved the gap — the entry had
        to be removed by hand, with nothing going red if it had been left.

        At least one run, not every run: a strip that only one job needs is a
        legitimate asymmetry; a strip no job performs is a dead note.
        """
        stripped_anywhere: set[str] = set()
        for run in _pytest_runs():
            stripped_anywhere |= _stripped_in(run)
        orphaned = sorted(set(_LEFTHOOK_ONLY_STRIPS) - stripped_anywhere)
        self.assertEqual(
            orphaned,
            [],
            "declared in _LEFTHOOK_ONLY_STRIPS but no lefthook pytest run strips "
            f"them any more: {orphaned}. Delete the entry with the machinery.",
        )


class TestThePinnedVarIsNotStrippedInProcess(unittest.TestCase):
    def test_the_registry_pins_rather_than_strips_the_session_id(self):
        """The reason the rule is containment and not equality, asserted rather
        than only explained above."""
        self.assertNotIn(PINNED_SESSION_ID_VAR, STRIPPED_VARS)


if __name__ == "__main__":
    unittest.main()

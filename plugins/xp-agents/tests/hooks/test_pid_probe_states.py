#!/usr/bin/env python3
"""One pid probe in the tree, and both call sites' verdicts unchanged.

`in_place_marker._probe_pid` and `migration_lock.holder_state` each carried
their own `os.kill(pid, 0)` liveness probe. Deduplicating them is NOT a
mechanical copy-paste removal, because the two are not semantically identical:

    condition                _probe_pid            holder_state
    os.kill succeeds         True                  True
    ProcessLookupError       False (proven dead)   False
    OverflowError            None                  None
    OSError (EPERM)          None (unadjudicable)  True  (exists, reads as held)
    pid <= 0 / non-digit     None                  None

Both EPERM mappings are deliberate. A shared TRI-state probe cannot serve both:
it would collapse EPERM and OverflowError onto one `None`, and `holder_state`
could then no longer read EPERM as *held* — silently changing `lock_state`
inside a lock.

So the shared probe reports the CONDITION, not a verdict — four states — and
each call site maps it to its own answer. These tests pin the mapping at both
sites for all five conditions, which is the only thing that makes the dedup
provably behaviour-preserving.

`pid <= 0` maps to `unknown`, never `dead`. Mapping it to `dead` would flip
`in_place_marker` into deleting a marker it cannot prove dead — the exact
failure the original tri-state guarded against.
"""

import ast
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
import in_place_marker
import migration_lock
from _pin_helpers import scan_root, shipped_files_to_scan
from conftest import _PLUGIN_ROOT, dead_pid, live_pid

# The pid every probe rejects before it ever reaches os.kill: too big for a C
# int, so os.kill raises OverflowError rather than answering.
_OVERFLOW_PID = 10**30


def _os_kill_calls(tree: ast.AST) -> list[int]:
    """Line numbers of real `os.kill(...)` CALLS in *tree*.

    AST, not a substring search: `os.kill` is named in prose all over both
    modules' docstrings (explaining why pid 0 is not death), and a text scan
    reads those as second probes.
    """
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "kill"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "os"
    ]


class TestExactlyOneProbeInTheTree(unittest.TestCase):
    """AC#3: one probe, reached by both former call sites.

    Proven structurally rather than by behaviour, because two identical copies
    behave identically — that is what made the duplication survive this long.
    """

    def test_only_one_shipped_module_calls_os_kill(self) -> None:
        paths = shipped_files_to_scan(_PLUGIN_ROOT)
        self.assertGreater(len(paths), 50, "the shipped scan went vacuous")
        callers, parse_failures = scan_root(paths, _os_kill_calls)
        self.assertEqual(parse_failures, [], "a shipped module failed to parse")
        self.assertEqual(
            sorted(p.name for p in callers),
            ["migration_lock.py"],
            "a second os.kill liveness probe appeared in the shipped tree",
        )

    def test_the_one_caller_probes_exactly_once(self) -> None:
        """Two call sites inside the home module would be the duplication back."""
        source = Path(migration_lock.__file__).read_text(encoding="utf-8")
        self.assertEqual(len(_os_kill_calls(ast.parse(source))), 1)

    def test_in_place_marker_reaches_the_shared_probe_by_identity(self) -> None:
        self.assertIs(
            in_place_marker.probe_pid_condition,
            migration_lock.probe_pid_condition,
            "in_place_marker must import the shared probe, not copy it",
        )


class TestConditionsStayDistinct(unittest.TestCase):
    """The four states, because a tri-state cannot carry both EPERM verdicts.

    `exists_not_ours` and `unknown` must stay separable: they are the one pair
    the two call sites answer DIFFERENTLY.
    """

    def test_a_live_pid_reads_alive(self) -> None:
        with live_pid() as pid:
            self.assertEqual(migration_lock.probe_pid_condition(pid), "alive")

    def test_a_reaped_pid_reads_dead(self) -> None:
        self.assertEqual(migration_lock.probe_pid_condition(dead_pid()), "dead")

    def test_eperm_reads_exists_not_ours(self) -> None:
        with mock.patch.object(os, "kill", side_effect=PermissionError):
            self.assertEqual(
                migration_lock.probe_pid_condition(4242), "exists_not_ours"
            )

    def test_an_overflowing_pid_reads_unknown(self) -> None:
        self.assertEqual(migration_lock.probe_pid_condition(_OVERFLOW_PID), "unknown")

    def test_a_nonpositive_pid_reads_unknown_not_dead(self) -> None:
        for pid in (0, -1, -4242):
            with self.subTest(pid=pid):
                self.assertEqual(
                    migration_lock.probe_pid_condition(pid),
                    "unknown",
                    "os.kill(0, 0) signals our OWN process group and a negative"
                    " pid targets a group — neither is proof of death",
                )

    def test_the_two_eperm_conditions_are_not_the_same_state(self) -> None:
        with mock.patch.object(os, "kill", side_effect=PermissionError):
            eperm = migration_lock.probe_pid_condition(4242)
        self.assertNotEqual(
            eperm,
            migration_lock.probe_pid_condition(_OVERFLOW_PID),
            "collapsing these two is what breaks holder_state's EPERM verdict",
        )


class TestInPlaceMarkerVerdictIsUnchanged(unittest.TestCase):
    """`_probe_pid`: True = alive, False = PROVEN dead, None = unadjudicable.

    Only `False` lets a marker be reaped, so every state that is not proof of
    death must stay out of it.
    """

    def test_a_live_pid_is_alive(self) -> None:
        with live_pid() as pid:
            self.assertIs(in_place_marker._probe_pid(pid), True)

    def test_a_reaped_pid_is_proven_dead(self) -> None:
        self.assertIs(in_place_marker._probe_pid(dead_pid()), False)

    def test_eperm_is_unadjudicable_not_alive(self) -> None:
        with mock.patch.object(os, "kill", side_effect=PermissionError):
            self.assertIsNone(
                in_place_marker._probe_pid(4242),
                "another uid's process is not our teammate, which runs as us",
            )

    def test_an_overflowing_pid_is_unadjudicable(self) -> None:
        self.assertIsNone(in_place_marker._probe_pid(_OVERFLOW_PID))

    def test_a_nonpositive_pid_is_unadjudicable_not_dead(self) -> None:
        for pid in (0, -1):
            with self.subTest(pid=pid):
                self.assertIsNone(
                    in_place_marker._probe_pid(pid),
                    "reading this as dead would reap a live teammate's marker",
                )


class TestMigrationLockVerdictIsUnchanged(unittest.TestCase):
    """`holder_state`: True = held, False = stalled, None = unprobeable.

    EPERM reads TRUE here — the opposite of the other call site. A process
    owned by another uid still EXISTS, and a lock whose holder exists is held.
    """

    def test_a_live_pid_is_held(self) -> None:
        with live_pid() as pid:
            self.assertIs(migration_lock.holder_state(str(pid)), True)

    def test_a_reaped_pid_is_stalled(self) -> None:
        self.assertIs(migration_lock.holder_state(str(dead_pid())), False)

    def test_eperm_still_reads_as_held(self) -> None:
        with mock.patch.object(os, "kill", side_effect=PermissionError):
            self.assertIs(
                migration_lock.holder_state("4242"),
                True,
                "the holder EXISTS and is simply not ours; not proven dead",
            )

    def test_an_overflowing_pid_is_unprobeable(self) -> None:
        self.assertIsNone(migration_lock.holder_state(str(_OVERFLOW_PID)))

    def test_a_nonpositive_target_is_unprobeable_not_stalled(self) -> None:
        for target in ("0", "-1"):
            with self.subTest(target=target):
                self.assertIsNone(migration_lock.holder_state(target))

    def test_the_string_contract_still_lives_at_this_call_site(self) -> None:
        """The shared probe takes an int; the ASCII-digits parse stays here.

        `target.isascii() and target.isdigit()` deliberately mirrors init.sh's
        `^[0-9]+$` — the two sides must agree on what counts as a pid, or one
        waits for a holder the other clears. Moving the parse into the shared
        probe would put that agreement out of reach of the side that needs it.
        """
        for target in ("", "  ", "12x", "²", "٣", "1.0"):
            with self.subTest(target=target):
                self.assertIsNone(migration_lock.holder_state(target))


class TestTheTwoSitesDisagreeOnPurpose(unittest.TestCase):
    """The regression this file exists to catch, stated as one assertion.

    A future 'simplification' that hands both sites the same verdict function
    breaks exactly here, and the failure names which site it broke.
    """

    def test_eperm_is_held_for_the_lock_and_unadjudicable_for_the_marker(
        self,
    ) -> None:
        with mock.patch.object(os, "kill", side_effect=PermissionError):
            self.assertIs(migration_lock.holder_state("4242"), True)
            self.assertIsNone(in_place_marker._probe_pid(4242))


if __name__ == "__main__":
    unittest.main()

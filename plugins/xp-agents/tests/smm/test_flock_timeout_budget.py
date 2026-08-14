#!/usr/bin/env python3
"""A caller naming its own lock budget — `flock_with_timeout(timeout_s=...)`.

Coordination needs a 2s acquire on an advisory file rather than the 10s the
event log wants, and the alternative to a per-call budget was a second local
lock implementation with its own SIGALRM handling. So the budget became a
parameter.

Three properties here are not cosmetic, and each is a way the obvious
implementation goes wrong:

  * The default must be a `None` SENTINEL, never `LOCK_TIMEOUT_SECONDS` as a
    literal default value. Python evaluates default arguments once at `def`
    time, so a literal default freezes at import and
    `mock.patch.object(_append_impl, "LOCK_TIMEOUT_SECONDS", ...)` — the seam
    `_append_lock.py`'s docstring exists to protect, used by `_lock_helpers`
    and `_in_place_helpers` — would silently stop reaching it. That patch is
    how most of this suite makes a timeout fire fast, so breaking it does not
    fail loudly; it hangs.

  * `XP_LOCK_TIMEOUT_SECONDS` must still reach a caller that named a budget, but
    only to SHORTEN it. It is the cross-process lever: a subprocess re-imports
    the module and cannot see an in-process patch, so it is the only way to make
    a real contended acquire time out quickly (see
    `tests/integration/test_stop_gate_in_place.py`). If an explicit `timeout_s`
    shadowed it outright, every caller that named a budget would become
    unreachable by the one tool that works everywhere — but the converse shipped
    first and was worse: raising the var for its documented purpose inflated
    coordination's deliberate 2s cap to the raised value, blocking a synchronous
    write-path hook for it. `min` satisfies the lever and refuses the inflation.

  * The raised message must state the budget ACTUALLY USED. The handler used to
    rebuild it from the module default, so a 2s acquire reported "within 10
    seconds" — a fabricated number in the one line a human reads while
    diagnosing contention.

`held_events_lock` is deliberately NOT reused for the explicit-budget cases: it
patches `LOCK_TIMEOUT_SECONDS` as part of holding the lock, and that global is
exactly what these cases must prove is no longer consulted.
"""

import contextlib
import fcntl
import os
import signal
import sys
import unittest
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
import _append_impl
from _lock_helpers import held_events_lock
from conftest import _SMMTestCase


def _env(**overrides: str) -> dict:
    """os.environ minus the lock lever, plus *overrides*.

    `tests/_env_hygiene.py` already strips the lever session-wide, which is the
    real containment. This filter is belt to those braces: it also clears a
    value a sibling case in this process set, so `clear=True` below starts from
    "unset" whichever way it got there.
    """
    env = {k: v for k, v in os.environ.items() if k != "XP_LOCK_TIMEOUT_SECONDS"}
    env.update(overrides)
    return env


@contextlib.contextmanager
def _held(lock_path: Path) -> Iterator[None]:
    """Hold *lock_path* exclusively, patching NOTHING."""
    holder = open(lock_path, "a")  # noqa: SIM115
    try:
        fcntl.flock(holder, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(holder, fcntl.LOCK_UN)
        holder.close()


class TestTheAlarmIsAlwaysDisarmed(_SMMTestCase):
    """A pending alarm must never outlive the acquire.

    `signal.alarm(0)` sat on the success line, while only the handler restore
    was in the `finally`. So a `flock` failure that is NOT the alarm's own
    `LockTimeoutError` — `ENOLCK`/`EOPNOTSUPP` from a network-mounted SMM,
    `EDEADLK` — returned with the alarm still armed and the process default
    reinstalled. In a hook process the default action for `SIGALRM` is
    TERMINATE, so the hook dies seconds later, mid-run, with no
    `hook_errors.jsonl` entry: the same silent `-14` kill this suite's own
    module was changed to remove from the coordination path.

    PRE-EXISTING rather than introduced — `main` carries the identical shape —
    but every append and read routes through here, so it reaches further than
    the one path that was fixed.
    """

    def test_a_non_timeout_flock_error_leaves_no_alarm_pending(self):
        lock_path = self.smm_dir / "events.lock"
        fired: list[str] = []

        def _record(signum, frame):
            fired.append("alarm")

        previous = signal.signal(signal.SIGALRM, _record)
        try:
            with (
                mock.patch.dict(os.environ, _env(), clear=True),
                mock.patch.object(
                    _append_impl.fcntl, "flock", side_effect=OSError(37, "ENOLCK")
                ),
                contextlib.suppress(OSError),
                _append_impl.flock_with_timeout(lock_path, timeout_s=1),
            ):
                pass
            # The acquire is over. Nothing it armed may still be counting down:
            # `alarm(0)` returns the seconds left on any pending alarm, so a
            # non-zero answer IS the leak, observed without waiting for it.
            self.assertEqual(signal.alarm(0), 0, "an alarm outlived the acquire")
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)

        self.assertEqual(fired, [], "the alarm fired after the acquire returned")


class TestAnExplicitBudgetIsUsed(_SMMTestCase):
    def test_the_named_budget_reaches_the_alarm(self):
        """A 1s budget times out under contention rather than waiting 10s."""
        lock_path = self.smm_dir / "events.lock"
        with (
            mock.patch.dict(os.environ, _env(), clear=True),
            _held(lock_path),
            self.assertRaises(_append_impl.LockTimeoutError),
            _append_impl.flock_with_timeout(lock_path, timeout_s=1),
        ):
            pass

    def test_the_message_names_the_budget_actually_used(self):
        """Not the module default. A 1s acquire reporting "10 seconds" is a
        fabricated number in the only line a human reads while diagnosing."""
        lock_path = self.smm_dir / "events.lock"
        with (
            mock.patch.dict(os.environ, _env(), clear=True),
            _held(lock_path),
            self.assertRaises(_append_impl.LockTimeoutError) as caught,
            _append_impl.flock_with_timeout(lock_path, timeout_s=1),
        ):
            pass
        self.assertIn("1 second", str(caught.exception))
        self.assertNotIn("10 second", str(caught.exception))


class TestOmittingItPreservesTodaysBehaviour(_SMMTestCase):
    """The regression guard for the def-time default trap."""

    def test_a_patched_module_default_still_reaches_a_caller_naming_nothing(self):
        """`held_events_lock` patches `LOCK_TIMEOUT_SECONDS` down to 1 and
        expects the acquire to give up fast. A literal default argument would
        have frozen the real 10 at import and this would hang instead."""
        with (
            mock.patch.dict(os.environ, _env(), clear=True),
            held_events_lock(self.smm_dir, budget=1),
            self.assertRaises(_append_impl.LockTimeoutError),
            _append_impl.flock_with_timeout(self.smm_dir / "events.lock"),
        ):
            pass

    def test_the_resolver_falls_back_to_the_module_global(self):
        with (
            mock.patch.dict(os.environ, _env(), clear=True),
            mock.patch.object(_append_impl, "LOCK_TIMEOUT_SECONDS", 7),
        ):
            self.assertEqual(_append_impl._effective_lock_timeout_seconds(), 7)

    def test_a_named_budget_replaces_the_module_default(self):
        """Named 3 beats the global 7 — the `min` above applies to the ENV var,
        not to `LOCK_TIMEOUT_SECONDS`, which a named budget simply supersedes.
        (Renamed from "is the fallback not an override": that described the env
        precedence this branch reversed, and was never about the global.)"""
        with (
            mock.patch.dict(os.environ, _env(), clear=True),
            mock.patch.object(_append_impl, "LOCK_TIMEOUT_SECONDS", 7),
        ):
            self.assertEqual(_append_impl._effective_lock_timeout_seconds(3), 3)


class TestTheEnvLeverMayOnlyShorten(_SMMTestCase):
    """It is the only lever that reaches a subprocess, so a per-call budget must
    not put a caller beyond its reach — but reach is not authority to inflate."""

    def test_the_env_var_shortens_a_longer_named_budget(self):
        """What the lever is FOR: speeding up a real contended acquire in a
        subprocess, including one whose caller named its own budget."""
        with mock.patch.dict(os.environ, _env(XP_LOCK_TIMEOUT_SECONDS="1"), clear=True):
            self.assertEqual(_append_impl._effective_lock_timeout_seconds(9), 1)

    def test_the_env_var_cannot_lengthen_a_shorter_named_budget(self):
        """The reversal. `XP_LOCK_TIMEOUT_SECONDS=30` is set for a slow event-log
        lock; it used to turn coordination's deliberate 2s into 30s and block
        every Write/Edit PostToolUse hook for the raised value — the exact harm
        the 2s cap exists to prevent, caused by tuning an unrelated lock."""
        with mock.patch.dict(
            os.environ, _env(XP_LOCK_TIMEOUT_SECONDS="30"), clear=True
        ):
            self.assertEqual(_append_impl._effective_lock_timeout_seconds(2), 2)

    def test_the_env_var_still_stands_alone_when_no_budget_is_named(self):
        """Its documented purpose, unchanged: with nothing to compare against it
        replaces the module default outright, in BOTH directions."""
        for raw, expected in (("30", 30), ("1", 1)):
            with (
                self.subTest(raw=raw),
                mock.patch.dict(
                    os.environ, _env(XP_LOCK_TIMEOUT_SECONDS=raw), clear=True
                ),
            ):
                self.assertEqual(
                    _append_impl._effective_lock_timeout_seconds(), expected
                )

    def test_a_garbage_env_value_falls_back_to_the_named_budget(self):
        """Unparseable or non-positive is "unset", and the caller's own budget
        is what "unset" now means — not the module default."""
        for raw in ("", "  ", "abc", "0", "-3"):
            with (
                self.subTest(raw=raw),
                mock.patch.dict(
                    os.environ, _env(XP_LOCK_TIMEOUT_SECONDS=raw), clear=True
                ),
            ):
                self.assertEqual(_append_impl._effective_lock_timeout_seconds(2), 2)


if __name__ == "__main__":
    unittest.main()

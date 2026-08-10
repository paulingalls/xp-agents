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

  * `XP_LOCK_TIMEOUT_SECONDS` must still WIN over an explicit budget. It is the
    cross-process lever: a subprocess re-imports the module and cannot see an
    in-process patch, so it is the only way to make a real contended acquire
    time out quickly (see `tests/integration/test_stop_gate_in_place.py`). If an
    explicit `timeout_s` shadowed it, every caller that named a budget would
    become unreachable by the one tool that works everywhere.

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

    The lever is NOT in `tests/_env_hygiene.py`'s strip list, so a developer
    shell that exports it would otherwise silently set every budget here.
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

    def test_a_named_budget_is_the_fallback_not_an_override(self):
        with (
            mock.patch.dict(os.environ, _env(), clear=True),
            mock.patch.object(_append_impl, "LOCK_TIMEOUT_SECONDS", 7),
        ):
            self.assertEqual(_append_impl._effective_lock_timeout_seconds(3), 3)


class TestTheEnvLeverStillWins(_SMMTestCase):
    """It is the only lever that reaches a subprocess, so a per-call budget
    must not put a caller beyond its reach."""

    def test_the_env_var_outranks_an_explicit_budget(self):
        with mock.patch.dict(os.environ, _env(XP_LOCK_TIMEOUT_SECONDS="4"), clear=True):
            self.assertEqual(_append_impl._effective_lock_timeout_seconds(2), 4)

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

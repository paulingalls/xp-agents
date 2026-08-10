#!/usr/bin/env python3
"""A contended coordination lock must not kill the hook holding it.

Both lock sites in `coordination.py` used to arm SIGALRM with `SIG_DFL` before a
blocking `flock`. `SIG_DFL` for SIGALRM is TERMINATE, so a lock held past the
budget killed the hook process outright: the `except` never ran, the `finally`
never ran, and nothing reached `hook_errors.jsonl`. `.coordination.json` is
precisely the file parallel teammates contend, so the failure was likeliest
under the condition the file exists to handle.

WHY EVERY CONTENTION CASE HERE RUNS IN A SUBPROCESS. The repo's established
helper (`tests/_lock_helpers.py`) holds the lock and calls the target
in-process. That shape cannot express this defect: a process death takes the
pytest worker with it, so under `-n auto` the pre-fix behaviour arrives as a
crashed worker rather than a red bar. The contended acquire has to be something
whose exit status we can read.

The holder releases as soon as the child exits, so these cases cost roughly the
child's own budget rather than a fixed sleep.
"""

import fcntl
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import marker_names
from conftest import _HookTestCase

_SCRIPTS = str(Path(__file__).parent.parent.parent / "scripts")
_SMM = str(Path(__file__).parent.parent.parent / "smm")

# The child's own budget, narrowed from coordination's 2s so a contended case
# costs ~1s. Reaches the child because it is an ENV var: an in-process
# `mock.patch.object(LOCK_TIMEOUT_SECONDS)` is invisible across a fork, and
# coordination's explicit `timeout_s` outranks that global anyway by design.
_CHILD_BUDGET = "1"


def _child_source(call: str) -> str:
    return (
        f"import sys\n"
        f"sys.path.insert(0, {_SCRIPTS!r})\n"
        f"sys.path.insert(0, {_SMM!r})\n"
        f"from pathlib import Path\n"
        f"import coordination\n"
        f"{call}\n"
    )


class _ContendedCase(_HookTestCase):
    def _run_contended(self, call: str) -> subprocess.CompletedProcess:
        """Hold the coordination lock, run *call* in a child, release."""
        lock_path = self.smm_dir / marker_names.COORDINATION_LOCK
        lock_path.touch()
        holder = open(lock_path, "a")  # noqa: SIM115
        try:
            fcntl.flock(holder, fcntl.LOCK_EX)
            return subprocess.run(
                [sys.executable, "-c", _child_source(call)],
                capture_output=True,
                text=True,
                timeout=60,
                env={
                    **os.environ,
                    "SMM_DIR": str(self.smm_dir),
                    "XP_LOCK_TIMEOUT_SECONDS": _CHILD_BUDGET,
                },
            )
        finally:
            fcntl.flock(holder, fcntl.LOCK_UN)
            holder.close()

    def _hook_errors(self) -> list[dict]:
        path = self.smm_dir / "hook_errors.jsonl"
        if not path.exists():
            return []
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def _entries(self) -> dict:
        path = self.smm_dir / marker_names.COORDINATION_JSON
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))


class TestTheWriterSurvivesContention(_ContendedCase):
    def test_the_child_exits_cleanly_rather_than_being_killed(self):
        """Pre-fix this returned a negative status (killed by SIGALRM)."""
        result = self._run_contended(
            f"coordination.update_coordination(Path({str(self.smm_dir)!r}),"
            f" 'other', ['src/a.py'])"
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_timeout_leaves_a_trace(self):
        self._run_contended(
            f"coordination.update_coordination(Path({str(self.smm_dir)!r}),"
            f" 'other', ['src/a.py'])"
        )
        reasons = [e.get("reason", "") for e in self._hook_errors()]
        self.assertTrue(
            any("coordination" in r for r in reasons),
            f"no coordination lock failure recorded; got {reasons}",
        )

    def test_no_entry_is_written_when_the_lock_was_never_taken(self):
        self._run_contended(
            f"coordination.update_coordination(Path({str(self.smm_dir)!r}),"
            f" 'other', ['src/a.py'])"
        )
        self.assertNotIn("other", self._entries())


class TestTheRemoverSurvivesContention(_ContendedCase):
    """Both lock sites, not just the writer — the defect was duplicated."""

    def test_the_child_exits_cleanly_rather_than_being_killed(self):
        result = self._run_contended(
            f"coordination.clear_coordination_agent(Path({str(self.smm_dir)!r}),"
            f" 'other')"
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_timeout_leaves_a_trace(self):
        self._run_contended(
            f"coordination.clear_coordination_agent(Path({str(self.smm_dir)!r}),"
            f" 'other')"
        )
        reasons = [e.get("reason", "") for e in self._hook_errors()]
        self.assertTrue(
            any("coordination" in r for r in reasons),
            f"no coordination lock failure recorded; got {reasons}",
        )


class TestASymlinkedLockIsRefused(_HookTestCase):
    """`flock_with_timeout` opens with O_NOFOLLOW, which the hand-rolled
    `os.open` did not — a symlinked lock path was followed silently."""

    def test_the_writer_refuses_and_survives(self):
        target = self.smm_dir / "elsewhere.lock"
        target.touch()
        link = self.smm_dir / marker_names.COORDINATION_LOCK
        link.symlink_to(target)

        import coordination

        coordination.update_coordination(self.smm_dir, "other", ["src/a.py"])
        self.assertNotIn(
            "other",
            json.loads((self.smm_dir / marker_names.COORDINATION_JSON).read_text())
            if (self.smm_dir / marker_names.COORDINATION_JSON).exists()
            else {},
        )


class TestTheUncontendedPathIsUnchanged(_HookTestCase):
    def test_an_entry_still_carries_its_three_fields(self):
        import coordination

        coordination.update_coordination(self.smm_dir, "other", ["src/a.py"])
        entry = json.loads((self.smm_dir / marker_names.COORDINATION_JSON).read_text())[
            "other"
        ]
        self.assertEqual(entry["working_on"], ["src/a.py"])
        self.assertIn("updated", entry)
        self.assertIn("session_id", entry)

    def test_the_remover_still_removes(self):
        import coordination

        coordination.update_coordination(self.smm_dir, "other", ["src/a.py"])
        coordination.clear_coordination_agent(self.smm_dir, "other")
        data = json.loads((self.smm_dir / marker_names.COORDINATION_JSON).read_text())
        self.assertNotIn("other", data)


if __name__ == "__main__":
    unittest.main()

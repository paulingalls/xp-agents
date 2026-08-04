#!/usr/bin/env python3
"""Throwaway: instrument-validity checks for the two story-002 probes.

The shipped convention for spike code is that its SOURCE is exempt from review
but its VALIDITY is not: a rig's output feeds a shipped finding, so a known
input must produce the exact expected recorded output. These are those checks,
not tests of anything the plugin ships.

Each assertion here exists because its opposite would corrupt an observation
rather than merely inconvenience it. Plan review found three such holes in the
first draft of this story, and two of them are pinned below:

- An absent env alias recorded by OMITTING its key is indistinguishable from
  "we never looked". Absence is a finding; a missing key reads as "checked and
  fine". So every key in the alias set must appear, present or absent.
- A marker the injector does not GENERATE is a marker that could have reached
  the model some other way. AC-3 requires one "carried only by that context",
  so the marker must be fresh per invocation and must be recorded locally,
  which is what lets the outer runner tell a real echo from a coincidence.

Deleted with the rest of the rig at sprint close. Run explicitly:
    pytest plugins/xp-agents/spike/test_probes.py
(`pytest.ini` sets `testpaths` to the tests dir, so the default run skips it.)
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_SPIKE = Path(__file__).parent
_RESOLVE = _SPIKE / "_probe_resolve.py"
_INJECT = _SPIKE / "_inject_marker.py"

_SESSION_START = json.dumps(
    {
        "hook_event_name": "SessionStart",
        "session_id": "payload-session-abc",
        "source": "startup",
        "cwd": "/tmp/whatever",
    }
)


def _run(script: Path, payload: str, outdir: Path, extra_env: dict | None = None):
    env = {"XP_SPIKE_DIR": str(outdir), "PATH": "/usr/bin:/bin"}
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(script)],
        input=payload.encode("utf-8"),
        capture_output=True,
        env=env,
    )


def _records(outdir: Path, name: str) -> list[dict]:
    path = outdir / name
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class TestResolveProbe(unittest.TestCase):
    """AC-1's half that is genuinely unobserved: init.sh from inside a hook."""

    def test_records_every_env_alias_present_or_absent(self) -> None:
        # No alias is set in this env, so all four must be recorded as absent
        # rather than dropped. Reuses the recorder's key set by import, so the
        # two probes cannot disagree about which names were checked.
        sys.path.insert(0, str(_SPIKE))
        import _dump_payload

        with tempfile.TemporaryDirectory() as td:
            outdir = Path(td)
            self._run_probe(_SESSION_START, outdir)
            entry = self._one(outdir)
            for key in _dump_payload._ENV_KEYS:
                self.assertIn(
                    key,
                    entry["env"],
                    f"{key} must be recorded as absent, not omitted — an "
                    "omitted key reads downstream as 'never checked'",
                )
                self.assertIsNone(entry["env"][key])

    def test_records_payload_and_env_session_ids_separately(self) -> None:
        # The heartbeat is WRITTEN keyed on the payload's session_id but READ
        # from env. If those disagree, a session whose hooks demonstrably ran
        # reports "not live". Recording both is what makes that visible instead
        # of arriving as a mystery verdict on AC-4.
        with tempfile.TemporaryDirectory() as td:
            outdir = Path(td)
            self._run_probe(
                _SESSION_START, outdir, {"CODEX_THREAD_ID": "env-session-xyz"}
            )
            entry = self._one(outdir)
            self.assertEqual(entry["payload_session_id"], "payload-session-abc")
            self.assertEqual(
                entry["env_session_ids"]["CODEX_THREAD_ID"], "env-session-xyz"
            )
            self.assertFalse(
                entry["session_ids_agree"],
                "a disagreeing pair must be reported as disagreeing",
            )

    def test_records_resolution_outcome_when_no_plugin_root(self) -> None:
        # Absence of a plugin root is an outcome to record, not a reason to
        # write nothing. A probe that skips its record here is indistinguishable
        # from a hook that never fired.
        with tempfile.TemporaryDirectory() as td:
            outdir = Path(td)
            r = self._run_probe(_SESSION_START, outdir)
            self.assertEqual(r.returncode, 0)
            entry = self._one(outdir)
            self.assertIn("init_sh", entry)
            self.assertFalse(entry["init_sh"]["ran"])
            self.assertIsNotNone(entry["init_sh"]["reason"])

    def test_never_writes_stdout(self) -> None:
        # This probe is registered alongside the AC-3 injector. Stdout from a
        # hook is injected context, so anything here would contaminate the very
        # measurement the injector exists to make.
        with tempfile.TemporaryDirectory() as td:
            r = self._run_probe(_SESSION_START, Path(td))
            self.assertEqual(r.stdout, b"")
            self.assertEqual(r.returncode, 0)

    def test_unparseable_stdin_still_records(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            outdir = Path(td)
            r = self._run_probe("not json <<<", outdir)
            self.assertEqual(r.returncode, 0)
            entry = self._one(outdir)
            self.assertIsNone(entry["payload_session_id"])

    def _run_probe(self, payload: str, outdir: Path, extra_env: dict | None = None):
        return _run(_RESOLVE, payload, outdir, extra_env)

    def _one(self, outdir: Path) -> dict:
        entries = _records(outdir, "resolve.jsonl")
        self.assertEqual(len(entries), 1, f"expected one record, got {entries}")
        return entries[0]


class TestInjectMarker(unittest.TestCase):
    """AC-3's instrument: a marker the model can only have got by injection."""

    def test_emits_marker_as_additional_context_on_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            outdir = Path(td)
            r = _run(_INJECT, _SESSION_START, outdir)
            self.assertEqual(r.returncode, 0)
            payload = json.loads(r.stdout.decode("utf-8"))
            hso = payload["hookSpecificOutput"]
            self.assertEqual(hso["hookEventName"], "SessionStart")
            self.assertIn(self._recorded_marker(outdir), hso["additionalContext"])

    def test_marker_is_fresh_per_invocation(self) -> None:
        # A stale or predictable marker could reach the model by some route
        # other than injection, which is exactly what AC-3 must rule out.
        with tempfile.TemporaryDirectory() as td:
            outdir = Path(td)
            _run(_INJECT, _SESSION_START, outdir)
            _run(_INJECT, _SESSION_START, outdir)
            markers = [e["marker"] for e in _records(outdir, "injected_markers.jsonl")]
            self.assertEqual(len(markers), 2)
            self.assertNotEqual(
                markers[0], markers[1], "each firing must mint its own marker"
            )

    def test_marker_is_recorded_locally_for_the_outer_runner(self) -> None:
        # The outer run compares the model's output against this record. Without
        # it there is nothing to compare to, and "the marker appeared" becomes
        # an unverifiable claim.
        with tempfile.TemporaryDirectory() as td:
            outdir = Path(td)
            _run(_INJECT, _SESSION_START, outdir)
            entry = _records(outdir, "injected_markers.jsonl")[0]
            self.assertTrue(entry["marker"])
            self.assertIn("recorded_at", entry)

    def test_marker_is_not_read_from_the_environment(self) -> None:
        # If the injector honoured an env-supplied marker, the outer runner
        # could set it, the prompt could carry it, and the check would pass
        # against an injector that never ran.
        with tempfile.TemporaryDirectory() as td:
            outdir = Path(td)
            _run(_INJECT, _SESSION_START, outdir, {"XP_SPIKE_MARKER": "planted-value"})
            entry = _records(outdir, "injected_markers.jsonl")[0]
            self.assertNotIn("planted-value", entry["marker"])

    def _recorded_marker(self, outdir: Path) -> str:
        return _records(outdir, "injected_markers.jsonl")[0]["marker"]


if __name__ == "__main__":
    unittest.main()

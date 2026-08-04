#!/usr/bin/env python3
"""Throwaway: validity checks for the bounded Stop-block probe.

This probe deliberately BLOCKS a Stop event, which is the one thing in the rig
that could cost real money if it misbehaved: an unbounded block means the model
never gets to end its turn. The cap is therefore a safety property, not a
convenience, and plan review correctly refused to accept it as "checked" when no
test file existed and the story's acceptance command did not run one.

So the cap is pinned three ways, each against a specific way it could fail open:

- At the cap the probe must return NON-blocking. A probe that always blocks is
  the unbounded case.
- A counter that EXISTS but cannot be parsed must be treated as AT the cap, not
  as zero, since reading it as zero would restart the count on every firing — an
  unbounded loop assembled out of individually-bounded decisions. An ABSENT
  counter is a different case: that is the first firing, and zero is its true
  count. Conflating the two made the probe never block at all on the first
  implementation, which would have answered AC-3 with a non-observation.
- An unwritable counter directory must still yield non-blocking, since a probe
  that blocks and then cannot record that it blocked can never reach its cap.

Deleted with the rest of the rig at sprint close. Run explicitly:
    pytest plugins/xp-agents/spike/test_stop_probe.py
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_SPIKE = Path(__file__).parent
_PROBE = _SPIKE / "_stop_block_probe.py"

_STOP = json.dumps(
    {
        "hook_event_name": "Stop",
        "session_id": "s1",
        "cwd": "/tmp/x",
        "stop_hook_active": False,
    }
)


def _run(outdir: Path, payload: str = _STOP) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_PROBE)],
        input=payload.encode("utf-8"),
        capture_output=True,
        env={"XP_SPIKE_DIR": str(outdir), "PATH": "/usr/bin:/bin"},
    )


def _blocked(proc: subprocess.CompletedProcess) -> bool:
    """True when this firing asked the host to continue the turn.

    Asserts the probe actually RAN first. Without that, "no block" and "the
    probe crashed or does not exist" are the same observation, and the two
    fail-safe checks below would pass vacuously against a missing file — which
    is exactly what they did on the first red run.
    """
    assert proc.returncode == 0, (
        f"probe must exit 0, got {proc.returncode}: {proc.stderr.decode()[:400]}"
    )
    if not proc.stdout.strip():
        return False
    return json.loads(proc.stdout.decode("utf-8")).get("decision") == "block"


class TestCapIsTheSafetyProperty(unittest.TestCase):
    def test_blocks_up_to_the_cap_then_stops(self) -> None:
        import importlib.util

        spec = importlib.util.spec_from_file_location("_probe", _PROBE)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        cap = mod.CAP

        with tempfile.TemporaryDirectory() as td:
            outdir = Path(td)
            decisions = [_blocked(_run(outdir)) for _ in range(cap + 3)]
            self.assertEqual(
                decisions[:cap], [True] * cap, f"should block exactly {cap} times"
            )
            self.assertEqual(
                decisions[cap:],
                [False] * 3,
                "past the cap every firing must be non-blocking, forever",
            )

    def test_corrupt_counter_is_treated_as_at_cap_not_as_zero(self) -> None:
        # Named for what it actually pins: a counter that EXISTS but cannot be
        # parsed. Reading that as zero would restart the count on every firing —
        # an unbounded loop built from individually-bounded decisions. (An ABSENT
        # counter is the first firing and legitimately means zero; the two cases
        # are separated in the probe, and conflating them made it never block.)
        with tempfile.TemporaryDirectory() as td:
            outdir = Path(td)
            outdir.mkdir(parents=True, exist_ok=True)
            (outdir / "stop_block_count").write_text("not-a-number")
            self.assertFalse(
                _blocked(_run(outdir)),
                "a corrupt counter must fail SAFE (non-blocking), not open",
            )

    def test_unwritable_counter_dir_still_yields_non_blocking(self) -> None:
        # A probe that blocks but cannot record having blocked can never reach
        # its cap. Path under a regular file is portable and root-proof.
        with tempfile.TemporaryDirectory() as td:
            blocker = Path(td) / "blocker"
            blocker.write_text("not a directory")
            self.assertFalse(_blocked(_run(blocker / "under-a-file")))


class TestObservation(unittest.TestCase):
    def test_records_stop_hook_active_on_every_firing(self) -> None:
        # The whole point of the probe: whether the field ever flips to True is
        # AC-3's answer. Presence alone is not a release path.
        with tempfile.TemporaryDirectory() as td:
            outdir = Path(td)
            _run(outdir)
            _run(
                outdir,
                json.dumps({"hook_event_name": "Stop", "stop_hook_active": True}),
            )
            lines = (outdir / "stop_firings.jsonl").read_text().splitlines()
            observed = [json.loads(x)["stop_hook_active"] for x in lines]
            self.assertEqual(observed, [False, True])

    def test_a_firing_at_the_cap_is_still_recorded_as_a_firing(self) -> None:
        # The cap RELEASING is itself the observation: it is what shows the host
        # kept firing Stop after the probe stopped blocking. Record only the
        # blocking firings — a plausible refactor that moves the write inside the
        # `count < CAP` branch — and the log becomes indistinguishable from a
        # host that simply stopped firing at the cap.
        import importlib.util

        spec = importlib.util.spec_from_file_location("_probe_cap", _PROBE)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        cap = mod.CAP

        with tempfile.TemporaryDirectory() as td:
            outdir = Path(td)
            for _ in range(cap + 1):
                _run(outdir)
            entries = [
                json.loads(x)
                for x in (outdir / "stop_firings.jsonl").read_text().splitlines()
            ]
            self.assertEqual(
                [e["blocked"] for e in entries],
                [True] * cap + [False],
                "every firing is recorded, and the log says which ones blocked",
            )

    def test_absent_stop_hook_active_is_recorded_as_absent_not_false(self) -> None:
        # False and absent are different findings: False means the host sends the
        # field and has not set it; absent means no release channel exists at all.
        with tempfile.TemporaryDirectory() as td:
            outdir = Path(td)
            _run(outdir, json.dumps({"hook_event_name": "Stop"}))
            lines = (outdir / "stop_firings.jsonl").read_text().splitlines()
            entry = json.loads(lines[0])
            self.assertIsNone(entry["stop_hook_active"])
            self.assertFalse(entry["stop_hook_active_present"])


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""E2E: after work_selection_decide adopts a Try, a stale-snapshot probe
must reread events.jsonl (driven by the refresh sentinel) so commits
referencing the just-written decision don't divert as missing-event.
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import _common
import resolves_probe
from _bases import _PLUGIN_ROOT, _IntegrationTestCase
from conftest import make_event
from event_schema import (
    EVENT_TYPE_DECISION,
    EVENT_TYPE_RETROSPECTIVE,
    METADATA_KEY_PROBE_SNAPSHOT_MAX_TS,
    METADATA_KEY_PROBE_TAIL_TS,
)

_WORK_SELECTION_DECIDE = (
    _PLUGIN_ROOT
    / "skills"
    / "xp-work-selection"
    / "scripts"
    / "work_selection_decide.py"
)


class TestKickoffAdoptCommitProbeE2E(_IntegrationTestCase):
    def test_adopt_signals_refresh_then_probe_rereads_disk(self):
        target_id = "aabbccdd1111"
        # Pin seed ts to "now" so the wall-clock staleness branch
        # (>5s old) CANNOT fire — the only remaining signal that can
        # mark the snapshot stale is the refresh sentinel touched by
        # work_selection_decide adopt. Without this pin, make_event's
        # default 2026-03-12 ts trips wall-clock immediately and
        # masks whether signal_probe_refresh actually wired up.
        now_ts = _common.now_iso()
        seed_retro = make_event(
            EVENT_TYPE_RETROSPECTIVE,
            content="seed retro for E2E",
            ts=now_ts,
        )
        self._seed_events([seed_retro])

        events_pre_adopt, _ = _common.load_events_with_resolutions(self.smm_dir)
        self.assertGreater(len(events_pre_adopt), 0)

        adopt = subprocess.run(
            [
                "python3",
                str(_WORK_SELECTION_DECIDE),
                "adopt",
                "--smm-dir",
                str(self.smm_dir),
                "--topic",
                "retro-try-e2e",
                "--content",
                f"Adopt try [refs: {target_id}]",
            ],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
            env=self._env_with_plugin_root(),
        )
        self.assertEqual(adopt.returncode, 0, msg=adopt.stderr)

        sentinel = resolves_probe.refresh_sentinel_path(self.smm_dir)
        self.assertTrue(
            sentinel.exists(),
            "work_selection_decide adopt must signal probe refresh",
        )

        # Probe return ignored; assertions check out_meta + events on disk.
        # Pass now_ts == seed ts so the wall-clock staleness branch
        # (now - snapshot_max_ts > 5s) cannot fire; the sentinel branch
        # is the ONLY signal under test.
        out_meta: dict = {}
        resolves_probe.find_probe_candidates(
            self.smm_dir,
            commit_files=[],
            resolves=[target_id],
            cwd=str(self.tmpdir),
            events=events_pre_adopt,
            commit_message="commit referencing adopted try",
            now_ts=now_ts,
            out_meta=out_meta,
        )

        # Both ts are ISO-8601 UTC from the same writer; lex order == temporal order.
        snapshot_max_ts = out_meta[METADATA_KEY_PROBE_SNAPSHOT_MAX_TS]
        tail_ts = out_meta[METADATA_KEY_PROBE_TAIL_TS]
        self.assertGreater(
            tail_ts,
            snapshot_max_ts,
            "stale snapshot must trigger reread; tail_ts must postdate snapshot",
        )
        self.assertFalse(
            sentinel.exists(),
            "successful reread must consume the refresh sentinel",
        )

        events_post = self._read_events()
        adopt_decisions = [
            e
            for e in events_post
            if e.get("type") == EVENT_TYPE_DECISION
            and e.get("topic") == "retro-try-e2e"
        ]
        self.assertEqual(len(adopt_decisions), 1)
        self.assertEqual(
            adopt_decisions[0]["metadata"]["resolves"],
            [target_id],
            "adopt-decision must carry metadata.resolves with the Try id",
        )


if __name__ == "__main__":
    unittest.main()

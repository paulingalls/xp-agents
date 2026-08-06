#!/usr/bin/env python3
"""Shared reads and arming for the close-cycle abandonment pins.

Two suites cover the story — the in-process detectors
(`test_close_cycle_abandonment`) and the close preloads' subprocess one
(`test_close_cycle_abandonment_preload`) — and both need the same two things:
a marker back-dated past the age rule, and a way to read the concerns that
came out. Duplicating either would let the two halves disagree about what an
abandoned cycle even looks like.
"""

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import close_cycle_abandonment
import markers
from conftest import _MixinBase
from event_schema import CONCERN_KIND_CLOSE_CYCLE_BYPASS, EVENT_TYPE_CONCERN

ARMING_MODES = ("sprint", "plan", "free")


def arm_abandoned(smm_dir: Path, payload: str = "") -> None:
    """Arm the close marker and back-date it past the abandonment threshold.

    Every detector reads the marker's mtime, so a marker written NOW is a LIVE
    cycle to all three — which is the point of the age rule and the reason a
    test that wants the abandoned case has to say so.
    """
    markers.marker_write(smm_dir, markers.CLOSE_CYCLE_ACTIVE, payload)
    path = markers.marker_path(smm_dir, markers.CLOSE_CYCLE_ACTIVE)
    aged = path.stat().st_mtime - close_cycle_abandonment.ABANDONMENT_MIN_AGE_SEC - 60
    os.utime(path, (aged, aged))


class _AbandonmentAssertions(_MixinBase):
    """Shared reads over the recorded abandonment concerns.

    Both concrete bases below define `_read_events`, but `TestCase` (what
    `_MixinBase` resolves to for pyright) does not — so it is declared here
    under TYPE_CHECKING only, which adds nothing at runtime.
    """

    if TYPE_CHECKING:

        def _read_events(self) -> list[dict]: ...

    def _bypass_concerns(self) -> list[dict]:
        return [
            e
            for e in self._read_events()
            if e.get("type") == EVENT_TYPE_CONCERN
            and (e.get("metadata") or {}).get("kind") == CONCERN_KIND_CLOSE_CYCLE_BYPASS
        ]

    def _one_bypass_concern(self) -> dict:
        found = self._bypass_concerns()
        self.assertEqual(len(found), 1, f"expected exactly one, got {found!r}")
        return found[0]

#!/usr/bin/env python3
"""Capstone: adopting work links its target WITHOUT closing it.

The milestone's thesis in one sentence — **adopting work is not finishing it.**

Three legs read and write the same two link fields, and unit tests bound each
leg in isolation:

  * the suffix extractor WRITES the link (`event_builder.extract_refs_suffix`),
  * the triage/FORCE-CLOSE gate READS it back (`work_selection_*`),
  * the retro's adoption memory reads it AGAIN (`retro_history.annotate_try_status`).

A leg-to-leg DESYNC is invisible to all of them, and that is exactly how the
original defect survived: every leg was green while adoption silently closed its
target, the housekeeper read the closure as confirmed-fixed, and the work
evaporated. So this suite drives the REAL CLI end to end against a REAL SMM (no
mocks — the story's interface contract) and asserts BOTH halves at once: the
adopted target stays OPEN, and it is nonetheless REMEMBERED as adopted.

Half an assertion is what shipped the bug. "Nothing closed" alone would pass
against a seam that had forgotten the adoption entirely; "it is remembered"
alone would pass against one that closed the target too. Hence also
`test_a_dropped_try_is_closed` — the falsifier. Without it a suite asserting
only "nothing ever closes" would pass against a totally broken seam, because a
seam that can never close anything trivially satisfies it. It proves this suite
can tell CLOSURE from INTENT and would fail if the two were confused.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import materialize
import resolution
from conftest import _PLUGIN_ROOT, _IntegrationTestCase
from event_builder import REFERENCES_KEY
from event_schema import EVENT_TYPE_CONCERN, METADATA_KEY_RESOLVES

# The REAL threshold, not a copy of it. retrospective.py regenerates
# .retro-input.json ONLY when unanalyzed events reach it; below it the hook
# returns None, writes NOTHING, and an assertion against a stale or absent file
# passes while proving nothing at all. Every retro-driving test here seeds at
# least this many events AFTER the retrospective event (which is itself the
# watermark) and asserts the regeneration actually happened. Imported so a
# future bump re-pads these tests instead of leaving a stale 5 behind.
from retrospective import RETRO_THRESHOLD

_WORK_SELECTION_DECIDE = (
    _PLUGIN_ROOT
    / "skills"
    / "xp-work-selection"
    / "scripts"
    / "work_selection_decide.py"
)

_TRY_ID = "a1b2c3d4e5f6"


class _AdoptionCase(_IntegrationTestCase):
    """Drives the real work_selection_decide CLI against the real SMM."""

    def _decide(self, *args: str) -> str:
        """Run work_selection_decide.py as a SUBPROCESS. Returns the event id.

        A subprocess, not an import: the story's contract is the CLI, and an
        in-process call would silently bypass argparse, the budget truncation,
        and validate_event — the very chokepoints that route the link field.
        """
        result = subprocess.run(
            [
                "python3",
                str(_WORK_SELECTION_DECIDE),
                *args,
                "--smm-dir",
                str(self.smm_dir),
            ],
            capture_output=True,
            text=True,
            cwd=self.tmpdir,
            env=self._env_with_plugin_root(),
        )
        self.assertEqual(result.returncode, 0, f"CLI failed: {result.stderr}")
        return result.stdout.strip()

    def _verdict(self) -> tuple[list[dict], dict]:
        """Materialize the SMM and compute closure through the REAL reader stack.

        This is the production path (materialize -> resolution), not a
        re-implementation of it: a test that hand-rolled its own notion of
        "closed" could not catch the reader and the writer disagreeing.
        """
        events, _ = materialize.parse_events(self.smm_dir)
        return events, resolution.compute_resolutions(events)

    def _event_by_id(self, events: list[dict], event_id: str) -> dict:
        match = next((e for e in events if e.get("id") == event_id), None)
        return self._assert_not_none(match, f"no event {event_id} in the log")

    def _seed_concern(self, content: str = "Auth token refresh races") -> str:
        result = self._run_append(
            "--type", EVENT_TYPE_CONCERN, "--agent", "main",
            "--content", content, "--severity", "medium",
        )  # fmt: skip
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def _save_retro_with_try(self, try_content: str) -> None:
        """Write a REAL retrospective (event + file) carrying one Try.

        Through save_retrospective.py, so the Try exists in BOTH places the
        readers look: nested in the retrospective EVENT (where
        `intent.retro_try_ids` and `resolution.index_event` find it) and in the
        retrospectives/ FILE (where `gather_retro_history` reads it back).
        """
        result = self._run_script(
            "save_retrospective.py",
            {
                "keep": ["Tests stayed green"],
                "fix": ["Reader drifted from writer"],
                "try": [{"id": _TRY_ID, "content": try_content}],
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def _regenerate_retro_input(self) -> dict:
        """Run retrospective.py as a subprocess and return the FRESH retro input.

        Deletes .retro-input.json first and requires the hook to write it again,
        because the hook is a no-op below the unanalyzed-event threshold: a
        green check read off a stale file would certify something untrue, which
        is this milestone's own thesis. Failing loudly here is the point.
        """
        retro_input = self.smm_dir / ".retro-input.json"
        retro_input.unlink(missing_ok=True)

        result = self._run_script(
            "retrospective.py", {"session_id": "capstone", "source": "startup"}
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(
            retro_input.is_file(),
            "retrospective.py wrote NOTHING — it fell below RETRO_THRESHOLD, so "
            "any assertion past this point would have proved nothing. Seed more "
            "unanalyzed events.",
        )
        return json.loads(retro_input.read_text())

    def _pad_unanalyzed(self, count: int = RETRO_THRESHOLD) -> None:
        """Push the unanalyzed-event count over the retro threshold."""
        for i in range(count):
            self._run_append(
                "--type", "status", "--agent", "main",
                "--content", f"filler {i}", "--working-on", "[]",
            )  # fmt: skip

    def _try_status(self, retro_input: dict) -> dict:
        """The annotated status of the single Try in the regenerated retro input."""
        previous = retro_input["previous_retros"]
        self.assertTrue(previous, "retro input carries no previous retros")
        statuses = previous[0].get("try_status")
        self.assertTrue(statuses, "the Try was never annotated at all")
        return statuses[0]


class TestAdoptionRecordsIntentNotResolution(_AdoptionCase):
    """AC1-AC4: adoption links its target and leaves it OPEN; a drop closes."""

    def test_triage_adopt_links_the_concern_without_closing_it(self):
        """AC1. Adopting a concern names it in `references` and leaves it OPEN.

        Both halves in one test on purpose. Asserting only "still open" would
        pass against a seam that dropped the link entirely (the work is then
        forgotten, which is the OTHER way to lose it); asserting only "linked"
        would pass against the original bug, where the link WAS the closure.
        """
        concern_id = self._seed_concern()
        adopt_id = self._decide("triage-adopt", "--event-id", concern_id)

        events, resolutions = self._verdict()
        self.assertNotIn(
            concern_id,
            resolutions["resolved_concern_ids"],
            "adopting the concern CLOSED it — adopting work is not finishing it",
        )
        adopt_event = self._event_by_id(events, adopt_id)
        self.assertIn(concern_id, adopt_event.get(REFERENCES_KEY) or [])
        self.assertNotIn(
            concern_id,
            (adopt_event.get("metadata") or {}).get(METADATA_KEY_RESOLVES) or [],
            "the adoption wrote the CLOSURE link instead of the intent link",
        )

    def test_an_adopted_try_is_remembered_as_adopted_but_not_resolved(self):
        """AC2. The Try is annotated `adopted` AND stays open in the event log.

        This is the leg the unit tests could not reach: the adoption is written
        by the CLI and read back by a DIFFERENT module (retro_history), through
        the retro input the hook regenerates. A desync between them is what let
        an adopted Try read as "done" and vanish.
        """
        self._save_retro_with_try("Split the god module")
        self._decide(
            "adopt",
            "--topic",
            "retro-try-split-the-god-module",
            "--content",
            f"Adopted: split the god module [refs: {_TRY_ID}]",
        )
        self._pad_unanalyzed()

        status = self._try_status(self._regenerate_retro_input())
        self.assertEqual(status.get("intent"), "adopted")
        self.assertIs(
            status.get("resolved_this_session"),
            False,
            "the adopted Try reads as RESOLVED — a promise relabelled as delivery",
        )

        _, resolutions = self._verdict()
        self.assertNotIn(_TRY_ID, resolution.collect_all_resolved_ids(resolutions))

    def test_a_dropped_try_is_closed(self):
        """AC3. THE FALSIFIER — the same Try, dropped instead, IS closed.

        Without this, a capstone asserting only "nothing ever closes" would pass
        against a totally broken seam that had lost the ability to close
        anything. This proves the suite can tell closure from intent, and that
        it would go red if the two were ever confused again. Do not delete it.
        """
        self._save_retro_with_try("Split the god module")
        self._decide(
            "drop",
            "--content",
            f"Dropped: not worth the churn [refs: {_TRY_ID}]",
        )

        _, resolutions = self._verdict()
        self.assertIn(
            _TRY_ID,
            resolution.collect_all_resolved_ids(resolutions),
            "a DROP is terminal and must close its target — if this fails, the "
            "suite can no longer tell closure from intent and its other "
            "assertions prove nothing",
        )

    def test_the_adopt_then_retro_cycle_runs_green_end_to_end(self):
        """AC4. The whole cycle against a real SMM, no mocks: seed a concern and
        a Try, adopt BOTH through the real CLI, regenerate the retro input, and
        confirm nothing was closed and everything was remembered."""
        concern_id = self._seed_concern("Flaky worktree teardown")
        self._save_retro_with_try("Adopt the carried Try")
        self._decide("triage-adopt", "--event-id", concern_id)
        self._decide(
            "adopt",
            "--topic",
            "retro-try-adopt-the-carried-try",
            "--content",
            f"Adopted: the carried Try [refs: {_TRY_ID}]",
        )
        self._pad_unanalyzed()

        status = self._try_status(self._regenerate_retro_input())
        self.assertEqual(status.get("intent"), "adopted")
        self.assertIs(status.get("resolved_this_session"), False)

        _, resolutions = self._verdict()
        resolved = resolution.collect_all_resolved_ids(resolutions)
        self.assertNotIn(concern_id, resolved)
        self.assertNotIn(_TRY_ID, resolved)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Tests for coordination file helpers and working-on overlap detection."""

import json
import os
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import coordination
import hook_liveness
import markers
import pre_tool_write
import worktree
from _heartbeat_fixtures import env as _env
from conftest import _HookTestCase


class TestCoordination(_HookTestCase):
    """Test coordination file helpers: update, read, clear."""

    def test_update_creates_file(self):
        """update_coordination creates .coordination.json if missing."""
        coordination.update_coordination(self.smm_dir, "main", ["src/a.ts"])
        coord_file = self.smm_dir / ".coordination.json"
        self.assertTrue(coord_file.exists())

    def test_update_adds_agent_entry(self):
        """Entry has working_on list and updated timestamp."""
        coordination.update_coordination(self.smm_dir, "main", ["src/a.ts"])
        data = coordination.read_coordination(self.smm_dir)
        self.assertIn("main", data)
        self.assertEqual(data["main"]["working_on"], ["src/a.ts"])
        self.assertIn("updated", data["main"])

    def test_update_overwrites_previous(self):
        """Latest update replaces previous working_on."""
        coordination.update_coordination(self.smm_dir, "main", ["src/a.ts"])
        coordination.update_coordination(self.smm_dir, "main", ["src/b.ts"])
        data = coordination.read_coordination(self.smm_dir)
        self.assertEqual(data["main"]["working_on"], ["src/b.ts"])

    def test_read_returns_empty_on_missing(self):
        """read_coordination returns {} when file doesn't exist."""
        data = coordination.read_coordination(self.smm_dir)
        self.assertEqual(data, {})

    def test_read_ignores_stale_entries(self):
        """Entries older than max_age_seconds are excluded."""
        from datetime import datetime, timedelta, timezone

        old_time = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
        coord_file = self.smm_dir / ".coordination.json"
        coord_file.write_text(
            json.dumps(
                {
                    "stale-agent": {
                        "working_on": ["src/old.ts"],
                        "updated": old_time,
                    }
                }
            )
        )
        data = coordination.read_coordination(self.smm_dir)
        self.assertEqual(data, {})

    def test_read_keeps_fresh_entries(self):
        """Entries within max_age_seconds are kept."""
        coordination.update_coordination(self.smm_dir, "main", ["src/a.ts"])
        data = coordination.read_coordination(self.smm_dir)
        self.assertIn("main", data)

    def test_clear_removes_agent(self):
        """clear_coordination_agent removes the agent's entry."""
        coordination.update_coordination(self.smm_dir, "main", ["src/a.ts"])
        coordination.clear_coordination_agent(self.smm_dir, "main")
        data = coordination.read_coordination(self.smm_dir)
        self.assertNotIn("main", data)

    def test_clear_preserves_others(self):
        """Clearing one agent doesn't affect other agents."""
        coordination.update_coordination(self.smm_dir, "main", ["src/a.ts"])
        coordination.update_coordination(self.smm_dir, "agent-2", ["src/b.ts"])
        coordination.clear_coordination_agent(self.smm_dir, "main")
        data = coordination.read_coordination(self.smm_dir)
        self.assertNotIn("main", data)
        self.assertIn("agent-2", data)

    def test_clear_noop_on_missing_file(self):
        """clear_coordination_agent is a no-op if file doesn't exist."""
        coordination.clear_coordination_agent(self.smm_dir, "main")
        # Should not raise

    def test_corrupted_file_returns_empty(self):
        """read_coordination returns {} on invalid JSON."""
        coord_file = self.smm_dir / ".coordination.json"
        coord_file.write_text("not json{{{")
        data = coordination.read_coordination(self.smm_dir)
        self.assertEqual(data, {})


class _LivenessTestCase(_HookTestCase):
    """Fixtures for the has_active_teammates liveness leg.

    Every dead/live pair below is planted against the SAME constructed
    heartbeat marker, differing only in its timestamp. A "dead session" test
    that passes because no heartbeat was ever written proves nothing about the
    branch it claims to cover, so `_beat` is the one planting helper and the
    absence case says in its own name that absence is what it is testing.
    """

    TEAMMATE = "worktree-story-042"
    SESSION = "the-teammates-session"

    #: Comfortably inside the heartbeat trust window and inside the entry TTL.
    FRESH = 60.0
    #: Past the heartbeat trust window (15m) AND past the entry TTL (30m).
    #:
    #: Both bounds matter and the value has to clear BOTH: a heartbeat aged
    #: past the preload window instead (4h+) describes a state that cannot
    #: arise from a session that simply died — entry and heartbeat freeze
    #: together — so a pin written against it can only pass.
    AGED = 45 * 60.0

    def _entry(self, agent_id: str, *, age: float, session_id: str | None) -> None:
        """Write one coordination entry with a controlled age and writer."""
        updated = datetime.now(timezone.utc) - timedelta(seconds=age)
        path = self.smm_dir / ".coordination.json"
        data = {}
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
        data[agent_id] = {
            "working_on": [],
            "updated": updated.isoformat(),
            "session_id": session_id,
        }
        path.write_text(json.dumps(data), encoding="utf-8")

    def _beat(self, session_id: str, *, age: float) -> Path:
        """Plant that session's heartbeat, aged by *age* seconds."""
        hook_liveness.write_heartbeat(
            self.smm_dir, session_id=session_id, now=time.time() - age
        )
        return markers.marker_path(
            self.smm_dir, hook_liveness.heartbeat_marker(session_id)
        )

    def _active(self) -> bool:
        return coordination.has_active_teammates(self.smm_dir, "main")


class TestTheWriterRecordsWhoWrote(_HookTestCase):
    """An entry has to say which SESSION wrote it, or liveness has nothing
    to look up."""

    def test_the_entry_carries_the_writing_session_id(self):
        with patch.dict(os.environ, _env(CLAUDE_CODE_SESSION_ID="sess-writer")):
            coordination.update_coordination(self.smm_dir, "other", ["src/a.ts"])
        data = coordination.read_coordination(self.smm_dir)
        self.assertEqual(data["other"]["session_id"], "sess-writer")

    def test_a_host_with_no_discoverable_id_records_none(self):
        """Not a failure — the reader takes None as "cannot tell" and keeps
        the TTL. Codex exports no session-id variable to hook processes, and
        must not be degraded to a wrong verdict for it."""
        with patch.dict(os.environ, _env()):
            coordination.update_coordination(self.smm_dir, "other", ["src/a.ts"])
        data = coordination.read_coordination(self.smm_dir)
        self.assertIsNone(data["other"]["session_id"])

    def test_disagreeing_candidates_record_none_rather_than_a_guess(self):
        """`resolve_session_id` REFUSES when two candidates disagree, because
        one was inherited from whichever agent launched this one and picking
        wrong aims the lookup at the LAUNCHER's heartbeat. The refusal must
        reach the file as "cannot tell", never as one of the two ids."""
        with patch.dict(
            os.environ,
            _env(XP_SESSION_ID="mine", CLAUDE_CODE_SESSION_ID="inherited"),
        ):
            coordination.update_coordination(self.smm_dir, "other", ["src/a.ts"])
        data = coordination.read_coordination(self.smm_dir)
        self.assertIsNone(data["other"]["session_id"])


class TestLivenessOverridesTheTtl(_LivenessTestCase):
    """The Stop gate's release, in both directions.

    `has_active_teammates` answered from a timestamp alone, and time is not
    liveness, so the gate erred BOTH ways: it released the lead on a dead
    agent whose entry was merely recent, and forgot a live-but-quiet teammate
    whose entry had aged out — after which the lead read that teammate's
    unresolved failing-test concern as its own and falsely blocked.

    Each row is paired with its opposite against the same planted marker, so
    a verdict that stopped tracking the heartbeat cannot stay green.
    """

    def test_fresh_entry_and_a_live_session_is_active(self):
        """Control for the row below: today's answer, and still the answer."""
        self._entry(self.TEAMMATE, age=self.FRESH, session_id=self.SESSION)
        self._beat(self.SESSION, age=self.FRESH)
        self.assertTrue(self._active())

    def test_fresh_entry_and_a_dead_session_is_not_active(self):
        """AC-1. Same entry, same marker, older heartbeat."""
        self._entry(self.TEAMMATE, age=self.FRESH, session_id=self.SESSION)
        self._beat(self.SESSION, age=self.AGED)
        self.assertFalse(self._active())

    def test_aged_entry_and_a_live_session_is_active(self):
        """AC-2. The lead must not block on a teammate's red suite as if it
        were its own just because that teammate went quiet for 30 minutes.

        `sprint_stop_gate` consumes this same predicate, so its verdict on an
        aged-but-live entry changes here too: release becomes defer. The
        gate-level pin belongs to the story that owns that suite.
        """
        self._entry(self.TEAMMATE, age=self.AGED, session_id=self.SESSION)
        self._beat(self.SESSION, age=self.FRESH)
        self.assertTrue(self._active())

    def test_aged_entry_and_a_dead_session_is_not_active(self):
        """Control for the row above: today's answer, and still the answer."""
        self._entry(self.TEAMMATE, age=self.AGED, session_id=self.SESSION)
        self._beat(self.SESSION, age=self.AGED)
        self.assertFalse(self._active())

    def test_the_agent_asking_is_never_its_own_teammate(self):
        """However alive it is."""
        self._entry("main", age=self.FRESH, session_id=self.SESSION)
        self._beat(self.SESSION, age=self.FRESH)
        self.assertFalse(self._active())

    def test_one_live_teammate_among_dead_ones_is_enough(self):
        self._entry("worktree-story-001", age=self.FRESH, session_id="dead-session")
        self._beat("dead-session", age=self.AGED)
        self._entry(self.TEAMMATE, age=self.AGED, session_id=self.SESSION)
        self._beat(self.SESSION, age=self.FRESH)
        self.assertTrue(self._active())


class TestADeadTeammateStopsCountingAtTheWindow(_LivenessTestCase):
    """The shape a session actually dies in, which is the one that regressed.

    A killed teammate stops writing BOTH files at the same instant, so neither
    clock advances afterwards; `_dead_for` plants them at the SAME age, which
    is the closest the two ever get (the heartbeat has extra writers — Bash,
    Skill, prompts — so in the field it is the younger of the two). Reading it
    against the four-hour preload window held such an entry active for four
    hours — far longer than the 30-minute TTL it replaced, in the direction the
    liveness leg exists to close.

    Every row plants one age into both files and asks the predicate the Stop
    gates ask. The pairs on either side of the window are what stop the
    threshold drifting back up.
    """

    def _dead_for(self, seconds: float) -> bool:
        """A teammate killed *seconds* ago: entry and heartbeat frozen together."""
        self._entry(self.TEAMMATE, age=seconds, session_id=self.SESSION)
        self._beat(self.SESSION, age=seconds)
        return self._active()

    def test_ten_minutes_dead_still_reads_active(self):
        """Inside the window the gate still waits — a teammate this quiet is
        far more likely mid-tool-call than dead."""
        self.assertTrue(self._dead_for(10 * 60))

    def test_forty_five_minutes_dead_reads_dead(self):
        self.assertFalse(self._dead_for(45 * 60))

    def test_two_hours_dead_reads_dead(self):
        self.assertFalse(self._dead_for(2 * 60 * 60))

    def test_five_hours_dead_reads_dead(self):
        """Past the preload window too, so this row passed either way — it is
        here to keep the row above honest about which window decided it."""
        self.assertFalse(self._dead_for(5 * 60 * 60))

    def test_just_inside_the_window_reads_live(self):
        self.assertTrue(self._dead_for(coordination._HEARTBEAT_TRUST_SECONDS - 60))

    def test_just_outside_the_window_reads_dead(self):
        self.assertFalse(self._dead_for(coordination._HEARTBEAT_TRUST_SECONDS + 60))

    def test_the_window_stays_below_the_entry_ttl(self):
        """The threshold tightens the answer the TTL gives for the shape above,
        where both clocks are equal. It cannot promise that in general — the
        heartbeat has writers the entry does not, so it may be much younger —
        which is exactly why the window is not also allowed to be the larger of
        the two numbers. See `_HEARTBEAT_TRUST_SECONDS`."""
        self.assertLess(
            coordination._HEARTBEAT_TRUST_SECONDS, coordination._COORDINATION_MAX_AGE
        )

    def test_the_preload_window_is_left_alone(self):
        """This is a caller-side threshold. The scan's own window is shared
        with the preload check, which is deliberately loose."""
        self.assertEqual(hook_liveness.STALE_AFTER_SECONDS, 4 * 60 * 60)


class TestUndeterminedLivenessKeepsTheTtl(_LivenessTestCase):
    """Undetermined falls back to today's behaviour, never to a verdict.

    Both directions of the TTL are pinned for each undetermined shape: a
    fallback that always answered one way would satisfy half of these while
    silently deleting the signal.
    """

    def test_an_entry_with_no_session_id_is_active_while_fresh(self):
        """AC-5. Backward compatibility with a .coordination.json written
        before the writer recorded who wrote it."""
        self._entry(self.TEAMMATE, age=self.FRESH, session_id=None)
        self.assertTrue(self._active())

    def test_an_entry_with_no_session_id_is_not_active_once_aged(self):
        self._entry(self.TEAMMATE, age=self.AGED, session_id=None)
        self.assertFalse(self._active())

    def test_a_legacy_entry_missing_the_key_entirely_still_reads(self):
        """The pre-change file shape: no `session_id` key at all, not a null."""
        path = self.smm_dir / ".coordination.json"
        updated = datetime.now(timezone.utc) - timedelta(seconds=self.FRESH)
        path.write_text(
            json.dumps(
                {self.TEAMMATE: {"working_on": [], "updated": updated.isoformat()}}
            ),
            encoding="utf-8",
        )
        self.assertTrue(self._active())

    def test_an_absent_heartbeat_is_active_while_fresh(self):
        """Absence is NOT death, however tempting.

        The heartbeat is keyed on the id the host handed the hook; this entry
        is keyed on the id the environment exposes. Where those sources
        differ, a live session's entry addresses a marker nothing ever writes
        — and a writer whose heartbeat write failed leaves the same hole. Read
        as death, either would hold the lead at Stop over a working teammate.
        """
        self._entry(self.TEAMMATE, age=self.FRESH, session_id=self.SESSION)
        self.assertTrue(self._active())

    def test_an_absent_heartbeat_is_not_active_once_aged(self):
        self._entry(self.TEAMMATE, age=self.AGED, session_id=self.SESSION)
        self.assertFalse(self._active())

    def test_a_corrupt_heartbeat_is_active_while_fresh(self):
        """Present-but-unreadable says nothing about the runtime. Reading it
        as death would turn a corrupt file into a released Stop gate."""
        self._entry(self.TEAMMATE, age=self.FRESH, session_id=self.SESSION)
        self._beat(self.SESSION, age=self.FRESH).write_text(
            "{not json", encoding="utf-8"
        )
        self.assertTrue(self._active())

    def test_a_corrupt_heartbeat_is_not_active_once_aged(self):
        self._entry(self.TEAMMATE, age=self.AGED, session_id=self.SESSION)
        self._beat(self.SESSION, age=self.FRESH).write_text(
            "{not json", encoding="utf-8"
        )
        self.assertFalse(self._active())


class TestOurOwnSessionsEntryIsNotASibling(_LivenessTestCase):
    """Our own beating heartbeat is not evidence that ANOTHER agent id lives.

    One session holds several agent ids. The verdict is scoped to VOUCHING, not
    to discarding: our heartbeat says nothing about whether that agent id lives,
    but the entry's own age does. Fresh counts, aged does not.
    """

    OURS = "the-leads-own-session"

    def _active_as(self) -> bool:
        with patch.dict(os.environ, _env(CLAUDE_CODE_SESSION_ID=self.OURS)):
            return self._active()

    def test_our_own_sessions_aged_entry_is_not_an_active_teammate(self):
        self._entry("subagent-42", age=self.AGED, session_id=self.OURS)
        self._beat(self.OURS, age=self.FRESH)
        self.assertFalse(self._active_as())

    def test_our_own_sessions_fresh_entry_still_counts(self):
        """RE-REVERSED. story-003 flipped this to "not a sibling" because no
        teammate can be in this state — true, but the gates ask whether someone
        else may be WRITING, and a backgrounded non-xp subagent does:
        `is_xp_agent` never skips it. The aged row keeps what story-003 removed.
        """
        self._entry("subagent-42", age=self.FRESH, session_id=self.OURS)
        self._beat(self.OURS, age=self.FRESH)
        self.assertTrue(self._active_as())

    def test_another_sessions_aged_entry_still_reads_live(self):
        """Over-narrowing control: the liveness leg itself must survive."""
        self._entry(self.TEAMMATE, age=self.AGED, session_id=self.SESSION)
        self._beat(self.SESSION, age=self.FRESH)
        self.assertTrue(self._active_as())


class TestReadCoordinationKeepsItsTtl(_LivenessTestCase):
    """The liveness leg is confined to `has_active_teammates`.

    A settled customer decision: teaching `read_coordination` about liveness
    would pin a live-but-quiet teammate's last-written file as a rival
    INDEFINITELY, since the 30-minute TTL is the only thing that frees it
    today. Its other callers — the write-conflict detector and the scaffold
    CLI — keep today's behaviour by construction.
    """

    def test_a_dead_agents_fresh_entry_is_still_returned(self):
        self._entry(self.TEAMMATE, age=self.FRESH, session_id=self.SESSION)
        self._beat(self.SESSION, age=self.AGED)
        self.assertIn(self.TEAMMATE, coordination.read_coordination(self.smm_dir))

    def test_a_live_agents_aged_entry_is_still_filtered_out(self):
        self._entry(self.TEAMMATE, age=self.AGED, session_id=self.SESSION)
        self._beat(self.SESSION, age=self.FRESH)
        self.assertNotIn(self.TEAMMATE, coordination.read_coordination(self.smm_dir))

    def test_the_write_conflict_detector_still_ignores_a_live_aged_rival(self):
        """The reason the confinement matters, asserted through the caller
        rather than inferred from the reader."""
        path = worktree.normalize_path("src/app.ts", "/project")
        self._entry(self.TEAMMATE, age=self.AGED, session_id=self.SESSION)
        data = json.loads((self.smm_dir / ".coordination.json").read_text())
        data[self.TEAMMATE]["working_on"] = [path]
        (self.smm_dir / ".coordination.json").write_text(json.dumps(data))
        self._beat(self.SESSION, age=self.FRESH)
        self.assertIsNone(
            pre_tool_write.check_working_on_overlap(
                self.smm_dir, "main", "src/app.ts", "/project"
            )
        )


if __name__ == "__main__":
    unittest.main()

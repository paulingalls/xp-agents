#!/usr/bin/env python3
"""Tests for retrospective sprint sizing, link rates, and sprint detection.

Split from test_retrospective.py.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase, make_event


class TestSprintSizingInRetro(_HookTestCase):
    """M3: when a sprint ended, .retro-input.json includes sizing_analysis."""

    def setUp(self):
        super().setUp()
        (self.smm_dir / "retrospectives").mkdir()

    def _setup_sprint_with_end(self, event_count: int = 8) -> list[dict]:
        """Write sprint.json and return events including sprint_end."""
        from conftest import _s, _sprint_json

        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s(
                        "story-001",
                        "Add auth",
                        "M",
                        "done",
                        file_domain=["scripts/auth.py \u2014 add login"],
                    ),
                    _s(
                        "story-002",
                        "Add tests",
                        "S",
                        "done",
                        file_domain=["tests/test_auth.py \u2014 auth tests"],
                    ),
                ],
                sprint_id="sprint-042",
                started="2026-04-01",
                goal="Build auth",
            )
        )
        events = [make_event(content=f"event {i}") for i in range(event_count)]
        events.append(
            make_event(
                "commit",
                content="Committed: add login",
                files=["scripts/auth.py"],
                ts="2026-04-05T10:00:00+00:00",
                metadata={
                    "code_commit": True,
                    "commit_hash": "abc123",
                    "story_id": "story-001",
                },
            )
        )
        events.append(
            make_event(
                "sprint",
                content="Sprint ended",
                metadata={"sprint_id": "sprint-042", "action": "end"},
            )
        )
        return events

    def test_sprint_ended_retro_input_has_sizing_analysis(self):
        import retrospective

        events = self._setup_sprint_with_end()
        self._write_events(events)

        result = retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertTrue((self.smm_dir / ".retro-input.json").exists())

        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        self.assertIn("sizing_analysis", data)
        sizing = data["sizing_analysis"]
        self.assertEqual(sizing["sprint_id"], "sprint-042")
        self.assertEqual(sizing["velocity"]["stories_delivered"], 2)
        self.assertIn("per_story", sizing)
        self.assertIn("per_size", sizing)

    def test_no_sprint_ended_no_sizing(self):
        import retrospective

        events = [make_event(content=f"event {i}") for i in range(6)]
        self._write_events(events)

        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        self.assertNotIn("sizing_analysis", data)

    def test_sprint_ended_below_threshold_still_fires(self):
        """Sprint end should bypass the RETRO_THRESHOLD and produce
        .retro-input.json with sizing_analysis even with few events."""
        import retrospective

        events = self._setup_sprint_with_end(event_count=2)
        self._write_events(events)

        result = retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertTrue((self.smm_dir / ".retro-input.json").exists())
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        self.assertIn("sizing_analysis", data)

    def test_sprint_ended_cleans_stale_sprint_retro_input(self):
        """Even with sprint end, old .sprint-retro-input.json is cleaned up."""
        import retrospective

        (self.smm_dir / ".sprint-retro-input.json").write_text('{"stale": true}')
        events = self._setup_sprint_with_end()
        self._write_events(events)

        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertFalse((self.smm_dir / ".sprint-retro-input.json").exists())
        self.assertTrue((self.smm_dir / ".retro-input.json").exists())

    def test_sizing_analysis_attributes_commits_to_stories(self):
        import retrospective

        events = self._setup_sprint_with_end()
        self._write_events(events)

        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        sizing = data["sizing_analysis"]
        story_001 = next(s for s in sizing["per_story"] if s["id"] == "story-001")
        self.assertEqual(story_001["commits"], 1)
        self.assertEqual(story_001["cascade_size"], 0)


class TestResolvesLinkRate(_HookTestCase):
    """Probe-to-commit adoption rate appears under sizing_analysis."""

    def setUp(self):
        super().setUp()
        (self.smm_dir / "retrospectives").mkdir()

    def _write_sprint_json(self) -> None:
        from conftest import _s, _sprint_json

        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [_s("story-001", "Work", "S", "done")],
                sprint_id="sprint-005",
                started="2026-04-01",
                goal="Resolves-trailer loop",
            )
        )

    def _probe(self, candidate_ids: list[str], ts: str, commit_hash: str) -> dict:
        return make_event(
            "status",
            content=f"resolves_probe_shown: {len(candidate_ids)} candidates",
            working_on=[],
            ts=ts,
            metadata={
                "probe_candidates": candidate_ids,
                "commit_hash": commit_hash,
            },
        )

    def _commit(self, resolves_ids: list[str], ts: str, commit_hash: str) -> dict:
        return make_event(
            "commit",
            content="Work",
            ts=ts,
            files=["scripts/x.py"],
            metadata={
                "code_commit": True,
                "commit_hash": commit_hash,
                "resolves": resolves_ids,
            },
        )

    def _sprint_end(self) -> dict:
        return make_event(
            "sprint",
            content="Sprint ended",
            metadata={"sprint_id": "sprint-005", "action": "end"},
        )

    def _run(self, events: list[dict]) -> dict:
        import retrospective

        self._write_events(events)
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            return json.load(f)

    def test_three_probes_two_hits_one_miss(self):
        self._write_sprint_json()
        events = [
            self._probe(["aaaaaaaaaaaa"], "2026-04-05T10:00:00+00:00", "h1"),
            self._commit(["aaaaaaaaaaaa"], "2026-04-05T10:01:00+00:00", "h1"),
            self._probe(["bbbbbbbbbbbb"], "2026-04-06T10:00:00+00:00", "h2"),
            self._commit(["bbbbbbbbbbbb"], "2026-04-06T10:01:00+00:00", "h2"),
            self._probe(["cccccccccccc"], "2026-04-07T10:00:00+00:00", "h3"),
            self._commit([], "2026-04-07T10:01:00+00:00", "h3"),
            self._sprint_end(),
        ]
        data = self._run(events)
        sizing = data["sizing_analysis"]
        self.assertEqual(sizing["resolves_probe_total"], 3)
        self.assertEqual(sizing["resolves_probe_hits"], 2)
        self.assertAlmostEqual(sizing["resolves_link_rate"], 2 / 3, places=6)

    def test_zero_probes_omits_fields(self):
        """No probe events -> fields absent. Retro pipeline does not crash."""
        self._write_sprint_json()
        events = [
            self._commit(["aaaaaaaaaaaa"], "2026-04-05T10:01:00+00:00", "h1"),
            make_event(content="filler 1"),
            make_event(content="filler 2"),
            make_event(content="filler 3"),
            make_event(content="filler 4"),
            self._sprint_end(),
        ]
        data = self._run(events)
        sizing = data["sizing_analysis"]
        self.assertNotIn("resolves_link_rate", sizing)
        self.assertNotIn("resolves_probe_hits", sizing)
        self.assertNotIn("resolves_probe_total", sizing)

    def test_probe_direct_hit(self):
        """Probe candidates=[X] + commit resolves=[X] -> hit."""
        self._write_sprint_json()
        events = [
            self._probe(["abc123def456"], "2026-04-05T10:00:00+00:00", "h1"),
            self._commit(["abc123def456"], "2026-04-05T10:01:00+00:00", "h1"),
            self._sprint_end(),
        ]
        data = self._run(events)
        sizing = data["sizing_analysis"]
        self.assertEqual(sizing["resolves_probe_total"], 1)
        self.assertEqual(sizing["resolves_probe_hits"], 1)
        self.assertEqual(sizing["resolves_link_rate"], 1.0)

    def test_probe_miss_empty_resolves(self):
        """Probe + commit with empty resolves -> miss."""
        self._write_sprint_json()
        events = [
            self._probe(["abc123def456"], "2026-04-05T10:00:00+00:00", "h1"),
            self._commit([], "2026-04-05T10:01:00+00:00", "h1"),
            self._sprint_end(),
        ]
        data = self._run(events)
        sizing = data["sizing_analysis"]
        self.assertEqual(sizing["resolves_probe_total"], 1)
        self.assertEqual(sizing["resolves_probe_hits"], 0)
        self.assertEqual(sizing["resolves_link_rate"], 0.0)

    def test_probe_before_sprint_start_ignored(self):
        """Probes from before the sprint's started date do not count."""
        self._write_sprint_json()
        events = [
            self._probe(["aaaaaaaaaaaa"], "2026-03-15T10:00:00+00:00", "h0"),
            self._commit([], "2026-03-15T10:01:00+00:00", "h0"),
            self._probe(["bbbbbbbbbbbb"], "2026-04-05T10:00:00+00:00", "h1"),
            self._commit([], "2026-04-05T10:01:00+00:00", "h1"),
            self._sprint_end(),
        ]
        data = self._run(events)
        sizing = data["sizing_analysis"]
        self.assertEqual(sizing["resolves_probe_total"], 1)
        self.assertEqual(sizing["resolves_probe_hits"], 0)


class TestResolvesLinkRatePerAgent(unittest.TestCase):
    """per_agent rates scoped to each agent's probe+commit pairs."""

    def _probe(self, candidate_ids, ts, commit_hash, agent_id="main"):
        return make_event(
            "status",
            content=(f"resolves_probe_shown: {len(candidate_ids)} candidates"),
            working_on=[],
            ts=ts,
            agent_id=agent_id,
            metadata={
                "probe_candidates": candidate_ids,
                "commit_hash": commit_hash,
            },
        )

    def _commit(self, resolves_ids, ts, commit_hash, agent_id="main"):
        return make_event(
            "commit",
            content="Work",
            ts=ts,
            files=["scripts/x.py"],
            agent_id=agent_id,
            metadata={
                "code_commit": True,
                "commit_hash": commit_hash,
                "resolves": resolves_ids,
            },
        )

    def test_per_agent_link_rate_two_agents(self):
        """Two agents: agent-1 hits, agent-2 misses -- per_agent scoped."""
        import retro_metrics

        events = [
            self._probe(["aaa"], "2026-04-05T10:00:00+00:00", "h1", "agent-1"),
            self._commit(["aaa"], "2026-04-05T10:01:00+00:00", "h1", "agent-1"),
            self._probe(["bbb"], "2026-04-05T10:00:00+00:00", "h2", "agent-2"),
            self._commit([], "2026-04-05T10:01:00+00:00", "h2", "agent-2"),
        ]
        result = retro_metrics._compute_resolves_link_rate(events, "2026-04-01")
        self.assertIn("per_agent", result)
        pa = result["per_agent"]
        self.assertEqual(len(pa), 2)
        self.assertEqual(pa["agent-1"]["resolves_probe_hits"], 1)
        self.assertEqual(pa["agent-1"]["resolves_probe_total"], 1)
        self.assertEqual(pa["agent-1"]["resolves_link_rate"], 1.0)
        self.assertEqual(pa["agent-2"]["resolves_probe_hits"], 0)
        self.assertEqual(pa["agent-2"]["resolves_probe_total"], 1)
        self.assertEqual(pa["agent-2"]["resolves_link_rate"], 0.0)


def _sprint_start(sprint_id: str) -> dict:
    return make_event(
        "sprint",
        content=f"Sprint {sprint_id} started",
        metadata={"sprint_id": sprint_id, "action": "start"},
    )


def _sprint_end(sprint_id: str) -> dict:
    return make_event(
        "sprint",
        content=f"Sprint {sprint_id} ended",
        metadata={"sprint_id": sprint_id, "action": "end"},
    )


def _sprint_retro_done(sprint_id: str) -> dict:
    return make_event(
        "status",
        content="Sprint retrospective complete.",
        metadata={"sprint_id": sprint_id, "action": "sprint_retro_done"},
    )


class TestNeedsSprintRetro(unittest.TestCase):
    """needs_sprint_retro(events) returns sprint_id or None."""

    def test_dangling_sprint_end_returns_sprint_id(self):
        import retrospective

        events = [
            _sprint_start("s-001"),
            make_event(content="work during sprint"),
            _sprint_end("s-001"),
            make_event(content="post-sprint activity"),
        ]
        self.assertEqual(retrospective.needs_sprint_retro(events), "s-001")

    def test_sprint_end_with_matching_retro_done_returns_none(self):
        import retrospective

        events = [
            _sprint_start("s-001"),
            _sprint_end("s-001"),
            _sprint_retro_done("s-001"),
            make_event(content="post-retro activity"),
        ]
        self.assertIsNone(retrospective.needs_sprint_retro(events))

    def test_no_sprint_end_returns_none(self):
        import retrospective

        events = [
            _sprint_start("s-001"),
            make_event(content="mid-sprint work"),
        ]
        self.assertIsNone(retrospective.needs_sprint_retro(events))

    def test_empty_events_returns_none(self):
        import retrospective

        self.assertIsNone(retrospective.needs_sprint_retro([]))

    def test_abandoned_sprint_returns_none(self):
        import retrospective

        events = [
            _sprint_start("s-001"),
            _sprint_end("s-001"),
            _sprint_start("s-002"),
            make_event(content="new sprint work"),
        ]
        self.assertIsNone(retrospective.needs_sprint_retro(events))

    def test_stale_retro_done_different_sprint_id(self):
        import retrospective

        events = [
            _sprint_start("s-001"),
            _sprint_end("s-001"),
            _sprint_retro_done("s-001"),
            _sprint_start("s-002"),
            _sprint_end("s-002"),
        ]
        self.assertEqual(retrospective.needs_sprint_retro(events), "s-002")

    def test_most_recent_sprint_end_checked(self):
        import retrospective

        events = [
            _sprint_end("s-001"),
            _sprint_retro_done("s-001"),
            _sprint_end("s-002"),
            _sprint_retro_done("s-002"),
            _sprint_end("s-003"),
        ]
        self.assertEqual(retrospective.needs_sprint_retro(events), "s-003")


if __name__ == "__main__":
    unittest.main()

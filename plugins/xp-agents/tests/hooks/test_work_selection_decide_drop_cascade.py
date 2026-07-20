#!/usr/bin/env python3
"""Tests for work_selection_decide.py — drop's content-cascade resolution and
--force-drop's optional convention emission.

`drop` scans content for debt/concern/discovery hex IDs and cascades: when a
Try mentions an underlying open debt/concern/discovery event by its 12-hex ID
in prose (not just in `[refs: ...]`), dropping the Try must also resolve the
root events — otherwise the retro agent sees the root still open and
re-proposes a fresh Try every session. `--force-drop` can additionally emit a
durable `convention` suppression event via --record-convention-topic/-content.

Split from test_work_selection_decide.py to stay under the file-size budget.
Shared base TestCases live in _work_selection_decide_helpers.py.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(
    0,
    str(
        Path(__file__).parent.parent.parent / "skills" / "xp-work-selection" / "scripts"
    ),
)

import work_selection_decide
from _work_selection_decide_helpers import _DecideTestCase, _ForceCloseTestCase
from conftest import make_event
from event_schema import (
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_CONVENTION,
    EVENT_TYPE_DEBT,
    EVENT_TYPE_DECISION,
    EVENT_TYPE_DISCOVERY,
    EVENT_TYPE_QUESTION,
    EVENT_TYPE_STATUS,
)


class TestDropContentCascade(_DecideTestCase):
    """drop scans content for debt/concern/discovery hex IDs and cascades.

    When a Try mentions an underlying open debt/concern/discovery event by
    its 12-hex ID in prose (not just in `[refs: ...]`), dropping the Try
    must also resolve the root events — otherwise the retro agent sees the
    root still open and re-proposes a fresh Try every session. Cascade
    scope mirrors PROBE_RESOLVABLE_TYPES (debt + concern + discovery).
    """

    def _seed_event(
        self,
        event_type: str,
        event_id: str,
        extra: dict | None = None,
    ) -> dict:
        kwargs: dict = {"id": event_id, "content": f"seeded {event_type}"}
        if extra:
            kwargs.update(extra)
        event = make_event(event_type, **kwargs)
        existing = self._read_events()
        self._write_events([*existing, event])
        return event

    def test_drop_resolves_debt_in_content(self):
        debt = self._seed_event(EVENT_TYPE_DEBT, "9c3f5406cacd", {"files": ["x.py"]})
        self.mod.run(
            action="drop",
            smm_dir=self.smm_dir,
            content=f"1Password debt {debt['id']}: close with rationale",
        )
        event = self._last_event()
        self.assertEqual(event["metadata"]["disposition"], "dropped")
        self.assertIn(debt["id"], event["metadata"].get("resolves", []))

    def test_drop_cascade_survives_content_truncation(self):
        """A debt id mentioned past the 200-char budget still cascades.

        Guards fix ordering: cascade hex-token scan must run on the full
        content BEFORE the budget truncation, or a trailing id is lost.
        """
        debt = self._seed_event(EVENT_TYPE_DEBT, "9c3f5406cacd", {"files": ["x.py"]})
        prose = "Drop this Try " + "z" * 220 + f" closes {debt['id']}"
        self.assertGreater(prose.index(debt["id"]), 200)
        self.mod.run(action="drop", smm_dir=self.smm_dir, content=prose)
        event = self._last_event()
        self.assertLessEqual(len(event["content"]), 200)
        self.assertIn(debt["id"], event["metadata"].get("resolves", []))

    def test_drop_resolves_concern_in_content(self):
        concern = self._seed_event(
            EVENT_TYPE_CONCERN, "aaaaaaaaaaaa", {"severity": "medium", "files": []}
        )
        self.mod.run(
            action="drop",
            smm_dir=self.smm_dir,
            content=f"Concern {concern['id']} won't resolve — drop it",
        )
        event = self._last_event()
        self.assertIn(concern["id"], event["metadata"].get("resolves", []))

    def test_drop_resolves_discovery_in_content(self):
        discovery = self._seed_event(
            EVENT_TYPE_DISCOVERY, "bbbbbbbbbbbb", {"references": ["referenced-id"]}
        )
        self.mod.run(
            action="drop",
            smm_dir=self.smm_dir,
            content=f"Discovery {discovery['id']} no longer relevant",
        )
        event = self._last_event()
        self.assertIn(discovery["id"], event["metadata"].get("resolves", []))

    def test_drop_ignores_question_hex_token(self):
        question = self._seed_event(
            EVENT_TYPE_QUESTION, "cccccccccccc", {"priority": "\U0001f534"}
        )
        self.mod.run(
            action="drop",
            smm_dir=self.smm_dir,
            content=f"Question {question['id']} mentioned but not for cascade",
        )
        event = self._last_event()
        self.assertNotIn(question["id"], event["metadata"].get("resolves", []))

    def test_drop_ignores_decision_hex_token(self):
        decision = self._seed_event(
            EVENT_TYPE_DECISION, "dddddddddddd", {"topic": "some-topic"}
        )
        self.mod.run(
            action="drop",
            smm_dir=self.smm_dir,
            content=f"Per decision {decision['id']}, dropping this Try",
        )
        event = self._last_event()
        self.assertNotIn(decision["id"], event["metadata"].get("resolves", []))

    def test_drop_ignores_unknown_hex_token(self):
        self.mod.run(
            action="drop",
            smm_dir=self.smm_dir,
            content="Drop with stray hex eeeeeeeeeeee not matching any event",
        )
        event = self._last_event()
        self.assertNotIn("eeeeeeeeeeee", event["metadata"].get("resolves", []))

    def test_drop_dedupes_debt_id_in_both_content_and_refs_suffix(self):
        debt = self._seed_event(EVENT_TYPE_DEBT, "ffffffffffff", {"files": ["x.py"]})
        self.mod.run(
            action="drop",
            smm_dir=self.smm_dir,
            content=f"Debt {debt['id']} done [refs: {debt['id']}]",
        )
        event = self._last_event()
        resolves = event["metadata"].get("resolves", [])
        self.assertEqual(resolves.count(debt["id"]), 1)

    def test_force_drop_also_resolves_debt_in_content(self):
        debt = self._seed_event(EVENT_TYPE_DEBT, "111111111111", {"files": ["x.py"]})
        # Seed prior defers so force-drop is the only path through.
        prior_defers = [
            {
                "id": f"{i:012x}",
                "ts": f"2026-01-{i + 1:02d}T00:00:00+00:00",
                "type": EVENT_TYPE_STATUS,
                "agent_id": "main",
                "content": f"Defer {i}",
                "schema_version": 1,
                "working_on": [],
                "metadata": {
                    "resolves": ["aaaaaaaaaaaa"],
                    "disposition": "deferred",
                },
            }
            for i in range(3)
        ]
        existing = self._read_events()
        self._write_events([*existing, *prior_defers])
        self.mod.run(
            action="defer",
            smm_dir=self.smm_dir,
            content=f"Drop debt {debt['id']} [refs: aaaaaaaaaaaa]",
            force_drop=True,
        )
        event = self._last_event()
        self.assertEqual(event["metadata"]["disposition"], "dropped")
        self.assertIn(debt["id"], event["metadata"]["resolves"])

    def test_drop_resolves_multiple_debts_in_content(self):
        debt1 = self._seed_event(EVENT_TYPE_DEBT, "222222222222", {"files": ["a.py"]})
        debt2 = self._seed_event(EVENT_TYPE_DEBT, "333333333333", {"files": ["b.py"]})
        self.mod.run(
            action="drop",
            smm_dir=self.smm_dir,
            content=f"Drop both: {debt1['id']} and {debt2['id']}",
        )
        resolves = self._last_event()["metadata"].get("resolves", [])
        self.assertIn(debt1["id"], resolves)
        self.assertIn(debt2["id"], resolves)

    def test_drop_with_no_hex_tokens_skips_events_read(self):
        """Perf guard: bare prose drops must not scan events.jsonl.

        Protects the `if tokens:` short-circuit so future refactors can't
        accidentally make every drop O(events). Resolves concern eab4b083f5bf.
        """
        from unittest.mock import patch

        with patch.object(
            work_selection_decide._common, "read_events_locked"
        ) as mock_read:
            self.mod.run(
                action="drop",
                smm_dir=self.smm_dir,
                content="Drop forever, no hex tokens in prose",
            )
            mock_read.assert_not_called()


class TestForceDropConventionEmission(_ForceCloseTestCase):
    """--record-convention-topic + --record-convention-content on a
    `defer --force-drop` emits a convention event in addition to the drop
    status event. The convention is a durable suppression record so the
    retro agent won't re-propose the Try under any signal.

    Force-drop is the canonical "user explicitly rejects, never re-propose"
    moment — regular drops are one-shot per Wisdom and don't get a
    convention prompt (per design call).
    """

    def test_force_drop_with_convention_flags_emits_two_events(self):
        self._seed_prior_defers("aaaaaaaaaaaa", 3)
        self.mod.run(
            action="defer",
            smm_dir=self.smm_dir,
            content="Drop forever [refs: aaaaaaaaaaaa]",
            force_drop=True,
            convention_topic="retro-drop-security-review-diff-only",
            convention_content=(
                "/security-review is diff-only; never propose for docs-only changes."
            ),
        )
        events = self._read_events()
        # 3 seeded prior-defers + drop + convention
        self.assertEqual(len(events), 5)
        self.assertEqual(events[-2]["type"], EVENT_TYPE_STATUS)
        self.assertEqual(events[-2]["metadata"]["disposition"], "dropped")
        convention = events[-1]
        self.assertEqual(convention["type"], EVENT_TYPE_CONVENTION)
        self.assertEqual(convention["topic"], "retro-drop-security-review-diff-only")
        self.assertIn("diff-only", convention["content"])

    def test_force_drop_convention_overbudget_content_truncates(self):
        """An over-budget convention rationale truncates rather than failing.

        Mirrors the main-event chokepoint so the convention path can't raise
        "Content exceeds convention budget" and abort the drop's record.
        """
        self._seed_prior_defers("aaaaaaaaaaaa", 3)
        long_rationale = "Never re-propose this kind of Try because " + "w" * 250
        self.assertGreater(len(long_rationale), 250)
        self.mod.run(
            action="defer",
            smm_dir=self.smm_dir,
            content="Drop forever [refs: aaaaaaaaaaaa]",
            force_drop=True,
            convention_topic="retro-drop-overbudget-rationale",
            convention_content=long_rationale,
        )
        convention = self._read_events()[-1]
        self.assertEqual(convention["type"], EVENT_TYPE_CONVENTION)
        self.assertLessEqual(len(convention["content"]), 250)

    def test_force_drop_without_convention_flags_emits_only_drop(self):
        """Default behavior unchanged: force-drop alone emits one event."""
        self._seed_prior_defers("aaaaaaaaaaaa", 3)
        self.mod.run(
            action="defer",
            smm_dir=self.smm_dir,
            content="Drop forever [refs: aaaaaaaaaaaa]",
            force_drop=True,
        )
        events = self._read_events()
        self.assertEqual(len(events), 4)
        self.assertEqual(events[-1]["type"], EVENT_TYPE_STATUS)
        self.assertEqual(events[-1]["metadata"]["disposition"], "dropped")

    def test_regular_drop_rejects_convention_flags(self):
        """Convention prompt is force-drop only — plain `drop` rejects."""
        with self.assertRaises(ValueError) as ctx:
            self.mod.run(
                action="drop",
                smm_dir=self.smm_dir,
                content="Drop now",
                convention_topic="retro-drop-test",
                convention_content="rationale",
            )
        self.assertIn("force-drop", str(ctx.exception).lower())

    def test_convention_emission_is_idempotent(self):
        """Second invocation with same topic appends the drop but NOT a
        second convention. The discarded rationale surfaces on stderr —
        silent skipping would lose user signal.
        """
        import io
        from contextlib import redirect_stderr

        self._seed_prior_defers("aaaaaaaaaaaa", 3)
        self.mod.run(
            action="defer",
            smm_dir=self.smm_dir,
            content="Drop forever [refs: aaaaaaaaaaaa]",
            force_drop=True,
            convention_topic="retro-drop-test-foo",
            convention_content="rationale 1",
        )
        # Second force-drop against same topic — convention MUST be skipped
        # AND the second rationale's loss must surface on stderr (honesty).
        err = io.StringIO()
        with redirect_stderr(err):
            self.mod.run(
                action="defer",
                smm_dir=self.smm_dir,
                content="Drop again [refs: aaaaaaaaaaaa]",
                force_drop=True,
                convention_topic="retro-drop-test-foo",
                convention_content="rationale 2",
            )
        self.assertIn("retro-drop-test-foo", err.getvalue())
        self.assertIn("already recorded", err.getvalue())

        events = self._read_events()
        conventions = [e for e in events if e.get("type") == "convention"]
        self.assertEqual(len(conventions), 1)
        # First write wins
        self.assertIn("rationale 1", conventions[0]["content"])
        # Two drop events should exist (one per force-drop call)
        drops = [
            e
            for e in events
            if e.get("type") == EVENT_TYPE_STATUS
            and (e.get("metadata") or {}).get("disposition") == "dropped"
        ]
        self.assertEqual(len(drops), 2)

    def test_convention_topic_must_use_retro_drop_prefix(self):
        """Slug without retro-drop- prefix rejected to avoid collision
        with retro-try-<slug> adoption topics.
        """
        self._seed_prior_defers("aaaaaaaaaaaa", 3)
        with self.assertRaises(ValueError) as ctx:
            self.mod.run(
                action="defer",
                smm_dir=self.smm_dir,
                content="Drop forever [refs: aaaaaaaaaaaa]",
                force_drop=True,
                convention_topic="security-review-diff-only",
                convention_content="rationale",
            )
        self.assertIn("retro-drop-", str(ctx.exception))

    def test_convention_topic_must_be_kebab_case(self):
        """Topic must match ^[a-z0-9]+(-[a-z0-9]+)+$ (after prefix)."""
        self._seed_prior_defers("aaaaaaaaaaaa", 3)
        with self.assertRaises(ValueError) as ctx:
            self.mod.run(
                action="defer",
                smm_dir=self.smm_dir,
                content="Drop forever [refs: aaaaaaaaaaaa]",
                force_drop=True,
                convention_topic="retro-drop-NotKebab_Case",
                convention_content="rationale",
            )
        self.assertIn("kebab", str(ctx.exception).lower())

    def test_convention_flags_require_both_or_neither(self):
        """Topic without content (or vice versa) rejected."""
        self._seed_prior_defers("aaaaaaaaaaaa", 3)
        with self.assertRaises(ValueError):
            self.mod.run(
                action="defer",
                smm_dir=self.smm_dir,
                content="Drop forever [refs: aaaaaaaaaaaa]",
                force_drop=True,
                convention_topic="retro-drop-foo",
                # content missing
            )

    def test_convention_flags_require_force_drop(self):
        """--force-adopt or --force-defer-with-date must not silently
        accept the convention flags; only --force-drop honors them.
        """
        self._seed_prior_defers("aaaaaaaaaaaa", 3)
        with self.assertRaises(ValueError) as ctx:
            self.mod.run(
                action="defer",
                smm_dir=self.smm_dir,
                content="Adopt [refs: aaaaaaaaaaaa]",
                force_adopt_topic="retro-try-foo",
                convention_topic="retro-drop-foo",
                convention_content="rationale",
            )
        self.assertIn("force-drop", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()

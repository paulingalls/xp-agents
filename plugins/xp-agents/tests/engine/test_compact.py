#!/usr/bin/env python3
"""Tests for compaction logic (legacy compact entry point).

Curation-watermark-based compaction tests in test_compact_curation.py.
"""

import ast
import importlib
import json
import sys
import unittest
from pathlib import Path
from typing import ClassVar, NamedTuple

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
# `as es` alias is load-bearing: TestEventTypeMatchCompleteness reads
# `es.VALID_TYPES` and uses dynamic `getattr(es, name)` to introspect
# `EVENT_TYPE_*` constants by string name extracted from match-case AST.
# Don't drop it just because the EVENT_TYPE_* names are also imported below.
import event_schema as es
import materialize
from conftest import _SMMTestCase, make_event

# Explicit `from event_schema import EVENT_TYPE_*` so a future constant rename
# fails at test collection (NameError) instead of silently changing a
# make_event(...) call's behavior.
from event_schema import (
    EVENT_TYPE_ANSWER,
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_CUSTOMER_INPUT,
    EVENT_TYPE_DECISION,
    EVENT_TYPE_GOAL,
    EVENT_TYPE_QUESTION,
    EVENT_TYPE_SESSION_STARTED,
    EVENT_TYPE_STATUS,
)


class _MatchBlockSpec(NamedTuple):
    module_filename: str
    function_name: str
    subject_text: str
    allowlist_name: str | None


# ===========================================================================
# Compact (Milestone 8)
# ===========================================================================


class TestCompact(_SMMTestCase):
    """Tests for compact() legacy entry point (delegates to compact_after_curation)."""

    def _make_session(self, event_count: int = 3, session_num: int = 1) -> list[dict]:
        """Create a session: N events + a session_started boundary anchor."""
        ts_base = f"2026-03-{session_num:02d}T00:00:00+00:00"
        events = [
            make_event(
                EVENT_TYPE_CUSTOMER_INPUT,
                content=f"session {session_num} event {i}",
                ts=ts_base,
            )
            for i in range(event_count)
        ]
        events.append(
            make_event(
                EVENT_TYPE_SESSION_STARTED,
                content=f"start session {session_num}",
                ts=ts_base,
            )
        )
        return events

    def test_compact_empty_log(self):
        import compact

        result = compact.compact(self.smm_dir)
        self.assertEqual(result["archived"], 0)
        self.assertEqual(result["retained"], 0)

    def test_compact_delegates_to_compact_after_curation(self):
        """compact() uses curation-watermark-based retention via delegation."""
        import compact

        goal = make_event(
            EVENT_TYPE_GOAL, content="keep me", ts="2026-01-01T00:00:00+00:00"
        )
        filler = make_event(
            EVENT_TYPE_STATUS, content="discard", ts="2026-01-01T00:00:00+00:00"
        )
        session_started = make_event(
            EVENT_TYPE_SESSION_STARTED,
            content="start",
            ts="2026-01-02T00:00:00+00:00",
        )
        new_event = make_event(
            EVENT_TYPE_STATUS, content="new", ts="2026-02-01T00:00:00+00:00"
        )
        self._write_events([goal, filler, session_started, new_event])
        materialize.write_curation_watermark(self.smm_dir, 3, "xp-housekeeper")

        result = compact.compact(self.smm_dir)
        retained = self._read_events()
        retained_ids = {e["id"] for e in retained}
        # Unresolved goal retained (SMM-referenced)
        self.assertIn(goal["id"], retained_ids)
        # Filler archived
        self.assertNotIn(filler["id"], retained_ids)
        # Return has legacy keys
        self.assertIn("archived", result)
        self.assertIn("retained", result)
        self.assertIn("permanent", result)

    def test_compact_retains_last_3_session_started_anchors(self):
        """session_started anchors are the M2 aging boundary — the last 3
        must survive compaction or sessions_since_event loses its anchors
        and every aging count collapses to 0 (the re-anchor goes inert)."""
        import compact

        anchors = [
            make_event(
                EVENT_TYPE_SESSION_STARTED,
                content=f"start {i}",
                ts=f"2026-01-0{i}T00:00:00+00:00",
            )
            for i in range(1, 5)  # s1..s4, oldest first
        ]
        new_event = make_event(
            EVENT_TYPE_STATUS, content="new", ts="2026-02-01T00:00:00+00:00"
        )
        self._write_events([*anchors, new_event])
        materialize.write_curation_watermark(self.smm_dir, 4, "xp-housekeeper")

        compact.compact(self.smm_dir)
        retained_ids = {e["id"] for e in self._read_events()}

        # Last 3 anchors retained as aging boundaries.
        self.assertIn(anchors[1]["id"], retained_ids)
        self.assertIn(anchors[2]["id"], retained_ids)
        self.assertIn(anchors[3]["id"], retained_ids)
        # Oldest anchor beyond the 3-cap is archived.
        self.assertNotIn(anchors[0]["id"], retained_ids)

    def test_compact_unresolved_questions_retained(self):
        """Unresolved questions retained via SMM-referenced policy."""
        import compact

        q = make_event(
            EVENT_TYPE_QUESTION,
            content="Unanswered?",
            priority="\U0001f534",
            ts="2026-01-01T00:00:00+00:00",
        )
        filler = make_event(
            EVENT_TYPE_STATUS, content="filler", ts="2026-01-01T00:00:00+00:00"
        )
        session_started = make_event(
            EVENT_TYPE_SESSION_STARTED,
            content="start",
            ts="2026-01-02T00:00:00+00:00",
        )
        self._write_events([q, filler, session_started])
        materialize.write_curation_watermark(self.smm_dir, 3, "xp-housekeeper")

        compact.compact(self.smm_dir)
        retained = self._read_events()
        retained_ids = {e["id"] for e in retained}
        self.assertIn(q["id"], retained_ids)

    def test_compact_resolved_questions_archivable(self):
        """Resolved questions before watermark can be archived."""
        import compact

        q = make_event(
            EVENT_TYPE_QUESTION,
            content="Answered",
            priority="\U0001f534",
            ts="2026-01-01T00:00:00+00:00",
        )
        a = make_event(
            EVENT_TYPE_ANSWER,
            content="Yes",
            references=[q["id"]],
            ts="2026-01-01T00:00:01+00:00",
        )
        session_started = make_event(
            EVENT_TYPE_SESSION_STARTED,
            content="start",
            ts="2026-01-02T00:00:00+00:00",
        )
        self._write_events([q, a, session_started])
        materialize.write_curation_watermark(self.smm_dir, 3, "xp-housekeeper")

        compact.compact(self.smm_dir)
        retained = self._read_events()
        retained_ids = {e["id"] for e in retained}
        self.assertNotIn(q["id"], retained_ids)

    def test_compact_unresolved_concerns_retained(self):
        """Unresolved concerns retained via SMM-referenced policy."""
        import compact

        c = make_event(
            EVENT_TYPE_CONCERN,
            content="Unresolved concern",
            ts="2026-01-01T00:00:00+00:00",
        )
        session_started = make_event(
            EVENT_TYPE_SESSION_STARTED,
            content="start",
            ts="2026-01-02T00:00:00+00:00",
        )
        self._write_events([c, session_started])
        materialize.write_curation_watermark(self.smm_dir, 2, "xp-housekeeper")

        compact.compact(self.smm_dir)
        retained = self._read_events()
        retained_ids = {e["id"] for e in retained}
        self.assertIn(c["id"], retained_ids)

    def test_compact_creates_archive(self):
        """Archived events written to backups/archive-{ts}.jsonl."""
        import compact

        old = self._make_session(session_num=1)
        new_event = make_event(
            EVENT_TYPE_STATUS, content="new", ts="2026-02-01T00:00:00+00:00"
        )
        self._write_events([*old, new_event])
        materialize.write_curation_watermark(self.smm_dir, len(old), "xp-housekeeper")

        compact.compact(self.smm_dir)
        backups = self.smm_dir / "backups"
        self.assertTrue(backups.exists())
        archives = list(backups.glob("archive-*.jsonl"))
        self.assertEqual(len(archives), 1)
        archive_text = archives[0].read_text().strip()
        self.assertGreater(len(archive_text), 0)

    def test_compact_removes_orphaned_watermarks(self):
        """Orphaned .watermark-* files removed, prompt-nugget reset."""
        import compact

        self._write_events(self._make_session(session_num=1))
        materialize.write_curation_watermark(self.smm_dir, 4, "xp-housekeeper")
        (self.smm_dir / ".watermark-main").write_text("5")
        (self.smm_dir / ".watermark-housekeeping").write_text("3")
        (self.smm_dir / ".watermark-prompt-nugget").write_text("10")

        compact.compact(self.smm_dir)
        # Orphaned removed
        self.assertFalse((self.smm_dir / ".watermark-main").exists())
        self.assertFalse((self.smm_dir / ".watermark-housekeeping").exists())
        # Prompt-nugget preserved with updated value
        self.assertTrue((self.smm_dir / ".watermark-prompt-nugget").exists())

    def test_compact_atomic_replacement(self):
        """events.jsonl is replaced atomically (not corrupted on crash)."""
        import compact

        events = self._make_session(session_num=1)
        self._write_events(events)
        materialize.write_curation_watermark(
            self.smm_dir, len(events), "xp-housekeeper"
        )
        compact.compact(self.smm_dir)
        for line in (self.smm_dir / "events.jsonl").read_text().splitlines():
            line = line.strip()
            if line:
                json.loads(line)  # Should not raise

    def test_compact_no_watermark_no_archival(self):
        """Without curation watermark, nothing is archived."""
        import compact

        self._write_events(self._make_session(session_num=1))
        result = compact.compact(self.smm_dir)
        self.assertEqual(result["archived"], 0)

    def test_compact_returns_counts(self):
        """Return dict has archived, retained, permanent keys."""
        import compact

        old = self._make_session(session_num=1)
        new_event = make_event(
            EVENT_TYPE_STATUS, content="new", ts="2026-02-01T00:00:00+00:00"
        )
        self._write_events([*old, new_event])
        materialize.write_curation_watermark(self.smm_dir, len(old), "xp-housekeeper")

        result = compact.compact(self.smm_dir)
        self.assertIn("archived", result)
        self.assertIn("retained", result)
        self.assertIn("permanent", result)
        self.assertEqual(
            result["archived"] + result["retained"],
            len(old) + 1,
        )

    def test_compact_preserves_event_order(self):
        """Retained events maintain original order."""
        import compact

        decision = make_event(
            EVENT_TYPE_DECISION,
            content="first",
            topic="t",
            ts="2026-01-01T00:00:00+00:00",
        )
        session_started = make_event(
            EVENT_TYPE_SESSION_STARTED,
            content="start",
            ts="2026-01-02T00:00:00+00:00",
        )
        new_event = make_event(
            EVENT_TYPE_STATUS, content="new", ts="2026-02-01T00:00:00+00:00"
        )
        self._write_events([decision, session_started, new_event])
        materialize.write_curation_watermark(self.smm_dir, 2, "xp-housekeeper")

        compact.compact(self.smm_dir)
        retained = self._read_events()
        ids = [e["id"] for e in retained]
        self.assertEqual(ids[0], decision["id"])


# ===========================================================================
# Match-block completeness smoke (story-005)
# ===========================================================================


def _find_function(tree: ast.AST, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Function {name!r} not found in source")


def _find_match_node(func: ast.FunctionDef, subject_text: str) -> ast.Match:
    candidates = [
        n
        for n in ast.walk(func)
        if isinstance(n, ast.Match) and ast.unparse(n.subject) == subject_text
    ]
    if not candidates:
        raise AssertionError(
            f"No Match node with subject {subject_text!r} in {func.name!r}"
        )
    if len(candidates) > 1:
        raise AssertionError(
            f"Multiple Match nodes with subject {subject_text!r} in "
            f"{func.name!r}; subject must uniquely identify the block"
        )
    return candidates[0]


def _collect_case_values(pattern: ast.AST) -> set[str]:
    """Return string values matched by a case pattern, or {'_'} for wildcard.

    Raises AssertionError on unrecognized pattern shapes — silent skip would
    let a future MatchSingleton/MatchClass/MatchSequence false-pass the gate.
    """
    if isinstance(pattern, ast.MatchAs) and pattern.pattern is None:
        return {"_"}
    if isinstance(pattern, ast.MatchOr):
        return {v for sub in pattern.patterns for v in _collect_case_values(sub)}
    if isinstance(pattern, ast.MatchValue):
        value = pattern.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return {value.value}
        if isinstance(value, ast.Attribute) and value.attr.startswith("EVENT_TYPE_"):
            if not hasattr(es, value.attr):
                raise AssertionError(
                    f"Case references unknown event_schema attribute {value.attr!r}"
                )
            return {getattr(es, value.attr)}
    raise AssertionError(
        f"Unsupported case pattern {type(pattern).__name__}; "
        f"extend _collect_case_values to handle it"
    )


class TestEventTypeMatchCompleteness(unittest.TestCase):
    """Every match-block keyed on event type must either handle every
    EVENT_TYPE_* constant, contain a `case _:` wildcard, or declare its
    intentional exclusions in a module-level allowlist. Prevents the
    silent-drop bug class where a new EVENT_TYPE_* is added without
    updating the match block.
    """

    SMM_ROOT: ClassVar[Path] = Path(__file__).parent.parent.parent / "smm"

    MATCH_BLOCKS: ClassVar[list[_MatchBlockSpec]] = [
        _MatchBlockSpec(
            "compact.py",
            "_collect_smm_referenced_ids",
            "etype",
            "_COMPACT_INTENTIONALLY_ABSENT",
        ),
        _MatchBlockSpec(
            "materialize.py",
            "_bucket_new_events",
            "etype",
            "_BUCKET_INTENTIONALLY_ABSENT",
        ),
        _MatchBlockSpec(
            "event_schema.py",
            "validate_event",
            "event_type",
            "_VALIDATE_NO_TYPE_RULES",
        ),
        _MatchBlockSpec(
            "resolution.py",
            "compute_resolutions",
            "target.get('type')",
            None,
        ),
    ]

    def test_each_match_block_covers_all_event_types(self):
        valid_types = set(es.VALID_TYPES)

        for spec in self.MATCH_BLOCKS:
            with self.subTest(module=spec.module_filename, function=spec.function_name):
                source = (self.SMM_ROOT / spec.module_filename).read_text(
                    encoding="utf-8"
                )
                tree = ast.parse(source)
                func = _find_function(tree, spec.function_name)
                match_node = _find_match_node(func, spec.subject_text)

                handled: set[str] = set()
                has_wildcard = False
                for case in match_node.cases:
                    values = _collect_case_values(case.pattern)
                    if "_" in values:
                        has_wildcard = True
                    handled |= values - {"_"}

                module = importlib.import_module(
                    spec.module_filename.removesuffix(".py")
                )
                where = f"{spec.module_filename}:{spec.function_name}"

                if has_wildcard:
                    self.assertIsNone(
                        spec.allowlist_name,
                        f"{where} has `case _:` wildcard; the allowlist "
                        f"{spec.allowlist_name!r} is redundant",
                    )
                    continue

                assert spec.allowlist_name is not None, (
                    f"{where} has no `case _:` wildcard and no allowlist — "
                    f"silently drops {sorted(valid_types - handled)}"
                )

                self.assertTrue(
                    hasattr(module, spec.allowlist_name),
                    f"{spec.module_filename} missing module-level constant "
                    f"{spec.allowlist_name!r}",
                )
                allowlist = set(getattr(module, spec.allowlist_name))

                missing = valid_types - handled - allowlist
                self.assertEqual(
                    missing,
                    set(),
                    f"{where} silently drops event types: {sorted(missing)}. "
                    f"Add a `case` arm or list each in {spec.allowlist_name}.",
                )

                stale = handled & allowlist
                self.assertEqual(
                    stale,
                    set(),
                    f"{where} declares already-handled types in "
                    f"{spec.allowlist_name}: {sorted(stale)}. Remove from allowlist.",
                )


if __name__ == "__main__":
    unittest.main()

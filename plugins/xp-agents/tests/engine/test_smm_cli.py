#!/usr/bin/env python3
"""Tests for smm_cli.py CLI behaviors.

Contract:
- `dump` prints render_markdown(smm) to stdout with no side effects.
- `render` prints render_markdown(smm) AND drops an agent-scoped marker
  .pending-render-smm-{agent_id} with signature content.
- `--agent-id` overrides CWD-based agent_id resolution on `render`.
- `section`, `has-section`, `save` do NOT drop the marker.
- Marker writes go through markers.marker_write → symlink-safe,
  per-agent isolated.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _SMMTestCase, make_event, run_cli

_CLI = Path(__file__).parent.parent.parent / "smm" / "smm_cli.py"

_SMM_SIGNATURE = "# Shared Mental Model \u2014 Curated View"
_MARKER_PREFIX = ".pending-render-smm-"


def _seed_smm(smm_dir: Path) -> None:
    """Write a minimal valid SMM file so load_smm returns real content."""
    import smm_store
    from smm_schema import empty_smm

    data = empty_smm()
    smm_store.save_smm(smm_dir, data)


class TestDumpPureOutput(_SMMTestCase):
    """dump is side-effect-free — prints markdown, drops NO marker."""

    def test_dump_prints_signature_header(self):
        _seed_smm(self.smm_dir)
        result = run_cli(_CLI, ["dump"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(_SMM_SIGNATURE, result.stdout)

    def test_dump_does_not_drop_marker(self):
        _seed_smm(self.smm_dir)
        result = run_cli(_CLI, ["dump"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        leaked = list(self.smm_dir.glob(f"{_MARKER_PREFIX}*"))
        self.assertEqual(
            leaked, [], f"dump must not drop marker; found {[p.name for p in leaked]}"
        )

    def test_dump_without_seeded_smm_still_pure(self):
        result = run_cli(_CLI, ["dump"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(_SMM_SIGNATURE, result.stdout)
        leaked = list(self.smm_dir.glob(f"{_MARKER_PREFIX}*"))
        self.assertEqual(leaked, [])


class TestRenderDropsMarker(_SMMTestCase):
    """render produces the same output as dump AND drops an agent-scoped marker."""

    def test_render_prints_signature_header(self):
        _seed_smm(self.smm_dir)
        result = run_cli(_CLI, ["render", "--agent-id", "main"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(_SMM_SIGNATURE, result.stdout)

    def test_render_drops_agent_scoped_marker(self):
        _seed_smm(self.smm_dir)
        result = run_cli(_CLI, ["render", "--agent-id", "main"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        marker = self.smm_dir / f"{_MARKER_PREFIX}main"
        self.assertTrue(
            marker.is_file(),
            f"marker missing; files: {[p.name for p in self.smm_dir.iterdir()]}",
        )
        self.assertEqual(marker.read_text().strip(), _SMM_SIGNATURE)

    def test_render_marker_name_from_constants(self):
        import marker_names

        # Template uses {agent_id} placeholder now.
        self.assertIn("{agent_id}", marker_names.PENDING_RENDER_SMM)
        self.assertTrue(marker_names.PENDING_RENDER_SMM.startswith(_MARKER_PREFIX))

    def test_render_per_agent_isolation(self):
        _seed_smm(self.smm_dir)
        r1 = run_cli(_CLI, ["render", "--agent-id", "teammate-a"], self.smm_dir)
        r2 = run_cli(_CLI, ["render", "--agent-id", "teammate-b"], self.smm_dir)
        self.assertEqual(r1.returncode, 0, r1.stderr)
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertTrue((self.smm_dir / f"{_MARKER_PREFIX}teammate-a").is_file())
        self.assertTrue((self.smm_dir / f"{_MARKER_PREFIX}teammate-b").is_file())

    def test_render_rejects_symlink(self):
        _seed_smm(self.smm_dir)
        real = self.smm_dir / ".real-file"
        real.write_text("old")
        link = self.smm_dir / f"{_MARKER_PREFIX}main"
        link.symlink_to(real)
        result = run_cli(_CLI, ["render", "--agent-id", "main"], self.smm_dir)
        # Non-zero exit: marker_write must refuse symlinks.
        self.assertNotEqual(
            result.returncode, 0, f"expected failure; stderr={result.stderr}"
        )
        # The symlink must remain untouched (not replaced via tempfile+rename).
        self.assertTrue(link.is_symlink())
        # Marker-first contract: on enforcement failure, no signature line
        # must leak to stdout, because the echo-gate has nothing to check.
        self.assertNotIn(_SMM_SIGNATURE, result.stdout)


class TestOtherCommandsDoNotDrop(_SMMTestCase):
    """section, has-section, save must NOT drop the echo marker."""

    def test_section_does_not_drop_marker(self):
        _seed_smm(self.smm_dir)
        result = run_cli(_CLI, ["section", "intent"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        leaked = list(self.smm_dir.glob(f"{_MARKER_PREFIX}*"))
        self.assertEqual(leaked, [])

    def test_has_section_does_not_drop_marker(self):
        _seed_smm(self.smm_dir)
        run_cli(_CLI, ["has-section", "intent"], self.smm_dir)
        leaked = list(self.smm_dir.glob(f"{_MARKER_PREFIX}*"))
        self.assertEqual(leaked, [])

    def test_save_does_not_drop_marker(self):
        import smm_schema

        payload = json.dumps(smm_schema.empty_smm())
        result = run_cli(_CLI, ["save"], self.smm_dir, stdin_data=payload)
        self.assertEqual(result.returncode, 0, result.stderr)
        leaked = list(self.smm_dir.glob(f"{_MARKER_PREFIX}*"))
        self.assertEqual(leaked, [])


class TestGetEvent(_SMMTestCase):
    """get-event retrieves individual events from events.jsonl."""

    def _append_event(self, event_type: str = "status", content: str = "test") -> str:
        """Append an event and return its ID."""
        event = make_event(event_type, content=content)
        events_file = self.smm_dir / "events.jsonl"
        with events_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
        return event["id"]

    def test_get_event_exact_match(self):
        """get-event with full ID prints event JSON."""
        event_id = self._append_event(content="exact match test")
        result = run_cli(_CLI, ["get-event", event_id], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed["id"], event_id)
        self.assertEqual(parsed["content"], "exact match test")

    def test_get_event_prefix_match(self):
        """get-event with 6-char prefix resolves to full event."""
        event_id = self._append_event(content="prefix test")
        prefix = event_id[:6]
        result = run_cli(_CLI, ["get-event", prefix], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed["id"], event_id)

    def test_get_event_not_found(self):
        """get-event with nonexistent ID returns exit 1."""
        self._append_event()
        result = run_cli(_CLI, ["get-event", "000000000000"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not found", result.stderr.lower())

    def test_get_event_ambiguous_prefix(self):
        """get-event with prefix matching multiple events returns exit 1."""
        # Write two events sharing a 4-char prefix but different full IDs.
        shared = "abcd"
        for suffix in ["00000001", "00000002"]:
            event = make_event("status", content="ambig")
            event["id"] = shared + suffix
            events_file = self.smm_dir / "events.jsonl"
            with events_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event) + "\n")
        result = run_cli(_CLI, ["get-event", shared], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ambiguous", result.stderr.lower())


class TestSmmCliHelp(_SMMTestCase):
    def test_help_contains_examples(self):
        result = run_cli(_CLI, ["--help"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Examples:", result.stdout)


if __name__ == "__main__":
    unittest.main()

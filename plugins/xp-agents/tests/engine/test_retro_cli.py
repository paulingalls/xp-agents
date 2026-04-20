#!/usr/bin/env python3
"""Tests for retro_cli.py: render retrospective JSON as markdown.

Contract:
- `render` prints Keep/Fix/Try markdown with signature header on stdout.
- `render` drops an agent-scoped marker .pending-render-retro-{agent_id}
  with the signature line as content (atomic, symlink-safe via
  markers.marker_write).
- `--agent-id` overrides CWD-based resolution; teammate-a and teammate-b
  produce distinct marker files (per-agent isolation).
- Missing / invalid JSON exits non-zero with stderr, drops no marker.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _SMMTestCase, run_cli

_CLI = Path(__file__).parent.parent.parent / "smm" / "retro_cli.py"

_SIGNATURE = "# XP Retrospective \u2014 Keep / Fix / Try"
_MARKER_PREFIX = ".pending-render-retro-"


def _make_retro(**overrides) -> dict:
    data = {
        "timestamp": "2026-04-18T12:00:00+00:00",
        "keep": [{"content": "tight TDD loop"}],
        "fix": [{"content": "flaky subprocess test"}],
        "try": [{"content": "pair on the housekeeping refactor"}],
    }
    data.update(overrides)
    return data


class TestRenderMarkdown(_SMMTestCase):
    def test_signature_header_present(self):
        retro_path = self.smm_dir / "retro.json"
        retro_path.write_text(json.dumps(_make_retro()))

        result = run_cli(
            _CLI, ["render", str(retro_path), "--agent-id", "main"], self.smm_dir
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(_SIGNATURE, result.stdout)

    def test_sections_and_bullets_emitted(self):
        retro_path = self.smm_dir / "retro.json"
        retro_path.write_text(
            json.dumps(
                _make_retro(
                    keep=[{"content": "keep-one"}, {"content": "keep-two"}],
                    fix=[{"content": "fix-one"}],
                    **{"try": [{"content": "try-one"}]},
                )
            )
        )

        result = run_cli(
            _CLI, ["render", str(retro_path), "--agent-id", "main"], self.smm_dir
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        out = result.stdout
        self.assertIn("## Keep", out)
        self.assertIn("## Fix", out)
        self.assertIn("## Try", out)
        self.assertIn("- keep-one", out)
        self.assertIn("- keep-two", out)
        self.assertIn("- fix-one", out)
        self.assertIn("- try-one", out)

    def test_empty_sections_still_emit_header_and_marker(self):
        retro_path = self.smm_dir / "retro.json"
        retro_path.write_text(
            json.dumps(
                {
                    "timestamp": "2026-04-18T12:00:00+00:00",
                    "keep": [],
                    "fix": [],
                    "try": [],
                }
            )
        )

        result = run_cli(
            _CLI, ["render", str(retro_path), "--agent-id", "main"], self.smm_dir
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(_SIGNATURE, result.stdout)
        marker = self.smm_dir / f"{_MARKER_PREFIX}main"
        self.assertTrue(marker.is_file())
        self.assertIn(_SIGNATURE, marker.read_text())


class TestMarkerDrop(_SMMTestCase):
    def test_marker_written_with_signature_agent_scoped(self):
        retro_path = self.smm_dir / "retro.json"
        retro_path.write_text(json.dumps(_make_retro()))

        result = run_cli(
            _CLI, ["render", str(retro_path), "--agent-id", "main"], self.smm_dir
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        marker = self.smm_dir / f"{_MARKER_PREFIX}main"
        self.assertTrue(
            marker.is_file(),
            f"marker missing; files: {[p.name for p in self.smm_dir.iterdir()]}",
        )
        self.assertEqual(marker.read_text().strip(), _SIGNATURE)

    def test_marker_template_uses_agent_id(self):
        import marker_names

        self.assertIn("{agent_id}", marker_names.PENDING_RENDER_RETRO)
        self.assertTrue(marker_names.PENDING_RENDER_RETRO.startswith(_MARKER_PREFIX))

    def test_render_per_agent_isolation(self):
        retro_path = self.smm_dir / "retro.json"
        retro_path.write_text(json.dumps(_make_retro()))

        r1 = run_cli(
            _CLI, ["render", str(retro_path), "--agent-id", "teammate-a"], self.smm_dir
        )
        r2 = run_cli(
            _CLI, ["render", str(retro_path), "--agent-id", "teammate-b"], self.smm_dir
        )

        self.assertEqual(r1.returncode, 0, r1.stderr)
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertTrue((self.smm_dir / f"{_MARKER_PREFIX}teammate-a").is_file())
        self.assertTrue((self.smm_dir / f"{_MARKER_PREFIX}teammate-b").is_file())

    def test_render_rejects_symlink(self):
        retro_path = self.smm_dir / "retro.json"
        retro_path.write_text(json.dumps(_make_retro()))
        real = self.smm_dir / ".real-file"
        real.write_text("old")
        link = self.smm_dir / f"{_MARKER_PREFIX}main"
        link.symlink_to(real)

        result = run_cli(
            _CLI, ["render", str(retro_path), "--agent-id", "main"], self.smm_dir
        )

        self.assertNotEqual(
            result.returncode, 0, f"expected failure; stderr={result.stderr}"
        )
        self.assertTrue(link.is_symlink())
        # Marker-first contract: on enforcement failure, no signature line
        # must leak to stdout, because the echo-gate has nothing to check.
        self.assertNotIn(_SIGNATURE, result.stdout)


class TestErrorHandling(_SMMTestCase):
    def test_missing_json_path_errors(self):
        missing = self.smm_dir / "does-not-exist.json"

        result = run_cli(
            _CLI, ["render", str(missing), "--agent-id", "main"], self.smm_dir
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(result.stderr.strip(), "expected stderr message")
        leaked = list(self.smm_dir.glob(f"{_MARKER_PREFIX}*"))
        self.assertEqual(leaked, [], "marker must not drop on error")

    def test_invalid_json_errors(self):
        bad_path = self.smm_dir / "bad.json"
        bad_path.write_text("{ not valid json")

        result = run_cli(
            _CLI, ["render", str(bad_path), "--agent-id", "main"], self.smm_dir
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(result.stderr.strip())


if __name__ == "__main__":
    unittest.main()

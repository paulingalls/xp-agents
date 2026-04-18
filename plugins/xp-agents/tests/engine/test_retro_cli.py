#!/usr/bin/env python3
"""Tests for retro_cli.py: render retrospective JSON as markdown.

Validates:
- Stdout markdown with signature header and keep/fix/try sections.
- Atomic marker drop at <smm_dir>/.pending-render-retro with signature content.
- Missing JSON path fails cleanly (nonzero exit, stderr message).
- Empty keep/fix/try still produces header + marker.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _SMMTestCase

_CLI = Path(__file__).parent.parent.parent / "smm" / "retro_cli.py"

_SIGNATURE = "# XP Retrospective \u2014 Keep / Fix / Try"
_MARKER_NAME = ".pending-render-retro"


def _make_retro(**overrides) -> dict:
    data = {
        "timestamp": "2026-04-18T12:00:00+00:00",
        "keep": [{"content": "tight TDD loop"}],
        "fix": [{"content": "flaky subprocess test"}],
        "try": [{"content": "pair on the housekeeping refactor"}],
    }
    data.update(overrides)
    return data


def _run_cli(
    args: list[str],
    smm_dir: Path,
) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(_CLI), "--smm-dir", str(smm_dir), *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=10,
    )


class TestRenderMarkdown(_SMMTestCase):
    def test_signature_header_present(self):
        retro_path = self.smm_dir / "retro.json"
        retro_path.write_text(json.dumps(_make_retro()))

        result = _run_cli(["render", str(retro_path)], self.smm_dir)

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

        result = _run_cli(["render", str(retro_path)], self.smm_dir)

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

        result = _run_cli(["render", str(retro_path)], self.smm_dir)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(_SIGNATURE, result.stdout)
        marker = self.smm_dir / _MARKER_NAME
        self.assertTrue(marker.is_file())
        self.assertIn(_SIGNATURE, marker.read_text())


class TestMarkerDrop(_SMMTestCase):
    def test_marker_written_with_signature(self):
        retro_path = self.smm_dir / "retro.json"
        retro_path.write_text(json.dumps(_make_retro()))

        result = _run_cli(["render", str(retro_path)], self.smm_dir)

        self.assertEqual(result.returncode, 0, result.stderr)
        marker = self.smm_dir / _MARKER_NAME
        self.assertTrue(marker.is_file(), "marker file missing")
        self.assertEqual(marker.read_text().strip(), _SIGNATURE)

    def test_marker_name_from_constants(self):
        import marker_names

        self.assertEqual(marker_names.PENDING_RENDER_RETRO, _MARKER_NAME)

    def test_atomic_write_used_for_marker(self):
        """Marker drop must go through write_text_atomic (tempfile + rename)."""
        import _append_impl
        import retro_cli

        retro_path = self.smm_dir / "retro.json"
        retro_path.write_text(json.dumps(_make_retro()))

        with mock.patch.object(
            _append_impl, "write_text_atomic", wraps=_append_impl.write_text_atomic
        ) as spy:
            # retro_cli must resolve write_text_atomic via _append_impl at
            # call time so the patch is observed.
            retro_cli.run_render(retro_path, self.smm_dir)

        marker_calls = [c for c in spy.call_args_list if c.args[0].name == _MARKER_NAME]
        self.assertEqual(
            len(marker_calls),
            1,
            f"expected 1 atomic marker write, got {len(marker_calls)}",
        )


class TestErrorHandling(_SMMTestCase):
    def test_missing_json_path_errors(self):
        missing = self.smm_dir / "does-not-exist.json"

        result = _run_cli(["render", str(missing)], self.smm_dir)

        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(result.stderr.strip(), "expected stderr message")
        marker = self.smm_dir / _MARKER_NAME
        self.assertFalse(marker.exists(), "marker must not drop on error")

    def test_invalid_json_errors(self):
        bad_path = self.smm_dir / "bad.json"
        bad_path.write_text("{ not valid json")

        result = _run_cli(["render", str(bad_path)], self.smm_dir)

        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(result.stderr.strip())


if __name__ == "__main__":
    unittest.main()

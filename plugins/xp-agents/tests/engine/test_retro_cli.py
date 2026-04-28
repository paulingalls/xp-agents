#!/usr/bin/env python3
"""Tests for retro_cli.py: render retrospective JSON as markdown.

Contract:
- `render` finds the latest retrospective in <smm-dir>/retrospectives/*.json
  (max by filename — file names are ISO timestamps) and prints Keep/Fix/Try
  markdown with signature header on stdout.
- Empty retrospectives dir / missing dir / invalid JSON exits non-zero
  with stderr.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _SMMTestCase, run_cli

_CLI = Path(__file__).parent.parent.parent / "smm" / "retro_cli.py"

_SIGNATURE = "# XP Retrospective — Keep / Fix / Try"


def _make_retro(**overrides) -> dict:
    data = {
        "timestamp": "2026-04-18T12:00:00+00:00",
        "keep": [{"content": "tight TDD loop"}],
        "fix": [{"content": "flaky subprocess test"}],
        "try": [{"content": "pair on the housekeeping refactor"}],
    }
    data.update(overrides)
    return data


def _write_retro(smm_dir: Path, name: str, retro: dict) -> Path:
    """Write a retrospective JSON to the canonical location."""
    retros_dir = smm_dir / "retrospectives"
    retros_dir.mkdir(parents=True, exist_ok=True)
    path = retros_dir / f"{name}.json"
    path.write_text(json.dumps(retro))
    return path


class TestRenderMarkdown(_SMMTestCase):
    def test_signature_header_present(self):
        _write_retro(self.smm_dir, "2026-04-18T12-00-00", _make_retro())

        result = run_cli(_CLI, ["render"], self.smm_dir)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(_SIGNATURE, result.stdout)

    def test_sections_and_bullets_emitted(self):
        _write_retro(
            self.smm_dir,
            "2026-04-18T12-00-00",
            _make_retro(
                keep=[{"content": "keep-one"}, {"content": "keep-two"}],
                fix=[{"content": "fix-one"}],
                **{"try": [{"content": "try-one"}]},
            ),
        )

        result = run_cli(_CLI, ["render"], self.smm_dir)

        self.assertEqual(result.returncode, 0, result.stderr)
        out = result.stdout
        self.assertIn("## Keep", out)
        self.assertIn("## Fix", out)
        self.assertIn("## Try", out)
        self.assertIn("- keep-one", out)
        self.assertIn("- keep-two", out)
        self.assertIn("- fix-one", out)
        self.assertIn("- try-one", out)

    def test_empty_sections_still_emit_header(self):
        _write_retro(
            self.smm_dir,
            "2026-04-18T12-00-00",
            {
                "timestamp": "2026-04-18T12:00:00+00:00",
                "keep": [],
                "fix": [],
                "try": [],
            },
        )

        result = run_cli(_CLI, ["render"], self.smm_dir)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(_SIGNATURE, result.stdout)

    def test_renders_latest_when_multiple_retros_exist(self):
        """When multiple retros exist in the directory, render the most
        recent (max by filename — names are ISO timestamps)."""
        _write_retro(
            self.smm_dir,
            "2026-04-18T08-00-00",
            _make_retro(keep=[{"content": "older-retro"}]),
        )
        _write_retro(
            self.smm_dir,
            "2026-04-18T20-00-00",
            _make_retro(keep=[{"content": "newer-retro"}]),
        )

        result = run_cli(_CLI, ["render"], self.smm_dir)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("- newer-retro", result.stdout)
        self.assertNotIn("- older-retro", result.stdout)


class TestErrorHandling(_SMMTestCase):
    def test_missing_retrospectives_dir_errors(self):
        # No retrospectives/ dir under smm_dir
        result = run_cli(_CLI, ["render"], self.smm_dir)

        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(result.stderr.strip(), "expected stderr message")

    def test_empty_retrospectives_dir_errors(self):
        (self.smm_dir / "retrospectives").mkdir(parents=True, exist_ok=True)

        result = run_cli(_CLI, ["render"], self.smm_dir)

        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(result.stderr.strip())

    def test_invalid_json_errors(self):
        retros_dir = self.smm_dir / "retrospectives"
        retros_dir.mkdir(parents=True, exist_ok=True)
        (retros_dir / "2026-04-18T12-00-00.json").write_text("{ not valid json")

        result = run_cli(_CLI, ["render"], self.smm_dir)

        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(result.stderr.strip())


class TestRetroCliHelp(_SMMTestCase):
    def test_help_contains_examples(self):
        result = run_cli(_CLI, ["--help"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Examples:", result.stdout)


if __name__ == "__main__":
    unittest.main()

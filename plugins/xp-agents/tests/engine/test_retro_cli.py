#!/usr/bin/env python3
"""Tests for retro_cli.py: render retrospective JSON as markdown.

Contract:
- `render` prints Keep/Fix/Try markdown with signature header on stdout.
- Missing / invalid JSON exits non-zero with stderr.
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


class TestRenderMarkdown(_SMMTestCase):
    def test_signature_header_present(self):
        retro_path = self.smm_dir / "retro.json"
        retro_path.write_text(json.dumps(_make_retro()))

        result = run_cli(_CLI, ["render", str(retro_path)], self.smm_dir)

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

        result = run_cli(_CLI, ["render", str(retro_path)], self.smm_dir)

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

        result = run_cli(_CLI, ["render", str(retro_path)], self.smm_dir)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(_SIGNATURE, result.stdout)


class TestErrorHandling(_SMMTestCase):
    def test_missing_json_path_errors(self):
        missing = self.smm_dir / "does-not-exist.json"

        result = run_cli(_CLI, ["render", str(missing)], self.smm_dir)

        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(result.stderr.strip(), "expected stderr message")

    def test_invalid_json_errors(self):
        bad_path = self.smm_dir / "bad.json"
        bad_path.write_text("{ not valid json")

        result = run_cli(_CLI, ["render", str(bad_path)], self.smm_dir)

        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(result.stderr.strip())


class TestRetroCliHelp(_SMMTestCase):
    def test_help_contains_examples(self):
        result = run_cli(_CLI, ["--help"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Examples:", result.stdout)


if __name__ == "__main__":
    unittest.main()

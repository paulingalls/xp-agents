#!/usr/bin/env python3
"""Tests for smm_cli.py CLI behaviors.

Focuses on the dump command's echo-enforcement marker drop:
- `dump` prints render_markdown(smm) to stdout.
- `dump` atomically drops .pending-render-smm with signature content.
- `section` and `has-section` do NOT drop the marker.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _SMMTestCase

_CLI = Path(__file__).parent.parent.parent / "smm" / "smm_cli.py"

_SMM_SIGNATURE = "# Shared Mental Model"
_MARKER_NAME = ".pending-render-smm"


def _seed_smm(smm_dir: Path) -> None:
    """Write a minimal valid SMM file so load_smm returns real content."""
    import smm_store
    from smm_schema import empty_smm

    data = empty_smm()
    smm_store.save_smm(smm_dir, data)


def _run_cli(
    args: list[str],
    smm_dir: Path,
    stdin_data: str | None = None,
) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(_CLI), "--smm-dir", str(smm_dir), *args]
    return subprocess.run(
        cmd,
        input=stdin_data,
        capture_output=True,
        text=True,
        timeout=10,
    )


class TestDumpDropsMarker(_SMMTestCase):
    def test_dump_prints_signature_header(self):
        _seed_smm(self.smm_dir)
        result = _run_cli(["dump"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(_SMM_SIGNATURE, result.stdout)

    def test_dump_drops_marker_with_signature(self):
        _seed_smm(self.smm_dir)
        result = _run_cli(["dump"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        marker = self.smm_dir / _MARKER_NAME
        self.assertTrue(marker.is_file(), "marker file missing")
        self.assertEqual(marker.read_text().strip(), _SMM_SIGNATURE)

    def test_dump_marker_name_from_constants(self):
        import marker_names

        self.assertEqual(marker_names.PENDING_RENDER_SMM, _MARKER_NAME)

    def test_dump_without_seeded_smm_still_drops_marker(self):
        """Fresh SMM directory: load_smm returns empty_smm, dump still works."""
        result = _run_cli(["dump"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(_SMM_SIGNATURE, result.stdout)
        marker = self.smm_dir / _MARKER_NAME
        self.assertTrue(marker.is_file())


class TestOtherCommandsDoNotDrop(_SMMTestCase):
    def test_section_does_not_drop_marker(self):
        _seed_smm(self.smm_dir)
        result = _run_cli(["section", "intent"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        marker = self.smm_dir / _MARKER_NAME
        self.assertFalse(
            marker.exists(), "section must not drop echo-enforcement marker"
        )

    def test_has_section_does_not_drop_marker(self):
        _seed_smm(self.smm_dir)
        # has-section returns 1 when empty; either exit code is fine for this
        # assertion — we only care the marker is absent.
        _run_cli(["has-section", "intent"], self.smm_dir)
        marker = self.smm_dir / _MARKER_NAME
        self.assertFalse(
            marker.exists(), "has-section must not drop echo-enforcement marker"
        )

    def test_save_does_not_drop_marker(self):
        import smm_schema

        payload = json.dumps(smm_schema.empty_smm())
        result = _run_cli(["save"], self.smm_dir, stdin_data=payload)
        self.assertEqual(result.returncode, 0, result.stderr)
        marker = self.smm_dir / _MARKER_NAME
        self.assertFalse(marker.exists(), "save must not drop echo marker")


if __name__ == "__main__":
    unittest.main()

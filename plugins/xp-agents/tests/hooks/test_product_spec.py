#!/usr/bin/env python3
"""Tests for save_product_spec.py and product spec preload."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase

# ===========================================================================
# save_product_spec.py — Atomic writer for product_spec.md
# ===========================================================================

_SAVE_SCRIPT = (
    Path(__file__).parent.parent.parent
    / "skills"
    / "xp-product-spec"
    / "scripts"
    / "save_product_spec.py"
)


class TestSaveProductSpec(_HookTestCase):
    """Tests for the save_product_spec.py atomic writer."""

    def _run_save(self, content: str) -> None:
        """Import and call save_product_spec.run() directly."""
        if not _SAVE_SCRIPT.is_file():
            self.skipTest("save_product_spec.py not yet created")
        sys.path.insert(0, str(_SAVE_SCRIPT.parent))
        import importlib

        mod = importlib.import_module("save_product_spec")
        importlib.reload(mod)  # ensure fresh import
        mod.run(content, self.smm_dir)

    def test_writes_product_spec(self):
        """Creates product_spec.md with given content."""
        content = "# Product Spec: Test\n\n## Overview\nA test product.\n"
        self._run_save(content)
        target = self.smm_dir / "product_spec.md"
        self.assertTrue(target.is_file())
        self.assertEqual(target.read_text(), content)

    def test_overwrites_existing(self):
        """Replaces existing product_spec.md content."""
        target = self.smm_dir / "product_spec.md"
        target.write_text("old content")
        new_content = "# Product Spec: Updated\n"
        self._run_save(new_content)
        self.assertEqual(target.read_text(), new_content)

    def test_rejects_symlink(self):
        """Raises OSError when product_spec.md is a symlink."""
        target = self.smm_dir / "product_spec.md"
        real_file = self.smm_dir / "real.md"
        real_file.write_text("real")
        target.symlink_to(real_file)
        with self.assertRaises(OSError):
            self._run_save("new content")

    def test_content_passthrough(self):
        """Delivered markers are preserved verbatim (writer is pass-through)."""
        content = (
            "# Product Spec: Test\n\n"
            "## Features\n\n"
            "### Auth [delivered: sprint-001]\n"
            "- Login with email\n\n"
            "### Search [planned]\n"
            "- Full-text search\n"
        )
        self._run_save(content)
        self.assertEqual((self.smm_dir / "product_spec.md").read_text(), content)


if __name__ == "__main__":
    unittest.main()

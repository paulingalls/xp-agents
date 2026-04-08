#!/usr/bin/env python3
"""Tests for save_product_spec.py and product spec preload."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase, _IntegrationTestCase

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

    def test_clears_needs_product_spec_marker(self):
        """NEEDS_PRODUCT_SPEC marker cleared after successful write."""
        (self.smm_dir / ".needs-product-spec").write_text("startup")
        self._run_save("# Product Spec: Test\n")
        self.assertFalse((self.smm_dir / ".needs-product-spec").exists())

    def test_no_marker_no_error(self):
        """Running without the marker present does not error."""
        self._run_save("# Product Spec: Test\n")
        # No assertion needed — should not raise


# ===========================================================================
# preload.sh — Product spec preload script
# ===========================================================================

_PRELOAD_SCRIPT = (
    Path(__file__).parent.parent.parent
    / "skills"
    / "xp-product-spec"
    / "scripts"
    / "preload.sh"
)


class TestProductSpecPreload(_IntegrationTestCase):
    """Tests for the product spec preload script."""

    def test_preload_no_spec(self):
        """Outputs create-mode message when no product_spec.md exists."""
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("No product spec", result.stdout)

    def test_preload_with_spec_outputs_path(self):
        """Outputs path to spec file, not full content."""
        spec_content = (
            "# Product Spec: Test\n\n"
            "## Features\n\n"
            "### Auth [planned]\n"
            "- Login with email\n"
        )
        (self.smm_dir / "product_spec.md").write_text(spec_content)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("PRODUCT_SPEC=", result.stdout)
        # Should NOT contain full spec content — agent reads via Read tool
        self.assertNotIn("Auth [planned]", result.stdout)

    def test_preload_feature_counts(self):
        """Outputs correct planned/delivered feature counts."""
        spec_content = (
            "# Product Spec: Test\n\n"
            "## Features\n\n"
            "### Auth [delivered: sprint-001]\n"
            "- Login\n\n"
            "### Search [planned]\n"
            "- Full-text search\n\n"
            "### Billing [planned]\n"
            "- Stripe integration\n"
        )
        (self.smm_dir / "product_spec.md").write_text(spec_content)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("2", result.stdout)  # 2 planned
        self.assertIn("1", result.stdout)  # 1 delivered


if __name__ == "__main__":
    unittest.main()

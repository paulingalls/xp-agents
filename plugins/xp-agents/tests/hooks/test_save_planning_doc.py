#!/usr/bin/env python3
"""Tests for save_planning_doc.py, marker_names, sprint_state."""

import sys
import tempfile
import unittest
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "scripts"))
sys.path.insert(0, str(_PLUGIN_ROOT / "smm"))


class TestSavePlanningDoc(unittest.TestCase):
    """Tests for save_planning_doc.py run() function."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.smm_dir = Path(self.tmp)
        # Create lock file (required by SMM dir convention)
        (self.smm_dir / "events.lock").touch()

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_writes_system_context(self):
        """--type system_context writes system_context.md."""
        from save_planning_doc import run

        content = "# System Context: Test\n\n## Overview\nTest system."
        run(content, self.smm_dir, doc_type="system_context")

        target = self.smm_dir / "system_context.md"
        self.assertTrue(target.exists())
        self.assertEqual(target.read_text(), content)

    def test_clears_system_context_marker(self):
        """Writing system_context.md clears .needs-system-context marker."""
        import marker_names
        from save_planning_doc import run

        marker = self.smm_dir / marker_names.NEEDS_SYSTEM_CONTEXT
        marker.touch()
        self.assertTrue(marker.exists())

        run("# System Context", self.smm_dir, doc_type="system_context")
        self.assertFalse(marker.exists())

    def test_marker_missing_is_fine(self):
        """Clearing a non-existent marker does not raise."""
        from save_planning_doc import run

        # No marker exists — should not raise
        run("# System Context", self.smm_dir, doc_type="system_context")

    def test_rejects_symlink_system_context(self):
        """Symlink target for system_context.md is rejected."""
        from save_planning_doc import run

        real = self.smm_dir / "real.md"
        real.write_text("real")
        link = self.smm_dir / "system_context.md"
        link.symlink_to(real)

        with self.assertRaises(OSError):
            run("# System Context", self.smm_dir, doc_type="system_context")

    def test_invalid_type_raises(self):
        """Unknown doc_type raises ValueError."""
        from save_planning_doc import run

        with self.assertRaises(ValueError):
            run("content", self.smm_dir, doc_type="invalid")

    def test_overwrites_existing(self):
        """Writing over an existing file replaces content."""
        from save_planning_doc import run

        target = self.smm_dir / "system_context.md"
        target.write_text("old content")

        run("new content", self.smm_dir, doc_type="system_context")
        self.assertEqual(target.read_text(), "new content")


class TestMarkerNames(unittest.TestCase):
    """Tests for marker_names.py additions."""

    def test_needs_execution_plan_exists(self):
        import marker_names

        self.assertEqual(marker_names.NEEDS_EXECUTION_PLAN, ".needs-execution-plan")

    def test_needs_system_context_exists(self):
        import marker_names

        self.assertEqual(marker_names.NEEDS_SYSTEM_CONTEXT, ".needs-system-context")


class TestSprintStateAdditions(unittest.TestCase):
    """Tests for sprint_state.py additions."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.smm_dir = Path(self.tmp)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_execution_plan_exists_true(self):
        from sprint_state import execution_plan_exists

        (self.smm_dir / "execution_plan.json").write_text("{}")
        self.assertTrue(execution_plan_exists(self.smm_dir))

    def test_execution_plan_exists_false(self):
        from sprint_state import execution_plan_exists

        self.assertFalse(execution_plan_exists(self.smm_dir))

    def test_execution_plan_md_not_detected(self):
        """Old .md format is not detected by execution_plan_exists."""
        from sprint_state import execution_plan_exists

        (self.smm_dir / "execution_plan.md").write_text("# Plan")
        self.assertFalse(execution_plan_exists(self.smm_dir))

    def test_execution_plan_rejects_symlink(self):
        from sprint_state import execution_plan_exists

        real = self.smm_dir / "real.json"
        real.write_text("{}")
        (self.smm_dir / "execution_plan.json").symlink_to(real)

        self.assertFalse(execution_plan_exists(self.smm_dir))

    def test_system_context_exists_true(self):
        from sprint_state import system_context_exists

        (self.smm_dir / "system_context.json").write_text("{}")
        self.assertTrue(system_context_exists(self.smm_dir))

    def test_system_context_exists_false(self):
        from sprint_state import system_context_exists

        self.assertFalse(system_context_exists(self.smm_dir))

    def test_system_context_rejects_symlink(self):
        from sprint_state import system_context_exists

        real = self.smm_dir / "real.json"
        real.write_text("{}")
        (self.smm_dir / "system_context.json").symlink_to(real)

        self.assertFalse(system_context_exists(self.smm_dir))


if __name__ == "__main__":
    unittest.main()

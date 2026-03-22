#!/usr/bin/env python3
"""Tests for simplify_gate.py and security triage marker helpers.

Quality review gate and TDD stop gate tests are in test_stop_gates.py.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import security
from conftest import _HookTestCase, _make_stop_input, make_event

# ===========================================================================
# Simplify Gate (Milestone 5.4)
# ===========================================================================


class TestSimplifyGate(_HookTestCase):
    """Tests for simplify_gate.py Stop command hook."""

    def setUp(self):
        super().setUp()
        import simplify_gate

        self.mod = simplify_gate

    def test_xp_agent_skips(self):
        inp = _make_stop_input(agent_type="xp-nav")
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_stop_hook_active_skips(self):
        inp = _make_stop_input(stop_hook_active=True)
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_no_smm_dir_degrades(self):
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=Path("/nonexistent/smm"))
        self.assertIsNone(result)

    def test_no_events_no_output(self):
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_no_customer_input_no_output(self):
        self._write_events([make_event("status", content="busy")])
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_no_file_changes_no_output(self):
        self._write_events(
            [
                make_event("customer_input", content="do something"),
                make_event("status", content="thinking", working_on=[]),
            ]
        )
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_only_docs_no_trigger(self):
        self._write_events(
            [
                make_event("customer_input", content="update docs"),
                make_event("status", content="wrote", working_on=["README.md"]),
            ]
        )
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_only_config_no_trigger(self):
        self._write_events(
            [
                make_event("customer_input", content="update config"),
                make_event("status", content="wrote", working_on=["package.json"]),
            ]
        )
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_only_images_no_trigger(self):
        self._write_events(
            [
                make_event("customer_input", content="add logo"),
                make_event("status", content="wrote", working_on=["logo.png"]),
            ]
        )
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_code_plus_docs_triggers(self):
        self._write_events(
            [
                make_event("customer_input", content="build feature"),
                make_event("status", content="wrote", working_on=["README.md"]),
                make_event(
                    "status",
                    content="wrote",
                    working_on=["src/app.ts", "src/util.ts", "src/index.ts"],
                ),
            ]
        )
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNotNone(result)

    def test_file_changes_triggers_simplify(self):
        self._write_events(
            [
                make_event("customer_input", content="build feature"),
                make_event(
                    "status",
                    content="wrote file",
                    working_on=["src/app.ts", "src/util.ts", "src/index.ts"],
                ),
            ]
        )
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNotNone(result)
        self.assertIn("/simplify", result)

    def test_tracker_prevents_retrigger(self):
        self._write_events(
            [
                make_event("customer_input", content="build feature"),
                make_event(
                    "status",
                    content="wrote file",
                    working_on=["src/app.ts", "src/util.ts", "src/index.ts"],
                ),
            ]
        )
        inp = _make_stop_input()
        result1 = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNotNone(result1)
        # Second call — tracker should prevent re-trigger
        result2 = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result2)

    def test_new_loop_resets_tracker(self):
        ci1 = make_event("customer_input", content="first task")
        self._write_events(
            [
                ci1,
                make_event(
                    "status",
                    content="wrote",
                    working_on=["src/a.ts", "src/b.ts", "src/c.ts"],
                ),
            ]
        )
        inp = _make_stop_input()
        result1 = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNotNone(result1)

        # New loop: new customer_input + changes
        ci2 = make_event("customer_input", content="second task")
        self._write_events(
            [
                ci1,
                make_event(
                    "status",
                    content="wrote",
                    working_on=["src/a.ts", "src/b.ts", "src/c.ts"],
                ),
                ci2,
                make_event(
                    "status",
                    content="wrote2",
                    working_on=["src/d.ts", "src/e.ts", "src/f.ts"],
                ),
            ]
        )
        result2 = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNotNone(result2)
        self.assertIn("/simplify", result2)

    def test_tracker_written_with_loop_id(self):
        ci = make_event("customer_input", content="build")
        self._write_events(
            [
                ci,
                make_event(
                    "status",
                    content="wrote",
                    working_on=["src/x.ts", "src/y.ts", "src/z.ts"],
                ),
            ]
        )
        inp = _make_stop_input()
        self.mod.run(inp, smm_dir=self.smm_dir)

        tracker_file = self.smm_dir / ".simplify-main.json"
        self.assertTrue(tracker_file.exists())
        tracker = json.loads(tracker_file.read_text())
        self.assertEqual(tracker["loop_id"], ci["id"])


# ===========================================================================
# Security: agent_id validation + symlink protection
# ===========================================================================


class TestSimplifyGateSecurity(_HookTestCase):
    """Security tests for simplify_gate.py."""

    def setUp(self):
        super().setUp()
        import simplify_gate

        self.mod = simplify_gate

    def test_path_traversal_agent_id_rejected(self):
        """agent_id with path traversal is rejected."""
        self._write_events(
            [
                make_event("customer_input", content="build"),
                make_event("status", content="wrote", working_on=["src/a.ts"]),
            ]
        )
        inp = _make_stop_input(agent_id="../../../etc/evil")
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_slash_agent_id_rejected(self):
        self._write_events(
            [
                make_event("customer_input", content="build"),
                make_event("status", content="wrote", working_on=["src/a.ts"]),
            ]
        )
        inp = _make_stop_input(agent_id="foo/bar")
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

        self.assertIsNone(result)


# ===========================================================================
# Security triage marker helpers — replaces hash-based tracker
# ===========================================================================


class TestSecurityTriageMarker(_HookTestCase):
    """Tests for security triage marker helpers in security.py."""

    def test_triaged_path(self):
        """security_triaged_path returns correct path."""
        path = security.security_triaged_path(self.smm_dir)
        self.assertEqual(path, self.smm_dir / ".security-triaged")

    def test_write_and_exists(self):
        """write_security_triaged creates file, security_triaged_exists finds it."""
        security.write_security_triaged(self.smm_dir)
        self.assertTrue(security.security_triaged_exists(self.smm_dir))

    def test_not_exists_when_missing(self):
        """security_triaged_exists returns False when no marker file."""
        self.assertFalse(security.security_triaged_exists(self.smm_dir))

    def test_consume_deletes_marker(self):
        """consume_security_triaged removes the marker."""
        security.write_security_triaged(self.smm_dir)
        self.assertTrue(security.security_triaged_exists(self.smm_dir))
        security.consume_security_triaged(self.smm_dir)
        self.assertFalse(security.security_triaged_exists(self.smm_dir))

    def test_consume_no_op_when_missing(self):
        """consume_security_triaged is safe when marker doesn't exist."""
        security.consume_security_triaged(self.smm_dir)  # no crash

    def test_rejects_symlink(self):
        """security_triaged_exists returns False for symlinks."""
        real_file = self.smm_dir / "real_target"
        real_file.write_text("x")
        link = security.security_triaged_path(self.smm_dir)
        link.symlink_to(real_file)
        self.assertFalse(security.security_triaged_exists(self.smm_dir))

    def test_write_marker_content(self):
        """write_security_triaged writes JSON with ts."""
        security.write_security_triaged(self.smm_dir)
        path = security.security_triaged_path(self.smm_dir)
        data = json.loads(path.read_text())
        self.assertIn("ts", data)

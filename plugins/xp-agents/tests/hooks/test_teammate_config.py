#!/usr/bin/env python3
"""Tests for markers.py — TEAMMATE_CONFIG session-scoped marker.

Covers token<->dict roundtrip for every valid token, fail-safe default
when the marker is missing or corrupt, and sweep registration so the
marker is cleared on fresh SessionStart.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import markers
from conftest import _HookTestCase


class TestTeammateConfigRoundtrip(_HookTestCase):
    """Every valid token survives a write/read roundtrip."""

    def test_off_token(self):
        markers.write_teammate_config(self.smm_dir, "off")
        result = markers.read_teammate_config(self.smm_dir)
        self.assertEqual(result, {"enabled": False, "default_model": None})

    def test_inherit_token(self):
        markers.write_teammate_config(self.smm_dir, "inherit")
        result = markers.read_teammate_config(self.smm_dir)
        self.assertEqual(result, {"enabled": True, "default_model": None})

    def test_haiku_token(self):
        markers.write_teammate_config(self.smm_dir, "haiku")
        result = markers.read_teammate_config(self.smm_dir)
        self.assertEqual(result, {"enabled": True, "default_model": "haiku"})

    def test_sonnet_token(self):
        markers.write_teammate_config(self.smm_dir, "sonnet")
        result = markers.read_teammate_config(self.smm_dir)
        self.assertEqual(result, {"enabled": True, "default_model": "sonnet"})

    def test_opus_token(self):
        markers.write_teammate_config(self.smm_dir, "opus")
        result = markers.read_teammate_config(self.smm_dir)
        self.assertEqual(result, {"enabled": True, "default_model": "opus"})

    def test_off_and_inherit_both_have_null_default_model(self):
        """off and inherit differ only in enabled field."""
        markers.write_teammate_config(self.smm_dir, "off")
        off_result = markers.read_teammate_config(self.smm_dir)
        markers.write_teammate_config(self.smm_dir, "inherit")
        inherit_result = markers.read_teammate_config(self.smm_dir)
        self.assertIsNone(off_result["default_model"])
        self.assertIsNone(inherit_result["default_model"])
        self.assertFalse(off_result["enabled"])
        self.assertTrue(inherit_result["enabled"])

    def test_write_invalid_token_raises(self):
        with self.assertRaises(ValueError):
            markers.write_teammate_config(self.smm_dir, "weekly")

    def test_all_valid_tokens_covered(self):
        """VALID_TEAMMATE_TOKENS contains exactly the five specified tokens."""
        self.assertEqual(
            markers.VALID_TEAMMATE_TOKENS,
            frozenset({"off", "haiku", "sonnet", "opus", "inherit"}),
        )


class TestTeammateConfigFailSafe(_HookTestCase):
    """Fail-safe to {enabled: True, default_model: None} when missing or corrupt."""

    def test_failsafe_when_missing(self):
        result = markers.read_teammate_config(self.smm_dir)
        self.assertEqual(result, {"enabled": True, "default_model": None})

    def test_failsafe_when_corrupt_json(self):
        path = self.smm_dir / markers.TEAMMATE_CONFIG.filename()
        path.write_text("not json{")
        result = markers.read_teammate_config(self.smm_dir)
        self.assertEqual(result, {"enabled": True, "default_model": None})

    def test_failsafe_when_missing_enabled_key(self):
        markers.marker_write(
            self.smm_dir, markers.TEAMMATE_CONFIG, {"default_model": "haiku"}
        )
        result = markers.read_teammate_config(self.smm_dir)
        self.assertEqual(result, {"enabled": True, "default_model": None})

    def test_failsafe_when_unknown_model_value(self):
        markers.marker_write(
            self.smm_dir,
            markers.TEAMMATE_CONFIG,
            {"enabled": True, "default_model": "gpt-4"},
        )
        result = markers.read_teammate_config(self.smm_dir)
        self.assertEqual(result, {"enabled": True, "default_model": None})


class TestTeammateConfigSweep(_HookTestCase):
    """TEAMMATE_CONFIG is swept on fresh SessionStart."""

    def test_registered_in_stale_session_markers(self):
        self.assertIn(markers.TEAMMATE_CONFIG, markers._STALE_SESSION_MARKERS)

    def test_write_then_sweep_removes_marker(self):
        markers.write_teammate_config(self.smm_dir, "sonnet")
        self.assertTrue(markers.marker_exists(self.smm_dir, markers.TEAMMATE_CONFIG))
        markers.sweep_stale_session_markers(self.smm_dir)
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.TEAMMATE_CONFIG))

    def test_failsafe_after_sweep(self):
        """After sweep the absent marker fail-safes to inherit."""
        markers.write_teammate_config(self.smm_dir, "off")
        markers.sweep_stale_session_markers(self.smm_dir)
        result = markers.read_teammate_config(self.smm_dir)
        self.assertEqual(result, {"enabled": True, "default_model": None})


if __name__ == "__main__":
    unittest.main()

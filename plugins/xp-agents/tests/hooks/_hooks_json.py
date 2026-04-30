#!/usr/bin/env python3
"""Shared base for hooks.json registration tests.

Loaded by test_validation.py and test_validation_hooks.py — both check
hooks.json structural assertions against milestone-specific registrations.
Lives next to its consumers (private to tests/hooks/) rather than in
conftest.py, which is reserved for cross-suite test bases.
"""

import json
import unittest
from pathlib import Path


class HooksJsonTestCase(unittest.TestCase):
    """Base class for hooks.json registration tests."""

    def setUp(self):
        hooks_path = Path(__file__).parent.parent.parent / "hooks" / "hooks.json"
        with open(hooks_path) as f:
            self.data = json.load(f)

    def _find_matcher_entry(self, hook_event: str, matcher: str) -> dict | None:
        """Find the entry with the given matcher in a hook event list."""
        for entry in self.data["hooks"].get(hook_event, []):
            if entry.get("matcher") == matcher:
                return entry
        return None

    def _find_default_entry(self, hook_event: str) -> dict | None:
        """Find an entry without a matcher (default) in a hook event list."""
        for entry in self.data["hooks"].get(hook_event, []):
            if "matcher" not in entry:
                return entry
        return None

#!/usr/bin/env python3
"""close_started action string stays in sync between bash producer and Python consumer.

`_preload_base.sh:emit_close_started_event` hardcodes the literal
"close_started" in the event metadata JSON. The Python consumer
(`retro_metrics.security_close_ran`) filters on the
`STATUS_ACTION_CLOSE_STARTED` constant. If anyone edits one without the
other, they silently diverge — and the security_checks=0 Courage rule
gated on `close_cycle_ran` quietly stops firing.

This test extracts the bash literal at the producer site and asserts
equality with the Python constant. Catches a renamed/typo'd literal
the moment a CI run hits it.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _bases import _PLUGIN_ROOT
from event_metadata import STATUS_ACTION_CLOSE_STARTED


def _extract_function_body(source: str, function_name: str) -> str | None:
    """Return text between `function_name() {` and its matching `}`.

    Scoped extraction prevents the action-literal regex from matching
    `"action":"<other>"` literals elsewhere in the file (e.g., a future
    sibling helper). Walks brace depth to locate the closing `}` so
    nested blocks inside the function body don't terminate early.
    """
    opener = f"{function_name}() {{"
    start = source.find(opener)
    if start < 0:
        return None
    depth = 1
    i = start + len(opener)
    while i < len(source) and depth > 0:
        ch = source[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    if depth != 0:
        return None
    return source[start:i]


class TestCloseStartedActionStringPin(unittest.TestCase):
    _PRELOAD_BASE = _PLUGIN_ROOT / "skills" / "_preload_base.sh"

    @classmethod
    def setUpClass(cls):
        cls.source = cls._PRELOAD_BASE.read_text()

    def test_emit_close_started_event_action_matches_python_constant(self):
        # Scope the regex to the function body so a future sibling helper
        # adding `"action":"<other>"` elsewhere in the file doesn't make
        # this pin silently match the wrong literal.
        body = _extract_function_body(self.source, "emit_close_started_event")
        self.assertIsNotNone(
            body,
            "emit_close_started_event() helper not found in _preload_base.sh",
        )
        # Grep the function body for the action-literal pattern. The bash
        # builds metadata JSON inline as a double-quoted shell string, so
        # the inner JSON quotes are backslash-escaped: `\"action\":\"value\"`.
        # The regex tolerates optional backslashes around each quote and
        # whitespace around the colon.
        match = re.search(
            r'\\?"action\\?"\s*:\s*\\?"([^"\\]+)\\?"',
            body or "",
        )
        self.assertIsNotNone(
            match,
            "emit_close_started_event body must emit an `action` key — "
            "JSON literal not found",
        )
        assert match is not None  # pyright narrow
        bash_literal = match.group(1)
        self.assertEqual(
            bash_literal,
            STATUS_ACTION_CLOSE_STARTED,
            f"bash literal {bash_literal!r} in _preload_base.sh "
            f"emit_close_started_event diverged from Python constant "
            f"STATUS_ACTION_CLOSE_STARTED={STATUS_ACTION_CLOSE_STARTED!r}. "
            "Update one to match the other — retro_metrics.security_close_ran "
            "filters on the Python constant, so divergence silently disables "
            "the security_checks=0 Courage rule.",
        )

    def test_helper_present_with_expected_shape(self):
        # Belt-and-suspenders: assert the helper itself exists by name so
        # a refactor that moves the emit to a different function (and
        # changes the action literal there) doesn't silently pass the
        # regex above by matching a stale `"action":"close_started"` in
        # some other location.
        self.assertIn(
            "emit_close_started_event()",
            self.source,
            "emit_close_started_event helper must exist by name in "
            "_preload_base.sh — the action-literal pin is scoped to "
            "that helper's site",
        )


if __name__ == "__main__":
    unittest.main()

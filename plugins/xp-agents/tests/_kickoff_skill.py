#!/usr/bin/env python3
"""Shared helpers for kickoff SKILL.md prose tests.

`_SKILL_MD` (the path) and `slice_step` (one `## Step` section slicer) are used
by every test_kickoff_*.py module — defined once here so the prose-anchoring
tests share a single definition.
"""

from conftest import _PLUGIN_ROOT

_SKILL_MD = _PLUGIN_ROOT / "skills" / "xp-kickoff" / "SKILL.md"


def slice_step(text: str, heading: str) -> str:
    """Return one `## Step ...` section, sliced to the next `## Step` header."""
    start = text.find(heading)
    if start < 0:
        return ""
    end = text.find("\n## Step", start + len(heading))
    return text[start:end] if end > 0 else text[start:]

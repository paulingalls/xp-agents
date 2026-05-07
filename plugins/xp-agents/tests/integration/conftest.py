#!/usr/bin/env python3
"""Single canonical home for integration-suite preload paths.

Per-file copies drift when a skill moves; the pin in
test_conftest_consolidation_pin enforces this is the only definition site.
"""

from _bases import _PLUGIN_ROOT

_XP_ACCEPT_PRELOAD = _PLUGIN_ROOT / "skills" / "xp-accept" / "scripts" / "preload.sh"
_XP_STORY_CLOSE_PRELOAD = (
    _PLUGIN_ROOT / "skills" / "xp-story-close" / "scripts" / "preload.sh"
)

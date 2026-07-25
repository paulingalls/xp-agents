#!/usr/bin/env python3
"""Plugin-root resolution and guide loading.

Resolves CLAUDE_PLUGIN_ROOT (from env or __file__ fallback) and loads
the three guides we ship to agents — XP_VALUES.md, PROCESS_GUIDE.md,
TEAMMATE_GUIDE.md. Extracted from _common.py so the hook-helpers module
isn't doing double duty as a plugin-asset loader.

Agent Bash strips CLAUDE_PLUGIN_ROOT, so guide text must be expanded
before injection — otherwise the documented
`${CLAUDE_PLUGIN_ROOT}/smm/append.sh` pattern breaks silently in
`claude -p` subprocesses.

Why no caching: env-var read is O(1) and the __file__ fallback is
constant. A previous @functools.lru_cache on resolve_plugin_root
introduced staleness when tests pinned the env var — pytest's
source-order test runs would poison the result for every subsequent
in-process caller.
"""

import json
import os
from pathlib import Path


def resolve_plugin_root() -> Path:
    """Resolve plugin root from CLAUDE_PLUGIN_ROOT env var or __file__."""
    env_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env_root:
        return Path(env_root)
    return Path(__file__).parent.parent


def plugin_version() -> str:
    """Version string from the plugin manifest, or '?' if unreadable.

    Lives here rather than in a hook entry point: a library module must not
    import a hook, so every reader that is not session_start would otherwise
    copy this.
    """
    try:
        path = resolve_plugin_root() / ".claude-plugin" / "plugin.json"
        return str(json.loads(path.read_text(encoding="utf-8")).get("version", "?"))
    except (OSError, json.JSONDecodeError, ValueError):
        return "?"


def expand_plugin_root(text: str) -> str:
    """Substitute ${CLAUDE_PLUGIN_ROOT} with the resolved plugin root."""
    return text.replace("${CLAUDE_PLUGIN_ROOT}", str(resolve_plugin_root()))


def _load_plugin_file(filename: str) -> str:
    """Read a plugin-root file and expand ${CLAUDE_PLUGIN_ROOT} in its text."""
    try:
        path = resolve_plugin_root() / filename
        if path.is_file():
            return expand_plugin_root(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return ""


def load_xp_values() -> str:
    return _load_plugin_file("XP_VALUES.md")


def load_process_guide() -> str:
    return _load_plugin_file("PROCESS_GUIDE.md")


def load_teammate_guide() -> str:
    return _load_plugin_file("TEAMMATE_GUIDE.md")

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
import re
from pathlib import Path

_UNKNOWN = "?"

# Every shipped manifest, without naming a single host. A literal directory name
# here would put harness-specific vocabulary into shipped resolution logic, and
# a third manifest would silently go unread the day it appears.
_MANIFEST_GLOB = ".*-plugin/plugin.json"

# What a version-keyed path component looks like. Deliberately NARROW: the job
# is to tell "this path names a version" from "this path names nothing of the
# kind", and a looser shape would read an ordinary directory like `2` or `1.0`
# as a cache key and answer unknown for an ordinary checkout.
_VERSION_SHAPED = re.compile(r"^v?\d+\.\d+\.\d+$")


def resolve_plugin_root() -> Path:
    """Resolve plugin root from CLAUDE_PLUGIN_ROOT env var or __file__."""
    env_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env_root:
        return Path(env_root)
    return Path(__file__).parent.parent


def _manifest_versions(root: Path) -> list[str]:
    """Every version DECLARED by a manifest under `root`.

    A manifest that exists but cannot be parsed, or declares no version,
    contributes nothing rather than suppressing its readable siblings: it is a
    tree-integrity failure, and the question here is which copy is executing —
    which a manifest that WAS read still answers. Suppressing on it turned an
    interrupted regeneration of a derived manifest into a permanent unknown for
    a copy whose own manifest was perfectly readable.
    """
    versions: list[str] = []
    try:
        found = sorted(root.glob(_MANIFEST_GLOB))
    except OSError:
        return []
    for path in found:
        try:
            declared = json.loads(path.read_text(encoding="utf-8")).get("version")
        except (OSError, json.JSONDecodeError, ValueError, AttributeError):
            continue
        if not declared:
            continue
        versions.append(str(declared))
    return versions


def _version_key_component(root: Path) -> str | None:
    """The host's version key for this copy: `root`'s OWN final component.

    Position is the evidence, not decoration. Measured on both hosts, an install
    lands at `.../<plugin>/<version>/` and the plugin root IS the version-keyed
    directory. Judging every component instead reads any unrelated version-shaped
    ANCESTOR — `/opt/python/3.11.9/...`, a `1.0.0/` release directory, a
    versioned sync folder — as a cache key that names no manifest, and answers
    unknown for the ordinary checkout sitting under it.
    """
    last = root.parts[-1] if root.parts else ""
    return last if _VERSION_SHAPED.match(last) else None


def plugin_version() -> str:
    """Version of the plugin copy that is EXECUTING, or '?' when unknowable.

    Lives here rather than in a hook entry point: a library module must not
    import a hook, so every reader that is not session_start would otherwise
    copy this.

    Reading one fixed manifest was the measured defect — a session reported one
    number while the version-keyed cache directory it executed from held
    another, hiding the only value that says which cached copy is running. Two
    manifests now ship and agree by construction, so the signal is agreement
    between a manifest and the PATH being executed:

    - the root is a version-keyed directory naming a declared version -> that
      version, the executing copy;
    - a version-keyed root naming NO manifest -> unknown. This is the
      cache-bumped-in-place state, and reporting it is the point: a confident
      wrong number is worse than a visible '?';
    - an ordinary checkout (no version key) and one agreed version among the
      manifests that could be read -> that version;
    - anything else -> unknown, rather than preferring a candidate for which
      there is no evidence.
    """
    root = resolve_plugin_root()
    versions = _manifest_versions(root)
    if not versions:
        return _UNKNOWN
    key = _version_key_component(root)
    if key is not None:
        declared = key.removeprefix("v")
        return declared if declared in versions else _UNKNOWN
    if len(set(versions)) == 1:
        return versions[0]
    return _UNKNOWN


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

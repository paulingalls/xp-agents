#!/usr/bin/env python3
"""Which acceptance surfaces a set of paths touches, and the commands covering them.

Pure: every function takes plain dicts and loads nothing. The CLI seam
(`system_context_surface_cli.py`) owns reading system_context.json and
sprint.json, because a story's paths live in one document and the surfaces
in the other, and a module that loaded either could not be reused by a
caller that already has them.

Two reuse rules, both load-bearing:

`triage.compile_glob` — NOT `fnmatch`, and not a bare
`re.compile(glob_translator.glob_to_regex(...))`. The first is wrong twice
over: fnmatch's `*` crosses slashes, so `smm/*.py` wrongly claims
`smm/sub/a.py`, and it cannot express zero-segment `**`-recursion, so
`tests/**/*.py` wrongly misses `tests/a.py`. The second loses the re.error
guard that absorbs a malformed bracket class (`src/[]*.py`) — file_domain_lock
carries the same warning for the same reason, having been crashed by it.

Callers must hand in EXPANDED paths (see `commands_for_story`). Matching a
surface glob against a raw file_domain pattern would be glob-vs-glob, which
silently agrees far too often: `plugins/**` "matches" the literal string
`plugins/xp-agents/smm/*.py` because the regex `.*` happily eats the `*`.

`status` is deliberately not consulted. A surface marked `gap` that declares
a `command` is still selected: nothing in the schema couples the two fields,
and skipping a command the author explicitly wrote would be a rule invented
here rather than one the customer declared.
"""

from collections.abc import Iterable

import triage

__all__ = ["commands_for_paths", "commands_for_story", "surfaces_for_paths"]


def _surface_claims_any(surface: dict, paths: list[str]) -> bool:
    """True when any of the surface's declared globs matches any path.

    A surface declaring no `paths` claims NOTHING — never everything. That is
    the state every existing project is in (the field postdates their
    system_context.json), so the fail-open reading would silently select every
    surface for every story on first upgrade.
    """
    globs = surface.get("paths")
    if not isinstance(globs, list):
        return False
    for pattern in globs:
        if not isinstance(pattern, str):
            continue
        matcher = triage.compile_glob(pattern)
        if any(matcher.fullmatch(path) for path in paths):
            return True
    return False


def surfaces_for_paths(surfaces: Iterable[dict], paths: Iterable[str]) -> list[dict]:
    """The surface entries claiming at least one of `paths`, in declaration order.

    Returns the entries themselves, not just their commands: judging whether a
    selected set covers all-or-nearly-all surfaces needs surface identity.
    """
    path_list = list(paths)
    return [
        surface
        for surface in surfaces
        if isinstance(surface, dict) and _surface_claims_any(surface, path_list)
    ]


def commands_for_paths(surfaces: Iterable[dict], paths: Iterable[str]) -> list[str]:
    """De-duplicated commands of the surfaces claiming any of `paths`.

    Declaration order is preserved and duplicates collapse, so two surfaces
    sharing one command run it once. A matched surface that declares no
    command contributes nothing rather than blocking the others.
    """
    commands: list[str] = []
    for surface in surfaces_for_paths(surfaces, paths):
        command = surface.get("command")
        if isinstance(command, str) and command and command not in commands:
            commands.append(command)
    return commands


def story_file_domain(sprint: dict, story_id: str) -> list[str]:
    """One story's raw `file_domain` entries.

    Raises ValueError when the story is absent — the caller asked about a
    specific story, and an empty list would be indistinguishable from a story
    that genuinely claims nothing, which selects no surface and reads as
    "no narrowing available" instead of "you named the wrong story".
    """
    for story in sprint.get("stories", []):
        if isinstance(story, dict) and story.get("id") == story_id:
            domain = story.get("file_domain")
            return (
                [e for e in domain if isinstance(e, str)]
                if isinstance(domain, list)
                else []
            )
    raise ValueError(f"story not found in sprint: {story_id!r}")


def commands_for_story(
    system_context: dict,
    sprint: dict,
    story_id: str,
    *,
    cwd: str,
) -> list[str]:
    """Surface commands covering one story's file domain.

    `cwd` is required and is passed straight to
    `triage.extract_file_domain_paths`, which refuses a glob entry with no
    root rather than falling back to the process cwd. Expansion is what makes
    the comparison literal-path-vs-glob; see the module docstring.
    """
    paths = triage.extract_file_domain_paths(
        story_file_domain(sprint, story_id), cwd=cwd
    )
    surfaces = system_context.get("acceptance_surfaces")
    if not isinstance(surfaces, list):
        return []
    return commands_for_paths(surfaces, paths)

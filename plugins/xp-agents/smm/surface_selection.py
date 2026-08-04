#!/usr/bin/env python3
"""Which acceptance surfaces a set of paths touches, and the commands covering them.

Pure: every function takes plain dicts and loads nothing. The CLI seam
(`system_context_surface_cli.py`) owns reading system_context.json, because a
module that loaded it could not be reused by a caller that already has it.

Two reuse rules, both load-bearing:

`triage.compile_glob` — NOT `fnmatch`, and not a bare
`re.compile(glob_translator.glob_to_regex(...))`. The first is wrong twice
over: fnmatch's `*` crosses slashes, so `smm/*.py` wrongly claims
`smm/sub/a.py`, and it cannot express zero-segment `**`-recursion, so
`tests/**/*.py` wrongly misses `tests/a.py`. The second loses the re.error
guard that absorbs a malformed bracket class (`src/[]*.py`) — file_domain_lock
carries the same warning for the same reason, having been crashed by it.

Callers hand in LITERAL paths — `git diff --name-only` output, the changed-file
set. Never `file_domain` entries: a surface glob matched against a raw
file_domain pattern is glob-vs-glob, which silently agrees far too often
(`plugins/**` "matches" the literal string `plugins/xp-agents/smm/*.py`,
because the regex `.*` eats the `*`). The declared domain is also the wrong
input for a second reason — the close gate tolerates drift, so a story's
declaration is not what it changed.

Selection is all-or-nothing (`commands_for_changed_paths`, and therefore the
CLI): a path set only PARTLY claimed selects nothing. See `unclaimed_paths`.
That is the one direction in which narrowing tests LESS than the full command
it replaces, and the consumer is an auto-merge gate — so the veto lives in the
one door callers use, never beside it.

`status` is deliberately not consulted. A surface marked `gap` that declares
a `command` is still selected: nothing in the schema couples the two fields,
and skipping a command the author explicitly wrote would be a rule invented
here rather than one the customer declared.
"""

from collections.abc import Iterable

import triage

__all__ = [
    "commands_for_changed_paths",
    "commands_for_paths",
    "should_collapse",
    "surfaces_for_paths",
    "unclaimed_paths",
]


def _claimed_paths(surface: dict, paths: list[str]) -> set[str]:
    """The subset of `paths` the surface's declared globs match.

    A surface declaring no `paths` claims NOTHING — never everything. That is
    the state every existing project is in (the field postdates their
    system_context.json), so the fail-open reading would silently select every
    surface for every story on first upgrade.
    """
    globs = surface.get("paths")
    if not isinstance(globs, list):
        return set()
    claimed: set[str] = set()
    for pattern in globs:
        if not isinstance(pattern, str):
            continue
        matcher = triage.compile_glob(pattern)
        claimed.update(path for path in paths if matcher.fullmatch(path))
    return claimed


def unclaimed_paths(surfaces: Iterable[dict], paths: Iterable[str]) -> list[str]:
    """The paths NO surface claims, sorted — the residue, and the veto.

    A caller that narrows while this is non-empty runs less than it runs
    today: the unclaimed file's tests are in neither the selected commands
    nor anything else. Both close paths need the same answer (story close
    from a file_domain, free close from a branch diff), so the rule is a
    shared helper rather than a private branch inside one entry point.
    """
    path_list = list(paths)
    claimed: set[str] = set()
    for surface in surfaces:
        if isinstance(surface, dict):
            claimed |= _claimed_paths(surface, path_list)
    return sorted(set(path_list) - claimed)


def surfaces_for_paths(surfaces: Iterable[dict], paths: Iterable[str]) -> list[dict]:
    """The surface entries claiming at least one of `paths`, in declaration order.

    Returns the entries themselves, not just their commands: judging whether a
    selected set covers all-or-nearly-all surfaces needs surface identity.
    """
    path_list = list(paths)
    return [
        surface
        for surface in surfaces
        if isinstance(surface, dict) and _claimed_paths(surface, path_list)
    ]


def commands_for_paths(surfaces: Iterable[dict], paths: Iterable[str]) -> list[str]:
    """De-duplicated commands of the surfaces claiming any of `paths`.

    NOT a selection door — it carries NO coverage veto, so a caller that hands
    its result to a gate narrows to less testing than the full command it
    replaces the moment one path is unclaimed. Call
    `commands_for_changed_paths`; this is its final step, exposed only because
    the veto and the collapse rule are tested against it.

    Declaration order is preserved and duplicates collapse, so two surfaces
    sharing one command run it once. A matched surface that declares no
    command contributes nothing rather than blocking the others.
    """
    commands: list[str] = []
    for surface in surfaces_for_paths(surfaces, paths):
        command = _declared_command(surface)
        if command and command not in commands:
            commands.append(command)
    return commands


def _declared_command(surface: dict) -> str | None:
    """The surface's command, or None when it declares none.

    ONE predicate for "declares a command", shared by the selection and the
    collapse rule — two spellings would let a surface count as commanded for
    one and uncommanded for the other. Whitespace-only counts as none: the
    schema only type- and length-checks the field, so `"  "` reaches here, and
    a blank command is a bullet the gate cannot run.
    """
    command = surface.get("command")
    return command if isinstance(command, str) and command.strip() else None


def _distinct_commands(surfaces: Iterable[dict]) -> set[str]:
    return {
        command
        for s in surfaces
        if isinstance(s, dict) and (command := _declared_command(s)) is not None
    }


def should_collapse(surfaces: Iterable[dict], matched: Iterable[dict]) -> bool:
    """True when running the selection is no cheaper than running everything.

    Collapse when every DISTINCT declared command is selected AND there are at
    least two of them. The `>= 2` floor is arithmetic, not an invented
    threshold: the rule exists because N narrowed runs cost more than the one
    full command they replace, and at N=1 that is never true. Collapsing at
    N=1 would make narrowing never fire in the commonest shape — the feature
    complete and inert.

    Surfaces sharing one command count once, so two surfaces both declaring
    `pytest all` are one run, not two.

    ASSUMES the caller's fallback command covers every surface. Collapse
    swaps N runs for that one, so a project whose surfaces name DIFFERENT
    harnesses (browser=playwright, cli=pytest) while `stack.test_command`
    names only one tests LESS after collapsing than before. The same
    assumption already underwrites the partial-coverage veto's fallback —
    both hand the caller back to that one command — so it is stated here
    rather than re-decided: nothing in the schema can check it.
    """
    declared = _distinct_commands(surfaces)
    return len(declared) >= 2 and _distinct_commands(matched) == declared


def commands_for_changed_paths(system_context: dict, paths: Iterable[str]) -> list[str]:
    """Surface commands covering a CHANGED-path set — all of it, or none.

    The single selection door. Callers pass literal paths (`git diff
    --name-only`), never `file_domain` entries: the declared domain misses
    files a story drifted onto, and the close gate tolerates that drift, so
    selecting on the declaration would leave a drifted file's tests running
    nowhere at an auto-merge.

    Paths are used AS GIVEN — never re-expanded over disk. A deleted file
    matches no glob on the filesystem, so expansion would drop it from the
    residue and weaken the veto in the fail-open direction.

    Returns EMPTY when any path is unclaimed. That veto is the whole point of
    this function existing beside `commands_for_paths`, which has none: a door
    without it narrows to LESS testing than the full command it replaces.
    """
    surfaces = system_context.get("acceptance_surfaces")
    if not isinstance(surfaces, list):
        return []
    path_list = [p for p in paths if p]
    if not path_list:
        return []  # an empty diff is not "everything is covered"
    if unclaimed_paths(surfaces, path_list):
        return []
    matched = surfaces_for_paths(surfaces, path_list)
    if should_collapse(surfaces, matched):
        # Selecting everything is not cheaper than the one command it
        # replaces, so say "no narrowing available" and let the caller's
        # existing fallback run the full suite ONCE rather than N times.
        return []
    return commands_for_paths(surfaces, path_list)

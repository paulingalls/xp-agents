#!/usr/bin/env python3
"""The skill-to-preload-invocation mapping, in one place.

A skill's `!`...`` SKILL.md line used to be the only existing record of which
command that skill's preload is; no skill carries one any more. This module is
the resolver that replaced that record for BOTH harnesses this plugin ships
to: one expands the `!`...`` line itself, the other places only the skill
locator in context and needs a hook to run the preload and inject its output
instead.

Derivation, not a maintained registry: the script name comes from the
`skills/*/scripts/*.sh` glob, so a differently-named entry point, like
`xp-kickoff/scripts/check_session_needs.sh`, resolves for free — nothing to
keep in sync, nothing to drift. Nothing is hand-maintained here at all now: the
table of extra arguments went with its last entry (`xp-assign`'s
`--consume-gate`, story-021), removed rather than left as a lookup over an
empty dict whose own superset guard an empty set satisfies vacuously.

What an invocation IS has not narrowed: it is still argv AND environment, and
`PreloadInvocation.argv` is a list precisely so a script that needs an argument
can be given one. Re-add the table if a second such script appears — with a
guard that fails on an empty one.

The conformance pin that compared this resolver against each `!`...`` line
(`tests/skills/test_skill_preload_map.py`) was retired with the last line
(story-013), as its own docstring required — removed rather than left scanning
an empty set. What it proved is asserted directly against the resolver now:
per-skill script name and the env-name contract.

`CLAUDE_PLUGIN_DATA` is the one name every shipped invocation requires
forwarded, and an empty value is a SUPPORTED state, not a failure: it is
legacy-SMM-discovery input only (see `smm_dir_resolve.plugin_managed_roots`
and `init.sh`'s `DISCOVER_LEGACY` branch). Where the `!` line ran inside a
shell that had a real value and a hook process runs with none, legacy
discovery silently does not happen, and the preload it resolves may find a
different SMM dir than the shell invocation would have. That is a cost this
module accepts, not a bug it hides.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

import plugin_loader

# Every environment variable name a shipped preload invocation requires
# forwarded — not a copy of the ambient environment. Today this is uniform
# across all 17 preload-bearing skills.
_REQUIRED_ENV: tuple[str, ...] = ("CLAUDE_PLUGIN_DATA",)


@dataclass(frozen=True)
class PreloadInvocation:
    argv: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


def _skills_dir() -> Path:
    # Not memoized: resolve_plugin_root() reads CLAUDE_PLUGIN_ROOT, and
    # caching it breaks test isolation (see plugin_loader's own docstring).
    return plugin_loader.resolve_plugin_root() / "skills"


def _discover_preload_scripts() -> dict[str, Path]:
    """Every skill's own preload script, keyed by skill name.

    Exactly one `.sh` per skill's `scripts/` dir is assumed; a skill that
    ships two fails loudly here rather than silently picking one.
    """
    by_skill: dict[str, list[Path]] = {}
    for script in sorted(_skills_dir().glob("*/scripts/*.sh")):
        by_skill.setdefault(script.parent.parent.name, []).append(script)

    scripts: dict[str, Path] = {}
    for name, paths in by_skill.items():
        if len(paths) != 1:
            raise ValueError(
                f"{name} ships {len(paths)} preload scripts under scripts/, "
                f"expected exactly one: {[str(p) for p in paths]}"
            )
        scripts[name] = paths[0]
    return scripts


def _names_a_shipped_skill(skill_name: str) -> bool:
    """A bare directory name under `skills/`, and nothing else.

    The shape check is not decoration: `""`, `"."`, `".."`, a nested path and
    an absolute path all pass the `is_dir()` check while matching none of the
    glob's bare-name keys, so without it each reads as "a skill that declares
    no preload" instead of "no such skill". `""` is the reachable one — a
    consumer reading the skill name out of hook input gets it whenever the
    field is missing. The relative components are named explicitly because
    pathlib does not collapse them: `Path("..").name` is `".."`.
    """
    if skill_name in ("", ".", "..") or skill_name != Path(skill_name).name:
        return False
    return (_skills_dir() / skill_name).is_dir()


def resolve_preload(skill_name: str) -> PreloadInvocation | None:
    """The preload invocation `skill_name` declares, or None if it has none.

    Raises ValueError for a skill name that names no shipped skill at all —
    distinct from None, which means "this skill exists and declares no
    preload."
    """
    if not _names_a_shipped_skill(skill_name):
        raise ValueError(f"unknown skill: {skill_name!r}")

    script = _discover_preload_scripts().get(skill_name)
    if script is None:
        return None

    argv = [str(script.resolve())]
    env = {name: os.environ.get(name, "") for name in _REQUIRED_ENV}
    return PreloadInvocation(argv=argv, env=env)


def resolve_preload_required(skill_name: str) -> PreloadInvocation:
    """`resolve_preload`, narrowed for callers that know a preload MUST
    exist. Raises ValueError when it doesn't."""
    invocation = resolve_preload(skill_name)
    if invocation is None:
        raise ValueError(f"{skill_name} declares no preload invocation")
    return invocation

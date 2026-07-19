#!/usr/bin/env python3
"""The teammate command line: what flags build_command emits, and why.

Extracted from spawn_teammate.py (which owns worktree/marker lifecycle, prompt
resolution, and the story promote) to keep both files under the size cap. Pure
argv construction and no I/O, but it consults the smm/ sibling ``tier_wire`` for
effort-support gating, so it adds smm/ to sys.path itself (mirroring markers.py
and retrospective.py) — this keeps it importable standalone rather than relying
on the importer's bootstrap.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import tier_wire

_ALLOWED_TOOLS = "Read,Write,Edit,Bash,Grep,Glob,Skill,Agent"


def build_command(
    name: str,
    model: str | None = None,
    plugin_dir: str | None = None,
    effort: str | None = None,
) -> list[str]:
    """Construct the claude -p command for a teammate.

    Prompt is piped via stdin, not passed as a CLI flag. When *model* is
    given, a --model flag selects the teammate's tier (e.g. sonnet for a
    delegated solo teammate); otherwise the claude -p default is inherited.

    When *plugin_dir* is given, a --plugin-dir flag loads that plugin into the
    headless teammate session. This is REQUIRED for the teammate to get the
    xp-agents skills, agents, and hooks: a worktree `claude -p` session does
    not apply the project-scoped marketplace enablement, so without
    --plugin-dir the plugin (and its full hook lifecycle) never loads.

    When *effort* is given, a --effort flag forwards the reasoning-effort
    level — but only when the resolved *model* is known to support it
    (tier_wire.effort_supported). Support is non-uniform across tiers (the
    cheapest tier rejects effort outright), so an unsupported model+effort
    pair is dropped with a stderr note rather than erroring the spawn: it
    fail-safes to the model default. When *model* is None the resolved tier
    is inherited from the orchestrator and unknown here, so effort is treated
    as unverifiable and dropped — never forward a param we can't confirm.
    """
    cmd = [
        "claude",
        "-p",
        "--name",
        name,
        "--dangerously-skip-permissions",
        "--allowedTools",
        _ALLOWED_TOOLS,
        "--output-format",
        "stream-json",
        "--include-partial-messages",
        "--verbose",
    ]
    if model is not None:
        cmd += ["--model", model]
    if plugin_dir is not None:
        cmd += ["--plugin-dir", plugin_dir]
    if effort is not None:
        if model is None:
            sys.stderr.write(
                f"spawn_teammate: model inherited from orchestrator (unknown "
                f"here) — cannot verify effort {effort!r} support, dropping "
                f"--effort, using model default\n"
            )
        elif not tier_wire.effort_supported(model, effort):
            sys.stderr.write(
                f"spawn_teammate: model {model!r} does not support effort "
                f"{effort!r} — dropping --effort, using model default\n"
            )
        else:
            cmd += ["--effort", effort]
    return cmd

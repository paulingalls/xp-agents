#!/usr/bin/env python3
"""Pure-logic plan/preview/decline helpers for /xp-scaffold-acceptance.

Three pure functions consumed by the scaffold-acceptance skill:

- build_plan(...): assemble the structured in-memory ``ScaffoldPlan`` the
  skill shows the customer in Step 4. Files-to-create / files-to-modify
  entries may carry an optional ``body`` field with the full file contents
  the apply pipeline will write.
- render_preview(plan, show_files=False): format the plan per scaffolding
  doctrine §Preview-before-write, ending with the verbatim
  ``Proceed? [yes / show files / no]`` prompt. When ``show_files=True``
  and at least one entry carries a body, an additional ``Files:`` section
  with fenced code blocks is rendered before the install/verify section.
- decline_if_unreliable(tool, guidance): structured ``DeclineResult`` for
  non-canonical tools where the agent's web research did not surface
  reliable install/config guidance.

No I/O, no subprocess, no network. Skill orchestration (web refresh,
AskUserQuestion) lives in SKILL.md; disk I/O lives in scaffold_apply.
"""

from dataclasses import dataclass, field
from typing import NamedTuple

PROCEED_PROMPT = "Proceed? [yes / show files / no]"
VERIFY_SUFFIX = "    # must pass green"
BRANCH_NEW_SUFFIX = "(new, off main)"


@dataclass
class ScaffoldPlan:
    surface: str
    tool: str
    tool_version: str
    verify_cmd: str
    branch_name: str
    files_to_create: list[dict] = field(default_factory=list)
    files_to_modify: list[dict] = field(default_factory=list)
    install_cmds: list[str] = field(default_factory=list)
    # Identity-verify probe: when verify_identity_cmd is set, the apply
    # pipeline runs it after install and asserts its stdout matches
    # expected_version_pattern (Python regex, re.search) — guards against
    # name-collision installs landing the wrong binary. Empty defaults
    # preserve back-compat for plans built before the field existed.
    verify_identity_cmd: str = ""
    expected_version_pattern: str = ""


class DeclineResult(NamedTuple):
    decline: bool
    reason: str | None


def build_plan(
    *,
    surface: str,
    tool: str,
    tool_version: str,
    files_to_create: list[dict],
    files_to_modify: list[dict],
    install_cmds: list[str],
    verify_cmd: str,
    branch_name: str,
    verify_identity_cmd: str = "",
    expected_version_pattern: str = "",
) -> ScaffoldPlan:
    """Return the structured scaffold plan.

    Each entry in files_to_create / files_to_modify is a dict with at
    least ``path`` and ``description``; files_to_create entries may also
    carry ``line_count``. Lists are defensively copied so caller
    mutation post-build does not leak into the plan.

    ``verify_identity_cmd`` and ``expected_version_pattern`` (default
    empty) carry the optional tool-identity-probe state — see the
    ScaffoldPlan field comment.
    """
    return ScaffoldPlan(
        surface=surface,
        tool=tool,
        tool_version=tool_version,
        verify_cmd=verify_cmd,
        branch_name=branch_name,
        files_to_create=list(files_to_create),
        files_to_modify=list(files_to_modify),
        install_cmds=list(install_cmds),
        verify_identity_cmd=verify_identity_cmd,
        expected_version_pattern=expected_version_pattern,
    )


def render_preview(plan: ScaffoldPlan, *, show_files: bool = False) -> str:
    """Format ``plan`` per scaffolding doctrine §Preview-before-write.

    Output ends with the verbatim ``PROCEED_PROMPT`` so the skill's
    confirm step can present a single deterministic string to the
    customer.

    When ``show_files=True`` and at least one ``files_to_create`` /
    ``files_to_modify`` entry carries a ``body`` key (including an empty
    string, which renders an explicit empty fence pair), a ``Files:``
    section with fenced code blocks renders before the install/verify
    section. Entries with a missing or ``None`` body are omitted from
    that section. With ``show_files=False`` (default), bodies are never
    rendered.
    """
    lines: list[str] = []
    lines.append(f"Selected surface: {plan.surface}")
    lines.append(f"Selected tool: {plan.tool} (latest: {plan.tool_version})")
    lines.append("")
    lines.append("Planning scaffold:")
    lines.append("")
    for entry in plan.files_to_create:
        line_count = entry.get("line_count")
        suffix = f", {line_count} lines" if line_count is not None else ""
        lines.append(f"  Create: {entry['path']} ({entry['description']}{suffix})")
    for entry in plan.files_to_modify:
        lines.append(f"  Modify: {entry['path']} ({entry['description']})")
    lines.append("")
    if show_files:
        bodied = [
            entry
            for entry in (*plan.files_to_create, *plan.files_to_modify)
            if entry.get("body") is not None
        ]
        if bodied:
            lines.append("Files:")
            lines.append("")
            for entry in bodied:
                lines.append(f"### {entry['path']}")
                lines.append("```")
                if entry["body"]:
                    lines.append(entry["body"].rstrip("\n"))
                lines.append("```")
                lines.append("")
    lines.append("Install + verify:")
    for cmd in plan.install_cmds:
        lines.append(f"  {cmd}")
    lines.append(f"  {plan.verify_cmd}{VERIFY_SUFFIX}")
    lines.append("")
    lines.append(f"Commit branch: {plan.branch_name} {BRANCH_NEW_SUFFIX}")
    lines.append("")
    lines.append(PROCEED_PROMPT)
    return "\n".join(lines)


def decline_if_unreliable(tool: str, guidance: str | None) -> DeclineResult:
    """Decide whether to decline scaffolding for a non-canonical tool.

    Returns ``DeclineResult(decline=True, reason="...")`` when ``guidance``
    is None, empty, or whitespace-only — the doctrine's "decline rather
    than guess" path. Returns ``DeclineResult(decline=False, reason=None)``
    when the caller has gathered usable install/config guidance.
    """
    if guidance is None or not guidance.strip():
        return DeclineResult(
            decline=True,
            reason=(
                f"No reliable install/configuration guidance found for {tool!r}. "
                "Per scaffolding doctrine, declining rather than guessing — "
                "pick a canonical tool or supply guidance and re-invoke."
            ),
        )
    return DeclineResult(decline=False, reason=None)

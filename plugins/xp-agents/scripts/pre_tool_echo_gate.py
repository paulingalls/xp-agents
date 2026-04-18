#!/usr/bin/env python3
"""PreToolUse + UserPromptSubmit hook: echo-enforcement for rendered content.

When kickoff asks the housekeeper/retrospective agents to render the curated
SMM and the latest retrospective, the render CLIs drop
`.pending-render-{smm,retro}-{agent_id}` markers at SMM_DIR carrying the
signature line of the rendered block. Subagent tool-results are not visible
to the user, so without enforcement the main agent could silently skip the
echo step.

This hook runs before the next tool invocation (Agent, Write, Edit,
MultiEdit, Bash, Skill) and before the next user prompt is processed. When
a pending render marker exists for the calling agent, it scans the
assistant-authored text of the transcript for the signature line and either
consumes the marker (verified echo) or blocks the tool call (exit 2 with
`Unechoed render` reason on stderr).

Fail-open conditions: missing transcript_path, unreadable transcript file,
missing/invalid SMM directory, xp-* agent invocations (recursion).
Only role=='assistant' / type=='text' blocks are scanned — tool_use and
tool_result blocks are excluded so tool output containing the signature
does not falsely clear the marker.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import identity
import marker_names
import markers

# (MarkerDef, signature line, human-readable kind)
_GATED_MARKERS: tuple[tuple[markers.MarkerDef, str, str], ...] = (
    (
        markers.PENDING_RENDER_RETRO,
        marker_names.RENDER_RETRO_SIGNATURE,
        "retrospective",
    ),
    (markers.PENDING_RENDER_SMM, marker_names.RENDER_SMM_SIGNATURE, "SMM"),
)


def _assistant_text(transcript_path: Path) -> str | None:
    """Concatenate assistant-authored text blocks from the transcript.

    Returns None when the transcript is unreadable (signaling fail-open).
    Returns "" when the transcript exists but has no assistant text — that
    is a genuine empty state, not a fail-open signal, so callers should
    still enforce the gate.

    Only role=='assistant' message entries are scanned, and within those
    only content blocks with type=='text'. tool_use and tool_result blocks
    are excluded so tool output containing the signature does not falsely
    clear the marker.
    """
    try:
        raw = transcript_path.read_text(encoding="utf-8")
    except OSError:
        return None
    parts: list[str] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        message = entry.get("message") if isinstance(entry, dict) else None
        if not isinstance(message, dict):
            continue
        if message.get("role") != "assistant":
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "text":
                continue
            text = block.get("text", "")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts)


def _block_reason(kind: str, signature: str) -> str:
    return (
        f"Unechoed render: {kind}. The {kind} content carries a distinctive "
        f"signature line that must appear verbatim in the assistant's text "
        f"output before the next tool call. Echo the full block to the user "
        f"now — it must include the line '{signature}'."
    )


def run(input_data: dict, smm_dir: Path | None = None) -> None:
    """Core logic. Returns None on allow. Raises BlockedError on block.

    Follows the established convention in pre_tool_write.py / pre_tool_bash.py
    so main() can share a single exit path.
    """
    if _common.is_xp_agent(input_data):
        return None
    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        return None
    agent_id = identity.resolve_agent_id(input_data)

    pending = [
        (marker, signature, kind)
        for marker, signature, kind in _GATED_MARKERS
        if markers.marker_exists(smm_dir, marker, agent_id)
    ]
    if not pending:
        return None

    transcript_path_str = input_data.get("transcript_path")
    if not transcript_path_str:
        return None
    assistant_text = _assistant_text(Path(transcript_path_str))
    if assistant_text is None:
        return None

    for marker, signature, kind in pending:
        if signature in assistant_text:
            markers.marker_consume(smm_dir, marker, agent_id)
        else:
            raise _common.BlockedError(_block_reason(kind, signature))
    return None


def main() -> None:
    input_data = _common.read_hook_input()
    try:
        run(input_data)
    except _common.BlockedError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""PreToolUse:Skill hook — inject guidance before skills run.

Two injections:
- /simplify: courage nudge to run all 3 review subagents
- /xp-quality-review: resolves-trailer probe (open concerns matching changed files)
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import _common
import resolves_probe

_SIMPLIFY_COURAGE = (
    "Courage means doing the right thing even when it's uncomfortable. "
    "/simplify requires launching 3 review subagents in parallel "
    "(code reuse, code quality, efficiency) — every time, on every change. "
    "Skipping subagents because the change 'looks small' is the easy path. "
    "Small changes hide duplication that only the code reuse agent catches "
    "by searching the broader codebase. Run all 3 agents."
)


def _run_qr_probe() -> str:
    """Run the resolves-trailer probe for quality review."""
    smm_dir = _common.resolve_smm_dir()
    if smm_dir is None:
        return "(SMM unavailable — skip probe)"

    cwd = os.getcwd()
    changed = resolves_probe.changed_files(cwd)
    if not changed:
        return "(no changed files)"

    candidates = resolves_probe.find_probe_candidates(
        smm_dir, changed, resolves=[], cwd=cwd
    )
    if not candidates:
        return "(no open concerns match changed files)"

    lines = resolves_probe.build_nudge_lines(candidates)
    return "\n".join(lines)


def run(input_data: dict, **_kwargs) -> str | None:
    """Inject guidance before skills run."""
    if _common.is_xp_agent(input_data):
        return None

    skill = input_data.get("tool_input", {}).get("skill", "")

    if "simplify" in skill:
        return _SIMPLIFY_COURAGE

    if "quality-review" in skill:
        return _run_qr_probe()

    return None


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result:
        _common.hook_output("PreToolUse", result)
    sys.exit(0)

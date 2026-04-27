#!/usr/bin/env python3
"""CLI wrapper for /xp-scaffold-acceptance helpers.

Thin wrapper over scaffold_detect.py, scaffold_plan.py, and
coordination.py for the SKILL.md to invoke. Subcommands:

- teammates-active: exit 0 = no teammates, exit 1 = active (JSON on stdout)
- detect-surfaces: print acceptance_surfaces with detection results as JSON
- assess-tool: read guidance from stdin, print decline_if_unreliable result
- build-plan: read plan-input JSON from stdin, print ScaffoldPlan as JSON
- render-preview: read ScaffoldPlan JSON from stdin, print preview text

Stdin/stdout are the canonical channels for structured input/output —
no shell-quoted Python embeds.
"""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import coordination
import scaffold_detect
import scaffold_plan


def _require_smm_dir(args: argparse.Namespace, command: str) -> int | None:
    if args.smm_dir is None:
        print(f"--smm-dir is required for {command}", file=sys.stderr)
        return 2
    return None


def _cmd_teammates_active(args: argparse.Namespace) -> int:
    err = _require_smm_dir(args, "teammates-active")
    if err is not None:
        return err
    try:
        coord = coordination.read_coordination(args.smm_dir)
    except Exception as exc:
        # Exit 2 (not 1) so the agent doesn't misfire the doctrine refusal
        # — exit 1 means "teammates active," exit 2 means "couldn't tell."
        print(f"Failed to read coordination: {exc}", file=sys.stderr)
        return 2
    others = {aid: entry for aid, entry in coord.items() if aid != args.agent_id}
    if not others:
        return 0
    payload = {
        "count": len(others),
        "worktrees": [
            {"agent_id": aid, "worktree": entry.get("worktree", "")}
            for aid, entry in sorted(others.items())
        ],
    }
    print(json.dumps(payload))
    return 1


def _cmd_detect_surfaces(args: argparse.Namespace) -> int:
    err = _require_smm_dir(args, "detect-surfaces")
    if err is not None:
        return err
    surfaces = scaffold_detect.read_acceptance_surfaces(args.smm_dir)
    repo_root = args.repo_root
    out = []
    for surface in surfaces:
        name = surface.get("name", "")
        detection = scaffold_detect.detect_existing_tooling(name, repo_root)
        out.append(
            {
                "name": name,
                "status": surface.get("status", ""),
                "harness": surface.get("harness"),
                "has_tooling": detection["has_tooling"],
                "tool_name": detection["tool_name"],
                "config_files": [str(p) for p in detection["config_files"]],
            }
        )
    print(json.dumps(out))
    return 0


def _cmd_assess_tool(args: argparse.Namespace) -> int:
    guidance = sys.stdin.read()
    result = scaffold_plan.decline_if_unreliable(args.tool, guidance)
    print(json.dumps(result._asdict()))
    return 0


def _cmd_build_plan(args: argparse.Namespace) -> int:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON on stdin: {exc}", file=sys.stderr)
        return 1
    try:
        plan = scaffold_plan.build_plan(**data)
    except TypeError as exc:
        print(f"build-plan input error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(asdict(plan), indent=2))
    return 0


def _cmd_render_preview(args: argparse.Namespace) -> int:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON on stdin: {exc}", file=sys.stderr)
        return 1
    try:
        plan = scaffold_plan.ScaffoldPlan(**data)
    except TypeError as exc:
        print(f"render-preview input error: {exc}", file=sys.stderr)
        return 1
    print(scaffold_plan.render_preview(plan))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scaffold-acceptance skill CLI",
        epilog=(
            "Examples:\n"
            "  scaffold_cli.py --smm-dir DIR teammates-active --agent-id main\n"
            "  scaffold_cli.py --smm-dir DIR detect-surfaces --repo-root .\n"
            "  echo 'guidance...' | scaffold_cli.py --smm-dir DIR"
            " assess-tool --tool playwright\n"
            "  cat plan-input.json | scaffold_cli.py --smm-dir DIR build-plan\n"
            "  cat plan.json | scaffold_cli.py --smm-dir DIR render-preview"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--smm-dir",
        type=Path,
        required=False,
        help="SMM directory path (required for teammates-active, detect-surfaces)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    teammates = sub.add_parser(
        "teammates-active",
        help="Exit 0 if no teammates active; exit 1 with JSON payload otherwise",
    )
    teammates.add_argument("--agent-id", required=True, help="This agent's ID")

    detect = sub.add_parser(
        "detect-surfaces",
        help="Print acceptance_surfaces with detection results as JSON",
    )
    detect.add_argument(
        "--repo-root",
        type=Path,
        required=True,
        help="Repository root for config-file detection",
    )

    assess = sub.add_parser(
        "assess-tool",
        help="Decline check for a non-canonical tool (guidance on stdin)",
    )
    assess.add_argument("--tool", required=True, help="Tool name")

    sub.add_parser(
        "build-plan",
        help="Build ScaffoldPlan from JSON on stdin; print JSON on stdout",
    )

    sub.add_parser(
        "render-preview",
        help="Render preview text from ScaffoldPlan JSON on stdin",
    )

    args = parser.parse_args()

    dispatch = {
        "teammates-active": _cmd_teammates_active,
        "detect-surfaces": _cmd_detect_surfaces,
        "assess-tool": _cmd_assess_tool,
        "build-plan": _cmd_build_plan,
        "render-preview": _cmd_render_preview,
    }

    sys.exit(dispatch[args.command](args))


if __name__ == "__main__":
    main()

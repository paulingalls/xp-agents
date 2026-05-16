#!/usr/bin/env python3
"""CLI wrapper for /xp-scaffold-acceptance helpers.

Thin wrapper over scaffold_detect.py, scaffold_plan.py, scaffold_apply.py,
and coordination.py for the SKILL.md to invoke. Subcommands:

- teammates-active: exit 0 = no teammates, exit 1 = active (JSON on stdout)
- detect-surfaces: print acceptance_surfaces with detection results as JSON
- assess-tool: read guidance from stdin, print decline_if_unreliable result
- build-plan: read plan-input JSON from stdin, print ScaffoldPlan as JSON
- render-preview: read ScaffoldPlan JSON from stdin, print preview text
  (use --show-files to render bodies under a Files: section)
- apply-write: read plan JSON from stdin, snapshot + write all bodies,
  print ApplyResult JSON. Auto-reverts on write failure.
- apply-install: --snapshot-id, run install_cmds, auto-revert on failure
- apply-verify: --snapshot-id, run verify_cmd, auto-revert on failure
- apply-revert: --snapshot-id, explicit cancel — restore snapshot

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

# Re-export shim — `from scaffold_cli import _cmd_apply_*` keeps working
# for callers that imported from here before the apply-* family was
# extracted into scaffold_cli_apply.
from scaffold_cli_apply import (
    _cmd_apply_commit,
    _cmd_apply_install,
    _cmd_apply_record,
    _cmd_apply_revert,
    _cmd_apply_verify,
    _cmd_apply_verify_identity,
    _cmd_apply_write,
    _emit,
    _load_stdin_json,
    _require_smm_dir,
)


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
    _emit(payload)
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


def _cmd_find_introducing_commit(args: argparse.Namespace) -> int:
    """JSON-on-stdout wrapper for scaffold_detect.find_introducing_commit.

    SKILL.md Step 1c (redo branch) calls this to pin the revert pointer when
    the customer chose 'redo from scratch'. Prints the JSON dict on stdout
    when an introducing commit is found, ``null`` otherwise. Caller decides
    whether ``null`` means "untracked" or "non-git" — the helper is
    intentionally best-effort.
    """
    result = scaffold_detect.find_introducing_commit(args.repo_root, args.config_files)
    print(json.dumps(result))
    return 0


def _cmd_detect_monorepo(args: argparse.Namespace) -> int:
    """JSON-on-stdout wrapper for scaffold_detect.detect_monorepo.

    SKILL.md Step 1d calls this to decide whether to ask the customer where
    in the monorepo to land the scaffold. Always prints a JSON dict (with
    ``is_monorepo=False`` when no signal fires).
    """
    result = scaffold_detect.detect_monorepo(args.repo_root)
    print(json.dumps(result))
    return 0


def _cmd_assess_tool(args: argparse.Namespace) -> int:
    guidance = sys.stdin.read()
    result = scaffold_plan.decline_if_unreliable(args.tool, guidance)
    print(json.dumps(result._asdict()))
    return 0


def _cmd_build_plan(args: argparse.Namespace) -> int:
    data = _load_stdin_json()
    try:
        plan = scaffold_plan.build_plan(**data)
    except TypeError as exc:
        print(f"build-plan input error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(asdict(plan), indent=2))
    return 0


def _cmd_render_preview(args: argparse.Namespace) -> int:
    data = _load_stdin_json()
    try:
        plan = scaffold_plan.ScaffoldPlan(**data)
    except TypeError as exc:
        print(f"render-preview input error: {exc}", file=sys.stderr)
        return 1
    print(scaffold_plan.render_preview(plan, show_files=args.show_files))
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
        help=(
            "SMM directory path (required for teammates-active, detect-surfaces, "
            "apply-commit, apply-record)"
        ),
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

    find_introducing = sub.add_parser(
        "find-introducing-commit",
        help=(
            "Print JSON for the OLDEST commit that introduced any of the "
            "given config files; 'null' when not tracked"
        ),
    )
    find_introducing.add_argument(
        "--repo-root", type=Path, required=True, help="Repository root"
    )
    find_introducing.add_argument(
        "--config-files",
        type=Path,
        action="append",
        required=True,
        help="Config file path (repeat for multiple)",
    )

    detect_mono = sub.add_parser(
        "detect-monorepo",
        help=(
            "Print JSON {is_monorepo, kind, packages} for the repo's "
            "monorepo structure; always prints (kind=null when no signal)"
        ),
    )
    detect_mono.add_argument(
        "--repo-root", type=Path, required=True, help="Repository root"
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

    render = sub.add_parser(
        "render-preview",
        help="Render preview text from ScaffoldPlan JSON on stdin",
    )
    render.add_argument(
        "--show-files",
        action="store_true",
        help="Render file bodies under a Files: section (requires bodies in plan)",
    )

    apply_write = sub.add_parser(
        "apply-write",
        help="Snapshot + write all bodies; print ApplyResult JSON",
    )
    apply_write.add_argument(
        "--repo-root",
        type=Path,
        required=True,
        help="Repository root",
    )

    for name, helptext in [
        ("apply-install", "Run install_cmds; auto-revert on failure"),
        (
            "apply-verify-identity",
            "Run verify_identity_cmd, assert version pattern; auto-revert on mismatch",
        ),
        ("apply-verify", "Run verify_cmd; auto-revert on failure"),
        ("apply-revert", "Explicit cancel — restore the snapshot"),
    ]:
        p = sub.add_parser(name, help=helptext)
        p.add_argument(
            "--snapshot-id", required=True, help="Snapshot ID from apply-write"
        )
        p.add_argument(
            "--repo-root",
            type=Path,
            required=True,
            help="Repository root",
        )

    apply_commit = sub.add_parser(
        "apply-commit",
        help="Stage-aware branch + commit for a green scaffold",
    )
    apply_commit.add_argument(
        "--snapshot-id", required=True, help="Snapshot ID from apply-write"
    )
    apply_commit.add_argument(
        "--repo-root", type=Path, required=True, help="Repository root"
    )
    apply_commit.add_argument("--surface", required=True, help="Acceptance surface")
    apply_commit.add_argument("--tool", required=True, help="Scaffolded tool name")
    apply_commit.add_argument(
        "--concern-id",
        default=None,
        help="Concern event ID resolved by this commit (omit for 'none')",
    )

    apply_record = sub.add_parser(
        "apply-record",
        help="Flip system_context surface to covered + decision event",
    )
    apply_record.add_argument(
        "--snapshot-id", required=True, help="Snapshot ID from apply-write"
    )
    apply_record.add_argument(
        "--repo-root", type=Path, required=True, help="Repository root"
    )
    apply_record.add_argument("--surface", required=True, help="Acceptance surface")
    apply_record.add_argument(
        "--concern-id",
        default=None,
        help="Missing-acceptance concern event ID to resolve (decision event)",
    )
    apply_record.add_argument(
        "--agent-id",
        required=True,
        help="Agent ID for the decision event (skill is inline; pass caller agent)",
    )
    apply_record.add_argument(
        "--commit-sha",
        required=True,
        help=(
            "Scaffold commit SHA from apply-commit; required so apply-record "
            "can verify the commit landed and HEAD has not advanced past it "
            "before flipping the surface to covered (atomicity gate)"
        ),
    )

    args = parser.parse_args()

    dispatch = {
        "teammates-active": _cmd_teammates_active,
        "detect-surfaces": _cmd_detect_surfaces,
        "find-introducing-commit": _cmd_find_introducing_commit,
        "detect-monorepo": _cmd_detect_monorepo,
        "assess-tool": _cmd_assess_tool,
        "build-plan": _cmd_build_plan,
        "render-preview": _cmd_render_preview,
        "apply-write": _cmd_apply_write,
        "apply-install": _cmd_apply_install,
        "apply-verify-identity": _cmd_apply_verify_identity,
        "apply-verify": _cmd_apply_verify,
        "apply-revert": _cmd_apply_revert,
        "apply-commit": _cmd_apply_commit,
        "apply-record": _cmd_apply_record,
    }

    sys.exit(dispatch[args.command](args))


if __name__ == "__main__":
    main()

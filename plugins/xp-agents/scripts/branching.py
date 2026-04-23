#!/usr/bin/env python3
"""Branch lifecycle operations for story and sprint branches.

Provides branch naming, creation, merge, and deletion for the
branching doctrine's stage-based workflow.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "smm"))

import identity


def _slugify(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def _git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=10)


def branch_name(user_ns: str, story_id: str, slug: str) -> str:
    return f"{user_ns}/{story_id}-{_slugify(slug)}"


def get_branching_stage(smm_dir: Path) -> int:
    path = smm_dir / "system_context.json"
    if not path.exists() or path.is_symlink():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("branching_strategy", {}).get("stage", 0)
    except (json.JSONDecodeError, OSError):
        return 0


_PROTECTED_BRANCHES = {"main", "master"}


def is_protected_branch(stage: int, branch: str) -> bool:
    return stage >= 1 and branch in _PROTECTED_BRANCHES


_HEREDOC_MSG_RE = re.compile(
    r"-m\s+\"\$\(cat\s+<<'?\w+'?\n(.*?)\n\w+\n\)\"",
    re.DOTALL,
)
_SIMPLE_MSG_RE = re.compile(
    r"""-m\s+(?:"((?:[^"\\]|\\.)*)"|'([^']*)')""",
)


def extract_commit_message(command: str) -> str | None:
    """Extract the -m argument value from a git commit command."""
    heredoc = _HEREDOC_MSG_RE.search(command)
    if heredoc:
        return heredoc.group(1)
    m = _SIMPLE_MSG_RE.search(command)
    if m:
        return m.group(1) if m.group(1) is not None else m.group(2)
    return None


_ESCAPE_HATCH_RE = re.compile(r"^\[(release|chore)\]", re.IGNORECASE)


def is_escape_hatch_commit(command: str) -> bool:
    msg = extract_commit_message(command)
    if msg is None:
        return False
    return bool(_ESCAPE_HATCH_RE.match(msg))


def is_worktree_clean(cwd: str) -> bool:
    r = _git(["git", "status", "--porcelain"], cwd)
    return r.returncode == 0 and r.stdout.strip() == ""


def branch_exists(cwd: str, name: str) -> bool:
    r = _git(["git", "rev-parse", "--verify", f"refs/heads/{name}"], cwd)
    return r.returncode == 0


def create_story_branch(
    cwd: str, story_id: str, slug: str, smm_dir: Path
) -> str | None:
    """Returns branch name or None if Stage 0."""
    stage = get_branching_stage(smm_dir)
    if stage < 1:
        return None

    user_ns = identity.user_namespace(cwd)
    name = branch_name(user_ns, story_id, slug)

    if branch_exists(cwd, name):
        r = _git(["git", "checkout", name], cwd)
        if r.returncode != 0:
            print(f"Failed to checkout {name}: {r.stderr}", file=sys.stderr)
            sys.exit(1)
        return name

    if not is_worktree_clean(cwd):
        print("Working tree is dirty — commit or stash changes first", file=sys.stderr)
        sys.exit(1)

    r = _git(["git", "checkout", "-b", name], cwd)
    if r.returncode != 0:
        print(f"Failed to create branch: {r.stderr}", file=sys.stderr)
        sys.exit(1)

    return name


def merge_story_branch(cwd: str, story_branch: str, target: str = "main") -> None:
    r = _git(["git", "checkout", target], cwd)
    if r.returncode != 0:
        print(f"Failed to checkout {target}: {r.stderr}", file=sys.stderr)
        sys.exit(1)

    r = _git(
        ["git", "merge", "--no-ff", story_branch, "-m", f"Merge {story_branch}"],
        cwd,
    )
    if r.returncode != 0:
        print(f"Merge failed: {r.stderr}", file=sys.stderr)
        sys.exit(1)


def delete_branch(cwd: str, name: str) -> bool:
    r = _git(["git", "branch", "-d", name], cwd)
    return r.returncode == 0


def _cmd_create(args: argparse.Namespace) -> int:
    result = create_story_branch(args.cwd, args.story, args.slug, Path(args.smm_dir))
    if result is None:
        print("Skipped (stage < 1)")
    else:
        print(result)
    return 0


def _cmd_merge(args: argparse.Namespace) -> int:
    merge_story_branch(args.cwd, args.branch, args.target)
    return 0


def _cmd_delete(args: argparse.Namespace) -> int:
    ok = delete_branch(args.cwd, args.branch)
    return 0 if ok else 1


def _cmd_stage(args: argparse.Namespace) -> int:
    stage = get_branching_stage(Path(args.smm_dir))
    print(stage)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Branch lifecycle operations")
    parser.add_argument("--smm-dir", required=True, help="SMM directory path")
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create", help="Create a story branch")
    p_create.add_argument("--cwd", required=True)
    p_create.add_argument("--story", required=True)
    p_create.add_argument("--slug", required=True)
    p_create.set_defaults(func=_cmd_create)

    p_merge = sub.add_parser("merge", help="Merge a story branch")
    p_merge.add_argument("--cwd", required=True)
    p_merge.add_argument("--branch", required=True)
    p_merge.add_argument("--target", default="main")
    p_merge.set_defaults(func=_cmd_merge)

    p_delete = sub.add_parser("delete", help="Delete a branch")
    p_delete.add_argument("--cwd", required=True)
    p_delete.add_argument("--branch", required=True)
    p_delete.set_defaults(func=_cmd_delete)

    p_stage = sub.add_parser("stage", help="Print branching stage")
    p_stage.set_defaults(func=_cmd_stage)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Verify-path extraction + touch-check primitive.

Implements the harness path-parsing rules. `agents/xp-plan-reviewer.md` §10b
is the AUTHORITATIVE spec; `_extract_paths_from_command` implements it — keep
the two in sync (a new runner shape belongs in §10b first, then here). Given a
story's per-AC verify objects and story-level acceptance_execution, extract the
test-file paths their commands point at, then check which of those paths no
commit on the story branch ever touched.

Both the commit-time verify nudge and the story-close gate consume this
single source of truth; the CLI serves the close preload.
"""

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import branching
import sprint_store
from _acceptance_execution import extract_commands

# pytest short flags that consume a following token as their argument — the
# token after one of these is a value, never a path.
_PYTEST_ARG_FLAGS = {"-k", "-m", "-p", "-c", "-o", "-n", "-r", "--maxfail"}

# CLI exit codes. 1 is a gate signal (untouched paths found), NOT an error —
# the story-close preload distinguishes it from a real failure (2).
_EXIT_CLEAN = 0
_EXIT_UNTOUCHED = 1
_EXIT_ERROR = 2

# Bare `unittest discover` (no -s) defaults to the cwd: the whole tree. Any
# branch change satisfies it, so the gate fails open rather than silent.
_WHOLE_TREE_SENTINEL = "."


def _split_cd_prefix(tokens: list[str]) -> tuple[str | None, list[str]]:
    """Peel a leading `cd <dir> &&` off the token list (the monorepo shape).

    Returns (cd_dir, remaining_tokens). Only a leading `cd <dir> &&` is
    recognized — mid-chain cd is out of scope (§10b). Paths after such a
    prefix are cd-relative and must be rebased to repo-relative by callers.
    """
    if len(tokens) >= 3 and tokens[0] == "cd" and tokens[2] == "&&":
        return tokens[1], tokens[3:]
    return None, tokens


def _extract_paths_from_command(command: str) -> set[str]:
    """Parse test-file/dir path tokens from a single command string.

    Recognizes the four harness shapes §10b enumerates: pytest /
    `python -m pytest <path>` (positional paths, `::selector` stripped),
    `python -m unittest discover -s <startdir> [-t <topdir>]`, and direct
    `python <path>` / `bash <path>`. Unrecognized runners yield no paths —
    honest about what we can't parse, never a false positive.

    A leading `cd <dir> &&` prefix rebases every extracted path with `<dir>/`
    so it is repo-relative (git reports repo-relative paths). The whole-tree
    sentinel is left unprefixed — it already matches any change (fail open).
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        return set()
    if not tokens:
        return set()

    cd_dir, tokens = _split_cd_prefix(tokens)
    if not tokens:
        return set()

    if "unittest" in tokens and "discover" in tokens:
        paths = _extract_unittest_discover_dirs(tokens)
    elif "pytest" in tokens:
        paths = _extract_pytest_paths(tokens)
    elif tokens[0] in ("python", "python3", "bash", "sh"):
        paths = _extract_direct_script(tokens)
    else:
        return set()

    if cd_dir:
        prefix = cd_dir.rstrip("/")
        paths = {p if p == _WHOLE_TREE_SENTINEL else f"{prefix}/{p}" for p in paths}
    return paths


def _extract_unittest_discover_dirs(tokens: list[str]) -> set[str]:
    """Collect the -s start dir and -t top dir of `unittest discover`.

    A bare `discover` (no -s) defaults to the cwd per unittest — return the
    whole-tree sentinel rather than an empty set so a recognized runner never
    reads as an unparsable no-binding (which would silently pass the gate).
    """
    paths: set[str] = set()
    for flag in ("-s", "-t"):
        if flag in tokens:
            idx = tokens.index(flag)
            if idx + 1 < len(tokens):
                paths.add(tokens[idx + 1])
    return paths or {_WHOLE_TREE_SENTINEL}


def _extract_pytest_paths(tokens: list[str]) -> set[str]:
    """Collect positional path tokens passed to pytest, selector-stripped."""
    start = tokens.index("pytest") + 1
    paths: set[str] = set()
    skip_next = False
    for tok in tokens[start:]:
        if skip_next:
            skip_next = False
            continue
        if tok.startswith("-"):
            if tok in _PYTEST_ARG_FLAGS:
                skip_next = True
            continue
        paths.add(tok.split("::", 1)[0])
    return paths


def _extract_direct_script(tokens: list[str]) -> set[str]:
    """Path of a direct `python <path>` / `bash <path>` invocation.

    Skips `python -m <module> ...` — module runs are handled by the
    pytest/unittest branches; a bare `-m` form names no script path here.
    """
    for tok in tokens[1:]:
        if tok == "-m":
            return set()
        if tok.startswith("-"):
            continue
        return {tok}
    return set()


def extract_verify_paths(story: dict) -> set[str]:
    """Return the set of verify-bearing test paths a story declares.

    Union of paths parsed from each object-shaped acceptance_criteria item
    carrying a command/commands verify block AND the story-level
    acceptance_execution. String ACs and a story with no verify commands
    yield an empty set.
    """
    paths: set[str] = set()
    for item in story.get("acceptance_criteria", []):
        if isinstance(item, dict) and ("command" in item or "commands" in item):
            for cmd in extract_commands(item):
                paths |= _extract_paths_from_command(cmd)
    ae = story.get("acceptance_execution")
    if ae:
        for cmd in extract_commands(ae):
            paths |= _extract_paths_from_command(cmd)
    return paths


def _changed_files(cwd: str, base: str, head: str = "HEAD") -> set[str]:
    """Every file touched by a commit on base..head (log-walk, not net diff).

    A net `git diff base..head` would miss a path written then reverted on
    the branch; the gate asks "was this path ever touched", so we walk every
    commit. `head` defaults to HEAD; the close-gate backstop passes the source
    branch (it runs on the target branch, so HEAD would be the wrong end).
    Raises ValueError when git fails (bad ref, not a repo) so callers pick
    their own fail-open/fail-closed policy rather than seeing a silent empty
    set.
    """
    try:
        result = subprocess.run(
            ["git", "log", f"{base}..{head}", "--name-only", "--pretty=format:"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=cwd,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise ValueError(f"git log {base}..{head} failed: {exc}") from exc
    if result.returncode != 0:
        raise ValueError(f"git log {base}..{head} failed: {result.stderr.strip()}")
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _is_touched(declared: str, changed: set[str]) -> bool:
    """True when a changed file equals `declared` or lives inside it.

    Directory declarations match any file beneath them (§10b "inside or
    equals"): `tests/hooks/` matches `tests/hooks/test_x.py`. The whole-tree
    sentinel (bare unittest discover) matches any change.
    """
    if declared == _WHOLE_TREE_SENTINEL:
        return bool(changed)
    prefix = declared if declared.endswith("/") else declared + "/"
    return any(f == declared or f.startswith(prefix) for f in changed)


def untouched_verify_paths(
    paths: set[str], cwd: str, base: str, head: str = "HEAD"
) -> list[str]:
    """Sorted declared paths that no commit on base..head touched."""
    changed = _changed_files(cwd, base, head)
    return sorted(p for p in paths if not _is_touched(p, changed))


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Report a story's declared verify paths untouched on its branch. "
            "Exit codes: 0 = all paths touched (clean), 1 = untouched paths "
            "found (gate signal, printed one per line), 2 = error."
        )
    )
    parser.add_argument("--smm-dir", required=True, help="SMM directory")
    parser.add_argument("--cwd", default=".", help="Repo working directory")
    parser.add_argument("--story", required=True, help="Story id, e.g. story-001")
    parser.add_argument(
        "--base",
        default=None,
        help="Base ref (defaults to the story base branch via branching).",
    )
    args = parser.parse_args()

    smm_dir = Path(args.smm_dir)
    try:
        story = sprint_store.get_story(smm_dir, args.story)
    except (ValueError, OSError) as exc:
        print(f"verify_paths: {exc}", file=sys.stderr)
        return _EXIT_ERROR

    paths = extract_verify_paths(story)
    if not paths:
        return _EXIT_CLEAN

    base = args.base or branching.get_story_base_branch(smm_dir, args.cwd)
    try:
        untouched = untouched_verify_paths(paths, args.cwd, base)
    except ValueError as exc:
        print(f"verify_paths: {exc}", file=sys.stderr)
        return _EXIT_ERROR

    for path in untouched:
        print(path)
    return _EXIT_UNTOUCHED if untouched else _EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main())

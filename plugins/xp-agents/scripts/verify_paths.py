#!/usr/bin/env python3
"""Verify-path extraction + touch-check primitive.

Implements the harness path-parsing rules. `agents/xp-plan-reviewer.md` §10b
is the AUTHORITATIVE spec; `_extract_paths_from_command` implements it — keep
the two in sync (a new runner shape belongs in §10b first, then here).
`test_parsing.is_test_run` owns runner classification (the framework
vocabulary); this module owns the verify-path policy (which frameworks name a
CLI path — the positional/whole-tree partition — and the token mechanics).
Given a story's per-AC verify objects and story-level acceptance_execution,
extract the test-file paths their commands point at, then check which of those
paths no commit on the story branch ever touched.

Both the commit-time verify nudge and the story-close gate consume this
single source of truth; the CLI serves the close preload.
"""

import argparse
import posixpath
import re
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import branching
import sprint_store
import test_parsing
from _acceptance_execution import extract_commands

# pytest short flags that consume a following token as their argument — the
# token after one of these is a value, never a path.
_PYTEST_ARG_FLAGS = {"-k", "-m", "-p", "-c", "-o", "-n", "-r", "--maxfail"}

# Leading tokens to skip before a positional runner's binary: package-manager
# wrappers (`npx jest`, `pnpm exec playwright`, `yarn dlx vitest`).
_WRAPPER_TOKENS = {
    "npm",
    "npx",
    "pnpm",
    "yarn",
    "bun",
    "bunx",
    "lerna",
    "corepack",
    "exec",
    "dlx",
}
# Subcommands that follow the runner binary and precede the paths
# (`playwright test <spec>`, `deno test <dir>`, `vitest run <path>`). `--test`
# is node's run-mode flag (`node --test <path>`) — a mode selector, not a
# value-consuming flag, so it belongs here rather than triggering skip-next.
_RUN_SUBCOMMANDS = {"test", "run", "--test"}

# Verify-path extraction policy by framework (keyed on is_test_run's returns).
# Positional runners name their proof file as a CLI token; whole-tree runners
# name a package/module/scheme/target — no CLI path — so they map to the
# sentinel. agents/xp-plan-reviewer.md §10b mirrors this partition.
_POSITIONAL_FRAMEWORKS = frozenset(
    {
        "pytest",
        "unittest",
        "playwright",
        "jest",
        "vitest",
        "mocha",
        "node-test",
        "deno",
        "rspec",
        "phpunit",
        "dart",
        "elixir",
        "bun",
    }
)
_WHOLE_TREE_FRAMEWORKS = frozenset(
    {
        "turbo",
        "nx",
        "cargo",
        "maven",
        "gradle",
        "xcodebuild",
        "dotnet",
        "ctest",
        "go",
        "swift",
        "minitest",
    }
)

# CLI exit codes. 1 is a gate signal (untouched paths found), NOT an error —
# the story-close preload distinguishes it from a real failure (2).
_EXIT_CLEAN = 0
_EXIT_UNTOUCHED = 1
_EXIT_ERROR = 2

# Bare `unittest discover` (no -s) defaults to the cwd: the whole tree. Any
# branch change satisfies it, so the gate fails open rather than silent.
_WHOLE_TREE_SENTINEL = "."


def classify_path_strategy(command: str) -> str:
    """Verify-path extraction strategy for a command: "positional",
    "whole_tree", or "none".

    Leans on `test_parsing.is_test_run`'s precedence (single source of truth)
    rather than re-matching launcher patterns — `pnpm exec playwright test`
    already resolves to "playwright", not a script alias. A runner that names
    its test file(s) on the CLI → "positional"; a script-alias/workspace
    launcher or a package/module/scheme/target runner → "whole_tree"
    (sentinel, fail-open); unrecognized → "none".

    `is_test_run` returns "jest" for BOTH the direct binary (`npx jest
    x.test.js`, names a path) AND npm/pnpm/yarn/lerna script aliases
    (`npm run test:e2e`, no path). A literal `jest` binary token
    disambiguates: present → direct (positional); absent → alias (whole_tree,
    so `test:e2e` is never read as a path). (Direct `python`/`bash <path>`
    and pytest/unittest are handled by the shape branches in
    `_extract_paths_from_command` before this is consulted.)

    "bun" has the same alias/direct split, but the disambiguator differs: a
    literal `bun` token is present in BOTH forms (bun is the binary either
    way), so `test_parsing.is_bun_script_alias` reads the `run`/colon-suffix
    shape instead of a binary-name check.
    """
    framework = test_parsing.is_test_run(command)
    if framework is None:
        return "none"
    if framework == "jest":
        return "positional" if re.search(r"\bjest\b", command) else "whole_tree"
    if framework == "bun":
        if test_parsing.is_bun_script_alias(command):
            return "whole_tree"
        return "positional"
    if framework in _POSITIONAL_FRAMEWORKS:
        return "positional"
    if framework in _WHOLE_TREE_FRAMEWORKS:
        return "whole_tree"
    return "none"


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

    Python shapes have dedicated branches: pytest / `python -m pytest <path>`
    (positional paths, `::selector` stripped), `python -m unittest discover -s
    <startdir> [-t <topdir>]`, and direct `python <path>` / `bash <path>`.
    Every other command is routed by `test_parsing.classify_path_strategy`:
    positional runners (playwright/jest/vitest/...) extract their CLI path
    tokens (a whole-suite run with no path → whole-tree sentinel); whole-tree
    runners (script aliases / package-or-scheme runners) → sentinel.
    Unrecognized runners yield no paths — honest about what we can't parse,
    never a false positive.

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
        match classify_path_strategy(" ".join(tokens)):
            case "positional":
                paths = _extract_positional_paths(tokens) or {_WHOLE_TREE_SENTINEL}
            case "whole_tree":
                paths = {_WHOLE_TREE_SENTINEL}
            case _:
                return set()

    if cd_dir:
        prefix = cd_dir.rstrip("/")
        paths = {_rebase(prefix, p) for p in paths}
    return paths


def _rebase(prefix: str, path: str) -> str:
    """Prefix a cd-relative path with the cd dir and normalize to repo-relative.

    `posixpath.normpath` collapses `..`/`.`/`//` so a cross-package token
    (`../shared/tests/` under `cd apps/agent`) resolves to git's actual
    repo-relative path (`apps/shared/tests/` — `..` cancels `agent`, one
    level, not the repo root) instead of failing the touch match.
    Trailing slash is preserved (normpath strips it) because a directory
    declaration drives `_is_touched`'s inside-or-equals match. The whole-tree
    sentinel is left untouched — it already matches any change (fail open).
    """
    if path == _WHOLE_TREE_SENTINEL:
        return path
    normalized = posixpath.normpath(f"{prefix}/{path}")
    return normalized + "/" if path.endswith("/") else normalized


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


def _extract_positional_paths(tokens: list[str]) -> set[str]:
    """Path tokens of a positional-path runner (playwright/jest/vitest/mocha/
    node-test/deno/rspec/phpunit/mix/dart/bun...).

    Skips package-manager wrappers, then a single leading flag (a bun
    workspace token like `--filter <pkg>` — the flag is skipped so the next
    token, "the runner binary", is never a flag itself), then the runner
    binary, then a leading `test`/`run` subcommand, then keeps only
    **path-shaped** positional tokens (containing `/` or `.`, with a
    `::selector` stripped). For bun specifically, `bun` IS the binary and
    `test` is its subcommand — the pre-binary flag-skip keeps a workspace
    flag's value (e.g. `@legacy/db` in `bun --filter @legacy/db test`) from
    being misread as "the binary" and, from there, as a path; that would be a
    false positive, which is strictly worse than the whole-tree sentinel it
    yields instead (a false positive demands a file that can never be
    touched). The token after a space-form bare flag (starts with `-`, no
    `=`) is dropped as that flag's value — so a path-shaped value like
    `--config jest.config.js` or `--reporter ./r.js` is never mistaken for a
    proof file. (A spurious gate firing is worse than under-extraction, which
    fails open; conservatively skipping a boolean flag's following token only
    ever under-extracts.) An attached `--flag=value` carries its own value,
    so the next token survives. No path tokens (a whole-suite run) yields an
    empty set; the caller maps that to the whole-tree sentinel.
    """
    i = 0
    n = len(tokens)
    while i < n and tokens[i] in _WRAPPER_TOKENS:
        i += 1
    if i < n and tokens[i].startswith("-"):
        i += 1
    if i < n:  # the runner binary itself
        i += 1
    while i < n and tokens[i] in _RUN_SUBCOMMANDS:
        i += 1
    paths: set[str] = set()
    skip_next = False
    for tok in tokens[i:]:
        if skip_next:
            skip_next = False
            continue
        if tok.startswith("-"):
            skip_next = "=" not in tok
            continue
        candidate = tok.split("::", 1)[0]
        if "/" in candidate or "." in candidate:
            paths.add(candidate)
    return paths


def extract_verify_paths(story: dict) -> set[str]:
    """Return the set of verify-bearing test paths a story declares.

    Union of paths parsed from each object-shaped acceptance_criteria item
    carrying a command/commands verify block AND the story-level
    acceptance_execution. String ACs and a story with no verify commands
    yield an empty set.

    A story may declare acceptance_execution.pins: a list of repo-relative,
    post-rebase path tokens (the same form extracted paths already take —
    a `cd apps/x && pytest tests/y` command yields `apps/x/tests/y`) that
    are deliberate regression pins: an existing test staying green
    unchanged IS the proof, so those paths are exempt from the untouched
    check. Both sides are posixpath-normalized before comparison so a pin
    written with a trailing slash or redundant `./` still matches.
    """
    paths: set[str] = set()
    for item in story.get("acceptance_criteria", []):
        if isinstance(item, dict) and ("command" in item or "commands" in item):
            for cmd in extract_commands(item):
                paths |= _extract_paths_from_command(cmd)
    ae = story.get("acceptance_execution")
    # The presence guard is not optional and not symmetry for its own sake: a
    # `manual` block carrying only `steps` is the CANONICAL command-less shape,
    # and `extract_commands` falls through to `ae["command"]`. Without this,
    # every caller inherited a KeyError -- including the story-close merge gate
    # and `verify_deferred`, which is documented as never raising and feeds the
    # PreToolUse:Bash hook. A hook that dies gates nothing, silently.
    if ae and ("command" in ae or "commands" in ae):
        for cmd in extract_commands(ae):
            paths |= _extract_paths_from_command(cmd)
    pins = (ae or {}).get("pins", []) or []
    pinned = {posixpath.normpath(p) for p in pins if isinstance(p, str)}
    if pinned:
        paths = {p for p in paths if posixpath.normpath(p) not in pinned}
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

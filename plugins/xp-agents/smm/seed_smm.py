#!/usr/bin/env python3
"""Seed a default shared_mental_model.json for new projects.

Scans the project for linter config, tests, git hooks, and CI setup.
Writes an initial SMM dict with XP-aligned Constraints and Risks
based on what's detected (or missing).

Only runs if shared_mental_model.json does not already exist.
"""

import hashlib
import subprocess
import sys
from pathlib import Path

from seed_detect import (
    has_ci,
    has_formatter,
    has_git_hooks,
    has_linter,
    has_tests,
)
from smm_schema import SOURCE_SEED, empty_smm
from smm_store import SMM_FILENAME, save_smm

_SEED_TS = "1970-01-01T00:00:00+00:00"


def _find_git_root() -> Path | None:
    """Find the git root directory."""
    try:
        root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        return Path(root)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


# ---------------------------------------------------------------------------
# SMM generation
# ---------------------------------------------------------------------------


def _seed_entry(pillar: str, content: str, **extra: str) -> dict:
    """Build a seed entry with a deterministic ID from content."""
    entry = {
        "id": hashlib.sha256(f"seed:{pillar}:{content}".encode()).hexdigest()[:12],
        "content": content,
        "source": SOURCE_SEED,
        "ts": _SEED_TS,
    }
    entry.update(extra)
    return entry


def generate_smm(root: Path) -> dict:
    """Generate seed SMM as a structured dict based on project analysis."""
    linter = has_linter(root)
    formatter = has_formatter(root)
    tests = has_tests(root)
    hooks = has_git_hooks(root)
    ci = has_ci(root)

    constraints = [
        _seed_entry(
            "constraints",
            "Write tests before implementation (TDD) — red, green, commit, refactor",
            type="convention",
        ),
        _seed_entry(
            "constraints",
            "Plan before building new features — use plan mode for design",
            type="convention",
        ),
        _seed_entry(
            "constraints",
            "Small commits — one logical change per commit",
            type="convention",
        ),
        _seed_entry(
            "constraints",
            "Small files — target 300 lines, max 500. "
            "Large files eat agent context on every read",
            type="convention",
        ),
        _seed_entry(
            "constraints",
            "Use strict linting — catch bugs and anti-patterns automatically",
            type="convention",
        ),
        _seed_entry(
            "constraints",
            "Use a code formatter — consistent style keeps diffs clean",
            type="convention",
        ),
        _seed_entry(
            "constraints",
            "Use git commit hooks — run lint and tests before every commit",
            type="convention",
        ),
        _seed_entry(
            "constraints",
            "Tests are production code — same review cycle, same quality bar. "
            "Never skip or abbreviate reviews for test-only changes",
            type="convention",
        ),
    ]

    risks: list[dict] = []
    if not linter:
        risks.append(
            _seed_entry(
                "risks",
                "No linter configured — add one to catch bugs automatically "
                "(e.g., ruff for Python, eslint for JS/TS, clippy for Rust, "
                "golangci-lint for Go)",
                type="concern",
                severity="problem",
            )
        )
    if not formatter:
        risks.append(
            _seed_entry(
                "risks",
                "No code formatter configured — add one for consistent style "
                "(e.g., ruff format for Python, prettier for JS/TS, gofmt "
                "for Go, rustfmt for Rust)",
                type="concern",
                severity="problem",
            )
        )
    if not tests:
        risks.append(
            _seed_entry(
                "risks",
                "No test files detected — create a test directory and write "
                "tests before implementation",
                type="concern",
                severity="problem",
            )
        )
    if not hooks:
        risks.append(
            _seed_entry(
                "risks",
                "No git commit hooks configured — add lefthook or husky to "
                "run lint and tests on every commit",
                type="concern",
                severity="problem",
            )
        )
    if not ci:
        risks.append(
            _seed_entry(
                "risks",
                "No CI/CD configured — add a workflow to run tests on push",
                type="concern",
                severity="problem",
            )
        )

    wisdom = [
        _seed_entry(
            "wisdom",
            "Run /xp-kickoff at every session start — "
            "it handles retrospective, goals, and housekeeping",
        ),
        _seed_entry(
            "wisdom",
            "Commit after every green test run — "
            "frequent commits keep /xp-quality-review small",
        ),
        _seed_entry(
            "wisdom",
            "Review cadence (commit | story), chosen at kickoff: in commit "
            "cadence run /xp-quality-review before each commit; in story "
            "cadence the per-commit gate defers and /xp-quality-review runs "
            "at /xp-story-close on the cumulative diff. /code-review "
            "(Workflow tool) runs once at free/sprint/plan close; LLM "
            "/security-review fires at close Step 4.",
        ),
        _seed_entry(
            "wisdom",
            "After exiting plan mode, run /xp-review-plan before writing "
            "code — it extracts assumptions, decisions, and risks into the SMM",
        ),
        _seed_entry(
            "wisdom",
            "Keep files small with single responsibility and DRY — "
            "one concern per file, extract when you see duplication "
            "or mixed responsibilities",
        ),
        _seed_entry(
            "wisdom",
            "Fail fast, fail loud — raise exceptions rather than "
            "returning None or empty results when something is wrong",
        ),
        _seed_entry(
            "wisdom",
            "Name things well — use descriptive names over comments. "
            "If you need a comment to explain what, rename instead",
        ),
        _seed_entry(
            "wisdom",
            "Test at boundaries — validate at system edges "
            "(external input, APIs, I/O), trust internal logic. "
            "Test behavior, not implementation",
        ),
        _seed_entry(
            "wisdom",
            "Checkable claims go in tests, where they rot loudly; comments "
            "carry only the why or constraint the code cannot express. "
            "History lives in git",
        ),
    ]

    smm = empty_smm()
    smm["constraints"] = constraints
    smm["risks"] = risks
    smm["wisdom"] = wisdom
    return smm


def main() -> None:
    """Seed SMM if it doesn't exist. Called by init.sh."""
    if len(sys.argv) < 2:
        print("Usage: seed_smm.py <smm_dir>", file=sys.stderr)
        sys.exit(1)

    smm_dir = Path(sys.argv[1])
    smm_file = smm_dir / SMM_FILENAME

    # Only seed if the JSON file doesn't exist.
    # A stale SHARED_MENTAL_MODEL.md may be present — leave it alone.
    if smm_file.exists():
        sys.exit(0)

    root = _find_git_root()
    if root is None:
        sys.exit(0)

    data = generate_smm(root)
    save_smm(smm_dir, data)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Shared subprocess + git fixture helpers for scaffold tests.

Extracted from test_scaffold_commit / test_scaffold_cli / test_scaffold_e2e
once a third copy made the duplication concrete (resolves debt
f61d0b067e11). Seed-file choice differs per test (README vs
package.json), so init_git_identity stops at git init + identity and
lets the caller stage whatever it needs.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """Run a git command in cwd with capture+text+10s timeout."""
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=10)


def init_git_identity(repo: Path) -> None:
    """git init -b main + set the test identity. Caller stages seed files."""
    run_git(["git", "init", "-b", "main"], repo)
    run_git(["git", "config", "user.email", "test@example.com"], repo)
    run_git(["git", "config", "user.name", "Test"], repo)


def init_git_with_seed(repo: Path, seed_path: str, seed_body: str) -> None:
    """init_git_identity + write+stage+commit a single seed file.

    Used by tests that need a non-empty HEAD (e.g. branch creation,
    revert-to-HEAD). seed_path is repo-relative.
    """
    init_git_identity(repo)
    (repo / seed_path).write_text(seed_body, encoding="utf-8")
    run_git(["git", "add", seed_path], repo)
    run_git(["git", "commit", "-m", "[chore] seed"], repo)


def valid_system_context(surfaces: list[dict] | None = None) -> dict:
    """Minimal schema-valid system_context.json doc with optional surfaces.

    Used by record / cli / e2e tests that need to seed an SMM dir before
    invoking apply-record (which goes through schema validation).
    """
    doc: dict = {
        "product": "Test product.",
        "architecture_overview": "Test architecture.",
        "stack": {"languages": ["Python"]},
        "modules": [{"name": "core", "purpose": "Core", "path": "src/core"}],
        "conventions": ["Use type hints"],
        "key_decisions": [{"topic": "lang", "decision": "Use Python"}],
        "sources": ["CLAUDE.md"],
        "project_specific": [],
    }
    if surfaces is not None:
        doc["acceptance_surfaces"] = surfaces
    return doc

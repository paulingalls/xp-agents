#!/usr/bin/env python3
"""Shared test fixtures for system_context tests.

Consolidates `valid_doc` and `write_doc` helpers that lived as
near-identical copies across system_context test files (7 in
tests/engine/, 1 in tests/scaffold/). The `**overrides` shape lets
callers inject any top-level field (branching_strategy,
acceptance_surfaces, etc.); no-arg calls produce a minimal valid doc.
"""

from __future__ import annotations

import json
from pathlib import Path

from system_context_schema import SYSTEM_CONTEXT_FILENAME


def valid_doc(**overrides: object) -> dict:
    """Return a minimal valid system context document with optional overrides."""
    doc = {
        "product": "A test product.",
        "architecture_overview": "Simple architecture.",
        "stack": {"languages": ["Python"]},
        "modules": [{"name": "core", "purpose": "Core logic", "path": "src/core"}],
        "conventions": ["Use type hints"],
        "key_decisions": [{"topic": "language", "decision": "Use Python"}],
        "sources": ["CLAUDE.md"],
        "project_specific": [],
    }
    doc.update(overrides)
    return doc


def write_doc(smm_dir: Path, doc: dict | None = None) -> None:
    """Write a valid system context doc to the SMM directory."""
    (smm_dir / SYSTEM_CONTEXT_FILENAME).write_text(json.dumps(doc or valid_doc()))

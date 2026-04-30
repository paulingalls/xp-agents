#!/usr/bin/env python3
"""Shared test fixtures for system_context tests.

Consolidates `valid_doc` and `write_doc` helpers that lived as 8
near-identical copies across the system_context test files. The
`**overrides` shape supports the test_system_context_branching.py
caller that needs to inject branching_strategy variants; no-arg
calls behave identically to the previous `_valid_doc()` form.
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

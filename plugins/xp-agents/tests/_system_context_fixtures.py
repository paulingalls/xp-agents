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
        "principles": [{"topic": "language", "decision": "Use Python"}],
        "project_specific": [],
    }
    doc.update(overrides)
    return doc


def write_doc(smm_dir: Path, doc: dict | None = None) -> None:
    """Write a valid system context doc to the SMM directory."""
    (smm_dir / SYSTEM_CONTEXT_FILENAME).write_text(json.dumps(doc or valid_doc()))


def seed_entries(field: str, n: int) -> list:
    """Build N schema-valid entries for a given list field."""
    if field == "modules":
        return [
            {"name": f"m{i}", "purpose": "x", "path": f"src/m{i}"} for i in range(n)
        ]
    if field == "conventions":
        return [f"c{i}" for i in range(n)]
    if field == "principles":
        return [{"topic": f"t{i}", "decision": "d"} for i in range(n)]
    if field == "project_specific":
        return [{"name": f"ps{i}", "content": "x"} for i in range(n)]
    if field == "acceptance_surfaces":
        return [
            {"name": f"s{i}", "signals": ["x"], "status": "covered"} for i in range(n)
        ]
    raise ValueError(f"unknown field: {field}")


def valid_test_layout(
    convention: str = "python_pytest",
    overrides: tuple[dict, ...] = (),
) -> dict:
    """Build a valid test_layout object. Single object, not a list.

    Default is python_pytest with no overrides. Pass a tuple of
    well-formed override dicts (3 required + up to 3 optional keys)
    when exercising the overrides path.
    """
    layout: dict[str, object] = {"convention": convention}
    if overrides:
        layout["overrides"] = list(overrides)
    return layout


def surfaces(*names: str) -> list[dict]:
    """Build covered acceptance_surfaces by name (signals stubbed)."""
    return [{"name": n, "signals": ["x"], "status": "covered"} for n in names]


def seed_doc(field: str, n: int) -> dict:
    """Return a valid_doc with `field` replaced by N seed entries."""
    doc = valid_doc()
    doc[field] = seed_entries(field, n)
    return doc


def read_events(smm_dir: Path) -> list[dict]:
    """Read events.jsonl as a list of dicts; empty list if missing."""
    events_path = smm_dir / "events.jsonl"
    if not events_path.exists():
        return []
    return [json.loads(line) for line in events_path.read_text().splitlines() if line]

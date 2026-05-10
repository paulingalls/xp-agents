#!/usr/bin/env python3
"""Branch-naming string helpers split out of branching.py.

Pure string operations: slug normalization, branch-name composition for
each lifecycle (story/sprint/plan/free/scaffold), and the
``is_sprint_branch`` predicate used by gate hooks. No git, no SMM I/O,
no subprocess — pulling these into their own module keeps branching.py
under its 500-line budget.

Re-exported from ``branching`` for back-compat; importers can use either
``from branching import branch_name`` or ``from branch_names import
branch_name``.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone


def _slugify(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def branch_name(user_ns: str, id_: str, slug: str) -> str:
    return f"{user_ns}/{id_}-{_slugify(slug)}"


def sprint_branch_name(user_ns: str, sprint_id: str, slug: str) -> str:
    return branch_name(user_ns, sprint_id, slug)


def plan_branch_name(user_ns: str, slug: str) -> str:
    return f"{user_ns}/plan-{_slugify(slug)}"


def _utc_today_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def free_branch_name(user_ns: str, slug: str) -> str:
    return f"{user_ns}/free-{_utc_today_iso()}-{_slugify(slug)}"


_SPRINT_BRANCH_RE = re.compile(r"^[^/]+/sprint-\d{3}-[a-z0-9-]+$")


def is_sprint_branch(name: str) -> bool:
    """True for branches matching ``<user>/sprint-NNN-<slug>``."""
    return bool(_SPRINT_BRANCH_RE.match(name))

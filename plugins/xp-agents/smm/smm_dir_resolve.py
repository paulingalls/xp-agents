#!/usr/bin/env python3
"""SMM directory resolution.

Moved out of ``_append_impl.py`` to keep that file under the line-count cap.
Re-exported from ``_append_impl`` BY IDENTITY (``from smm_dir_resolve import
now_iso, resolve_smm_dir, _derive_smm_dir``) so every existing
``from _append_impl import resolve_smm_dir`` / ``_append_impl.resolve_smm_dir``
reference — and every ``mock.patch`` site targeting it — resolves unchanged.
"""

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def now_iso() -> str:
    """Current UTC time as an ISO 8601 string.

    Canonical source for the ``datetime.now(timezone.utc).isoformat()``
    pattern. ``event_builder.build_event`` keeps its own inline call:
    ``_append_impl`` imports ``event_builder`` at module top level (see
    the ``from event_builder import ...`` block below), so adding a
    top-level ``from _append_impl import now_iso`` in ``event_builder``
    would close the cycle. When a caller imports ``event_builder``
    first (e.g. ``smm_store``, ``session_end``, ``duplicate_debt_probe``),
    Python would re-enter ``_append_impl`` mid-init and raise
    ``ImportError: cannot import name 'build_event' from partially
    initialized module``. All other call sites route through
    ``now_iso``, so a future timestamp policy change is a near-one-line
    edit.
    """
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# SMM path resolution
# ---------------------------------------------------------------------------


_INIT_SH = Path(__file__).parent / "init.sh"


MIGRATION_POINTER = ".migrated-to"


def _follow_migration_pointer(smm_dir: Path) -> Path:
    """One hop along a ``.migrated-to`` pointer, else the input unchanged.

    The Python half of init.sh's ``follow_migration_pointer``, and it has to
    exist: a pinned $SMM_DIR skips init.sh entirely, so without this the shell
    half of the plugin follows the relocation while every hook, append and
    marker write keeps addressing the abandoned tree for the rest of that
    process's life. The two halves must agree on one SMM.

    One hop only, matching the shell: a chain would mean two relocations raced,
    which the lock prevents, and following one blindly risks a cycle.
    """
    try:
        target = (smm_dir / MIGRATION_POINTER).read_text().strip()
    except OSError:
        return smm_dir
    if not target:
        return smm_dir
    candidate = Path(target)
    return candidate if candidate.is_dir() else smm_dir


def resolve_smm_dir() -> Path | None:
    """Return the SMM directory, or None if it can't be resolved.

    Honors $SMM_DIR env var as the single canonical handle — lets teammate
    spawners propagate the lead's SMM across process boundaries — but follows
    a relocation pointer left at that path, because the handle was pinned at
    spawn and the tree can have moved since. When unset, delegates to
    ``_derive_smm_dir`` which runs init.sh (which follows the pointer itself).

    The env-var read happens on every call (cheap), so test isolation that
    pins SMM_DIR per test takes effect immediately. ``_derive_smm_dir`` is
    not cached: caching across calls in a single process is unsafe when the
    derivation depends on cwd/env that tests may mutate, and in production
    each hook is a fresh `python3` invocation so a process-local cache
    never had a hit anyway.
    """
    env_smm = os.environ.get("SMM_DIR", "").strip()
    if env_smm:
        return _follow_migration_pointer(Path(env_smm))
    return _derive_smm_dir()


_PLUGIN_MANAGED_DIR_NAMES = ("xp-agents-xp-agents", "xp-agents-inline")


def plugin_managed_roots() -> list[Path]:
    """Data roots the plugin host owns, and therefore deletes on uninstall.

    Mirrors init.sh's legacy candidate list, in the same order and for the same
    reason: the host names the root when it can, and the two defaults cover a
    marketplace install and a dev-mode one, which resolve the plugin id
    differently. Kept as a list rather than one path because the host does not
    export the variable to every process.
    """
    roots: list[Path] = []
    env_root = os.environ.get("CLAUDE_PLUGIN_DATA", "").strip()
    if env_root:
        roots.append(Path(env_root))
    try:
        home = Path.home()
    except RuntimeError:
        return roots
    roots.extend(
        home / ".claude" / "plugins" / "data" / name
        for name in _PLUGIN_MANAGED_DIR_NAMES
    )
    return roots


def named_data_root() -> Path | None:
    """The data root the caller NAMED via ``XP_AGENTS_DATA``, if any.

    Same variable, same precedence as init.sh, where naming a root switches off
    legacy discovery and relocation entirely.
    """
    value = os.environ.get("XP_AGENTS_DATA", "").strip()
    return Path(value) if value else None


def _is_under(path: Path, root: Path | None) -> bool:
    """Containment by path components, tolerant of an unresolvable root."""
    if root is None:
        return False
    try:
        path.relative_to(root.resolve())
    except (ValueError, OSError):
        return False
    return True


def is_under_plugin_managed_root(smm_dir: Path) -> bool:
    """True when ``smm_dir`` still sits inside a host-managed data root.

    A POSITIVE test against the roots that carry the risk, deliberately not a
    negative test against the preferred root: a user who points the data-root
    override or the SMM handle somewhere of their own choosing is not one
    uninstall away from losing the project's memory, and must not be warned
    every session as though they were.

    Path containment, not string prefix — a sibling directory sharing a name
    prefix is not inside the root.

    An explicitly-set ``XP_AGENTS_DATA`` wins over the risk list for anything
    under it, mirroring init.sh: a named root is AUTHORITATIVE there — it skips
    both discovery and relocation — so warning about one would produce an
    advisory nothing can clear, naming a tool that resolves to the same path
    and reports that relocation did not happen. Only the named root is exempt;
    a handle pinned to some other managed root is still at risk.
    """
    try:
        resolved = smm_dir.resolve()
    except OSError:
        return False
    if _is_under(resolved, named_data_root()):
        return False
    return any(_is_under(resolved, root) for root in plugin_managed_roots())


def _derive_smm_dir() -> Path | None:
    """Run init.sh to derive SMM dir from project state."""
    try:
        out = subprocess.check_output(
            ["bash", str(_INIT_SH)],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return Path(out) if out else None

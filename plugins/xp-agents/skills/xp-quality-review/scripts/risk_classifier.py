#!/usr/bin/env python3
"""Project-agnostic risk classifier for /xp-quality-review (story-002).

Scores each changed file against generic CS risk signals — state-field
density, exit/decision blocks, lock/async primitives, lifecycle method
pairs, async complexity — and emits a repo-level RISK=high|low signal +
SIGNALS=<file>:<sig>+<sig> ... line that the SKILL routes to bounded
parallel fan-out (2-3 angle-focused reviewer spawns) on RISK=high.

Project-agnosticism: the plugin ships to many projects. Signals are
content-shape heuristics, NOT path patterns — the same logic must catch
state-machine code in any codebase. The xp-agents repo serves as a
convenient test fixture (see test_convenience_fixture_real_plugin_file_high),
not as the implementation vocabulary. See system_context principle
'plugin-project-agnostic' and SMM convention 2dac3b6c2098.

Scope (v1): .py files only. Other extensions return 0 signals and a
quiet skip — story-003 may extend to .sh if regression-replay shows need.
Binary/missing files are silently skipped (never crash the preload).
"""

import argparse
import re
from pathlib import Path

# A file with ANY signal is high-risk. Each signal is intentionally narrow
# enough that casual code does not trip it; the thresholds inside each
# signal (≥4 state writes, ≥3 awaits, etc.) prevent false positives from
# small/normal files. See test_pure_data_module_low for the negative case.
_FILE_HIGH_THRESHOLD = 1

# Matches `self.X = ...` and augmented assigns (`self.X += 1`, `//=`, `**=` ...).
# The trailing `(?!=)` rejects `self.X == Y` comparisons (false positive on
# statement-level boolean expressions); the optional augmented-op alternation
# captures mutations the bare `=` form would miss (false negative on counters
# / flags mutated via `+=`).
_SELF_ASSIGN_RE = re.compile(
    r"^\s*self\.[A-Za-z_][A-Za-z0-9_]*\s*(?:[+\-*/%&|^@]|//|\*\*|>>|<<)?=(?!=)",
    re.MULTILINE,
)
_EXIT_DECISION_RE = re.compile(
    r"\b(?:sys\.exit\s*\(|raise\s+SystemExit\b|os\._exit\s*\()"
)
_LOCK_PRIMITIVES_RE = re.compile(
    r"\b("
    r"threading\.(?:Lock|RLock|Semaphore|BoundedSemaphore|Event|Condition)"
    r"|asyncio\.(?:Lock|Semaphore|Event|Condition)"
    r"|multiprocessing\.(?:Lock|RLock|Semaphore|Event)"
    r"|fcntl\.flock"
    r"|filelock\.FileLock"
    r")\b"
)
_AWAIT_RE = re.compile(r"\bawait\s+")
_GATHER_WAIT_RE = re.compile(r"\basyncio\.(?:gather|wait)\s*\(")

_LIFECYCLE_PAIRS = [
    ("__enter__", "__exit__"),
    ("setUp", "tearDown"),
    ("setUpClass", "tearDownClass"),
    ("start", "stop"),
    ("open", "close"),
    ("connect", "disconnect"),
]


def _def_pattern(name: str) -> re.Pattern[str]:
    # `def NAME(` or `async def NAME(` — covers both sync and async.
    return re.compile(rf"^\s*(?:async\s+)?def\s+{re.escape(name)}\s*\(", re.MULTILINE)


def has_state_field_density(src: str) -> bool:
    """True when ≥4 `self.X = ...` assignments live in one file."""
    return len(_SELF_ASSIGN_RE.findall(src)) >= 4


def has_exit_decision(src: str) -> bool:
    """True when src calls `sys.exit`, `raise SystemExit`, or `os._exit`."""
    return _EXIT_DECISION_RE.search(src) is not None


def has_lock_primitives(src: str) -> bool:
    """True when src names a known sync/async/process lock or filelock."""
    return _LOCK_PRIMITIVES_RE.search(src) is not None


def has_lifecycle_methods(src: str) -> bool:
    """True when src defines BOTH halves of any recognized lifecycle pair."""
    for a, b in _LIFECYCLE_PAIRS:
        if _def_pattern(a).search(src) and _def_pattern(b).search(src):
            return True
    return False


def has_async_complexity(src: str) -> bool:
    """True when ≥3 `await` calls OR an `asyncio.gather/wait` usage appears."""
    if _GATHER_WAIT_RE.search(src):
        return True
    return len(_AWAIT_RE.findall(src)) >= 3


_SIGNAL_CHECKS: list[tuple[str, callable]] = [  # type: ignore[type-arg]
    ("state-field-density", has_state_field_density),
    ("exit-decision", has_exit_decision),
    ("lock-primitives", has_lock_primitives),
    ("lifecycle-methods", has_lifecycle_methods),
    ("async-complexity", has_async_complexity),
]


def _read_source(path: Path) -> str | None:
    """Read a .py file's text, or None if unreadable / wrong extension."""
    if path.suffix != ".py":
        return None
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeError):
        return None


def classify(file_paths: list[str], repo_root: Path = Path(".")) -> dict:
    """Classify a set of file paths by content-shape risk signals.

    Returns:
        {
          'risk': 'high' | 'low',
          'signals': [{'file': '<relpath>', 'matched': ['<sig>', ...]}, ...]
        }

    Only files that match ≥1 signal appear in 'signals'. 'risk' is 'high'
    when at least one file's matched-signal count meets the per-file
    threshold; else 'low'. Files outside scope (non-.py, missing, binary)
    contribute zero signals — never block, never crash.
    """
    signals: list[dict] = []
    for raw in file_paths:
        path = (repo_root / raw) if not Path(raw).is_absolute() else Path(raw)
        src = _read_source(path)
        if src is None:
            continue
        matched = [name for name, check in _SIGNAL_CHECKS if check(src)]
        if matched:
            signals.append({"file": raw, "matched": matched})

    is_high = any(len(s["matched"]) >= _FILE_HIGH_THRESHOLD for s in signals)
    return {"risk": "high" if is_high else "low", "signals": signals}


def _format_signals_line(signals: list[dict]) -> str:
    """Render SIGNALS= line as space-separated `<file>:<sig>+<sig>` tokens."""
    parts = [f"{s['file']}:{'+'.join(s['matched'])}" for s in signals]
    return "SIGNALS=" + " ".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description="Project-agnostic risk classifier")
    parser.add_argument("files", nargs="*", help="Changed file paths (relative to cwd)")
    args = parser.parse_args()

    result = classify(args.files, repo_root=Path("."))
    print(f"RISK={result['risk']}")
    print(_format_signals_line(result["signals"]))


if __name__ == "__main__":
    main()

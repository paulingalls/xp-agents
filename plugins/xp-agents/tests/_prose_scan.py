#!/usr/bin/env python3
"""Prose measurement scan over the shipped roots (`scripts`, `smm`, `skills`).

A report a human runs ad hoc, not a test a runner discovers: it builds no
ceiling and asserts nothing. The ratchet is a later milestone's deliverable,
scheduled after the sweep so its ceilings are post-sweep numbers.

LIMITS -- READ THIS BEFORE TRUSTING A NUMBER FROM THIS SCAN. It counts LINES,
not information: a comment that says nothing (`# fix`) counts the same as one
that explains a real invariant, and nothing here judges whether a comment is
TRUE, current, or worth keeping. Staleness detection is deliberately out of
scope -- a scan that claimed to catch stale comments without reading them for
meaning would be a green check certifying something untrue, the exact failure
this milestone exists to kill.
"""

import argparse
import ast
import sys
import tokenize
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

from _pin_helpers import parse_files, rel, shipped_files_by_root

_DOCSTRING_NODE_TYPES = (
    ast.Module,
    ast.ClassDef,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
)
_LONG_DOCSTRING_THRESHOLD = 25


@dataclass(frozen=True)
class FileProse:
    """One file's prose counts. Each `long_docstring_locations` entry is
    `(lineno, line_count)`."""

    path: Path
    total_lines: int
    docstring_lines: int
    comment_lines: int
    max_docstring_lines: int
    long_docstrings: int
    long_docstring_locations: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class RootProse:
    """One shipped root's counts, rolled up over `files`."""

    root: str
    files: tuple[FileProse, ...]
    total_lines: int
    docstring_lines: int
    comment_lines: int
    max_docstring_lines: int
    long_docstrings: int
    parse_failures: tuple[tuple[Path, str], ...] = ()


def _docstring_entries(tree: ast.AST) -> list[tuple[int, int]]:
    """`(lineno, line_count)` for every docstring node in *tree*.

    Counted as PHYSICAL source lines, quotes included, rather than
    `len(doc.splitlines())`: the ratio's denominator is physical lines, so a
    content-line numerator would mix units and drop the closing-quote line of
    every docstring that has one.
    """
    entries: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, _DOCSTRING_NODE_TYPES):
            continue
        if ast.get_docstring(node, clean=False) is None:
            continue
        doc_node = node.body[0]
        end_lineno = doc_node.end_lineno or doc_node.lineno
        entries.append((doc_node.lineno, end_lineno - doc_node.lineno + 1))
    return entries


def _count_comments(text: str) -> int:
    """Comment lines in *text*, via `tokenize.COMMENT` -- never a raw
    `line.startswith("#")` scan, which would miscount a `#` inside a string
    literal."""
    count = 0
    for tok in tokenize.generate_tokens(StringIO(text).readline):
        if tok.type != tokenize.COMMENT:
            continue
        if tok.start[0] == 1 and tok.string.startswith("#!"):
            continue
        count += 1
    return count


def scan_file(path: Path) -> FileProse:
    """Scan one already-known-parseable file. Raises `SyntaxError` if it is
    not -- callers that must survive a parse failure go through `scan_roots`,
    which uses `_pin_helpers.parse_files` to filter to parseable paths first."""
    text = path.read_text(encoding="utf-8")
    entries = _docstring_entries(ast.parse(text))
    long_entries = tuple(
        (lineno, n) for lineno, n in entries if n >= _LONG_DOCSTRING_THRESHOLD
    )
    return FileProse(
        path=path,
        total_lines=len(text.splitlines()),
        docstring_lines=sum(n for _, n in entries),
        comment_lines=_count_comments(text),
        max_docstring_lines=max((n for _, n in entries), default=0),
        long_docstrings=len(long_entries),
        long_docstring_locations=long_entries,
    )


def _roll_up(root: str, paths: list[Path]) -> RootProse:
    _trees, failures = parse_files(paths)
    failed = {path for path, _err in failures}
    files = tuple(scan_file(p) for p in paths if p not in failed)
    return RootProse(
        root=root,
        files=files,
        total_lines=sum(f.total_lines for f in files),
        docstring_lines=sum(f.docstring_lines for f in files),
        comment_lines=sum(f.comment_lines for f in files),
        max_docstring_lines=max((f.max_docstring_lines for f in files), default=0),
        long_docstrings=sum(f.long_docstrings for f in files),
        parse_failures=tuple(failures),
    )


def scan_roots(plugin_root: Path) -> dict[str, RootProse]:
    """Prose counts for every shipped root under *plugin_root*, keyed
    `"scripts"` / `"smm"` / `"skills"` -- the same vocabulary as
    `shipped_files_by_root`, the `--root` flag, and the printed report line."""
    groups = shipped_files_by_root(plugin_root)
    return {name: _roll_up(name, paths) for name, paths in groups.items()}


def _ratio(prose: int, total: int) -> float:
    return (prose / total * 100) if total else 0.0


def _render(path: Path, base: Path | None) -> str:
    """*path* rendered repo-relative against *base*, absolute when it has no
    base or falls outside one. Absolute paths embed the worktree they were
    scanned in, so a before/after diff taken in two worktrees would be noise."""
    if base is None:
        return str(path)
    try:
        return rel(path, base)
    except ValueError:
        return str(path)


def format_report(
    roots: dict[str, RootProse], per_file: bool = False, base: Path | None = None
) -> str:
    """Render *roots* as the frozen `root=...` line per root, optional
    per-file detail, then the Bucket C/D triage list of long docstrings.

    The `root=` line's shape is an interface contract with stories
    002/003/004, which grep it for their before/after numbers -- do not
    reorder or rename its fields.
    """
    lines: list[str] = []
    long_docstring_lines: list[str] = []
    for name, root in roots.items():
        prose = root.docstring_lines + root.comment_lines
        lines.append(
            f"root={name} files={len(root.files)} lines={root.total_lines} "
            f"prose={prose} ratio={_ratio(prose, root.total_lines):.1f}% "
            f"max_docstring={root.max_docstring_lines} "
            f"long_docstrings={root.long_docstrings}"
        )
        for failure_path, message in root.parse_failures:
            lines.append(
                f"root={name} PARSE FAILURE: {_render(failure_path, base)} ({message})"
            )
        if per_file:
            for f in root.files:
                f_prose = f.docstring_lines + f.comment_lines
                lines.append(
                    f"  {_render(f.path, base)} lines={f.total_lines} "
                    f"prose={f_prose} "
                    f"ratio={_ratio(f_prose, f.total_lines):.1f}%"
                )
        for f in root.files:
            for lineno, n in f.long_docstring_locations:
                long_docstring_lines.append(
                    f"{_render(f.path, base)}:{lineno} docstring {n} lines"
                )
    if long_docstring_lines:
        lines.append("")
        lines.append("Docstrings >= 25 lines:")
        lines.extend(long_docstring_lines)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prose measurement scan")
    parser.add_argument(
        "--root",
        choices=("scripts", "smm", "skills", "all"),
        default="all",
        help="Shipped root to report on (default: all)",
    )
    parser.add_argument(
        "--per-file",
        action="store_true",
        help="Also print each file's own prose ratio",
    )
    args = parser.parse_args(argv)

    plugin_root = Path(__file__).resolve().parent.parent
    roots = scan_roots(plugin_root)
    if args.root != "all":
        roots = {args.root: roots[args.root]}
    print(format_report(roots, per_file=args.per_file, base=plugin_root.parent.parent))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Prose measurement scan over the shipped roots (`scripts`, `smm`, `skills`).

Nothing measures prose today. Every ratio quoted in the sprint so far came
from a throwaway script, and three recorded baselines disagree with each
other. This module is the one tool: it counts docstring lines (via `ast`) and
comment lines (via `tokenize`) per file, rolls them up per shipped root, and
prints a report the delete-only sweep stories (Bucket A/B) grep for a
before/after number. It builds no ceiling and asserts nothing -- the ratchet
is a later milestone's deliverable, scheduled after the sweep so its ceilings
are the post-sweep numbers rather than today's.

LIMITS -- READ THIS BEFORE TRUSTING A NUMBER FROM THIS SCAN.

It counts LINES, not information. A docstring with ten blank lines counts as
ten lines of prose; a comment that says nothing (`# fix`) counts the same as
one that explains a real invariant. Nothing here judges whether a comment is
TRUE, current, or worth keeping -- staleness detection is out of scope, and
that omission is deliberate: a scan that claimed to catch stale comments
without actually reading them for meaning would be a green check certifying
something untrue, which is the exact failure this milestone exists to kill.

A comment is counted by `tokenize.COMMENT` token, one per physical line --
a multi-line comment block is N separate comments, not one prose unit. The
first-line shebang (`#!...`) is excluded by convention (every shipped module
has one; counting it as prose would inflate every file by a constant that
carries no information), but every other `#!` mid-file, if one ever appeared,
would count.

Docstrings are read via `ast.get_docstring(node, clean=False)` on `Module`,
`ClassDef`, `FunctionDef` and `AsyncFunctionDef` nodes -- the four shapes a
docstring can attach to. A raw triple-quoted string elsewhere in a function
body (not the first statement) is an ordinary expression, not a docstring,
and is invisible to this scan, exactly as it is invisible to `ast.get_docstring`.

This is the first argparse entry point under `tests/` -- every other
`__main__` block there is `unittest.main()`. That is deliberate here: this is
a reporting scan a human runs ad hoc (`--root scripts`, `--per-file`), not a
test a runner discovers.
"""

import argparse
import ast
import sys
import tokenize
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

from _pin_helpers import parse_files, shipped_files_by_root

_DOCSTRING_NODE_TYPES = (
    ast.Module,
    ast.ClassDef,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
)
_LONG_DOCSTRING_THRESHOLD = 25


@dataclass(frozen=True)
class FileProse:
    """One file's prose counts. `long_docstring_locations` is `(lineno,
    length)` for every docstring at or above `_LONG_DOCSTRING_THRESHOLD` --
    the Bucket C/D triage list the design doc asks for starts here."""

    path: Path
    total_lines: int
    docstring_lines: int
    comment_lines: int
    max_docstring_lines: int
    long_docstrings: int
    long_docstring_locations: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class RootProse:
    """One shipped root's rolled-up counts. `max_docstring_lines` is the max
    across `files`, not a sum -- everything else here is a sum (or, for
    `long_docstrings`, a count) over `files`."""

    root: str
    files: tuple[FileProse, ...]
    total_lines: int
    docstring_lines: int
    comment_lines: int
    max_docstring_lines: int
    long_docstrings: int
    parse_failures: tuple[tuple[Path, str], ...] = ()


def _docstring_entries(tree: ast.AST) -> list[tuple[int, int]]:
    """`(lineno, line_count)` for every docstring node in *tree*."""
    entries: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, _DOCSTRING_NODE_TYPES):
            continue
        doc = ast.get_docstring(node, clean=False)
        if doc is None:
            continue
        body = getattr(node, "body", None)
        lineno = body[0].lineno if body else getattr(node, "lineno", 1)
        entries.append((lineno, len(doc.splitlines())))
    return entries


def _count_comments(text: str) -> int:
    """Comment lines in *text*, via `tokenize.COMMENT` -- never a raw
    `line.startswith("#")` scan, which would miscount a `#` inside a string
    literal and would see comments `ast` never does. The first-line shebang
    is excluded; every other comment counts."""
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


def format_report(roots: dict[str, RootProse], per_file: bool = False) -> str:
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
            lines.append(f"root={name} PARSE FAILURE: {failure_path} ({message})")
        if per_file:
            for f in root.files:
                f_prose = f.docstring_lines + f.comment_lines
                lines.append(
                    f"  {f.path} lines={f.total_lines} prose={f_prose} "
                    f"ratio={_ratio(f_prose, f.total_lines):.1f}%"
                )
        for f in root.files:
            for lineno, n in f.long_docstring_locations:
                long_docstring_lines.append(f"{f.path}:{lineno} docstring {n} lines")
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
    print(format_report(roots, per_file=args.per_file))
    return 0


if __name__ == "__main__":
    sys.exit(main())

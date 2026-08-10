#!/usr/bin/env python3
"""Find test-file pointers in shipped prose. Matchers and finders only.

No assertions and no verdicts — those belong to the pin, per the detection-seam
convention. Text is an argument rather than a path, so the same finders serve a
real file and a synthetic string.

WHY FILE-SHAPED, NOT IDENTIFIER-SHAPED. A pointer is recognised by a token
ending in `.py`, never by a bare `test_x` / `TestX` identifier. Shipped code
carries both shapes for things that are not test files at all: event and schema
FIELD names (`test_passed`, `test_count`, `test_command`) and domain TYPES
(`TestLayout`, `TestLayoutRule` in `sister_layout.py` are sister-test config
dataclasses). Matching those would report every one as a dead pointer. Reaching
for a preceding phrase — "pinned by", "see" — to disambiguate is what
over-matched once already, so the shape does the work instead.
"""

import ast
import io
import re
import tokenize
from pathlib import Path

_DOCSTRING_NODES = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)

# A path-shaped token ending in `.py`. The trailing `\b` is what strips the
# punctuation real pointers carry: `test_x.py.`, `test_x.py's`,
# `test_x.py::TestClass` and `test_x.py:_SYMBOL` all yield `test_x.py`, while
# `foo.pyc` and `foo.pyi` do not match at all (a word character follows `py`).
_TOKEN_RE = re.compile(r"[\w./*?\[\]-]*\.py\b")

_GLOB_CHARS = "*?["


def is_glob(token: str) -> bool:
    """True for a pattern rather than a path.

    Excluded structurally rather than allowlisted one at a time: a token like
    `tests/**/*.py` names no file by construction, so listing each one would be
    recording the same fact repeatedly.
    """
    return any(ch in token for ch in _GLOB_CHARS)


def is_test_shaped(token: str) -> bool:
    """True when the token names a test module: `test_`-prefixed, or under `tests/`.

    Deliberately narrow. A shipped module named in prose (`cli.py`, `src/app.py`,
    `render_history.py`) is not this rule's business, and treating every `.py`
    token as a pointer would leave ~30 unresolvable names that were never
    pointers to begin with.
    """
    parts = token.split("/")
    return parts[-1].startswith("test_") or "tests" in parts[:-1]


def python_prose(source: str) -> list[tuple[int, str]]:
    """`(lineno, text)` for every docstring and comment in *source*.

    Comments come from `tokenize`, never a `line.startswith("#")` scan, which
    would read a `#` inside a string literal as a comment. Docstrings come from
    the AST, so a string that merely sits in an expression is not mistaken for
    one.
    """
    segments: list[tuple[int, str]] = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, _DOCSTRING_NODES):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                segments.append((getattr(node, "lineno", 1), doc))
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.COMMENT:
            segments.append((tok.start[0], tok.string))
    return segments


def shell_prose(source: str) -> list[tuple[int, str]]:
    """`(lineno, text)` for whole-line comments in a shell script.

    Only whole-line comments. A trailing `# ...` on a command line would need a
    quoting-aware parse to separate from a `#` inside a string, and every
    pointer this rule has seen in shell sits on its own line.
    """
    return [
        (n, line)
        for n, line in enumerate(source.splitlines(), start=1)
        if line.lstrip().startswith("#")
    ]


def markdown_prose(source: str) -> list[tuple[int, str]]:
    """`(lineno, text)` for every line of a Markdown file.

    A `.md` surface is prose end to end, so there is nothing to separate out —
    including fenced blocks, where a command naming a test file that no longer
    exists rots exactly like a sentence naming it.
    """
    return list(enumerate(source.splitlines(), start=1))


def find_test_pointers(
    segments: list[tuple[int, str]], surface: str
) -> list[tuple[str, int, str]]:
    """`(surface, lineno, token)` for each test-shaped, non-glob `.py` token."""
    hits: list[tuple[str, int, str]] = []
    for lineno, text in segments:
        for token in _TOKEN_RE.findall(text):
            if is_test_shaped(token) and not is_glob(token):
                hits.append((surface, lineno, token))
    return hits


def index_python_files(repo_root: Path) -> set[str]:
    """Every `.py` path in the repo, repo-relative, for pointer resolution.

    DOT-PREFIXED directories are skipped, not just `.git`. Resolution is by
    suffix, so anything indexed can answer a pointer: a local `.venv` or
    `.tox` full of third-party test modules would resolve a name that is
    genuinely dead here, and would resolve the generic placeholders
    (`test_foo.py`) the pin asserts stay unresolvable. Excluding by shape
    keeps the index to files the repo actually owns.
    """
    return {
        str(rel).replace("\\", "/")
        for rel in (p.relative_to(repo_root) for p in repo_root.rglob("*.py"))
        if not any(part.startswith(".") for part in rel.parts)
    }


def resolves(token: str, known: set[str]) -> bool:
    """True when some indexed path IS the token or ends with it.

    Suffix matching, not a `tests/`-rooted lookup: `scripts/test_attribution.py`
    and `scripts/test_parsing.py` are SHIPPED scripts that happen to be named
    `test_*`, and prose refers to them by bare stem. A resolver that only looked
    under `tests/` would report those dead.
    """
    return token in known or any(p.endswith("/" + token) for p in known)

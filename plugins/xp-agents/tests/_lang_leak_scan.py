#!/usr/bin/env python3
"""The AST walker behind `test_no_language_leak.py` — finds file-extension
predicates in shipped code and reads their `# lang-ok:` justification.

Lives beside `_pin_helpers` (which owns file discovery) rather than inside the
pin, because the pin plus its walker plus the walker's own tests exceed the
500-line file cap. Read the pin's module docstring first: it states what this
scan covers, what it deliberately does NOT cover, and why it is an AST walk
rather than a grep.

The rule, in one line: every file-extension predicate in shipped code must
carry a `# lang-ok: <reason>` marker naming why it is language-agnostic —
unless its operand derives from the plugin's own `__file__`.
"""

import ast
import re
from collections.abc import Iterator
from pathlib import Path

MARKER = "lang-ok:"

# A string literal that ends in a file extension: ".py", "_test.go",
# "Tests.swift". Requiring the dot is what keeps `path.endswith("/")` and
# `key.endswith("_ids")` out of the results.
_EXTENSION_TAIL = re.compile(r"\.[A-Za-z0-9]{1,10}$")

# One predicate: (lineno, kind, reason). `reason is None` means unmarked;
# an empty string means the marker is there but says nothing.
Site = tuple[int, str, str | None]

SUFFIX_COMPARE = "suffix-compare"
SUFFIX_MATCH = "suffix-match"
ENDSWITH_EXTENSION = "endswith-extension"


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def _is_extension_literal(node: ast.expr) -> bool:
    """True for a literal ending in a file extension: ".py", "_test.go".

    Ending in an extension — rather than merely being one — is what catches
    `name.endswith("_test.py")`, a Python-only test detector, and not just the
    bare `.py` form.

    Requiring the dot is the guard against false positives. Shipped code is full
    of suffix tests that have nothing to do with language — `path.endswith("/")`
    for a directory, `key.endswith("_ids")` for a JSON field — and forcing
    markers onto those is how a guardrail becomes noise and then gets deleted.
    """
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "/" not in node.value
        and _EXTENSION_TAIL.search(node.value) is not None
    )


def _has_extension_arg(call: ast.Call) -> bool:
    """True if any argument is an extension literal, or a tuple/list holding
    one (`endswith((".ts", ".tsx"))`)."""
    for arg in call.args:
        if _is_extension_literal(arg):
            return True
        if isinstance(arg, ast.Tuple | ast.List) and any(
            _is_extension_literal(e) for e in arg.elts
        ):
            return True
    return False


def _is_suffix_expr(node: ast.expr) -> bool:
    """True for an expression that yields a path's extension.

    Matches `<anything>.suffix`, through a `.lower()`/`.upper()` normalizer,
    through the conditional form (`Path(p).suffix if p else None`), and through
    a walrus (`(ext := Path(p).suffix) == ".py"`). The base is deliberately
    unconstrained: `path.suffix != ".py"` on a bare parameter is the canonical
    leak CLAUDE.md names, and requiring a literal `Path(...)` call would let
    exactly that shape through.
    """
    match node:
        case ast.Attribute(attr="suffix"):
            return True
        case ast.Call(func=ast.Attribute(attr="lower" | "upper", value=inner)):
            return _is_suffix_expr(inner)
        case ast.IfExp(body=body, orelse=orelse):
            return _is_suffix_expr(body) or _is_suffix_expr(orelse)
        case ast.NamedExpr(value=inner):
            return _is_suffix_expr(inner)
        case _:
            return False


def _match_has_extension_case(node: ast.Match) -> bool:
    """True if any `case` arm of *node* matches a file-extension literal.

    `match Path(p).suffix: case ".py":` routes on an extension exactly as
    `==` does, and this project's coding standard mandates match/case for
    routing — so it is the shape a future author here is most likely to reach
    for. Walking each pattern catches the alternation form, `case ".ts" | ".tsx":`.
    """
    return any(
        isinstance(pattern, ast.MatchValue) and _is_extension_literal(pattern.value)
        for case in node.cases
        for pattern in ast.walk(case.pattern)
    )


def _is_none_check(node: ast.Compare) -> bool:
    """True for `suffix is None` / `suffix is not None`.

    A suffix can be absent, and guarding for that says nothing about any
    language. Demanding a marker on a None-guard is the kind of noise that
    trains authors to paste the marker without reading it.
    """
    return all(isinstance(op, ast.Is | ast.IsNot) for op in node.ops) and all(
        isinstance(c, ast.Constant) and c.value is None for c in node.comparators
    )


def _subject_of(node: ast.expr) -> ast.expr:
    """The path an expression is ultimately *about*, by walking its spine.

    `Path(__file__).parent.suffix` -> `__file__`, but
    `Path(user).relative_to(here).suffix` -> `user`, because the receiver of a
    method call — not its argument — is what the call is about.

    Walking the spine rather than the whole subtree is what stops the own-source
    exemption from being *borrowed*. A user's path measured against the plugin's
    own root still reasons about the USER's file; the `__file__` in there is
    incidental, and exempting on its mere presence would hand a real leak a
    silent pass. That is the failure mode this whole pin exists to kill, so the
    exemption has to be the narrow one.
    """
    while True:
        match node:
            case ast.Attribute(value=inner) | ast.Subscript(value=inner):
                node = inner
            case ast.Call(func=ast.Attribute(value=inner)):
                node = inner  # method call: the receiver carries the subject
            case ast.Call(func=ast.Name(), args=[inner, *_]):
                node = inner  # Path(x) / str(x): the subject is the argument
            case ast.BinOp(left=inner):
                node = inner  # `Path(__file__).parent / name` — a path join
            case ast.NamedExpr(value=inner) | ast.IfExp(body=inner):
                node = inner
            case _:
                return node


def _is_own_source(node: ast.expr, own_names: set[str]) -> bool:
    """True if the expression's subject is the plugin's OWN module path.

    `Path(__file__).suffix == ".py"` reasons about the plugin's own source — a
    file that is Python unconditionally — not about a user's file. Not a leak,
    and it needs no marker.
    """
    subject = _subject_of(node)
    return isinstance(subject, ast.Name) and (
        subject.id == "__file__" or subject.id in own_names
    )


def _walk_own(node: ast.AST) -> Iterator[ast.AST]:
    yield node
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        return
    for child in ast.iter_child_nodes(node):
        yield from _walk_own(child)


def _walk_scope(scope: ast.AST) -> Iterator[ast.AST]:
    """Yield every node in *scope*, without descending into nested functions.

    Scope isolation is load-bearing for the `__file__` exemption, not tidiness:
    a function that does `p = Path(__file__)` then `p.suffix == ".py"` is only
    recognisable as own-source while `p`'s binding is in view. Walking the same
    statement again from module scope — where `p` is unknown — would re-flag it.
    """
    for child in ast.iter_child_nodes(scope):
        yield from _walk_own(child)


def _scopes(tree: ast.Module) -> Iterator[ast.AST]:
    yield tree
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            yield node


def _bindings(scope: ast.AST) -> tuple[set[str], dict[str, bool]]:
    """One-hop local name resolution within a single scope.

    Returns (own_names, suffix_names): names bound to the plugin's own source,
    and names bound to a suffix expression, each mapped to whether that suffix
    came from own source.

    The hop is required, not a nicety. `suffix = Path(path).suffix.lower()` then
    `if suffix in _NON_CODE_SUFFIXES:`, and `file_suffix = Path(fp).suffix` then
    `if file_suffix not in allowed:`, are the SAME predicate one statement apart.
    A rule that fires on the inline form but not the hoisted one could be
    silenced by hoisting the suffix into a local.
    """
    own: set[str] = set()
    suffix: dict[str, bool] = {}

    for node in _walk_scope(scope):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if _is_suffix_expr(node.value):
            suffix[target.id] = _is_own_source(node.value, own)
        elif _is_own_source(node.value, own):
            own.add(target.id)

    return own, suffix


def _predicates(tree: ast.Module) -> list[tuple[int, int, str]]:
    """Return (lineno, end_lineno, kind) for every extension predicate.

    The span ends where the *predicate* ends, not where its enclosing block
    does — a `match` statement's body can run for pages, and letting the span
    swallow it would let any `lang-ok:` marker buried inside one arm silence the
    routing decision in the header.
    """
    found: dict[tuple[int, str], tuple[int, int, str]] = {}

    for scope in _scopes(tree):
        own, suffix = _bindings(scope)

        for node in _walk_scope(scope):
            kind: str | None = None
            span: tuple[int, int] | None = None

            match node:
                case ast.Compare(left=left) if _is_suffix_expr(left):
                    if not _is_none_check(node) and not _is_own_source(left, own):
                        kind = SUFFIX_COMPARE
                case ast.Compare(left=ast.Name(id=name)) if name in suffix:
                    if not _is_none_check(node) and not suffix[name]:
                        kind = SUFFIX_COMPARE
                case ast.Call(func=ast.Attribute(attr="endswith", value=base)) as call:
                    if _has_extension_arg(call) and not _is_own_source(base, own):
                        kind = ENDSWITH_EXTENSION
                case ast.Match(subject=subject) if _match_has_extension_case(node):
                    inline = _is_suffix_expr(subject) and not _is_own_source(
                        subject, own
                    )
                    hoisted = (
                        isinstance(subject, ast.Name)
                        and subject.id in suffix
                        and not suffix[subject.id]
                    )
                    if inline or hoisted:
                        kind = SUFFIX_MATCH
                        span = (node.lineno, subject.end_lineno or node.lineno)
                case _:
                    pass

            if kind is not None:
                assert isinstance(node, ast.Compare | ast.Call | ast.Match)
                start, end = span or (node.lineno, node.end_lineno or node.lineno)
                found[(start, kind)] = (start, end, kind)

    return sorted(found.values())


# ---------------------------------------------------------------------------
# Marker lookup — the AST discards comments, so this reads raw source lines
# ---------------------------------------------------------------------------


def _reason_in(text: str) -> str | None:
    """The justification on the marker's line, or None if the marker is absent.

    Only the marker's own line counts, so a docstring that says `lang-ok:` and
    then continues with unrelated prose cannot borrow the next paragraph as its
    reason.
    """
    if MARKER not in text:
        return None
    return text.split(MARKER, 1)[1].split("\n", 1)[0].strip()


def _function_markers(tree: ast.Module, lines: list[str]) -> list[tuple[int, int, str]]:
    """Return (start, end, marker_text) for every function carrying a
    scope-level marker on its `def` line or in its docstring.

    Function-scope granularity is required, not a convenience: `is_test_file` is
    one dispatch built from a dozen separate per-ecosystem predicates. A strict
    per-line rule would demand a dozen copies of a single justification inside
    one function, and repetition is how a marker decays into decoration.
    """
    out: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        def_line = lines[node.lineno - 1] if node.lineno <= len(lines) else ""
        doc = ast.get_docstring(node) or ""
        text = def_line if MARKER in def_line else doc
        if MARKER in text:
            out.append((node.lineno, node.end_lineno or node.lineno, text))
    return out


def _comment_block_above(start: int, lines: list[str]) -> Iterator[str]:
    """Yield the contiguous comment lines immediately above line *start*.

    A justification worth reading rarely fits on one line, and the marker opens
    the block rather than closing it — so checking only the line directly above
    the statement would miss every multi-line reason.
    """
    lineno = start - 1
    while lineno >= 1 and lines[lineno - 1].lstrip().startswith("#"):
        yield lines[lineno - 1]
        lineno -= 1


def _find_reason(
    start: int,
    end: int,
    lines: list[str],
    func_markers: list[tuple[int, int, str]],
) -> str | None:
    """Reason for the predicate spanning *start*..*end*, or None if unmarked.

    Looks in the comment block above the statement, then within the statement's
    own line span (a set literal or a formatter-wrapped call runs over several
    lines, and a trailing marker sits on only one of them), then falls back to
    the innermost enclosing marked function.
    """
    for text in _comment_block_above(start, lines):
        reason = _reason_in(text)
        if reason is not None:
            return reason

    for lineno in range(start, min(end, len(lines)) + 1):
        reason = _reason_in(lines[lineno - 1])
        if reason is not None:
            return reason

    enclosing = [m for m in func_markers if m[0] <= start <= m[1]]
    if enclosing:
        return _reason_in(max(enclosing, key=lambda m: m[0])[2])
    return None


def scan_file(path: Path) -> list[Site]:
    """Return every extension predicate in *path* with its marker status.

    Sites are returned whether marked or not: the pin reads the marker (unmarked
    -> fail, empty reason -> fail) and the vacuity guard counts them. A syntax
    error yields [] — a different bug class, caught elsewhere.
    """
    src = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []

    lines = src.splitlines()
    func_markers = _function_markers(tree, lines)

    return [
        (start, kind, _find_reason(start, end, lines, func_markers))
        for start, end, kind in _predicates(tree)
    ]

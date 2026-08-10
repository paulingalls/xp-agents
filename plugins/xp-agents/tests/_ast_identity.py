#!/usr/bin/env python3
"""Prove a prose edit changed only prose.

A pass that rewrites comments and docstrings across a subsystem cannot be
checked by reading the diff -- the whole point is that the diff is large and
almost entirely text. This compares each file's code shape before and after:
parse both, drop every docstring, and dump the trees. Equal shapes mean no
expression, branch, constant or signature moved.

WHAT THIS DOES NOT COVER. Comments are not in the AST at all, so this gives
zero protection to machine-checked markers (`# noqa`, `# type: ignore`,
`lang-ok:`, `# isort:`, `# fmt:`) -- deleting one is invisible here, and no
census pins them.

It is equally blind to a docstring consumed at runtime, because it strips
docstrings from both trees before comparing. THREE shipped modules pass
`__doc__` to argparse: `close_gate_commands.py` and `review_flag_cli.py` pass
the whole thing, and `worktree_differential.py` passes only its first line.
That blindness is no longer uncovered: `hooks/test_runtime_docstring_consumers.py`
pins all three against being emptied, deliberately without pinning their
wording, since narrowing a claim to what is true is the fix this repo asks for.

`include_attributes` stays False. At True the dump carries line numbers, so
every deletion would report as a change in each node below it.
"""

import ast

_DOCSTRING_OWNERS = (
    ast.Module,
    ast.ClassDef,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
)


def _strip_docstrings(tree: ast.AST) -> ast.AST:
    for node in ast.walk(tree):
        if not isinstance(node, _DOCSTRING_OWNERS):
            continue
        if ast.get_docstring(node, clean=False) is None:
            continue
        node.body = node.body[1:]
    return tree


def code_shape(source: str) -> str:
    """*source* as a dump of its docstring-free AST. Raises SyntaxError."""
    return ast.dump(_strip_docstrings(ast.parse(source)), include_attributes=False)


def shape_violations(pairs: list[tuple[str, str, str]]) -> list[str]:
    """One string per `(label, before, after)` whose code shape moved.

    Comparing nothing is itself a violation, at both scales: an empty *pairs*,
    and a pair whose two sources are both blank -- the shape a failed read of
    the pre- and post-edit source takes. Either reports clean otherwise, which
    is indistinguishable from a guard that passed.
    """
    if not pairs:
        return ["compared nothing -- no files were handed to the guard"]

    violations: list[str] = []
    for label, before, after in pairs:
        if not before.strip() and not after.strip():
            violations.append(f"{label}: compared nothing -- both sources blank")
            continue
        try:
            before_shape = code_shape(before)
        except SyntaxError as exc:
            violations.append(f"{label}: pre-edit source does not parse ({exc})")
            continue
        try:
            after_shape = code_shape(after)
        except SyntaxError as exc:
            violations.append(f"{label}: post-edit source does not parse ({exc})")
            continue
        if before_shape != after_shape:
            violations.append(
                f"{label}: code shape changed -- this edit was not prose-only"
            )
    return violations

#!/usr/bin/env python3
"""Ask git whether a ref exists. The leaf of the branch-resolution stack.

Extracted from ``branch_resolution.py`` at 501 lines. Everything here is a thin
wrapper over one `git` invocation and answers a yes/no question about a name —
no SMM state is read, nothing is decided. That is what makes it a LEAF: it
imports nothing from the modules that import it, so the layering stays one-way.

``_verified_local`` belongs with the primitives rather than with the resolvers
because it is the invariant they all share: a RECORDED branch name is
trustworthy only if it still EXISTS.

Re-exported from ``branch_resolution`` BY IDENTITY, so ``branching._git is
branch_resolution._git`` still holds and every existing
``mock.patch("branch_resolution.branch_exists")`` site resolves unchanged.
"""

import subprocess


def _git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=10)


def branch_exists(cwd: str, name: str) -> bool:
    r = _git(["git", "rev-parse", "--verify", f"refs/heads/{name}"], cwd)
    return r.returncode == 0


def ref_exists(cwd: str, ref: str) -> bool:
    """True when ``ref`` resolves to a commit — branch, tag, SHA, or remote ref.

    Deliberately broader than ``branch_exists`` (refs/heads only): a HANDED base
    is legitimately a bare SHA (chained stories fork off a commit) or a remote
    ref, so the trust question for one is "can git resolve this to a commit",
    not "is this a local branch". Empty and whitespace refs resolve to nothing
    and answer False, as they should.
    """
    r = _git(["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], cwd)
    return r.returncode == 0


def _verified_local(cwd: str, name: str | None) -> str | None:
    """Return ``name`` only if it is set AND still names a local branch.

    The invariant this module exists to enforce: a RECORDED branch name is
    trustworthy only if it still EXISTS. Branches get deleted, renamed, and
    left behind in other worktrees; sprint.json does not notice. Handing a
    recorded-but-vanished name to `git checkout`/`git merge` as a ref is the
    silent-corruption path — so every recorded name is verified before it is
    returned as an answer.
    """
    return name if name and branch_exists(cwd, name) else None


def match_local_branches(cwd: str, pattern: str) -> list[str]:
    """Run git for-each-ref against `refs/heads/<pattern>` and return short names."""
    r = _git(
        ["git", "for-each-ref", "--format=%(refname:short)", f"refs/heads/{pattern}"],
        cwd,
    )
    if r.returncode != 0:
        return []
    return [b for b in r.stdout.splitlines() if b]

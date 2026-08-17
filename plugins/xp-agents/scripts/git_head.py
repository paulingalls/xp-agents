#!/usr/bin/env python3
"""What HEAD points at, read from the files git keeps it in — no subprocess.

`commits.get_head_commit_hash` forks `git rev-parse`, which is the right answer
when a hook has already decided the command in front of it is worth inspecting.
`commit_observer` asks on EVERY Bash, and almost every answer is "unchanged", so
the price of watching is paid on the common path where nothing happened. A fork
per Bash to learn that is the wrong shape; two small file reads is the right one.

The layouts this has to cross, which is the whole reason it is not two lines:

* **`.git` is a directory** — an ordinary clone. HEAD and refs are both there.
* **`.git` is a FILE** holding `gitdir: <path>` — a linked worktree, which is
  how every teammate in this project runs. HEAD lives in that gitdir, but the
  BRANCH REFS do not: they live in the shared common dir, named by a `commondir`
  file beside HEAD.
* **The ref is packed.** `git gc`/`git pack-refs` moves loose ref files into a
  single `packed-refs` in the common dir, and the loose file simply vanishes. A
  reader that only stats `refs/heads/<branch>` reports "no HEAD" on any repo
  that has been packed — silently, and only sometimes, which is the worst shape
  a cheap-path optimisation can take.
* **`cwd` is a subdirectory** of the checkout, which it routinely is. Walk up.

Every failure returns None, and every caller must treat None as "cannot say" —
never as "HEAD did not move". Falling back to the fork is the caller's choice to
make; this module's job is to answer cheaply or not at all.
"""

import re
from pathlib import Path

__all__ = ["read_head", "resolve_git_dirs"]

# A full object name, anchored. Anything else in a HEAD or ref file — a symref
# loop, a truncated write, an `ORIG_HEAD` style annotation — is not an answer.
_OBJECT_NAME_RE = re.compile(r"^[0-9a-f]{40}$")

_SYMREF_PREFIX = "ref: "

# Depth guard on the walk to the checkout root. A cwd that is not in a repo at
# all walks to the filesystem root and stops there anyway; this only bounds a
# pathological path (a symlink cycle presenting as unbounded depth) so a hook
# cannot hang on a directory listing.
_MAX_PARENTS = 64


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None


def resolve_git_dirs(cwd: str) -> tuple[Path, Path] | None:
    """`(gitdir, commondir)` for the repo containing `cwd`, or None.

    They are the same path for an ordinary clone and differ for a linked
    worktree, where HEAD is per-worktree and `refs/heads/*` is shared. Returned
    as a pair rather than resolved here, because the two are searched in a
    specific order — see `_resolve_ref`.
    """
    start = Path(cwd)
    for _ in range(_MAX_PARENTS):
        candidate = start / ".git"
        if candidate.is_dir():
            return candidate, _common_dir(candidate)
        if candidate.is_file():
            pointer = _read(candidate)
            if pointer is None or not pointer.startswith("gitdir:"):
                return None
            gitdir = Path(pointer.partition(":")[2].strip())
            if not gitdir.is_absolute():
                gitdir = (start / gitdir).resolve()
            if not gitdir.is_dir():
                return None
            return gitdir, _common_dir(gitdir)
        if start.parent == start:
            return None
        start = start.parent
    return None


def _common_dir(gitdir: Path) -> Path:
    """The shared dir holding `refs/` and `packed-refs`, `gitdir` if unlinked.

    Written by git as a `commondir` file beside HEAD in a linked worktree, and
    conventionally relative (`../..`), so it is resolved against the gitdir.
    """
    pointer = _read(gitdir / "commondir")
    if not pointer:
        return gitdir
    common = Path(pointer)
    return common if common.is_absolute() else (gitdir / common).resolve()


def read_head(cwd: str) -> str | None:
    """The commit hash HEAD resolves to in the repo containing `cwd`, or None.

    None means "could not say" — not a repo, an unreadable HEAD, a symref to a
    branch with no commits yet (a fresh `git init`), or a ref this reader could
    not find in either the loose files or `packed-refs`.
    """
    dirs = resolve_git_dirs(cwd)
    if dirs is None:
        return None
    gitdir, commondir = dirs
    raw = _read(gitdir / "HEAD")
    if raw is None:
        return None
    if not raw.startswith(_SYMREF_PREFIX):
        # Detached HEAD stores the object name directly.
        return raw if _OBJECT_NAME_RE.match(raw) else None
    return _resolve_ref(gitdir, commondir, raw[len(_SYMREF_PREFIX) :].strip())


def _resolve_ref(gitdir: Path, commondir: Path, refname: str) -> str | None:
    """A ref name to an object name, loose first and packed second.

    Loose FIRST and in the GITDIR first, because that is git's own precedence:
    a per-worktree ref (`refs/bisect/*`, and `HEAD` itself) shadows the shared
    one, and a loose file is always newer than whatever `packed-refs` still
    holds for the same name — `git pack-refs` writes the pack before deleting
    the loose file, so the two coexist and disagree during that window.
    """
    if not refname.startswith("refs/"):
        return None
    for base in (gitdir, commondir):
        value = _read(base / refname)
        if value is not None and _OBJECT_NAME_RE.match(value):
            return value
    return _packed_ref(commondir, refname)


def _packed_ref(commondir: Path, refname: str) -> str | None:
    """`refname`'s object name from `packed-refs`, or None.

    A `^<hash>` line is the PEELED tag target of the line before it, never a
    ref of its own — skipped rather than parsed, or an annotated tag would
    resolve to the commit under the wrong name.
    """
    text = _read(commondir / "packed-refs")
    if text is None:
        return None
    for line in text.splitlines():
        if not line or line[0] in "#^":
            continue
        object_name, _, name = line.partition(" ")
        if name.strip() == refname and _OBJECT_NAME_RE.match(object_name):
            return object_name
    return None

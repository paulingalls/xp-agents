#!/usr/bin/env python3
"""Bash-command parsing helpers for git commit detection.

Extracted from commits.py to stay under the 500-line cap. Holds the
effective-cwd resolver, the `-C` target/reachability judgements, and the
repo-candidate scanner used to confirm which repo a `git commit` actually
landed in.

Message recovery and escape-hatch tags moved on to `commit_message.py` — see
its docstring for why the quoting a message arrived in needed room here that
this file did not have. Both are re-exported at the bottom so the historical
import paths keep resolving.

Reading the `-C` tokens themselves moved on to `dash_c_tokens.py` for the same
reason. What stays here is what the tokens are FOR — which repo the commit lands
in, whether we refuse it, and which candidates a post-hook may confirm against.
"""

import contextlib
import sys
from collections.abc import Iterator
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import git_commits
from dash_c_tokens import (
    HAS_GLOBAL_DASH_C_RE,
    cd_tokens,
    dash_c_tokens,
    mask_data_spans,
    token_unreachable,
)

# No path regex lives here any more. Both kinds — `git -C <path>` and `cd <path>`
# — are read by `dash_c_tokens`/`cd_tokens`, which LOCATE the token on an
# offset-preserving mask (so neither one inside a commit-message body counts) and
# READ the path from the RAW command at the same offsets (so a QUOTED literal
# path is not deleted before anyone sees it).
#
# `cd` used to keep its own regex over the quote-STRIPPED text, on the theory that
# stripping was what made a message body invisible. Masking gives that same
# immunity while also recovering the quoted literal, so the two properties were
# never in tension — the stripped-text reader just lost the path as well.


def _resolved_dir(candidate: str, fallback: str) -> str | None:
    """`candidate` as an existing directory, resolved against `fallback` when
    relative — or None when it is not a directory we can see.

    One definition for both readers of a `-C`/`cd` path. `parse_effective_cwd`
    and `head_probe_target` each spelled the rule out, so a change to how a
    RELATIVE target resolves had to be made twice to hold.
    """
    path = Path(candidate)
    if not path.is_absolute():
        path = Path(fallback) / path
    return str(path) if path.is_dir() else None


def parse_effective_cwd(command: str, fallback: str) -> str:
    """Return the effective cwd a git invocation in `command` ran under.

    `git -C <path>` wins (highest precedence); otherwise the last `cd <path>`
    segment whose target exists as a directory wins. Relative paths resolve
    against `fallback`. Returns `fallback` when nothing parses or the parsed
    path doesn't exist.

    Lets the post-Bash hook read HEAD from the right repo when an agent
    chained `cd <wt> && git commit && cd -` (the cd-back means input_data.cwd
    is no longer the worktree by the time the hook fires).

    BOTH kinds now read from ONE source: `dash_c_tokens` and `cd_tokens`, which
    locate on an offset-preserving mask and read the path from the raw command at
    the same offsets, over a single mask built here. Each kind used to be read off
    the quote-STRIPPED text, where the path had already been DELETED —
    `git -C "/p" commit` became `git -C  commit` and captured the literal token
    `commit`, and `cd "/a real dir" && git commit` produced no candidate at all.
    Both silently returned `fallback` while every downstream gate scanned the
    caller's repo, which an empty `git diff --cached` makes indistinguishable from
    a clean one.

    Masking rather than stripping is what allows that without losing the property
    stripping was there for: a commit MESSAGE that mentions a real `cd /tmp` is
    filler on the masked text, so it still cannot retarget anything. The two were
    never in tension — the stripped-text reader simply lost the path too.

    Takes no `scan_target`: it fed only the retired `cd` regex, and a parameter
    that no longer changes the answer is the shape this module's whole defect
    history is made of. `head_probe_target` and `commit_repo_candidates` keep
    theirs for `HAS_GLOBAL_DASH_C_RE` / `is_git_commit` and stop forwarding it.
    """
    if not command:
        return fallback

    # Fast-path: skip the strip+regex passes for commands that can't match
    # either pattern. PreToolUse:Bash fires on every Bash call (pytest, ls,
    # ruff, …), and none of those mention git at all, so the strip+two-regex
    # scan is still skipped for the 99% case.
    # Keyed on the bare word `git`, not on `git -`: the gap between `git` and
    # its flags can be a tab or a `\`-newline wrap, neither of which contains
    # the substring `git -`. That guard silently answered `fallback` for a
    # perfectly readable `-C` while `dash_c_unreachable`, which has no such
    # guard, read the same token — a third reader disagreeing with the other
    # two, which is the whole defect class here.
    if "cd " not in command and "git" not in command:
        return fallback

    def _last_validated(candidates: list[str]) -> str | None:
        for candidate in reversed(candidates):
            resolved = _resolved_dir(candidate, fallback)
            if resolved is not None:
                return resolved
        return None

    # Two passes encode precedence: -C beats cd. Within each kind, last
    # validated candidate wins so `cd /A && cd -` lands back on /A, and
    # `-C /a add && -C /b commit` targets /b — the precedence
    # `head_probe_target` is pinned to agree with.
    # INCOMPLETE tokens are dropped, not resolved: `-C '/tmp/'"$WT"` would
    # otherwise resolve confidently to its first segment — a real directory that
    # is not the target — which is worse than admitting we do not know.
    # `dash_c_unreachable` refuses it at the gate; this declines to guess.
    #
    # BOTH kinds now come from the same masked-locate/raw-read reader, over ONE
    # mask. `cd` used to be read off the quote-stripped text, where a quoted
    # literal had already been deleted — the same defect the `-C` side carried,
    # and the reason `cd "/a real dir" && git commit` silently scanned the
    # caller's repo.
    masked = mask_data_spans(command)
    dash_c_paths = [p for _q, p, complete in dash_c_tokens(command, masked) if complete]
    cd_paths = [p for _q, p, complete in cd_tokens(command, masked) if complete]
    for candidates in (dash_c_paths, cd_paths):
        resolved = _last_validated(candidates)
        if resolved is not None:
            return resolved

    return fallback


def head_probe_target(
    command: str, fallback: str, *, scan_target: str | None = None
) -> str | None:
    """The repo to probe HEAD from for a commit-shaped command that did NOT
    confirm — or None to suppress the probe (git aborted, nothing landed).

    A git-global `git -C <path>` change-directory flag is detected on the
    QUOTE-STRIPPED command, so a `-C` inside a commit-message body never
    counts. Its literal path — read from the RAW command so a quoted path
    survives — resolves against `fallback`.

    The LAST `-C` in the command wins, mirroring `parse_effective_cwd`, whose
    answer this one exists to stand in for: in `git -C /a add && git -C /b
    commit` the committing target is /b, and the two functions reading opposite
    ends meant a non-confirming commit was probed in a repo it never touched —
    whose HEAD, if some earlier commit had advanced it, fabricates the very trace
    the "not a dir -> None" arm below is careful not to fabricate. Then:

      * reachable dir  -> probe THAT repo. A `git -C <reachable>` commit that
        landed but whose message a commit-msg hook rewrote fails confirmation;
        probing its own repo still lets the HEAD-moved disambiguator trace it.
      * not a dir      -> None. `git -C <nonexistent>` aborts before landing
        anything, so probing `parse_effective_cwd`'s fallback (the orchestrator
        cwd) would misread an unrelated repo's HEAD and fabricate a trace.

    With no global `-C` flag, defer to `parse_effective_cwd` (the last `cd`
    target, else the hook's own cwd).
    """
    if scan_target is None:
        scan_target = git_commits.strip_quoted(command)
    if HAS_GLOBAL_DASH_C_RE.search(scan_target):
        tokens = dash_c_tokens(command)
        # An unrecoverable token anywhere suppresses the probe, rather than
        # demoting it to the last RECOVERED one: in `git -C /a add && git -C
        # '/b/'"$X" commit` the commit targeted whatever the second token
        # expands to, so answering /a probes a repo the commit never touched —
        # the fabricated trace the "not a dir -> None" arm below guards against.
        if any(not complete for _q, _p, complete in tokens):
            return None
        raw_path = tokens[-1][1] if tokens else ""
        if not raw_path:
            # `-C` flag present but its path is unrecoverable — suppress rather
            # than probe the wrong repo (the safe default the old gate took).
            return None
        return _resolved_dir(raw_path, fallback)
    return parse_effective_cwd(command, fallback)


def dash_c_unreachable(command: str, *, scan_target: str | None = None) -> bool:
    """True only when a `git -C <path>` names a repo we cannot even locate —
    the path is hidden behind an unexpanded shell variable or command
    substitution, so the hook sees the literal text, never its value.

    A literal path that simply does not exist is NOT unreachable: git aborts
    with "cannot change to '<path>'" and creates no commit anywhere, so the
    unmatched HEAD is an ordinary failure that must stay silent — not a commit
    we merely could not inspect. Only the hidden-variable case leaves genuine
    ambiguity between "landed somewhere we can't look" and "was rejected", and
    only that case justifies the worktree scan / unconfirmed-commit trace.

    Which constructs actually expand depends on the QUOTING the path arrived in,
    so the three capture groups are judged separately — treating them alike
    misreports both directions, and once this predicate also gates a hard commit
    block a false positive costs a refused commit:

      * single-quoted -- the shell expands nothing. git receives the literal
        text, aborts, nothing lands: never unreachable.
      * double-quoted -- `$` and backtick expand; a leading `~` and glob
        metacharacters do NOT.
      * bare          -- `$`, backtick, a LEADING `~`, and a glob (`*?[`) all
        expand, and a backslash escape (`/tmp/a\\ dir`) joins the next word
        into the same path while the capture stops at the backslash.

    EVERY `-C` in the command is judged, not just the first. A chain stages in
    one repo and commits in another — `git -C /literal add -A && git -C "$WT"
    commit` — and reading only the first token let that pass the refusal while
    `parse_effective_cwd` resolved the LAST one, so every gate scanned a repo
    the commit never landed in: the exact bypass this predicate exists to close.
    Any unreachable target makes the destination unknowable, because nothing
    here can attribute a `-C` to the `commit` word specifically.

    The cost of ANY rather than the committing one: `git -C /repo commit && git
    -C "$OTHER" log` is refused for a `-C` that commits nothing. Under the
    fail-closed doctrine an actionable refusal beats an unscanned commit, and
    the remedy is the same either way — use literal paths.

    A `~` anywhere but the front (`/tmp/a~b`) is an ordinary literal character.

    A bare glob is the one form whose failure mode is NOT the safe abort: when
    it matches, the shell hands git a real directory and the commit lands, while
    the hook still sees the pattern, `is_dir()` fails, and every gate reads the
    caller's repo — the same bypass as `$WT`. The cost is a refused commit for a
    literal directory name that contains `*`, `?`, or `[`; under the fail-closed
    doctrine an actionable refusal beats an unscanned commit.

    The match still reads ONE quoting form per `-C` token, so a token that
    concatenates forms (`'/tmp/'"$WT"`) is captured only as far as its first
    segment. That used to read as reachable — fail-open. It no longer does: such
    a token is marked INCOMPLETE by `dash_c_tokens` and refused here, because
    what the remainder expands to was never seen. Story-011 closed it after
    measuring that the case is not merely theoretical — once `parse_effective_cwd`
    began reading raw tokens, a mixed-form path resolved *confidently* to its
    first segment, so a gate scanned a real-but-wrong repo.

    Presence of the flag is decided on the QUOTE-STRIPPED command, exactly as
    `head_probe_target` does: `git commit -m "prefer git -C $WT over cd"` has no
    `-C` flag at all — the text lives in the message body — and must not be read
    as one, or a commit that merely talks about `-C` is refused. The per-token
    scan holds that line too, via the token reader's offset-preserving mask: a
    message body becomes filler at its original offsets, so a real `-C` elsewhere
    in the same command no longer drags the mentioned one into the scan.
    """
    if scan_target is None:
        scan_target = git_commits.strip_quoted(command)
    if not HAS_GLOBAL_DASH_C_RE.search(scan_target):
        return False
    # An INCOMPLETE token is unreachable by construction: only the first segment
    # of a concatenation was captured, so whatever the rest expands to was never
    # seen. Judged alongside the quoting form rather than instead of it — a
    # complete token still has to survive `token_unreachable`.
    return any(
        not complete or token_unreachable(g, p)
        for g, p, complete in dash_c_tokens(command)
    )


def commit_repo_candidates(
    command: str, fallback: str, *, scan_target=None
) -> Iterator[str]:
    """Yield, in order, repos a `git commit` in `command` might have run in.

    `parse_effective_cwd` first (the explicit `cd`/`git -C` target), then the
    hook's own cwd, then every live teammate worktree. Callers confirm which
    candidate actually holds the commit by comparing HEAD's subject against the
    message the command supplied — matching, not parsing.

    Lazy on purpose: enumerating teammate worktrees shells out to
    `git worktree list --porcelain`, and this runs on every commit-shaped Bash
    (a hot PostToolUse path). Yielding lets the caller stop at the first
    matching candidate — so the common solo `git commit` in the main checkout
    never pays for the worktree scan, which only the quoted-`-C` case needs.

    The worktree candidates exist because `git -C "$WT" commit` hides its path
    behind an unexpanded shell variable: `strip_quoted` removes the quoted
    token before `parse_effective_cwd` ever sees it, so the parse silently
    yields the MAIN checkout and HEAD is read from the wrong repo. They are
    gated on exactly that case (`dash_c_unreachable`) — never a general
    fallback for any unmatched command. A rejected `git commit` in the main
    checkout has no unreachable `-C` target, so it never reaches the scan and
    can never be mis-attributed to a live worktree whose HEAD subject happens
    to equal the attempted message.
    """
    seen: set[str] = set()

    def _emit(path: str | None, *, require_dir: bool = True) -> Iterator[str]:
        if not path or path in seen:
            return
        if require_dir and not Path(path).is_dir():
            return
        seen.add(path)
        yield path

    # The parsed target and the hook's own cwd go in unconditionally: callers
    # (and tests) pass synthetic cwds, and `get_commit_message_body` already
    # degrades to None on a path that isn't a repo.
    yield from _emit(
        parse_effective_cwd(command, fallback),
        require_dir=False,
    )
    yield from _emit(fallback, require_dir=False)

    # The worktree scan recovers ONLY the `git -C "$VAR"` case where the shell
    # variable hid the real repo. Restricting it there is load-bearing: without
    # this gate, any command that failed to match on the cheap candidates
    # (e.g. a pre-commit rejection in the main checkout) would fall through and
    # match a live worktree by coincidental HEAD subject, fabricating a commit
    # event against the worktree's unrelated hash.
    if not dash_c_unreachable(command, scan_target=scan_target):
        return

    # Only reached when the caller keeps iterating past the cheap candidates
    # (no earlier match) — the `git worktree list` subprocess is deferred to
    # here so the common matched-on-first-candidate path never triggers it.
    with contextlib.suppress(Exception):
        import worktree

        for _story_id, wt_path in worktree.list_live_teammate_worktree_paths(fallback):
            yield from _emit(wt_path)


# Message recovery and the escape-hatch tags live in `commit_message` (moved
# there when the quoting-aware recovery needed room this file did not have).
# Re-exported so the historical `from commit_command import ...` /
# `from commits import ...` paths keep resolving.
from commit_message import (  # noqa: E402,F401  intentional mid-file re-export
    extract_commit_message,
    is_escape_hatch_commit,
    is_escape_hatch_message,
    recover_commit_message,
)

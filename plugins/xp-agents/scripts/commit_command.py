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
"""

import contextlib
import re
import sys
from collections.abc import Iterator
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import git_commits

# Match `cd <path>` and `git -C <path>` only at a shell-statement boundary
# (start, newline, semicolon, &&, ||) so we don't pick up the literal text
# of a commit-message heredoc that happens to mention "cd /something". The
# parsed path is then validated via `is_dir()` — a second filter against
# false positives. Last match wins so `cd /A && cd -` lands back on /A
# (the cd-back token doesn't validate).
#
# `[^\s;&|]+` excludes statement-boundary chars from the captured path so
# `cd /tmp;` yields `/tmp` (not `/tmp;`) and `cd /a||true` yields `/a`.
# `is_dir()` would reject the trailing-punctuation variants anyway, but
# tightening the capture keeps the helper honest with its docstring.
_BOUNDARY = r"(?:^|[\n;]|&&|\|\|)\s*"
_PATH_TOKEN = r"([^\s;&|]+)"

# Global git options that may sit between `git` and the `-C` change-directory
# flag. `-c <name>=<value>` takes its value as a SEPARATE token — the project's
# own CI-identity form `git -c commit.gpgsign=false -C /path commit` — so the
# chain must be able to consume that bare value token; a plain `(?:-\S+\s+)*?`
# chain stalls on it (the value does not start with `-`) and the `-C` goes
# unrecognized, leaving the repo to resolve to the hook's own cwd. Ordinary
# boolean flags (`--no-pager`) match the `-\S+` alternative. `commit`
# intervening still breaks the chain, so `git commit -C <commit>` (the
# reuse-message flag) is never mistaken for the global `-C`.
_GLOBAL_FLAG_CHAIN = r"(?:-c\s+\S+\s+|-\S+\s+)*?"

# No `-C` regex over the stripped text lives here any more: it could only ever
# see a path `strip_quoted` had already deleted. `_dash_c_tokens` (below) is the
# single reader for `-C` paths, shared with `dash_c_unreachable` and
# `head_probe_target`. `cd` keeps its stripped-text regex — a quoted message body
# mentioning a real `cd /tmp` must stay invisible.
_CD_RE = re.compile(_BOUNDARY + r"cd\s+" + _PATH_TOKEN)


def parse_effective_cwd(
    command: str, fallback: str, *, scan_target: str | None = None
) -> str:
    """Return the effective cwd a git invocation in `command` ran under.

    `git -C <path>` wins (highest precedence); otherwise the last `cd <path>`
    segment whose target exists as a directory wins. Relative paths resolve
    against `fallback`. Returns `fallback` when nothing parses or the parsed
    path doesn't exist.

    Lets the post-Bash hook read HEAD from the right repo when an agent
    chained `cd <wt> && git commit && cd -` (the cd-back means input_data.cwd
    is no longer the worktree by the time the hook fires).

    The two kinds are read from DIFFERENT sources, deliberately:

    - `-C` paths come from `_dash_c_tokens` — located on the offset-preserving
      mask, read from the RAW command. This is the same reader
      `dash_c_unreachable` and `head_probe_target` use, and sharing it is the
      point: this function used to scan the quote-STRIPPED text, where
      `git -C "/p" commit` has become `git -C  commit`, so it captured the
      literal token `commit` as the path, failed `is_dir()`, and silently
      returned `fallback`. Every gate downstream then read the caller's repo
      while the commit landed elsewhere. Three readers, one token source, so
      they cannot disagree about which repo a command names again.
    - `cd` paths stay on the quote-stripped text, where a commit message
      quoting a REAL `cd /tmp` must remain invisible. `cd` was never broken and
      its immunity depends on the deletion.

    `scan_target` lets callers pass a pre-stripped command (via
    `git_commits.strip_quoted`) so the same Bash invocation isn't
    quote-stripped twice when downstream functions also need it. It applies to
    the `cd` pass only — the `-C` pass needs the raw command by construction.
    """
    if not command:
        return fallback

    # Fast-path: skip the strip+regex passes for commands that can't match
    # either pattern. PreToolUse:Bash fires on every Bash call (pytest, ls,
    # ruff, …); the strip+two-regex scan is wasted work for the 99% case.
    # `git -` (not the tighter `git -C`) so the `-C` reached PAST a global
    # option — the CI-identity `git -c key=val -C /path` form — is not skipped:
    # a git command only carries `git -<flag>` when it has a global option
    # before the subcommand, which is exactly when `-C` can appear.
    if "cd " not in command and "git -" not in command:
        return fallback

    if scan_target is None:
        scan_target = git_commits.strip_quoted(command)

    def _resolve(candidate: str) -> str | None:
        path = Path(candidate)
        if not path.is_absolute():
            path = Path(fallback) / path
        return str(path) if path.is_dir() else None

    def _last_validated(candidates: list[str]) -> str | None:
        for candidate in reversed(candidates):
            resolved = _resolve(candidate)
            if resolved is not None:
                return resolved
        return None

    # Two passes encode precedence: -C beats cd. Within each kind, last
    # validated candidate wins so `cd /A && cd -` lands back on /A, and
    # `-C /a add && -C /b commit` targets /b — the precedence
    # `head_probe_target` is pinned to agree with.
    dash_c_paths = [path for _quoting, path in _dash_c_tokens(command)]
    cd_paths = [m.group(1) for m in _CD_RE.finditer(scan_target)]
    for candidates in (dash_c_paths, cd_paths):
        resolved = _last_validated(candidates)
        if resolved is not None:
            return resolved

    return fallback


# Matches `-C <path>` on the RAW command, before strip_quoted removes quoted
# tokens. `git -C "$WT" commit` otherwise loses its path entirely and the repo
# silently resolves to the hook's own cwd. Shares `_GLOBAL_FLAG_CHAIN` so the
# `-c key=val` CI-identity form is skipped, and is now the ONLY `-C` reader:
# `parse_effective_cwd` reads its paths from here too, via `_dash_c_tokens`.
_RAW_DASH_C_RE = re.compile(
    r"git\s+" + _GLOBAL_FLAG_CHAIN + r"""-C\s+(?:"([^"]+)"|'([^']+)'|([^\s;&|]+))"""
)

# Length-PRESERVING mask of the spans `strip_quoted` deletes outright: heredoc
# bodies, and the contents of quoted strings. Offsets survive, so a `-C` token
# located on the masked text can be read back from the RAW command at the same
# span — which is what lets every `-C` in a compound command be judged, rather
# than only the first. Deleting the spans instead (strip_quoted) shifts every
# later offset; keeping them shifts nothing but also can't be searched, because
# a commit MESSAGE that merely mentions `git -C $WT` would then read as a flag.
#
# Quote DELIMITERS are kept and only the contents are masked, so the quoting
# form a `-C` path arrived in is still visible — that form is what decides
# whether the shell expanded it. The filler is a plain letter: it must not
# introduce any construct `dash_c_unreachable` keys on ($, backtick, ~, glob),
# nor a quote, whitespace, or statement separator.
_ESCAPED_QUOTE_RE = re.compile(r"\\['\"]")
# Shared with `git_commits.strip_quoted` — see the ordering warning there. This
# site was always correct; the deleting twin was not, and one definition is what
# stops them diverging again.
_QUOTED_SPAN_RE = git_commits.QUOTED_SPAN_RE
_HEREDOC_SPAN_RE = re.compile(r"<<-?\s*'?(\w+)'?.*?\n.*?\1", re.DOTALL)
_MASK_FILL = "x"


def _mask_data_spans(command: str) -> str:
    """`strip_quoted`'s effect without moving any character's offset."""
    chars = list(command)

    def _fill(start: int, end: int) -> None:
        for i in range(start, end):
            if chars[i] != "\n":
                chars[i] = _MASK_FILL

    for match in _HEREDOC_SPAN_RE.finditer(command):
        _fill(*match.span())
    # Escaped quotes first, exactly as strip_quoted drops them first: an
    # unmasked `\"` would otherwise open or close a span it is not part of.
    for match in _ESCAPED_QUOTE_RE.finditer("".join(chars)):
        _fill(*match.span())
    for match in _QUOTED_SPAN_RE.finditer("".join(chars)):
        _fill(match.start() + 1, match.end() - 1)
    return "".join(chars)


def _dash_c_tokens(command: str) -> list[tuple[int, str]]:
    """Every git-global `-C` token, in command order.

    Each entry is (quoting-group index, the token's RAW text). The tokens are
    LOCATED on the masked command — so a `-C` inside a commit message is not one
    — and READ from the raw command at the same offsets, because the mask
    replaced the path text with filler. The group index carries the quoting form
    the path arrived in, which is what decides whether the shell expanded it.

    One list rather than a `search` in each caller: `dash_c_unreachable` needs
    every token, `head_probe_target` needs the one nearest the commit, and when
    those two disagreed about WHICH `-C` a command targeted, one refused nothing
    while the other probed the wrong repo.
    """
    tokens: list[tuple[int, str]] = []
    for match in _RAW_DASH_C_RE.finditer(_mask_data_spans(command)):
        for group in (1, 2, 3):
            if match.group(group) is not None:
                start, end = match.span(group)
                tokens.append((group, command[start:end]))
                break
    return tokens


# Detects the PRESENCE of a git-global `-C` flag on the QUOTE-STRIPPED command
# (a `-C` inside a commit-message body is stripped away, so it can never
# count). Path-agnostic: the path itself is read from the RAW command via
# `_RAW_DASH_C_RE` so a quoted literal path survives. `head_probe_target` uses
# this to tell an explicit `git -C <path>` apart from a plain/`cd` command.
_HAS_GLOBAL_DASH_C_RE = re.compile(r"git\s+" + _GLOBAL_FLAG_CHAIN + r"-C(?:\s|$)")


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
    if _HAS_GLOBAL_DASH_C_RE.search(scan_target):
        tokens = _dash_c_tokens(command)
        raw_path = tokens[-1][1] if tokens else ""
        if not raw_path:
            # `-C` flag present but its path is unrecoverable — suppress rather
            # than probe the wrong repo (the safe default the old gate took).
            return None
        path = Path(raw_path)
        if not path.is_absolute():
            path = Path(fallback) / path
        return str(path) if path.is_dir() else None
    return parse_effective_cwd(command, fallback, scan_target=scan_target)


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
        expand.

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

    Known limit: the match reads ONE quoting form per `-C` token, so a token
    that concatenates forms (`'/tmp/'"$WT"`) is judged by its first segment and
    a trailing expansion reads as reachable — fail-open, the pre-change
    behaviour. Tokenizing to close it costs more than the case is worth; no
    agent-authored command mixes quoting on a single path.

    Presence of the flag is decided on the QUOTE-STRIPPED command, exactly as
    `head_probe_target` does: `git commit -m "prefer git -C $WT over cd"` has no
    `-C` flag at all — the text lives in the message body — and must not be read
    as one, or a commit that merely talks about `-C` is refused. The per-token
    scan holds that line too, via `_mask_data_spans`: a message body is masked
    to filler at its original offsets, so a real `-C` elsewhere in the same
    command no longer drags the mentioned one into the scan.
    """
    if scan_target is None:
        scan_target = git_commits.strip_quoted(command)
    if not _HAS_GLOBAL_DASH_C_RE.search(scan_target):
        return False
    return any(_token_unreachable(g, p) for g, p in _dash_c_tokens(command))


# `_RAW_DASH_C_RE` group index -> the quoting the path arrived in.
_DOUBLE_QUOTED, _SINGLE_QUOTED, _BARE = 1, 2, 3


def _token_unreachable(quoting: int, path: str) -> bool:
    """Judge ONE `-C` token by the quoting its path arrived in."""
    if quoting == _SINGLE_QUOTED:
        return False
    if quoting == _DOUBLE_QUOTED:
        return "$" in path or "`" in path
    return (
        "$" in path
        or "`" in path
        or path.startswith("~")
        or any(ch in path for ch in "*?[")
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
        parse_effective_cwd(command, fallback, scan_target=scan_target),
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

#!/usr/bin/env python3
"""Bash-command parsing helpers for git commit detection.

Extracted from commits.py to stay under the 500-line cap. Holds the
effective-cwd resolver, commit-message extraction, escape-hatch tag
detection, and the repo-candidate scanner used to confirm which repo a
`git commit` actually landed in.
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

_GIT_DASH_C_RE = re.compile(
    _BOUNDARY + r"git\s+" + _GLOBAL_FLAG_CHAIN + r"-C\s+" + _PATH_TOKEN
)
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

    Quoted strings and heredoc bodies are stripped before scanning so a
    commit message that quotes `cd /tmp` or `git -C /elsewhere` cannot
    retarget cwd — real paths inside message bodies pass `is_dir()`.

    `scan_target` lets callers pass a pre-stripped command (via
    `git_commits.strip_quoted`) so the same Bash invocation isn't
    quote-stripped twice when downstream functions also need it.
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

    def _last_validated(regex: re.Pattern[str]) -> str | None:
        for m in reversed(list(regex.finditer(scan_target))):
            resolved = _resolve(m.group(1))
            if resolved is not None:
                return resolved
        return None

    # Two passes encode precedence: -C beats cd. Within each kind, last
    # validated match wins so `cd /A && cd -` lands back on /A.
    for regex in (_GIT_DASH_C_RE, _CD_RE):
        resolved = _last_validated(regex)
        if resolved is not None:
            return resolved

    return fallback


_HEREDOC_MSG_RE = re.compile(
    r"-m\s+\"\$\(cat\s+<<'?\w+'?\n(.*?)\n\w+\n\)\"",
    re.DOTALL,
)
_SIMPLE_MSG_RE = re.compile(
    r"""-m\s+(?:"((?:[^"\\]|\\.)*)"|'([^']*)')""",
)


# `-F -` / `--file -` reads the message from stdin, which in practice is a
# heredoc appended to the command. Capture the heredoc body so the commit can
# still be confirmed when `-q` suppresses git's `[branch hash]` stdout line.
_STDIN_FLAG_RE = re.compile(r"(?:^|\s)(?:-F|--file)(?:=|\s+)-(?=\s|$)")

# Two patterns, chosen by which form opened the heredoc — a conditional
# backreference would be less clear and each form is independently testable.
# `[^\n]*` after the delimiter admits a trailing redirect, pipe, or chained
# command on the opening line (all legal shell after a heredoc delimiter).
# `(?=\n|$)` makes the closing delimiter own its line, so a body line that
# merely STARTS WITH the delimiter word (a prefix, not the delimiter itself)
# is not mistaken for the close. Group numbering is (1)=delimiter, (2)=body
# in both, matching bash's own termination rules measured directly: plain
# `<<` terminates only at column 0 (no leading whitespace tolerated); `<<-`
# terminates on leading TABS only, never spaces.
_STDIN_HEREDOC_RE = re.compile(r"<<\s*'?(\w+)'?[^\n]*\n(.*?)\n\1(?=\n|$)", re.DOTALL)
_STDIN_HEREDOC_DASH_RE = re.compile(
    r"<<-\s*'?(\w+)'?[^\n]*\n(.*?)\n\t*\1(?=\n|$)", re.DOTALL
)
_FILE_FLAG_RE = re.compile(
    r"""(?:^|\s)(?:-F|--file)(?:=|\s+)(?!-\s|-$)(?:"([^"]+)"|'([^']+)'|([^\s;&|]+))"""
)


def _find_stdin_heredoc_body(command: str, start: int) -> str | None:
    """Return the stdin heredoc body introduced at or after `start`.

    Tries both the plain and `<<-` patterns and keeps whichever matches
    earliest — the two are mutually exclusive at the syntax level (a literal
    `<<-` can never satisfy the plain pattern's `(\\w+)` right after `<<`,
    since `-` is not a word character), so only one can ever match a given
    heredoc occurrence. `<<-` also strips leading tabs from EVERY body line
    (not just the closing delimiter line), so the extracted message matches
    what git actually stored rather than the raw indented source text.
    """
    plain = _STDIN_HEREDOC_RE.search(command, start)
    dash = _STDIN_HEREDOC_DASH_RE.search(command, start)
    if dash and (plain is None or dash.start() < plain.start()):
        return "\n".join(line.lstrip("\t") for line in dash.group(2).split("\n"))
    if plain:
        return plain.group(2)
    return None


def extract_commit_message(command: str) -> str | None:
    """Extract the commit message a git command supplies.

    Handles `-m` (simple and `"$(cat <<EOF …)"` heredoc forms), `-F -` /
    `--file -` with a heredoc body on stdin, and `-F <path>` when the file is
    still readable. Returns None when no message can be recovered.

    `-F` support is load-bearing for the commit-confirmation fallback: with
    `-q`, git prints no `[branch hash]` line, so comparing this message against
    HEAD's body is the only signal that the commit actually landed. Parsing
    only `-m` silently dropped every `-F`-bodied commit from the event log.
    """
    heredoc = _HEREDOC_MSG_RE.search(command)
    if heredoc:
        return heredoc.group(1)
    m = _SIMPLE_MSG_RE.search(command)
    if m:
        return m.group(1) if m.group(1) is not None else m.group(2)
    stdin_flag = _STDIN_FLAG_RE.search(command)
    if stdin_flag:
        # Bind to the heredoc introduced AFTER `-F -`, not merely the first in
        # the command. A compound line can open an earlier, unrelated heredoc
        # (e.g. `cat <<CFG ... CFG` writing a config file) whose body is not the
        # commit message; searching from the flag's end skips past it to the
        # one actually feeding this commit's stdin.
        return _find_stdin_heredoc_body(command, stdin_flag.end())
    file_flag = _FILE_FLAG_RE.search(command)
    if file_flag:
        # The message file may already be gone by PostToolUse time; a missing
        # file is not a failure, just an unrecoverable message. `errors=
        # "replace"` keeps a non-UTF-8 commit message (e.g. latin-1 bytes)
        # from raising UnicodeDecodeError — a decode error is NOT an OSError,
        # so it would otherwise escape the suppress and crash the hook.
        path = next(g for g in file_flag.groups() if g)
        with contextlib.suppress(OSError):
            return Path(path).read_text(errors="replace")
    return None


# Matches `-C <path>` on the RAW command, before strip_quoted removes quoted
# tokens. `git -C "$WT" commit` otherwise loses its path entirely and the repo
# silently resolves to the hook's own cwd. Shares `_GLOBAL_FLAG_CHAIN` so the
# `-c key=val` CI-identity form is skipped the same way as in `_GIT_DASH_C_RE`.
_RAW_DASH_C_RE = re.compile(
    r"git\s+" + _GLOBAL_FLAG_CHAIN + r"""-C\s+(?:"([^"]+)"|'([^']+)'|([^\s;&|]+))"""
)

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
    survives — resolves against `fallback`:

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
        m = _RAW_DASH_C_RE.search(command)
        raw_path = next((g for g in m.groups() if g), "") if m else ""
        if not raw_path:
            # `-C` flag present but its path is unrecoverable — suppress rather
            # than probe the wrong repo (the safe default the old gate took).
            return None
        path = Path(raw_path)
        if not path.is_absolute():
            path = Path(fallback) / path
        return str(path) if path.is_dir() else None
    return parse_effective_cwd(command, fallback, scan_target=scan_target)


def dash_c_unreachable(command: str) -> bool:
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
      * double-quoted -- `$` and backtick expand; a leading `~` does NOT.
      * bare          -- `$`, backtick, and a LEADING `~` all expand.

    A `~` anywhere but the front (`/tmp/a~b`) is an ordinary literal character.
    """
    m = _RAW_DASH_C_RE.search(command)
    if not m:
        return False
    double_quoted, single_quoted, bare = m.groups()
    if single_quoted:
        return False
    if double_quoted:
        return "$" in double_quoted or "`" in double_quoted
    return "$" in bare or "`" in bare or bare.startswith("~")


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
    if not dash_c_unreachable(command):
        return

    # Only reached when the caller keeps iterating past the cheap candidates
    # (no earlier match) — the `git worktree list` subprocess is deferred to
    # here so the common matched-on-first-candidate path never triggers it.
    with contextlib.suppress(Exception):
        import worktree

        for _story_id, wt_path in worktree.list_live_teammate_worktree_paths(fallback):
            yield from _emit(wt_path)


_ESCAPE_HATCH_RE = re.compile(r"^\[(release|chore|sprint-direct)\]", re.IGNORECASE)


def is_escape_hatch_message(message: str | None) -> bool:
    """True if a commit message opens with an escape-hatch tag
    ([release]/[chore]/[sprint-direct]). These bypass the review-cycle gate,
    so they neither require a review at commit time nor count toward the
    retro's review-required denominator."""
    if message is None:
        return False
    return bool(_ESCAPE_HATCH_RE.match(message))


def is_escape_hatch_commit(command: str) -> bool:
    return is_escape_hatch_message(extract_commit_message(command))

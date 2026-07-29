#!/usr/bin/env python3
"""What message a `git commit` command gave git — and whether the shell
expanded it on the way.

Extracted from `commit_command.py`, which was at its size ceiling holding four
responsibilities (effective-cwd resolution, message extraction, escape-hatch
tags, repo candidates). Message recovery is one of them, and the reason it
needed room is the second value here: the QUOTING a message arrived in decides
whether the text the hook read is the text git stored.

Two consumers care about that distinction:

* `commit_event._head_matches_command` compares the recovered subject against
  HEAD — a pre-expansion string simply never matches.
* `commit_emit._message_unreadable_from_command` reads the same fact as
  EVIDENCE: a message the hook can read, which did not match HEAD, means this
  command did not produce HEAD. Judging that by scanning for `$` or a backtick
  alone misread every single-quoted subject containing one as "unexpanded",
  which armed a rebuild that fabricated a commit event.

`commit_command._token_unreachable` already judges a `-C` path by its quoting
for the same reason; this module is that rule applied to the message.
"""

import contextlib
import re
from pathlib import Path

__all__ = [
    "extract_commit_message",
    "is_escape_hatch_commit",
    "is_escape_hatch_message",
    "recover_commit_message",
]

# `-m "$(cat <<EOF … EOF)"` — the multi-line form agents write. The delimiter's
# quoting is captured (group `mq`): `<<'EOF'` makes the body literal, a bare
# `<<EOF` expands `$VAR` and backticks inside it before cat ever sees them.
# The `"$( … )"` wrapper does NOT re-expand the substitution's result, so the
# delimiter is the whole question.
_HEREDOC_MSG_RE = re.compile(
    r"-m\s+\"\$\(cat\s+<<(?P<mq>'?)\w+'?\n(?P<body>.*?)\n\w+\n\)\"",
    re.DOTALL,
)
# Group 1 = double-quoted (the shell expands `$` and backticks inside it),
# group 2 = single-quoted (the shell expands nothing).
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
# is not mistaken for the close. Group numbering is (1)=delimiter quote,
# (2)=delimiter, (3)=body in both, matching bash's own termination rules
# measured directly: plain `<<` terminates only at column 0 (no leading
# whitespace tolerated); `<<-` terminates on leading TABS only, never spaces.
_STDIN_HEREDOC_RE = re.compile(r"<<\s*('?)(\w+)'?[^\n]*\n(.*?)\n\2(?=\n|$)", re.DOTALL)
_STDIN_HEREDOC_DASH_RE = re.compile(
    r"<<-\s*('?)(\w+)'?[^\n]*\n(.*?)\n\t*\2(?=\n|$)", re.DOTALL
)
_FILE_FLAG_RE = re.compile(
    r"""(?:^|\s)(?:-F|--file)(?:=|\s+)(?!-\s|-$)(?:"([^"]+)"|'([^']+)'|([^\s;&|]+))"""
)


def _find_stdin_heredoc_body(command: str, start: int) -> tuple[str, bool] | None:
    """The stdin heredoc body introduced at or after `start`, and its expansion.

    Tries both the plain and `<<-` patterns and keeps whichever matches
    earliest — the two are mutually exclusive at the syntax level (a literal
    `<<-` can never satisfy the plain pattern's `(\\w+)` right after `<<`,
    since `-` is not a word character), so only one can ever match a given
    heredoc occurrence. `<<-` also strips leading tabs from EVERY body line
    (not just the closing delimiter line), so the extracted message matches
    what git actually stored rather than the raw indented source text.

    The bool is False for a quoted delimiter (`<<'EOF'`), whose body the shell
    hands on verbatim, and True for a bare one, which expands first.
    """
    plain = _STDIN_HEREDOC_RE.search(command, start)
    dash = _STDIN_HEREDOC_DASH_RE.search(command, start)
    if dash and (plain is None or dash.start() < plain.start()):
        body = "\n".join(line.lstrip("\t") for line in dash.group(3).split("\n"))
        return body, not dash.group(1)
    if plain:
        return plain.group(3), not plain.group(1)
    return None


def recover_commit_message(command: str) -> tuple[str | None, bool]:
    """The message a git command supplies, and whether the SHELL expanded it.

    Handles `-m` (simple and `"$(cat <<EOF …)"` heredoc forms), `-F -` /
    `--file -` with a heredoc body on stdin, and `-F <path>` when the file is
    still readable. `(None, False)` when no message can be recovered.

    The second element is the load-bearing half for a caller reading the
    message as evidence rather than as text. True means the recovered string
    passed through a construct the shell resolved (a double-quoted `-m`, a
    bare-delimiter heredoc), so `$VAR` in it is a name whose VALUE git stored
    and the hook cannot see. False means git received these characters
    verbatim — a single-quoted `-m`, a `<<'EOF'` delimiter, or a `-F <path>`
    whose bytes git read straight off disk — so a `$` or backtick in it is an
    ordinary literal, not a sign the hook is reading a pre-expansion string.

    `-F` support is load-bearing for the commit-confirmation fallback: with
    `-q`, git prints no `[branch hash]` line, so comparing this message against
    HEAD's body is the only signal that the commit actually landed. Parsing
    only `-m` silently dropped every `-F`-bodied commit from the event log.
    """
    heredoc = _HEREDOC_MSG_RE.search(command)
    if heredoc:
        return heredoc.group("body"), not heredoc.group("mq")
    m = _SIMPLE_MSG_RE.search(command)
    if m:
        if m.group(1) is not None:
            return m.group(1), True
        return m.group(2), False
    stdin_flag = _STDIN_FLAG_RE.search(command)
    if stdin_flag:
        # Bind to the heredoc introduced AFTER `-F -`, not merely the first in
        # the command. A compound line can open an earlier, unrelated heredoc
        # (e.g. `cat <<CFG ... CFG` writing a config file) whose body is not the
        # commit message; searching from the flag's end skips past it to the
        # one actually feeding this commit's stdin.
        found = _find_stdin_heredoc_body(command, stdin_flag.end())
        return found if found is not None else (None, False)
    file_flag = _FILE_FLAG_RE.search(command)
    if file_flag:
        # The message file may already be gone by PostToolUse time; a missing
        # file is not a failure, just an unrecoverable message. `errors=
        # "replace"` keeps a non-UTF-8 commit message (e.g. latin-1 bytes)
        # from raising UnicodeDecodeError — a decode error is NOT an OSError,
        # so it would otherwise escape the suppress and crash the hook.
        path = next(g for g in file_flag.groups() if g)
        with contextlib.suppress(OSError):
            return Path(path).read_text(errors="replace"), False
    return None, False


def extract_commit_message(command: str) -> str | None:
    """The message a git command supplies, or None. See `recover_commit_message`
    when the QUOTING matters as well as the text."""
    return recover_commit_message(command)[0]


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

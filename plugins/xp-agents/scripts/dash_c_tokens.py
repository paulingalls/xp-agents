#!/usr/bin/env python3
"""Reading the target-directory tokens — `git -C <path>` and `cd <path>` — out of
a raw Bash command.

Extracted from commit_command.py (the seam its own debt entry named) once that
file crossed the headroom band below the 500-line cap. The split is the one the
module already had internally: everything here answers "what target tokens does
this command carry, and can we read their paths at all", while commit_command
answers "so which repo does the commit land in, and do we refuse it".

The one rule that spans both halves and both prefixes: a path is LOCATED on an
offset-preserving mask (so a `-C` or `cd` inside a commit message is not one) and
READ from the raw command at the same offsets (so a QUOTED literal path is not
deleted before anyone sees it). Three `-C` readers used to disagree about that,
and each disagreement cost a gate running against the wrong repo; `cd` was the
fourth, still on the deleting stripper, until it joined them here.

The filename still says `dash_c` because its only importer is commit_command.py
while `git_commits.py` names it in prose that a rename would also have to touch —
out of the story's domain. The rename is recorded as follow-up, not forgotten.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import git_commits

# Global git options that may sit between `git` and the `-C` change-directory
# flag. `-c <name>=<value>` takes its value as a SEPARATE token — the project's
# own CI-identity form `git -c commit.gpgsign=false -C /path commit` — so the
# chain must be able to consume that bare value token; a plain `(?:-\S+\s+)*?`
# chain stalls on it (the value does not start with `-`) and the `-C` goes
# unrecognized, leaving the repo to resolve to the hook's own cwd. Ordinary
# boolean flags (`--no-pager`) match the `-\S+` alternative. `commit`
# intervening still breaks the chain, so `git commit -C <commit>` (the
# reuse-message flag) is never mistaken for the global `-C`.
#
# Token gaps come from `git_commits.TOKEN_GAP` so a `\`-newline continuation
# inside the chain — the documented CI-identity form is long enough that an
# agent wraps it — does not hide the `-C` from every reader below.
_GAP = git_commits.TOKEN_GAP
_GLOBAL_FLAG_CHAIN = r"(?:-c" + _GAP + r"\S+" + _GAP + r"|-\S+" + _GAP + r")*?"

# Matches `-C <path>` on the RAW command, before strip_quoted removes quoted
# tokens. `git -C "$WT" commit` otherwise loses its path entirely and the repo
# silently resolves to the hook's own cwd. Shares `_GLOBAL_FLAG_CHAIN` so the
# `-c key=val` CI-identity form is skipped, and is the ONLY `-C` reader:
# `parse_effective_cwd` reads its paths from here too, via `dash_c_tokens`.
RAW_DASH_C_RE = re.compile(
    r"git"
    + _GAP
    + _GLOBAL_FLAG_CHAIN
    + r"-C"
    + _GAP
    + r"""(?:"([^"]+)"|'([^']+)'|([^\s;&|]+))"""
)

# Detects the PRESENCE of a git-global `-C` flag on the QUOTE-STRIPPED command
# (a `-C` inside a commit-message body is stripped away, so it can never
# count). Path-agnostic: the path itself is read from the RAW command via
# `RAW_DASH_C_RE` so a quoted literal path survives. `head_probe_target` uses
# this to tell an explicit `git -C <path>` apart from a plain/`cd` command.
HAS_GLOBAL_DASH_C_RE = re.compile(
    r"git" + _GAP + _GLOBAL_FLAG_CHAIN + r"-C(?:" + _GAP + r"|$)"
)

# `RAW_DASH_C_RE` group index -> the quoting the path arrived in. Declared with
# the patterns because the group index IS the quoting form: any pattern fed to
# `_target_tokens` must expose these three alternatives in this order.
_DOUBLE_QUOTED, _SINGLE_QUOTED, _BARE = 1, 2, 3

# A `cd` only counts at a statement boundary, so `--foo=cd x` or a path ending in
# `cd` is never mistaken for the builtin. Moved here from commit_command when the
# `cd` pass stopped reading the quote-STRIPPED text: the boundary rule and the
# path-token rule belong with the reader that applies them.
#
# `[^\s;&|]+` excludes statement-boundary characters from the bare capture so
# `cd /tmp;` yields `/tmp`, and the quoted alternatives come FIRST so a quoted
# path is taken whole rather than truncated at its opening delimiter. The three
# alternatives mirror `RAW_DASH_C_RE` exactly — same order, same meaning — because
# `token_unreachable` judges both by group index.
_CD_BOUNDARY = r"(?:^|[\n;]|&&|\|\|)\s*"
RAW_CD_RE = re.compile(
    _CD_BOUNDARY + r"cd" + _GAP + r"""(?:"([^"]+)"|'([^']+)'|([^\s;&|]+))"""
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
# introduce any construct `token_unreachable` keys on ($, backtick, ~, glob),
# nor a quote, whitespace, or statement separator.
_ESCAPED_QUOTE_RE = re.compile(r"\\['\"]")
# Shared with `git_commits.strip_quoted` — see the ordering warning there. This
# site was always correct; the deleting twin was not, and one definition is what
# stops them diverging again.
_QUOTED_SPAN_RE = git_commits.QUOTED_SPAN_RE
_HEREDOC_SPAN_RE = re.compile(r"<<-?\s*'?(\w+)'?.*?\n.*?\1", re.DOTALL)
_MASK_FILL = "x"


def mask_data_spans(command: str) -> str:
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


# A recovered `-C` token must be followed by whitespace, a statement separator,
# or nothing at all. Anything else means the regex captured only the FIRST
# segment of a concatenation — `-C '/tmp/'"$WT"` — so the path as a whole was
# never read.
_TOKEN_TERMINATORS = " \t\r\n;&|"


def _target_tokens(
    command: str, pattern: re.Pattern[str], masked: str
) -> list[tuple[int, str, bool]]:
    """Every path token `pattern` finds, in command order.

    The one rule this module exists for, in one place: tokens are LOCATED on
    `masked` — so a `cd` or `-C` inside a commit message is not one — and READ
    from the raw `command` at the same offsets, because the mask replaced the path
    text with filler rather than deleting it.

    `masked` is a PARAMETER, not computed here, so one Bash command is masked once
    however many prefixes are scanned. That is not only a saving: it makes it
    structurally impossible for two passes over the same command to disagree about
    which text they read, which is the defect class this module was extracted for.

    `pattern` must expose the same three capture groups as `RAW_DASH_C_RE` —
    double-quoted, single-quoted, bare — because the group index IS the quoting
    form, and `token_unreachable` judges by it.

    Completeness is judged from `match.end()` — the end of the whole alternation,
    NOT the end of the capture group. The groups exclude the quote delimiters, so
    a group-relative read lands ON the closing quote and would mark every quoted
    token incomplete.
    """
    tokens: list[tuple[int, str, bool]] = []
    for match in pattern.finditer(masked):
        for group in (_DOUBLE_QUOTED, _SINGLE_QUOTED, _BARE):
            if match.group(group) is not None:
                start, end = match.span(group)
                after = command[match.end() : match.end() + 1]
                complete = after == "" or after in _TOKEN_TERMINATORS
                tokens.append((group, command[start:end], complete))
                break
    return tokens


def dash_c_tokens(
    command: str, masked: str | None = None
) -> list[tuple[int, str, bool]]:
    """Every git-global `-C` token, in command order.

    One list rather than a `search` per caller: all three `-C` readers share it,
    because when two of them read the path from different sources one refused
    nothing while the other probed the wrong repo.

    Pass `masked` when the caller already has `mask_data_spans(command)` — the
    `cd` pass in the same function does — so the mask is built once.
    """
    return _target_tokens(
        command, RAW_DASH_C_RE, mask_data_spans(command) if masked is None else masked
    )


def cd_tokens(command: str, masked: str | None = None) -> list[tuple[int, str, bool]]:
    """Every statement-leading `cd` token, in command order.

    Same shape and same rule as `dash_c_tokens`, and that sharing is the point:
    `cd` used to be read off the quote-STRIPPED text, where `strip_quoted` had
    already deleted the path — so `cd "/a real dir" && git commit` produced no
    candidate at all and the repo silently resolved to the hook's own cwd, exactly
    the bug already fixed for `-C`.

    Masking rather than stripping is what lets both properties hold at once: a
    quoted commit-message body is filler on the masked text (so a message that
    mentions `cd /tmp` still cannot retarget anything), while the surviving
    delimiters let the raw read recover a genuinely quoted literal path.
    """
    return _target_tokens(
        command, RAW_CD_RE, mask_data_spans(command) if masked is None else masked
    )


def token_unreachable(quoting: int, path: str) -> bool:
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
        # A backslash escape joins the next word into ONE path the shell hands
        # git (`/tmp/a\ dir`), while the capture stops at the backslash — the
        # same unread-remainder case as a concatenated quoting form, and a
        # likelier spelling of it, since user paths do contain spaces. Only
        # BARE: inside either quote the backslash stays literal, so git gets
        # what we see and aborts on its own.
        or "\\" in path
    )

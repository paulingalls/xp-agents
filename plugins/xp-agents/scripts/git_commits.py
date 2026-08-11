#!/usr/bin/env python3
"""Git command parsing — detects commit-producing git invocations
(commit, merge) for the pre-Bash review-cycle gate and post-Bash commit-
event recording. Tolerates global options like `git -C <path> commit`
and `git -c k=v commit` so agent-style invocations don't bypass detection.
"""

import re

# The gap between two shell tokens: whitespace, or a `\`-newline line
# continuation, which the shell joins away before git ever sees it. A plain
# `\s+` reads a WRAPPED invocation as no invocation at all — `git -C /p \<nl>
# commit` matched nothing — and every gate keyed on this detection (tier-1
# secret scan, staged lint, review cycle, branch guard, commit-event recording)
# then skipped the commit silently. Unlike the deliberate evasions the spike
# catalogues (`sh -c`, aliases, `$GIT`), wrapping is ordinary formatting.
TOKEN_GAP = r"(?:\s|\\\n)+"

# `git` followed by zero-or-more global options before the subcommand.
# Each option is `-X` (standalone) or `-X <value>` (paired). Covers `-C <path>`
# (the form agents adopt to avoid cd-poisoning Stop hooks), `-c <kv>`,
# `--git-dir=<path>`, `--work-tree=<path>`, `--paginate`, etc. Without this
# tolerance, those forms silently bypass subcommand detection: pre-tool gate
# skips review cycle, post-tool hook skips commit-event recording + marker
# reset, and `commits.get_code_files_for_review` misses unstaged tracked
# files for `git -C add` / `git -C commit -a`.
GIT_PREFIX = r"\bgit(?:" + TOKEN_GAP + r"-\S+(?:" + TOKEN_GAP + r"\S+)?)*" + TOKEN_GAP

# Lifted to module level so both uses of the commit/merge test share one
# spelling. This module's own docstrings already argue that two spellings of
# one rule is how the last bug (the GIT_PREFIX gap) survived — see TOKEN_GAP.
_COMMIT_OR_MERGE_RE = re.compile(GIT_PREFIX + r"(?:commit|merge)\b(?!-)")

# `merge --abort` / `merge --quit` UNWIND a merge; they produce no commit. The
# `(?!-)` lookahead cannot reject them — it is evaluated at the character after
# `merge`, a space here, so the plumbing guard (`merge-tree`) never fires for an
# argument form. Gating them is worse than a false block: an operator who cannot
# abort a conflicted merge reaches for `git reset --hard`, which discards the
# uncommitted work the abort would have preserved.
#
# `--continue` is deliberately absent: it FINISHES the merge and writes a
# commit, so it stays gated like any other commit-producing form. That is a
# recorded decision, not the lookahead's accident.
#
# Requiring the flag as the FIRST token after `merge` is exhaustive, not a
# narrowing: git itself rejects any companion argument (`git merge -q --abort`
# exits 129, `fatal: --abort expects no arguments`).
#
# Subtractive, not an early `return False`: this function scans the whole Bash
# command, so a bare early return would exempt
# `git commit -m x && git merge --abort` and disarm four gates on a real commit.
_MERGE_NON_COMMITTING_RE = re.compile(
    GIT_PREFIX + r"merge" + TOKEN_GAP + r"--(?:abort|quit)\b"
)


def strip_heredocs(command: str) -> str:
    """Remove heredoc bodies (`<<'DELIM'...DELIM` / `<<DELIM...DELIM`).

    Split out of `strip_quoted` so a caller that must keep quoted arguments can
    still drop heredoc BODIES. A heredoc body is prose the shell passes as data —
    a commit message, most often — and any scanner that reads it is reading what
    a command SAYS rather than what it does. `pre_tool_bash`'s branch-delete
    refusal needs exactly this half: it tokenizes the command with the quotes
    intact (a quoted branch name is a real argument), so it cannot use
    `strip_quoted`, but it must not see a message body either.
    """
    return re.sub(r"<<-?\s*'?(\w+)'?.*?\n.*?\1", "", command, flags=re.DOTALL)


# One quoted span, EITHER kind, matched in source order. The alternation is
# load-bearing and is not interchangeable with two sequential passes: stripping
# all `'...'` before all `"..."` lets an apostrophe inside a double-quoted
# argument pair with the next apostrophe anywhere and delete every operator
# between them. `pytest -q -k "it's" ; echo X "don't"` then scanned as though it
# held no `;` at all, so the exit-status gate accepted a command whose runner's
# failure it could not see, and close auto-merged a red suite (found by security
# review at sprint-128 close). Scanning left to right, the `"` opens first and
# `"it's"` is correctly one span.
#
# It also fails CLOSED on an odd quote count: an unterminated quote matches no
# span, so nothing is deleted and the operators stay visible to the caller.
QUOTED_SPAN_RE = re.compile(r"'[^']*'|\"[^\"]*\"")


def strip_quoted(command: str) -> str:
    """Remove quoted strings and heredocs to avoid matching inside arguments.

    Public so callers (bash_post_tool, and the `-C` presence predicates
    `commit_command.dash_c_unreachable` / `head_probe_target`) can share one
    pre-stripped scan target with `is_git_commit` instead of each re-stripping
    the command independently.

    `parse_effective_cwd` is deliberately NOT one of them any more: it reads
    paths off `mask_data_spans` instead, because a stripped scan had already
    DELETED the path it needed.

    Shares `QUOTED_SPAN_RE` with `dash_c_tokens.mask_data_spans`, which needs
    the same spans without moving any character's offset. Two spellings of one
    rule is how the ordering bug above survived: the offset-preserving twin was
    already correct while this one was not.
    """
    s = strip_heredocs(command)
    # Escaped quotes first: an unmasked `\"` would otherwise open or close a
    # span it is not part of.
    s = s.replace("\\'", "").replace('\\"', "")
    return QUOTED_SPAN_RE.sub("", s)


def is_git_commit(command: str, *, scan_target: str | None = None) -> bool:
    """Detect a commit-producing git command (commit or merge), not inside
    quoted arguments. The `(?!-)` lookahead rejects plumbing subcommands
    like `commit-tree` / `merge-tree`.

    `merge --abort` / `merge --quit` are exempted subtractively: the
    non-committing span is removed and the question re-asked, so an appended
    `&& git merge --abort` cannot disarm detection of a real `git commit`
    earlier in the same command. See `_MERGE_NON_COMMITTING_RE`.

    `scan_target` lets callers pass a pre-stripped command (via
    `strip_quoted`) so the same Bash invocation isn't quote-stripped
    twice when downstream functions also need it.
    """
    if scan_target is None:
        scan_target = strip_quoted(command)
    if not _COMMIT_OR_MERGE_RE.search(scan_target):
        return False
    remaining = _MERGE_NON_COMMITTING_RE.sub("", scan_target)
    return bool(_COMMIT_OR_MERGE_RE.search(remaining))

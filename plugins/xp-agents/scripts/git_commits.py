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


# One heredoc: the `<<DELIM` operator, the REST of the line that introduces it,
# the body, and the terminator. `rest` is captured because it is the one part of
# the span that is CODE — `2>&1 | tail -20`, `&& git branch -D story-1` and any
# other operator an agent writes on the line it opens a message on. Deleting it
# with the body made every one of them invisible: `git commit -F - <<'EOF' |
# tail -20` reached the exit-status gate as a bare `git commit -F -` and was
# allowed, and the same span hid a chained branch delete from its refusal.
#
# Either quoting of the delimiter, or none: `<<"EOF"` is as ordinary as `<<'EOF'`
# and left the BODY visible to every scanner routed through here, so a message
# mentioning a piped push read as one. The two quote characters are not required
# to match — a mismatched pair is not a form the shell accepts, so accepting it
# here costs nothing and enumerating the pairs buys nothing.
_HEREDOC_RE = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?(?P<rest>[^\n]*)\n.*?\1", re.DOTALL)


def strip_heredocs(command: str) -> str:
    """Remove heredoc BODIES, keeping the line that opened them (`<<'DELIM'
    ...DELIM` / `<<DELIM...DELIM`).

    Split out of `strip_quoted` so a caller that must keep quoted arguments can
    still drop heredoc BODIES. A heredoc body is prose the shell passes as data —
    a commit message, most often — and any scanner that reads it is reading what
    a command SAYS rather than what it does. `pre_tool_bash`'s branch-delete
    refusal needs exactly this half: it tokenizes the command with the quotes
    intact (a quoted branch name is a real argument), so it cannot use
    `strip_quoted`, but it must not see a message body either.
    """
    return _HEREDOC_RE.sub(lambda m: m.group("rest"), command)


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


def strip_quoted(command: str, *, placeholder: str = "") -> str:
    """Remove quoted strings and heredocs to avoid matching inside arguments.

    ``placeholder`` replaces each quoted span instead of deleting it, for the one
    caller that counts TOKENS rather than searching: deleting `"drop both"` from
    `git commit -m "drop both" a.py` leaves `-m` adjacent to the pathspec, which
    then reads as the message's own value. A plain letter, so it introduces no
    quote, separator or pattern character (`_QUOTED_TOKEN`).

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
    return QUOTED_SPAN_RE.sub(placeholder, s)


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


# Characters reachable without leaving the CURRENT shell command. A bare
# newline terminates one exactly as `;` does, and omitting it read `git commit
# -m x<newline>ls -la` as a stage-all. A `\`-newline is the one crossable form:
# the shell joins it away, as `TOKEN_GAP` also allows.
_ONE_COMMAND = r"(?:\\\n|[^;&|\n])*?"

# Whether a command stages EVERY tracked change, not merely some. The review
# gate needs the distinction because a "ghost" — a deletion sitting unstaged in
# the working tree — stops being one the moment the command about to run stages
# it. `git add -A` turns three unstaged deletions into three code files the
# commit removes; `git add notes.md` leaves them ghosts.
#
# `_ONE_COMMAND` bounds each arm, so a trailing `&& git add -A` cannot vouch for
# an earlier narrow `git add`. Callers pass a quote-stripped scan target, so
# `git commit -m 'add -A everywhere'` reads as the message it is.
#
# Short forms match as a CLUSTER, because `git add -Av` and `git commit -qa`
# stage everything too. `(?<!\S)` pins the cluster to a token start: without it
# the `-a` inside `--amend` matches, and `--amend` stages nothing new.
#
# The judgement leans YES: a false yes costs one extra review, a false no is a
# gate gone silent on deleted code. So `-u` counts (a ghost is a tracked
# deletion by construction, and untracked files cannot be ghosts), and so do
# `git add .` and `git add -u src/`, which name one subtree, not the tree.
_STAGES_ALL_RE = re.compile(
    GIT_PREFIX
    + r"(?:add\b"
    + _ONE_COMMAND
    + r"(?:(?<!\S)-(?!-)[A-Za-z]*[Au]|(?<!\S)--(?:all|update)\b"
    + r"|(?<!\S)\.(?=\s|$))"
    + r"|commit\b"
    + _ONE_COMMAND
    + r"(?:(?<!\S)--all\b|(?<!\S)-(?!-)[A-Za-z]*a))"
)


def stages_all_tracked_changes(command: str, *, scan_target: str | None = None) -> bool:
    """Does this command stage every tracked change, deletions included?

    Answers the one question `commits.get_code_files_for_review` cannot settle
    from the working tree alone: whether an unstaged deletion is about to become
    part of the commit. `_STAGES_ALL_RE` says which forms count and which way
    the judgement leans.

    `scan_target` shares one `strip_quoted` pass with `is_git_commit`, as that
    function's own parameter does.
    """
    if scan_target is None:
        scan_target = strip_quoted(command)
    return bool(_STAGES_ALL_RE.search(scan_target))


# Any `git add`, however narrow. On the quote-STRIPPED command like every other
# predicate here: the raw scan this replaced matched the `git add` inside
# `git commit -m "git add -A"` and widened the review scan for a message.
_ADD_RE = re.compile(GIT_PREFIX + r"add\b")


def stages_a_path(command: str, *, scan_target: str | None = None) -> bool:
    """Does this command stage anything at all — a narrow pathspec included?

    A DIFFERENT question from `stages_all_tracked_changes`, and the two must not
    collapse: this one widens the review scan to the whole unstaged diff, which
    over-counts a `git add notes.md` on purpose because a wider set BLOCKS,
    while that one decides whether an unstaged deletion is part of the commit.
    A narrow add answers YES here and NO there.
    """
    if scan_target is None:
        scan_target = strip_quoted(command)
    return bool(_ADD_RE.search(scan_target))


# `git commit` on its own — not the commit-or-merge pair above, which answers
# "does this produce a commit". This asks about the commit's ARGUMENTS, and a
# merge has no pathspec form.
_COMMIT_RE = re.compile(GIT_PREFIX + r"commit\b(?!-)")

# The rest of the ONE command a match sits in. `_ONE_COMMAND` is lazy, so the
# lookahead is what carries it to the next statement boundary; sharing that span
# rather than respelling it greedily keeps one definition of "this command".
_COMMAND_TAIL_RE = re.compile(_ONE_COMMAND + r"(?=$|[;&|\n])")

# Commit options whose value is a SEPARATE token, so what follows one is not a
# pathspec. Deliberately SHORT: an option missing here makes its value read as a
# path, which counts one extra file toward a review, while one wrongly listed
# EATS a real pathspec and takes the gate silent. Hence no OPTIONAL-argument
# forms (`-u`, `-S`, `--cleanup`): git requires those values to be ATTACHED, so
# the next token really is a path.
_COMMIT_VALUE_OPTIONS = frozenset({"-m", "-F", "-C", "-c", "-t", "--message", "--file"})

_QUOTED_TOKEN = "x"


def commit_names_a_pathspec(command: str) -> bool:
    """Does a `git commit` here name PATHS rather than committing the index?

    `git commit <pathspec>` commits the WORKING TREE contents of those paths,
    index or no index — an unstaged deletion included. So the ghost rule in
    `commits._unstaged_worktree_deletions` ("every deletion a commit makes is
    gone from the index too") is false for this one form, and subtracting those
    deletions took the review gate to zero code files on a commit removing two.
    Measured against real git in test_review_ghosts.py.

    Leans YES exactly as `stages_all_tracked_changes` does: an argument this
    cannot place as an option's value reads as a path, because one extra review
    beats a gate gone quiet.

    No `scan_target`: this walk needs quoted spans MASKED rather than deleted,
    so it cannot share the pre-stripped target its siblings pass round.
    """
    target = strip_quoted(command, placeholder=_QUOTED_TOKEN)
    for match in _COMMIT_RE.finditer(target):
        tail = _COMMAND_TAIL_RE.match(target, match.end())
        expects_value = False
        for token in (tail.group() if tail else "").split():
            if expects_value:
                expects_value = False
            elif not token.startswith("-"):
                return True
            else:
                expects_value = token in _COMMIT_VALUE_OPTIONS
    return False


def absorbs_unstaged_changes(command: str, *, scan_target: str | None = None) -> bool:
    """Will this command make unstaged tracked changes part of the commit?

    ONE spelling of the question `commits.get_code_files_for_review` asks twice
    — once to widen its scan to unstaged changes, once to decide whether an
    unstaged deletion is a ghost. Two spellings is how `commit -q -a` slipped
    past that gate, and how a pathspec commit's deletions were dropped after it.

    `scan_target` reaches the stage-all leg only, for the caller sharing one
    `strip_quoted` pass; the pathspec leg masks its own, as it documents.
    """
    return stages_all_tracked_changes(
        command, scan_target=scan_target
    ) or commit_names_a_pathspec(command)

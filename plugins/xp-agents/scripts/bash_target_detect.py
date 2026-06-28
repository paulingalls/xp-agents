#!/usr/bin/env python3
"""Heuristic file-modification detection for Bash commands.

Extracted from pre_tool_bash.py to keep that file under the 500-line cap.
Bash parsing is fundamentally fragile (it's not a context-free grammar);
this module is best-effort coordination-guard, not a security boundary.
Sound when: tokens look like normal POSIX. Unsound (returns empty / over-
or under-includes) when: exotic shell expansions, eval-style indirection,
or escapes the tokenizer can't follow. The coordination gate is a courtesy
that catches the common cases.

Uses shlex tokenization (stdlib) for quote/space handling, plus targeted
recursion into `<shell> -c <body>` invocations and skip-over for heredoc
bodies — the cases pure shlex gets wrong on its own.
"""

import re
import shlex

# Per-command positional-arg specs. "all" = every positional; "last" = last
# positional only; "rest" = all but last; int N = 0-indexed Nth positional.
_POS_ALL = "all"
_POS_LAST = "last"

_FILE_MODIFY_COMMANDS: dict[str, tuple[str | int, ...]] = {
    # `mv src1 src2 ... destdir` — sources are removed; dest written. Every
    # arg is touched from the coordination perspective.
    "mv": (_POS_ALL,),
    # `cp src1 src2 ... destdir` — sources read-only; only dest modified.
    "cp": (_POS_LAST,),
    # `tee f1 f2 ... fn` — writes stdout to every listed file.
    "tee": (_POS_ALL,),
    # `sed -i [...] LASTARG` — only LASTARG when in-place flag is present.
    # See _has_sed_in_place for the in-place detection (handles -i, --in-place,
    # --in-place=<suffix>).
    "sed": (_POS_LAST,),
}

# Bash redirect operators that write to the following token. `2>` writes
# stderr to a file (still a write for coordination); `<` is read-only and
# intentionally NOT in the set. `_filter_target` drops /dev/* targets to
# avoid the `cmd 2> /dev/null` false-positive.
_REDIRECT_OPERATORS = ("&>>", ">>", "&>", "2>>", "2>", "1>", ">")

# Bash control operators that end a command's positional-arg run.
_COMMAND_BOUNDARIES = {"&&", "||", ";", "|", "&"}

# Shells whose `-c <body>` argument is itself a bash command to inspect.
_SHELL_DASH_C = {"bash", "sh", "zsh", "fish"}

# Heredoc start: `<<EOF`, `<<-EOF`, `<<'EOF'`, `<<"EOF"`. shlex strips quotes
# from the delimiter so we match the unquoted form here.
_HEREDOC_START_RE = re.compile(r"^<<-?(.+)$")


def _filter_target(t: str) -> bool:
    """Drop tokens that aren't real claimable paths (/dev/null, /dev/stderr,
    flags, empty, '-' for stdin/stdout)."""
    if not t or t.startswith("-"):
        return False
    return not t.startswith("/dev/")


def _has_sed_in_place(args: list[str]) -> bool:
    """True when sed's args include any in-place flag form: -i, -iEXT,
    --in-place, --in-place=EXT."""
    for a in args:
        if a == "--in-place" or a.startswith("--in-place="):
            return True
        if a.startswith("-i"):
            return True
    return False


def _resolve_positions(spec: tuple[str | int, ...], positional: list[str]) -> list[str]:
    """Map a position-spec to the actual positional tokens it picks out."""
    out: list[str] = []
    for pos in spec:
        if pos == _POS_ALL:
            out.extend(positional)
        elif pos == _POS_LAST and positional:
            out.append(positional[-1])
        elif isinstance(pos, int) and 0 <= pos < len(positional):
            out.append(positional[pos])
    return out


def _walk_tokens(tokens: list[str], depth: int = 0) -> list[str]:
    """Walk a tokenized command list and collect file-modify targets.

    Recurses into `<shell> -c <body>` invocations (depth-bounded so a
    pathological nested-quoting bomb can't loop forever).
    """
    if depth > 5:
        return []

    targets: list[str] = []
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]

        # Heredoc body skip: `cmd <<EOF ... EOF`. shlex tokenizes the body
        # as ordinary tokens; skip from <<DELIM through the matching DELIM.
        m = _HEREDOC_START_RE.match(tok)
        if m:
            delim = m.group(1)
            i += 1
            while i < n and tokens[i] != delim:
                i += 1
            if i < n:
                i += 1  # consume delimiter
            continue

        # Standalone redirect operator: `> file`, `>> file`, `2> file`, etc.
        if tok in _REDIRECT_OPERATORS and i + 1 < n:
            targets.append(tokens[i + 1])
            i += 2
            continue
        # Inline redirect: `>file`, `>>file`, `2>file`. Strip longest match.
        stripped = False
        for op in _REDIRECT_OPERATORS:
            if tok.startswith(op) and len(tok) > len(op):
                targets.append(tok[len(op) :])
                stripped = True
                break
        if stripped:
            i += 1
            continue

        # `<shell> -c <body>` — re-tokenize the body and recurse.
        if tok in _SHELL_DASH_C and i + 2 < n and tokens[i + 1] == "-c":
            body = tokens[i + 2]
            try:
                body_tokens = shlex.split(body, posix=True, comments=False)
            except ValueError:
                body_tokens = []
            targets.extend(_walk_tokens(body_tokens, depth=depth + 1))
            i += 3
            continue

        # Command-form: mv/cp/tee/sed. Collect positional args until next
        # boundary, strip flags, pick the configured positions.
        if tok in _FILE_MODIFY_COMMANDS:
            cmd_name = tok
            j = i + 1
            args: list[str] = []
            while j < n and tokens[j] not in _COMMAND_BOUNDARIES:
                args.append(tokens[j])
                j += 1
            if cmd_name == "sed" and not _has_sed_in_place(args):
                i = j
                continue
            positional = [a for a in args if not a.startswith("-")]
            spec = _FILE_MODIFY_COMMANDS[cmd_name]
            targets.extend(_resolve_positions(spec, positional))
            i = j
            continue

        i += 1

    return targets


# Cheap pre-filter: a command containing none of these substrings cannot
# possibly carry a file-modification target the walker would find. Skipping
# shlex tokenization on those (the supermajority of Bash calls: ls, grep,
# pytest, git status, find, ...) is the highest-leverage hot-path savings.
_FAST_PATH_MARKERS = ("mv", "cp", "tee", "sed", ">")


def detect_bash_target_files(command: str) -> list[str]:
    """Best-effort extraction of files a Bash command might modify.

    Handles:
    - Quoted paths with spaces (shlex)
    - Multi-arg mv/cp/tee (proper destination positions)
    - sed -i AND sed --in-place
    - bash/sh/zsh -c '<body>' (recursive walk)
    - cat <<EOF...EOF heredoc bodies (skipped)
    - >, >>, 2>, &>, 1>, 2>>, &>> redirect operators
    - /dev/* targets filtered (can't be claimed in coordination)

    Returns [] on malformed quoting/escapes (the coordination gate is a
    courtesy; failing-open lets the user's command execute, and the next
    pre-flight will catch a real conflict if one matters).
    """
    if not any(marker in command for marker in _FAST_PATH_MARKERS):
        return []
    try:
        tokens = shlex.split(command, posix=True, comments=False)
    except ValueError:
        return []
    targets = _walk_tokens(tokens)
    return [t for t in targets if _filter_target(t)]

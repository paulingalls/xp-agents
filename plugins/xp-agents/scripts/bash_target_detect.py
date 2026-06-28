#!/usr/bin/env python3
"""Heuristic file-modification detection for Bash commands.

Extracted from pre_tool_bash.py to keep that file under the 500-line cap
(CLAUDE.md `Keep files small and focused`). The single consumer
(pre_tool_bash.run) imports `detect_bash_target_files`; tests live in
tests/hooks/test_pre_tool_bash.py and test directly against this module.

Uses shlex tokenization (stdlib) instead of regex so quoted paths with
spaces are captured intact, and heredoc / `$(subshell)` blobs come back
as single tokens whose contents the walker never enters.
"""

import shlex

# Commands whose argument positions identify a file the command will modify.
# Tuple values are 0-indexed positions in the positional-arg list (after flags
# are stripped); -1 means "last positional arg".
_FILE_MODIFY_COMMANDS: dict[str, tuple[int, ...]] = {
    "mv": (0, 1),  # mv SOURCE DEST — both touched (source removed, dest written)
    "cp": (1,),  # cp SOURCE DEST — only DEST is overwritten
    "tee": (0,),  # tee FILE [...] — first file arg
    "sed": (-1,),  # sed -i [...] LASTARG — only when -i is present
}

# Bash redirect operators that write to the following token. `2>` writes
# stderr to a file (still a write for coordination purposes); `<` is read-only
# and intentionally NOT in the set. `_filter_target` drops /dev/* targets to
# avoid the `cmd 2> /dev/null` false-positive.
_REDIRECT_OPERATORS = ("&>>", ">>", "&>", "2>>", "2>", "1>", ">")

# Bash control operators that end a command's positional-arg run.
_COMMAND_BOUNDARIES = {"&&", "||", ";", "|", "&"}


def _filter_target(t: str) -> bool:
    """Drop tokens that aren't real claimable paths (/dev/null, /dev/stderr,
    flags, empty, '-' for stdin/stdout)."""
    if not t or t.startswith("-"):
        return False
    return not t.startswith("/dev/")


def detect_bash_target_files(command: str) -> list[str]:
    """Best-effort extraction of files a Bash command might modify.

    Uses shlex tokenization so:
    - Quoted paths with spaces (`"/dir with space/foo.py"`) are one token.
    - Heredoc bodies and `$(subshell)` blobs become single quoted tokens —
      `mv` inside them is invisible to the walker (no false-positive blocks
      on commit messages that reference past mv work).
    - Redirect operators (`>`, `>>`, `2>`, `&>`, `1>`, `2>>`, `&>>`) are
      tokenized and their target captured.
    - `/dev/null` etc. are filtered (not claimable in coordination).
    """
    try:
        tokens = shlex.split(command, posix=True, comments=False)
    except ValueError:
        # Malformed quoting/escapes — fall back silently. The conflict gate
        # is a coordination hint, not a security boundary, so failing open
        # here is acceptable; the user's command will execute as Bash sees it.
        return []

    targets: list[str] = []
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]

        # Standalone redirect operator: `> file`, `>> file`, `2> file`, etc.
        if tok in _REDIRECT_OPERATORS and i + 1 < n:
            targets.append(tokens[i + 1])
            i += 2
            continue
        # Inline redirect: `>file`, `>>file`, `2>file` (no space between op
        # and target). Strip the longest matching operator prefix.
        stripped = False
        for op in _REDIRECT_OPERATORS:
            if tok.startswith(op) and len(tok) > len(op):
                targets.append(tok[len(op) :])
                stripped = True
                break
        if stripped:
            i += 1
            continue

        # Command-form: mv/cp/tee/sed. Collect positional args until the next
        # boundary, strip flags, pick the configured positions.
        if tok in _FILE_MODIFY_COMMANDS:
            cmd_name = tok
            j = i + 1
            args: list[str] = []
            while j < n and tokens[j] not in _COMMAND_BOUNDARIES:
                args.append(tokens[j])
                j += 1
            # sed special-case: only -i variants are in-place modifications.
            if cmd_name == "sed" and not any(a.startswith("-i") for a in args):
                i = j
                continue
            positional = [a for a in args if not a.startswith("-")]
            for pos in _FILE_MODIFY_COMMANDS[cmd_name]:
                if pos == -1 and positional:
                    targets.append(positional[-1])
                elif 0 <= pos < len(positional):
                    targets.append(positional[pos])
            i = j
            continue

        i += 1

    return [t for t in targets if _filter_target(t)]

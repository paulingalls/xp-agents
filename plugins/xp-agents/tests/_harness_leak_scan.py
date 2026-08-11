#!/usr/bin/env python3
"""Find harness names in shipped PROSE, ignoring harness names in identifiers.

Shipped prose is injected into agent context on every harness, so text naming
one of them as though it were the only one is wrong for half its readers. The
measured instance: a shared preload told the user to look in one harness's
instruction file for the test command, and the other harness reads a different
file entirely.

The whole difficulty is that a harness name is usually NOT a leak. Measured
across shipped `.md` and `.sh`, 216 of ~230 occurrences are `${CLAUDE_PLUGIN_ROOT}`
— the name of an environment variable the harness defines, which is an interface,
not a claim about who is running. Six more are real paths. Excusing those one by
one would need a couple of hundred markers, and a guardrail with a couple of
hundred markers is noise that gets deleted. So identifiers are excluded
STRUCTURALLY here, and only what remains — prose — is judged.

`.md` and `.sh` need different prose models, and using one for both is how this
scanner would go silently useless. A shell file has no fenced blocks and is all
code, so a Markdown model would blank it out entirely — hiding the one measured
leak this exists to catch. In shell, the prose is what reaches a human: comment
bodies and the text inside `echo`/`printf` literals.
"""

import re
from pathlib import Path

# The harnesses this plugin targets. Word-boundary matched so `claude` does not
# fire inside a longer identifier that survived the exclusions.
HARNESS_NAMES = ("claude", "codex")
_HARNESS_RE = re.compile(r"\b(" + "|".join(HARNESS_NAMES) + r")\b", re.IGNORECASE)

# An environment variable the harness sets. Its NAME is an interface both
# harnesses' hooks receive; rewriting it would break the substitution.
_ENV_VAR = re.compile(r"\$\{?[A-Z_]*(?:CLAUDE|CODEX)[A-Z_]*\}?")

# Paths that exist under these names on disk. `.claude-plugin/plugin.json` is a
# real file; calling it something else would name nothing.
_PATHY = re.compile(r"[~.]?/?\.(?:claude|codex)[\w./-]*")

# Fenced blocks and inline spans. A command a reader types carries the harness's
# own binary name, and making it generic would make the instruction wrong.
#
# The opening run's LENGTH is captured because a closing fence must be at least
# as long as its opener and carry no info string. Toggling a boolean on every
# fence line instead reads the inner ``` of a four-backtick block as a close and
# its close as a new opening — from there every remaining line of the file scans
# as fenced, and the pin reports zero offenders over prose it never read.
_FENCE = re.compile(r"^\s*(?P<ticks>`{3,})(?P<info>.*)$")
_CODE_SPAN = re.compile(r"`[^`]*`")

# The escape hatch, mirroring the sibling prose pin's `lang-ok` shape with its
# own keyword so the two guardrails cannot silence each other. A reason that is
# absent or blank reads as NO hatch — an excuse that says nothing is not one.
#
# The reason runs to the HTML comment's close, or to the end of the line. It was
# once a class excluding `-`, which read every reason OPENING with a CLI flag as
# blank — and this branch's prose names `--disable unified_exec` and
# `--dangerously-bypass-hook-trust` routinely, so the natural excuse silently
# failed the pin and the natural repair was deleting accurate prose.
_HATCH_RE = re.compile(r"harness-ok:\s*(?P<reason>.*?)\s*(?:-->|$)")

# Shell prose: what a human reads. Comment bodies, and the insides of echo and
# printf literals.
#
# EVERY quoted run after the emitting word counts, not just the first. The
# tree's dominant printf shape is `printf '%s\n' "<payload>"`, where the first
# quoted run is the format string — a rule reading one run per line would scan
# `%s\n` and never the sentence beside it, which is the exact shape of the leak
# this scanner exists to catch.
_SH_COMMENT = re.compile(r"#(?P<body>.*)$")
_SH_EMITTER = re.compile(r"\b(?:echo|printf)\b")
_SH_QUOTED = re.compile(r"""(["'])(?P<body>.*?)\1""")


def shipped_prose_files(plugin_root: Path) -> list[Path]:
    """Every shipped prose file the pin judges.

    Tests and the throwaway spike rig are excluded: neither is shipped, and the
    spike's whole purpose was to name one harness concretely.
    """
    found: list[Path] = []
    for suffix in (".md", ".sh"):
        for path in plugin_root.rglob(f"*{suffix}"):
            if "tests" in path.parts or "spike" in path.parts:
                continue
            found.append(path)
    return sorted(found)


def _strip_identifiers(text: str) -> str:
    """Blank out every identifier class, leaving prose in place."""
    for pattern in (_ENV_VAR, _PATHY, _CODE_SPAN):
        text = pattern.sub(" ", text)
    return text


def _markdown_scan(text: str) -> tuple[list[tuple[int, str]], int | None]:
    """Prose lines, plus the line of a fence left OPEN at end of file.

    Fenced blocks are dropped rather than blanked line-by-line because a fence
    can open on one line and close many lines later; tracking the block is what
    keeps a command inside it from being read as prose.

    A fence closes only on a run at least as long as its opener and carrying no
    info string — the rule the format itself uses, and what lets a four-backtick
    block quote inner three-backtick ones without the inner run ending it.

    The open-fence line is reported rather than swallowed: a file whose fences
    do not balance scans as prose up to the stray marker and as code forever
    after, which is a guardrail that reads nothing while reporting nothing.
    """
    out: list[tuple[int, str]] = []
    opened_at = 0
    open_len = 0
    for number, line in enumerate(text.splitlines(), 1):
        fence = _FENCE.match(line)
        if fence:
            ticks = len(fence.group("ticks"))
            if not open_len:
                open_len, opened_at = ticks, number
                continue
            if ticks >= open_len and not fence.group("info").strip():
                open_len = 0
            continue
        if open_len:
            continue
        out.append((number, _strip_identifiers(line)))
    return out, opened_at if open_len else None


def markdown_prose(text: str) -> list[tuple[int, str]]:
    """(1-based line, prose) for a Markdown file, fenced blocks removed."""
    return _markdown_scan(text)[0]


def unterminated_fence(text: str) -> int | None:
    """1-based line of a Markdown fence that never closes, or None."""
    return _markdown_scan(text)[1]


def _echoed_bodies(line: str) -> list[str]:
    """Every quoted run on *line* from the first `echo`/`printf` onward."""
    emitter = _SH_EMITTER.search(line)
    if not emitter:
        return []
    return [m.group("body") for m in _SH_QUOTED.finditer(line, emitter.end())]


def shell_prose(text: str) -> list[tuple[int, str]]:
    """(1-based line, prose) for a shell file.

    Only comment bodies and echoed/printed literals count. Everything else —
    variable names, paths, command words — is code that a reader does not read
    as English.
    """
    out: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), 1):
        pieces = _echoed_bodies(line)
        comment = _SH_COMMENT.search(line)
        if comment:
            pieces.append(comment.group("body"))
        if pieces:
            out.append((number, _strip_identifiers(" ".join(pieces))))
    return out


def prose_lines(text: str, suffix: str) -> list[tuple[int, str]]:
    """Prose for a shipped file, chosen by extension."""
    if suffix == ".md":
        return markdown_prose(text)
    if suffix == ".sh":
        return shell_prose(text)
    raise ValueError(f"no prose model for {suffix!r}")


def hatched(lines: list[str], index: int) -> bool:
    """True when the line, or the one above it, carries a non-empty hatch.

    Same two-line window as the sibling pin: a marker often reads better above
    the sentence it excuses than trailing it.
    """
    for candidate in (lines[index], lines[index - 1] if index else ""):
        match = _HATCH_RE.search(candidate)
        if match and match.group("reason").strip():
            return True
    return False


def find_harness_mentions(text: str, suffix: str) -> list[tuple[int, str]]:
    """Every (1-based line, harness name) where PROSE names a harness.

    Hatched lines are skipped, not reported — the hatch is read from the RAW
    line, because the marker itself is a comment and the prose models would
    otherwise have stripped it before it could be seen.
    """
    raw = text.splitlines()
    found: list[tuple[int, str]] = []
    for number, prose in prose_lines(text, suffix):
        match = _HARNESS_RE.search(prose)
        if not match:
            continue
        if hatched(raw, number - 1):
            continue
        found.append((number, match.group(1).lower()))
    return found


def hatches_without_mentions(text: str, suffix: str) -> list[int]:
    """Lines carrying a hatch that excuses nothing.

    A marker lives on the line it excuses, so deleting the sentence deletes the
    marker with it — the drift a separate registry has to police cannot happen
    here. This reports the residue: a marker left behind after its prose was
    reworded, which is the only way an at-site excuse can go stale.
    """
    raw = text.splitlines()
    prose_by_line = dict(prose_lines(text, suffix))
    stale: list[int] = []
    for index, line in enumerate(raw):
        match = _HATCH_RE.search(line)
        if not match or not match.group("reason").strip():
            continue
        window = (index + 1, index + 2)  # the hatch covers its line and the next
        if not any(_HARNESS_RE.search(prose_by_line.get(n, "")) for n in window):
            stale.append(index + 1)
    return stale

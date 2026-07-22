"""Markdown parsing helpers shared across integration tests.

Scaffold's `frontmatter_body()` (tests/scaffold/_helpers.py) is a
deliberate sibling: the scaffold suite has its own conftest path setup
and stays isolated rather than cross-import.
"""

import re

# Language-specific tokens and plugin-internal surface names that must not
# appear in shipped agent/skill prose — the plugin ships to projects in any
# language, and this repo is a test fixture for it, not its vocabulary.
#
# USAGE CONTRACT — scan the RAW section text, never a `.lower()` copy. The
# tuple is deliberately mixed-case (`ACCEPT_IN_FLIGHT`, ` LOC`), so a scanner
# that lowercases its section first can never match those members and the
# guard silently degrades to an inert check that passes on a real leak.
#
# tests/skills/test_assign_tier_prose.py deliberately does NOT use this tuple:
# the assign skill prose names the plugin's own `.py`/`.js` script files, which
# is permitted (a leak is a predicate on a USER path, not on the plugin's own),
# so it keeps a narrower hand-rolled list.
#
# `def `/`class `/`function ` are declaration keywords, but they are also
# ordinary English ("its enclosing function", "a class of errors"). A hit on
# one of those three may be a FALSE POSITIVE — reword the prose (a comma or a
# possessive is usually enough), do not delete the member: removing it is what
# lets a real language leak back in. The mixed-case members are matched raw for
# the same reason, so both casings of a mixed-case name are listed explicitly.
PROJECT_AGNOSTIC_FORBIDDEN_VOCAB: tuple[str, ...] = (
    ".py",
    ".ts",
    ".js",
    ".go",
    ".rs",
    "def ",
    "class ",
    "function ",
    " LOC",
    "lines of code",
    "ACCEPT_IN_FLIGHT",
    "accept_in_flight",
    "close_cycle_stop_gate",
    "simplify_done",
    "quality_review_done",
    "assign-pending",
    "review_cycle_done",
)


def _split_frontmatter_body(text: str) -> tuple[str, str]:
    """Split a markdown doc into (frontmatter, body) on the closing `---` fence.

    Returns ("", text) when the doc has no YAML frontmatter — caller can
    then grep the whole text without a frontmatter/body distinction.
    """
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not match:
        return "", text
    return match.group(1), match.group(2)


def _slice(body: str, start_marker: str, end_markers: tuple[str, ...]) -> str:
    """Return the body region from start_marker up to the first end_marker."""
    start = body.index(start_marker)
    rest = body[start + len(start_marker) :]
    ends = [rest.index(m) for m in end_markers if m in rest]
    return rest[: min(ends)] if ends else rest

"""Markdown parsing helpers shared across integration tests.

Scaffold's `frontmatter_body()` (tests/scaffold/_helpers.py) is a
deliberate sibling: the scaffold suite has its own conftest path setup
and stays isolated rather than cross-import.
"""

import re
import unittest

# Language-specific tokens and plugin-internal surface names that must not
# appear in shipped agent/skill prose — the plugin ships to projects in any
# language, and this repo is a test fixture for it, not its vocabulary.
#
# USAGE CONTRACT — scan the RAW text, never a `.lower()` copy. Both tuples are
# deliberately mixed-case (`Docstring`, `ACCEPT_IN_FLIGHT`, ` LOC`), so a scanner
# that lowercases its input first can never match those members and the guard
# silently degrades to an inert check that passes on a real leak. Both casings of
# a mixed-case name are listed explicitly for the same reason.
#
# Split by SCOPE, not by content kind. Scope is the fact whose loss let a second
# copy of this vocabulary grow in the routing pin: that pin scans EVERY shipped
# prose file, so it can only ban tokens with no legitimate use anywhere, while
# `assert_project_agnostic` runs on a selected SECTION and can ban more. A
# content-kind split would also misfile ` LOC` and `lines of code`, which are
# neither paths nor keywords.

# Bannable across every shipped prose file — no member has a legitimate use in
# one. `test_prose_routing_pin.py`'s vocabulary leg IS that ban, and the only
# check of this category's scope: mis-filing a legitimately-used token here
# reddens that leg, whose failure message names both readings (leaked prose, or
# a token filed in the wrong category).
CORPUS_WIDE_FORBIDDEN: tuple[str, ...] = (
    "docstring",
    "Docstring",
    '"""',
)

# Legitimate SOMEWHERE in shipped prose, so these may only be applied to a
# selected section: the plugin naming its own script files is permitted — a leak
# is a predicate on a USER path, not on the plugin's own.
#
# `def `/`class `/`function ` are declaration keywords, but they are also
# ordinary English ("its enclosing function", "a class of errors"). A hit on one
# of those three may be a FALSE POSITIVE — reword the prose (a comma or a
# possessive is usually enough), do not delete the member: removing it is what
# lets a real language leak back in.
SECTION_SCOPED_FORBIDDEN: tuple[str, ...] = (
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

# The section-scoped guard applies BOTH categories: a token safe to ban
# tree-wide is a fortiori safe to ban inside one section.
#
# tests/skills/test_assign_tier_prose.py deliberately does NOT use this tuple:
# the assign skill prose names the plugin's own `.py`/`.js` script files, so it
# keeps a narrower hand-rolled list.
PROJECT_AGNOSTIC_FORBIDDEN_VOCAB: tuple[str, ...] = (
    CORPUS_WIDE_FORBIDDEN + SECTION_SCOPED_FORBIDDEN
)

# Members whose casing is load-bearing. Lives beside the vocabulary it
# describes because two suites need it: the helper's own contract pin
# (test_md_helpers.py) and the §1 mutation proof in the agent-prose suites.
MIXED_CASE_VOCAB_MEMBERS: tuple[str, ...] = ("ACCEPT_IN_FLIGHT", " LOC")


def assert_project_agnostic(
    testcase: unittest.TestCase,
    section: str,
    label: str,
) -> None:
    """Assert a shipped prose section carries none of the forbidden vocabulary.

    THE CONTRACT, and why it lives here: `section` is scanned RAW. Never pass a
    `.lower()` copy, and never lowercase inside this function — the tuple is
    deliberately mixed-case, so a lowercasing scan silently stops matching some
    members and degrades to an inert check that passes on a real leak. That rule
    used to survive only as a comment every call site had to remember, and two of
    the four sites had already forgotten it. Centralizing the loop centralizes
    the rule; `TestProjectAgnosticAssertHelper` pins it.

    A hit on `def `/`class `/`function ` may be a false positive (they are
    ordinary English too) — reword the prose, do not drop the member. See the
    tuple's comment above.

    `label` names the scanned region for the failure message (e.g. "Section 1c").

    Callers that also want a single-language check (`assertNotIn("python",
    section.lower(), ...)`) keep it at the call site: only two of the four sites
    have one, and folding it in here would silently add an assertion to the
    other two.
    """
    for token in PROJECT_AGNOSTIC_FORBIDDEN_VOCAB:
        testcase.assertNotIn(
            token,
            section,
            f"{label} must not contain language-specific or plugin-internal "
            f"token: {token!r}",
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
    """Return the body region from start_marker up to the first end_marker.

    Pass an empty `end_markers` to mean "to EOF" deliberately. A NON-empty
    tuple that matches nothing raises: story-004 found a pin whose end marker
    had drifted out of the skill ("Write the matching token" vs the actual
    "Write the chosen token"), so its slice silently ran to EOF and the caller's
    cap was enforced over the rest of the file. It passed by luck. Failing loud
    here is what stops the next drifted marker from reading as green.
    """
    start = body.index(start_marker)
    rest = body[start + len(start_marker) :]
    ends = [rest.index(m) for m in end_markers if m in rest]
    if end_markers and not ends:
        raise AssertionError(
            f"slice after {start_marker!r} found none of its end markers "
            f"{end_markers!r} — the region would silently run to EOF. Fix the "
            "marker, or pass () if slicing to EOF is intended."
        )
    return rest[: min(ends)] if ends else rest

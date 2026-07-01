"""Markdown parsing helpers shared across integration tests.

Scaffold's `frontmatter_body()` (tests/scaffold/_helpers.py) is a
deliberate sibling: the scaffold suite has its own conftest path setup
and stays isolated rather than cross-import.
"""

import re


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

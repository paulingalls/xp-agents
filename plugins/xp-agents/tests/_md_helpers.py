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

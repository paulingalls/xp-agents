#!/usr/bin/env python3
"""Boundary-aware matching for the project-agnostic vocabulary bans.

Shared by `_md_helpers.assert_project_agnostic` and `_routing_detect`'s two
finders, so a member's genuine-use rule is defined once and applied the same
way on both sides. No registry import here — token and text are arguments —
which is what keeps this module usable by both without making them mutually
dependent (`_routing_detect` already imports `_md_helpers`).

A member matches only where its own alphanumeric edges are not extended by
whatever surrounds it: `.rs` must not count `.rspec`, `docstring` must not
count `docstrings`. Underscore is deliberately excluded from the guard class
— with it included, `accept_in_flight_marker` would escape a ban on
`accept_in_flight`, and the same shape hides every other plugin-internal
`snake_case` name behind any suffixed variant.
"""

import re

_GUARD_CLASS = "A-Za-z0-9"


def _pattern(token: str) -> re.Pattern[str]:
    body = re.escape(token)
    if token[0].isalnum():
        body = f"(?<![{_GUARD_CLASS}])" + body
    if token[-1].isalnum():
        body = body + f"(?![{_GUARD_CLASS}])"
    return re.compile(body)


def token_occurs(token: str, text: str) -> bool:
    """Whether *token* occurs in *text* as a genuine use, not merely as a
    substring of a longer token."""
    return _pattern(token).search(text) is not None

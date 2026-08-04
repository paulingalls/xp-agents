#!/usr/bin/env python3
"""The `surface-commands` read seam: which surface commands cover one story.

Extracted from system_context_cli.py per the sibling convention
(system_context_edit_cli / _retire_cli / _caps_cli / _nested_field_cli /
_field_cli): re-imported by cli.py and re-exported via its `__all__`, so
callers and `mock.patch` targets see one object.

Its own module rather than an inline command for two reasons. It is the only
system-context command that also loads **sprint.json** — a story's paths live
in one document and the surfaces in the other. And system_context_cli.py sits
at 430 lines against a 450-line ratchet band, so inlining would have spent
headroom the extraction convention exists to protect.

Output contract, which the CALLER's fallback depends on:

    matched      one command per line on stdout, exit 0
    no match     nothing on stdout, exit 0
    cannot tell  nothing on stdout, exit 1, reason on stderr

`no match` covers PARTIAL match too: a story whose domain is only partly
claimed by declared surfaces prints nothing, because running the claimed
surface's command alone would test less than the full command it replaces.

`no match` and `cannot tell` both mean "fall back to the full command" for the
consumer, so the exit code is diagnostic rather than a decision — said plainly
here instead of implying the rc carries more than it does. What this command
must never do is print `stack.test_command` itself: substituting the full suite
would make a narrowed selection indistinguishable from no selection at all, and
the caller could no longer tell the two apart.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import sprint_store
import surface_selection
import system_context_store as store

__all__ = ["cmd_surface_commands"]


def cmd_surface_commands(args: argparse.Namespace) -> int:
    """Print the surface commands covering `args.story_id`'s file domain."""
    data = store.load_system_context(args.smm_dir)
    if data is None:
        print("No system context found.", file=sys.stderr)
        return 1

    sprint = sprint_store.load_sprint(args.smm_dir)
    if sprint is None:
        print("No sprint found.", file=sys.stderr)
        return 1

    try:
        commands = surface_selection.commands_for_story(
            data, sprint, args.story_id, cwd=args.cwd
        )
    except ValueError as exc:
        # The story id is the one thing the caller controls, so a typo must be
        # loud. Selection itself cannot raise: a malformed glob degrades to a
        # literal inside triage.compile_glob rather than escaping.
        print(str(exc), file=sys.stderr)
        return 1

    for command in commands:
        print(command)
    return 0

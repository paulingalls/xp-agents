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

import surface_selection
import system_context_store as store

__all__ = ["cmd_surface_commands"]


def cmd_surface_commands(args: argparse.Namespace) -> int:
    """Print the surface commands covering a CHANGED-path set read from stdin.

    Paths-only. The story-id door this replaced could not serve free close
    (which has no story) and, worse, selected on the DECLARED file_domain —
    which the close gate lets drift, so a drifted file never entered the
    coverage input and its tests ran nowhere at an auto-merge. The changed
    file set is the one input both close modes share and the only one that is
    true, so it is the only door.
    """
    data = store.load_system_context(args.smm_dir)
    if data is None:
        print("No system context found.", file=sys.stderr)
        return 1

    raw = sys.stdin.read() if args.paths_from == "-" else ""
    paths = [line.strip() for line in raw.splitlines() if line.strip()]

    for command in surface_selection.commands_for_changed_paths(data, paths):
        print(command)
    return 0

#!/usr/bin/env python3
"""Throwaway: tabulate observed hook-payload fields against our compatibility table.

Generated rather than hand-typed. Transcribing 14 fields across 8 events by hand
invites exactly the recording error this milestone exists to avoid, and later
stories add captures that need re-tabulating.

THREE states per field per event, not two. Measured in the real corpus:
`agent_type`/`agent_id` are ABSENT on top-level PreToolUse/PostToolUse and
'default' on subagent-scoped firings of the SAME events. "Present on PostToolUse"
is false at top level; "absent" is false when nested. A two-state table has to
pick one, and either choice misreports the sharpest finding in the sprint.

The corpus is read from OUT OF TREE and never committed: it carries absolute
home paths, session ids, transcript paths, verbatim prompts and an unreleased
model id. Deletion at sprint close would not contain that, because the merge
doctrine keeps every adding commit reachable — so it never enters git at all.
"""

import argparse
import json
import os
import sys
from pathlib import Path

# The fields our handlers actually consume, from the dual-target plan's
# compatibility surface. Order is the plan's (descending use count) so the
# generated table lines up with the doc a reader is comparing against.
TABLE_FIELDS = (
    "cwd",
    "tool_input",
    "agent_type",
    "agent_id",
    "stop_hook_active",
    "tool_name",
    "source",
    "tool_response",
    "prompt",
    "error",
    "reason",
    "name",
    "is_interrupt",
    "exit_code",
)

# The three that decide feasibility: subagent routing, every Stop gate's
# release, and SessionStart's fresh-vs-resume branch.
DECISIVE_FIELDS = ("agent_type", "agent_id", "stop_hook_active", "source")

ALWAYS = "always"
SOME_FIRINGS = "some-firings"
NEVER = "never"
NOT_OBSERVED = "not-observed"

_DEFAULT_CORPUS = Path(
    os.environ.get("XP_SPIKE_CORPUS", Path.home() / ".xp-agents-spike")
)


def _capture_files(corpus_root: Path) -> list[tuple[str, Path]]:
    """(run, path) for every capture, in chronological order within each run.

    The layout is nested: ``<root>/run-X/payloads/payloads/*.raw``. Filenames
    lead with nanoseconds, so a plain sort is chronological — which is what lets
    the decisive-field report show ORDER rather than a set.

    The run name is carried through deliberately: two runs' records must stay
    attributable, and a flat merge would silently overwrite one run's sibling
    index files with another's.

    Zero captures RAISES. An empty corpus otherwise renders a well-formed table
    of `not-observed` in every cell, which is indistinguishable from "no hook
    ever fired on any event" — the one observation this milestone must never
    produce by accident. Both ways to get there are live: the dump tells
    story-007's reader to re-run this on a machine where the out-of-tree corpus
    may be absent, and the layout is nested two deep, which the plan first had
    one level off.
    """
    out: list[tuple[str, Path]] = []
    for run_dir in sorted(p for p in corpus_root.glob("run-*") if p.is_dir()):
        payload_dir = run_dir / "payloads" / "payloads"
        if not payload_dir.is_dir():
            continue
        for raw in sorted(payload_dir.glob("*.raw")):
            out.append((run_dir.name, raw))
    if not out:
        raise FileNotFoundError(
            f"no captures under {corpus_root} — expected "
            f"{corpus_root}/run-*/payloads/payloads/*.raw. Refusing to tabulate: "
            "an empty corpus reads as 'no hook ever fired', not as 'no corpus'."
        )
    return out


def _load(path: Path) -> dict | None:
    try:
        parsed = json.loads(path.read_bytes().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, OSError):
        return None
    return parsed if isinstance(parsed, dict) else None


def unparseable(corpus_root: Path = _DEFAULT_CORPUS) -> list[str]:
    """Captures that could not be parsed — reported, never silently skipped.

    A corrupt file dropped in silence shrinks the denominator, which can turn a
    genuine ``some-firings`` into a false ``always``.
    """
    return [str(p) for _, p in _capture_files(corpus_root) if _load(p) is None]


def runs_without_captures(corpus_root: Path = _DEFAULT_CORPUS) -> list[str]:
    """Run dirs holding no captures — named, never silently dropped.

    Same reason ``unparseable`` exists, one level up: a dropped run shrinks the
    denominator far harder than a dropped file. One such run is a real finding
    (the untrusted-plugin control, whose hooks were skipped silently); another
    would be a layout mistake. Unnamed, the two read alike.
    """
    return [
        run_dir.name
        for run_dir in sorted(p for p in corpus_root.glob("run-*") if p.is_dir())
        if not sorted((run_dir / "payloads" / "payloads").glob("*.raw"))
    ]


def _by_event(corpus_root: Path) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for _, path in _capture_files(corpus_root):
        payload = _load(path)
        if payload is None:
            continue
        event = payload.get("hook_event_name")
        if isinstance(event, str) and event:
            grouped.setdefault(event, []).append(payload)
    return grouped


def registered_events(hooks_file: Path) -> list[str]:
    """Every event name registered in the hooks file, observed or not.

    Read from the file rather than hardcoded so an event we register but never
    see still gets a row. A missing row reads as "checked and fine".

    Unreadable or malformed propagates rather than degrading to ``[]``: an empty
    list makes the caller fall back to observed-only events, which deletes
    exactly the unfired rows this function exists to add.
    """
    data = json.loads(hooks_file.read_text(encoding="utf-8"))
    hooks = data.get("hooks") if isinstance(data, dict) else None
    if not isinstance(hooks, dict) or not hooks:
        raise ValueError(f"{hooks_file} has no non-empty 'hooks' object")
    return sorted(hooks)


def build_table(
    corpus_root: Path = _DEFAULT_CORPUS, registered: list[str] | None = None
) -> dict[str, object]:
    """{event: {field: state}}, or ``NOT_OBSERVED`` for an event with no captures."""
    grouped = _by_event(corpus_root)
    events = list(registered) if registered is not None else sorted(grouped)
    table: dict[str, object] = {}
    for event in events:
        firings = grouped.get(event, [])
        if not firings:
            table[event] = NOT_OBSERVED
            continue
        row: dict[str, str] = {}
        for field in TABLE_FIELDS:
            hits = sum(1 for f in firings if field in f)
            if hits == 0:
                row[field] = NEVER
            elif hits == len(firings):
                row[field] = ALWAYS
            else:
                row[field] = SOME_FIRINGS
        table[event] = row
    return table


def extra_fields(corpus_root: Path = _DEFAULT_CORPUS) -> dict[str, list[str]]:
    """Fields Codex sends that our table does not list: {field: [events]}.

    A field we never knew about is as much a finding as a missing one — it is
    what a normalisation layer would have no mapping for.
    """
    found: dict[str, set[str]] = {}
    for event, firings in _by_event(corpus_root).items():
        for payload in firings:
            for key in payload:
                if key in TABLE_FIELDS or key == "hook_event_name":
                    continue
                found.setdefault(key, set()).add(event)
    return {k: sorted(v) for k, v in sorted(found.items())}


def firing_sequence(corpus_root: Path = _DEFAULT_CORPUS) -> list[dict]:
    """Every firing in order, with the decisive fields — ORDER, not a set.

    A set hides the trap this exists to surface: firings AFTER SubagentStop
    still carry the finished subagent's ``agent_id``, so a handler attributing
    work by that field would assign parent tool calls to a dead subagent.

    Caveat for whoever reads this: hook processes can fire concurrently, and the
    filename timestamp is taken when the recorder starts. The ordering is
    evidence, not proof of causality.
    """
    seq: list[dict] = []
    for run, path in _capture_files(corpus_root):
        payload = _load(path)
        if payload is None:
            continue
        entry = {
            "run": run,
            "event": payload.get("hook_event_name"),
            "file": path.name,
            # Presence, carried separately, because `None` is an ambiguous value
            # here: it is both "the host sent JSON null" and "the host sent
            # nothing". On a DECISIVE field those are different answers to the
            # sprint's question, so the renderer filters on this, not on the value.
            "present": [f for f in DECISIVE_FIELDS if f in payload],
        }
        for field in DECISIVE_FIELDS:
            entry[field] = payload.get(field)
        seq.append(entry)
    return seq


def render(
    corpus_root: Path = _DEFAULT_CORPUS, registered: list[str] | None = None
) -> str:
    table = build_table(corpus_root, registered)
    lines = ["## Field presence by event", ""]
    lines.append("| event | " + " | ".join(TABLE_FIELDS) + " |")
    lines.append("|" + "---|" * (len(TABLE_FIELDS) + 1))
    for event, row in table.items():
        if row == NOT_OBSERVED:
            cells = " | ".join([NOT_OBSERVED] * len(TABLE_FIELDS))
            lines.append(f"| {event} | {cells} |")
            continue
        assert isinstance(row, dict)
        lines.append(f"| {event} | " + " | ".join(row[f] for f in TABLE_FIELDS) + " |")

    lines += ["", "## Fields Codex sends that our table does not list", ""]
    extras = extra_fields(corpus_root)
    if not extras:
        lines.append("(none observed)")
    for field, events in extras.items():
        lines.append(f"- `{field}` — on {', '.join(events)}")

    lines += ["", "## Decisive fields, in firing order", ""]
    for entry in firing_sequence(corpus_root):
        vals = " ".join(
            f"{f}={entry[f]!r}" for f in DECISIVE_FIELDS if f in entry["present"]
        )
        lines.append(f"- {entry['run']} {entry['event']}: {vals or '(none present)'}")

    empty = runs_without_captures(corpus_root)
    if empty:
        lines += ["", "## Runs that produced no captures", ""] + [
            f"- {r}" for r in empty
        ]

    bad = unparseable(corpus_root)
    if bad:
        lines += ["", "## Unparseable captures", ""] + [f"- {p}" for p in bad]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-root", type=Path, default=_DEFAULT_CORPUS)
    parser.add_argument(
        "--hooks-file",
        type=Path,
        default=Path(__file__).parent.parent / "hooks" / "hooks.codex.json",
        help="registered events come from here so unfired ones still get a row",
    )
    args = parser.parse_args(argv)
    sys.stdout.write(
        render(args.corpus_root, registered=registered_events(args.hooks_file))
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

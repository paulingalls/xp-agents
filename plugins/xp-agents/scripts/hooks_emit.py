#!/usr/bin/env python3
"""Derive the second harness's hooks manifest from the first's.

`hooks/hooks.json` is the hand-edited source of truth. This emitter reads it
and writes `hooks/hooks.codex.json`; it NEVER writes the source. That direction
is the whole design: the first harness's manifest is byte-identical after a run
by construction, so the fourteen suites that read it need no change, and the
second variant cannot drift because a pin regenerates it and compares.

Mostly subtraction, plus one rule that runs the other way. The two harnesses
trigger on different events — harness 1 sees a skill invocation as a tool call,
while harness 2 has no skill tool call and the skill's body reaches the model
through a shell read — so the variant needs a hook the source must not carry,
and subtracting from a source that must not contain it cannot express that.
`_VARIANT_ONLY_HOOKS` is that rule; the sibling `manifest_emit.py` derives the
second plugin manifest by addition in the same spirit.

Why a script under `scripts/` rather than under `hooks/`: `tests/_pin_helpers.py`
scans `scripts/` and `smm/` for shipped Python and deliberately skips `hooks/`
("it holds hooks.json and no Python at all"). An emitter under `hooks/` would
escape the file-size and language-leak pins entirely.

Run with no arguments to regenerate in place:

    python3 plugins/xp-agents/scripts/hooks_emit.py
"""

import argparse
import json
from pathlib import Path

_VARIANT_NAME = "hooks.codex.json"
_SOURCE_NAME = "hooks.json"

# Event names the second harness does not recognise. Measured in the dual-target
# spike: each was registered deliberately and never fired in any run.
#
# NOT-OBSERVED IS NOT UNRECOGNISED, and the difference is what this set turns on.
# The compaction events also never fired — no run compacted — yet the host named
# them in its own per-event warning, which is proof it knows them. They stay in
# the variant, because dropping them would leave a compacting session with no
# event-log backup and no compaction at all, mislabelled as a harness limit.
# Only the four the spike records as unrecognised are dropped.
#
# Unknown event names are ignored SILENTLY there, so leaving these in would cost
# nothing at runtime — dropping them is what makes the variant say only what is
# true of the harness it targets. The cost is carried elsewhere and recorded, not
# hidden: dropping PostToolUseFailure removes the test-failure gate outright, and
# no milestone yet owns replacing it.
#
# One run, one harness version. A later version that recognises one of these
# keeps being stripped until someone re-measures; the pin in
# tests/test_hooks_variants.py spells this set out independently so an edit here
# has to be argued for rather than absorbed.
_UNRECOGNISED_EVENTS = frozenset(
    {
        "PostToolUseFailure",
        "TeammateIdle",
        "TaskCompleted",
        "WorktreeCreate",
    }
)

# Per-hook keys the variant does not carry. The two are dropped for different
# reasons, and conflating them would lose the distinction that matters:
#
#   timeout — dropped because the UNIT differs. Measured on an installed copy:
#     `timeout: 2000` let a 3s handler run to completion (milliseconds would
#     have killed it at 2s) and `timeout: 1` killed the same handler mid-sleep,
#     so the second harness reads SECONDS and does enforce them. The source
#     declares MILLISECONDS, so carrying a value across literally would ask for
#     2500 seconds where 2.5 was meant — off by 1000x, and worse than no bound.
#     The same measurement retires the old SessionEnd puzzle: the clamp warning
#     fired on 2500 and 1500 because both are seconds meeting that event's 3s
#     cap. Re-establishing a bound is a CONVERSION (ms -> s, with sub-second
#     bounds unrepresentable as integers), which a later milestone owns.
#
#   async — dropped because it buys nothing. Measured: `async: true` on
#     SessionEnd is not skipped, it runs SYNCHRONOUSLY with a warning per
#     fire. Nothing is forfeited by removing a flag whose behaviour is
#     unavailable either way.
_DROPPED_HOOK_KEYS = ("timeout", "async")

# Hook objects the VARIANT carries and the source does not, keyed by the
# (event, matcher) pair of the entry each is appended to.
#
# Shape, decided by counting both shipped manifests rather than by preference:
# one entry carrying many hook objects occurs six times (Stop carries six,
# UserPromptSubmit three), while two entries sharing a matcher on one event has
# never shipped. The second harness's hook-merge rules are recorded as
# undocumented, so the addition takes the shape that harness demonstrably
# already runs. The pins assert JSON shape only, so a hook that never FIRED
# would look identical here — which is why the shape is chosen on evidence.
#
# These are authored FOR the variant, so unlike carried-across entries they are
# never passed through _DROPPED_HOOK_KEYS: they must not declare `timeout` or
# `async` in the first place, and the variant-wide pins in
# tests/test_hooks_variant_subtraction.py fail if one ever does.
#
# A carried-across command inherits path existence from the source's own pin
# (tests/hooks/test_plugin_integrity_structure_and_close.py, which reads
# hooks.json only); an authored one inherits nothing. The command below names a
# script a later story has yet to create, so until it does the variant registers
# a hook with no file behind it and no pin says so — an accepted, recorded gap
# rather than one a reader of this table has to discover.
_VARIANT_ONLY_HOOKS: dict[tuple[str, str], list[dict]] = {
    ("PreToolUse", "Bash"): [
        {
            "type": "command",
            "command": "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/preload_injection.py",
            "statusMessage": "Loading skill state...",
        }
    ],
}


def default_source() -> Path:
    """The checked-in source manifest, resolved from this file."""
    return Path(__file__).parent.parent / "hooks" / _SOURCE_NAME


def default_out_dir() -> Path:
    """The shipped hooks directory, resolved from this file."""
    return Path(__file__).parent.parent / "hooks"


def transform(source: dict) -> dict:
    """Return the second harness's manifest derived from the first's.

    Subtraction, then the declared additions. Every surviving entry is carried
    across untouched apart from the dropped keys and any hook objects
    `_VARIANT_ONLY_HOOKS` appends to it — no matcher is rewritten and no entry
    reordered. Matchers naming tools that do not exist on the second harness are
    left alone deliberately: making them fire needs the payload normalization
    and the explicit marker legs that later milestones own, and a matcher that
    fires into a handler reading a field the harness never sends is worse than
    one that never fires.

    Raises ValueError when a declared addition names an (event, matcher) the
    derived manifest has no entry for. That state is reachable rather than
    hypothetical — an edit to the source that renames or removes an entry turns
    the addition into a silent no-op — and the variant would still regenerate
    and still parse, so nothing else would say so at the moment of the edit.
    """
    derived = json.loads(json.dumps(source))
    derived["hooks"] = {
        event: entries
        for event, entries in derived["hooks"].items()
        if event not in _UNRECOGNISED_EVENTS
    }
    for entries in derived["hooks"].values():
        for entry in entries:
            for hook in entry.get("hooks", []):
                for key in _DROPPED_HOOK_KEYS:
                    hook.pop(key, None)

    for (event, matcher), added in _VARIANT_ONLY_HOOKS.items():
        targets = [
            entry
            for entry in derived["hooks"].get(event, [])
            if (entry.get("matcher") or "") == matcher
        ]
        if len(targets) != 1:
            raise ValueError(
                f"variant-only hooks declared for {event}:{matcher} match "
                f"{len(targets)} entries in the derived manifest, expected exactly "
                "one — the source entry was renamed, removed, or duplicated"
            )
        targets[0].setdefault("hooks", []).extend(json.loads(json.dumps(added)))
    return derived


def emit(source: Path | None = None, out_dir: Path | None = None) -> Path:
    """Write the derived variant into out_dir and return its path."""
    source = source or default_source()
    out_dir = out_dir or default_out_dir()
    data = json.loads(source.read_text(encoding="utf-8"))
    target = out_dir / _VARIANT_NAME
    out_dir.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(transform(data), indent=2) + "\n", encoding="utf-8")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, default=None, help="source manifest (default: shipped)"
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="output dir (default: shipped hooks/)",
    )
    args = parser.parse_args()
    print(emit(source=args.source, out_dir=args.out_dir))


if __name__ == "__main__":
    main()

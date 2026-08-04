#!/usr/bin/env python3
"""Which commands the close gate runs — the ONE implementation.

The close skills run every command in the `### GATE_COMMANDS` block and then
MERGE WITHOUT ASKING. Everything here is therefore a safety decision, not a
formatting one, and it lives in exactly one place so the preload and the
gate-time recheck cannot disagree.

RESOLUTION ORDER IS A CONTRACT, each step paid for by a defect:

1. `stack.test_command` unrunnable -> ("none", reason "not-set"). The
   documented opt-out is tested FIRST, before surfaces are consulted: a
   project that emptied the field to switch auto-merge off must not have it
   re-armed by declaring surface `paths`.
2. The declared command's own exit status must reach the shell, else
   ("none", reason "exit-status-masked").
3. Surfaces select via `surface_selection.commands_for_changed_paths`, which
   owns the all-or-nothing coverage veto and the collapse rule.
4. A selected surface command that fails the same exit-status check collapses
   the WHOLE surface leg to the full command — never a filter. See below.
5. Non-empty selection -> ("surface", commands); else ("full", [full]).

WHY THE EXIT-STATUS CHECK EXISTS, and why flattening was never it:

    pytest -q; echo done     exits 0 even when pytest FAILED

The gate reads that as pass and auto-merges a red suite. An earlier fix
collapsed newlines to spaces and a comment then claimed the block was safe;
`\\n;` defeats it (`pytest -q ; echo PWNED` is one bullet and two executed
commands) and bare `;`/`&`/`|` never went through it at all. A close review
found that by RUNNING the emitter rather than reading it.

Which operators discard an exit status is decidable from the string alone, so
`shell_exit_structure.exit_reaches_shell` (shipped by story-003, never wired to
this consumer until now) is the owner. `&&` propagates failure and is accepted;
`;`, a bare pipe and a trailing `&` are not. Structural, so it holds for a Rust
or TypeScript project as readily as a Python one — no language table.

REFUSAL IS ALL-OR-NOTHING, NEVER A FILTER. Step 3's veto has already proved
every changed path is claimed by some surface. Dropping just the refused
command from that set would leave the paths that surface claimed running
nowhere while the gate reports green — the same fail-open shape this module
exists to close, reintroduced by the fix. So any surface-leg refusal collapses
to the full command, and a refused full command yields "none".

`GATE_DISABLED_REASON` is emitted ONLY when there is no block, because it
exists to explain an absent one. Both close SKILL.md files print it verbatim
rather than carrying a hardcoded "set stack.test_command to enable" hint: a
user who declared `make test | tee log` HAS set it, and would otherwise read a
false message.
"""

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "smm"))

import shell_exit_structure
import surface_selection
import system_context_store as store

__all__ = ["REASON_EXIT_MASKED", "REASON_NOT_SET", "resolve"]

REASON_NOT_SET = "not-set"
REASON_EXIT_MASKED = "exit-status-masked"

_SEPARATOR = "--"


def _flat(value: str) -> str:
    """Collapse whitespace runs, matching the shell's `flat`.

    Applied only AFTER the exit-status check has accepted the raw value, so it
    normalises an already-single command rather than disguising a compound one
    as one. Running it first is what let `pytest -q\\n; echo X` through.
    """
    return " ".join(value.split())


def _usable(command: str | None) -> bool:
    """Runnable, and its failure reaches the gate."""
    if not command or not command.strip():
        return False
    return shell_exit_structure.exit_reaches_shell(command)


def _git(cwd: Path, *args: str) -> str:
    """Stdout of a git command, or "" on any failure.

    Swallowing is deliberate and safe in ONE direction only: an empty path set
    means no narrowing, which falls back to the full command. It can never
    invent coverage.
    """
    result = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True
    )
    return result.stdout if result.returncode == 0 else ""


def changed_paths(base: str, cwd: Path) -> list[str]:
    """Committed range UNION the working tree.

    `base` must be a resolved SHA, not a branch name. A triple-dot range
    against a branch re-computes its merge base, which MOVES if the target
    advances mid-close — in a parallel sprint that shifts the selection and
    trips the recheck, sending every narrowing close to the human prompt and
    quietly disabling the feature. The preload pins the SHA once.

    The working tree is unioned because the gate's commands run against it
    while `base...HEAD` sees only commits — so an UNCOMMITTED review fix, the
    exact case the recheck exists for, would otherwise be invisible. Untracked
    files count: a fix that authors a new test file is that case.
    """
    paths = {
        line.strip()
        for line in _git(cwd, "diff", f"{base}...HEAD", "--name-only").splitlines()
        if line.strip()
    }
    for line in _git(cwd, "status", "--porcelain").splitlines():
        entry = line[3:].strip()
        if "->" in entry:  # a rename reports "old -> new"
            entry = entry.split("->")[-1].strip()
        if entry:
            paths.add(entry)
    return sorted(paths)


def digest(scope: str, commands: list[str]) -> str:
    """Fingerprint of the RESOLVED COMMAND SET, deliberately not of the diff.

    This is what makes the recheck precise rather than paranoid: a review fix
    touching a file already inside a selected surface leaves the set identical
    and passes. Only a fix that changes what must RUN trips it.
    """
    return hashlib.sha256("\n".join([scope, *commands]).encode()).hexdigest()


def resolve(
    system_context: dict | None, paths: list[str], full_command: str
) -> tuple[str, list[str], str | None]:
    """Return (scope, commands, disabled_reason).

    scope is "none" | "surface" | "full". `disabled_reason` is non-None only
    when scope is "none" — it explains an ABSENT block and nothing else.
    """
    if not full_command or not full_command.strip():
        return ("none", [], REASON_NOT_SET)
    if not shell_exit_structure.exit_reaches_shell(full_command):
        return ("none", [], REASON_EXIT_MASKED)

    full = _flat(full_command)
    if not isinstance(system_context, dict):
        return ("full", [full], None)

    selected = surface_selection.commands_for_changed_paths(system_context, paths)
    if not selected:
        return ("full", [full], None)

    # Check the RAW declared commands, not `selected`. `_declared_command`
    # flattens on the way out, so by the time a command reaches `selected` a
    # newline has already become a space and `pytest tests/cli\nrm -rf build`
    # looks like one innocuous command. Checking only the flattened form let
    # exactly that through — caught by a test, not by reading.
    surfaces = system_context.get("acceptance_surfaces")
    matched = (
        surface_selection.surfaces_for_paths(surfaces, paths)
        if isinstance(surfaces, list)
        else []
    )
    raw = [
        surface.get("command")
        for surface in matched
        if isinstance(surface.get("command"), str) and surface["command"].strip()
    ]

    # All-or-nothing: one unusable command collapses the leg, never filters it.
    if not all(_usable(command) for command in [*raw, *selected]):
        return ("full", [full], None)

    return ("surface", [_flat(command) for command in selected], None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smm-dir", required=True)
    parser.add_argument(
        "--base",
        required=True,
        help="Resolved merge-base SHA, never a branch name — see changed_paths.",
    )
    parser.add_argument("--cwd", default=".", help="Checkout to read the diff from.")
    parser.add_argument(
        "--full-command",
        default="",
        help="The declared full command. Passed in rather than read here, so "
        "the preload keeps a single read of stack.test_command.",
    )
    parser.add_argument(
        "--expect-digest",
        default=None,
        help="Recheck mode: re-resolve NOW and exit non-zero if the command "
        "set no longer matches this digest. Run as the block's own first "
        "bullet, so condition 3's 'every command exits 0' enforces the freeze "
        "without any prose re-derivation.",
    )
    args = parser.parse_args(argv)

    cwd = Path(args.cwd)
    scope, commands, reason = resolve(
        store.load_system_context(Path(args.smm_dir)),
        changed_paths(args.base, cwd),
        args.full_command,
    )
    actual = digest(scope, commands)

    if args.expect_digest is not None:
        if actual == args.expect_digest:
            return 0
        # Name what changed. A silent trip reads as a mysterious gate failure
        # and the feature gets switched off; one readable line is the whole
        # mitigation for that.
        print(
            "close-gate drift: the command set resolved at preload time no "
            "longer covers this branch.\n"
            f"  now: scope={scope} commands={commands or '(none)'}\n"
            f"  expected-digest={args.expect_digest} actual={actual}\n"
            "  a change landed after the gate was computed — most likely a "
            "review fix touching a file the frozen set does not cover.\n"
            "  falling through to confirmation rather than auto-merging.",
            file=sys.stderr,
        )
        return 1

    print(f"SCOPE={scope}")
    print(f"REASON={reason or ''}")
    print(f"DIGEST={actual}")
    print(_SEPARATOR)
    for command in commands:
        print(command)
    return 0


if __name__ == "__main__":
    sys.exit(main())

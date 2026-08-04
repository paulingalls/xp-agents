#!/usr/bin/env python3
"""Throwaway spike probe: hook-side skill-preload injection.

Sixteen of eighteen shipped skills get their state from a host-expanded
`` !`…` `` line at the top of SKILL.md. This harness does not expand it — it has
the MODEL read SKILL.md as raw text — so those skills load stateless. The
customer's direction is to remove the model from the delivery path entirely, and
this handler is that: it becomes the preload expander the host is not.

The handle is an accident of the very defect it works around. Because the model
reads SKILL.md *with a shell command*, the skill's identity arrives in a
PreToolUse payload as `tool_input.command`, and PreToolUse accepts injected
context (measured: a marker minted here reached the model byte-identically).

Four properties are load-bearing, each because its opposite fails QUIETLY:

1. **Run the command the `!` line NAMES.** Of the sixteen, 14 say
   `scripts/preload.sh`, one says `preload.sh --consume-gate`, one says
   `check_session_needs.sh`. A hardcoded filename mishandles two — one of them
   the most-used skill — and looks fine on the other fourteen.
2. **Once per skill per session.** A chunk-read SKILL.md fires PreToolUse
   repeatedly. One shipped preload takes `--consume-gate` and CONSUMES a marker,
   so re-running it would burn a gate per chunk.
3. **The resolved dir must be under the plugin root.** This executes a command
   read out of a file whose path arrived in a payload; without the check, any
   `/skills/<name>/SKILL.md`-shaped token makes it run that file's `!` line.
4. **A failing preload injects NOTHING.** Injecting a partial payload that reads
   as success corrupts the observation rather than failing it.

Like the rest of the rig: never raises, always exit 0, stdout empty unless it is
deliberately injecting.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import _dump_payload

_LABEL = "XP-SPIKE-MARKER"

# The identity handle: a SKILL.md path anywhere in the command string. Bounded on
# the left by a path separator so `.../myskills/x/SKILL.md` cannot masquerade, and
# tolerant of any reader (sed/cat/head/python) because it never anchors.
_SKILL_PATH_RE = re.compile(
    r"(?P<dir>(?:/[^/\s'\"]+)*/skills/(?P<name>[^/\s'\"]+))/SKILL\.md"
)

# The host-expanded preload line: `!`<command>`` at the start of a line.
_PRELOAD_LINE_RE = re.compile(r"^!`(?P<cmd>.+?)`\s*$", re.MULTILINE)

_PRELOAD_TIMEOUT_SECONDS = 30

_RECORD_NAME = "skill_inject.jsonl"


def skill_dir_from_command(command: str) -> Path | None:
    """The skill directory named by a SKILL.md read, or None.

    Returns the DIRECTORY, not the name: the caller must validate the path
    against the plugin root, and a bare name would throw that away.
    """
    if not isinstance(command, str):
        return None
    match = _SKILL_PATH_RE.search(command)
    return Path(match.group("dir")) if match else None


def preload_command(skill_md: Path) -> str | None:
    """The command the skill's own `!` line names, or None when it has none.

    Two of eighteen shipped skills carry no preload line. That is not a failure.
    """
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError:
        return None
    match = _PRELOAD_LINE_RE.search(text)
    return match.group("cmd") if match else None


def _under(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
    except (ValueError, OSError):
        return False
    return True


def _once_marker(records: Path, skill: str, session: object) -> Path:
    """One path per (skill, session).

    Hashed rather than interpolated: the session id is untrusted input that would
    otherwise steer a filesystem path — the same reasoning the shipped
    session-scoped markers use.
    """
    key = f"{skill}\0{session}".encode()
    return records / f".injected-{hashlib.sha256(key).hexdigest()[:12]}"


def _record(records: Path, entry: dict) -> None:
    try:
        records.mkdir(parents=True, exist_ok=True)
        with (records / _RECORD_NAME).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError as exc:
        _dump_payload._report_write_failure("skill inject record", exc)


def main() -> int:
    try:
        raw = sys.stdin.buffer.read()
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            payload = {}
    except Exception:
        payload = {}

    command = (payload.get("tool_input") or {}).get("command")
    skill_dir = skill_dir_from_command(command or "")
    if skill_dir is None:
        # Not a skill read. Record NOTHING — otherwise every shell call in the
        # session looks like a skill invocation and the record becomes noise.
        return 0

    records = _dump_payload._spike_dir()
    skill = skill_dir.name
    session = payload.get("session_id")
    marker = f"{_LABEL}-{uuid.uuid4().hex}"
    base = {
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "skill": skill,
        "skill_dir": str(skill_dir),
        "session_id": session,
        "marker": marker,
        "hook_event_name": payload.get("hook_event_name"),
        "injected": False,
        "suppressed": False,
        "exit_status": None,
        "preload_command": None,
        "context_bytes": 0,
        "reason": None,
        "pid": os.getpid(),
    }

    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT") or os.environ.get("PLUGIN_ROOT")
    if not plugin_root or not _under(skill_dir, Path(plugin_root)):
        _record(records, {**base, "reason": "outside plugin root"})
        return 0

    once = _once_marker(records, skill, session)
    if once.exists():
        _record(records, {**base, "reason": "already injected this session"})
        return 0

    command_line = preload_command(skill_dir / "SKILL.md")
    if command_line is None:
        _record(records, {**base, "reason": "no preload line"})
        return 0

    # Expand exactly what the host would have. CLAUDE_SKILL_DIR is the whole
    # reason this works without the host: the dir is derivable from the path the
    # model just read.
    env = dict(os.environ)
    env["CLAUDE_SKILL_DIR"] = str(skill_dir)
    env.setdefault("CLAUDE_PLUGIN_DATA", os.environ.get("CLAUDE_PLUGIN_DATA", ""))

    # Run it where the SESSION runs, not in the skill dir. A preload resolves the
    # shared model by hashing the git common dir of its cwd, so running it under
    # the plugin cache resolves a DIFFERENT project's state — with exit 0 and no
    # error, injecting the wrong project's data as if it were right. The E2E
    # caught this; reasoning did not.
    session_cwd = payload.get("cwd")
    run_cwd = (
        session_cwd
        if isinstance(session_cwd, str) and Path(session_cwd).is_dir()
        else None
    )

    try:
        result = subprocess.run(
            ["bash", "-c", command_line],
            capture_output=True,
            text=True,
            timeout=_PRELOAD_TIMEOUT_SECONDS,
            env=env,
            cwd=run_cwd,
        )
    except Exception as exc:  # the failure text IS the finding
        _record(
            records,
            {
                **base,
                "preload_command": command_line,
                "reason": f"{type(exc).__name__}: {exc}",
            },
        )
        return 0

    if result.returncode != 0:
        _record(
            records,
            {
                **base,
                "preload_command": command_line,
                "exit_status": result.returncode,
                "reason": (
                    f"preload exited {result.returncode}: "
                    f"{(result.stderr or '')[-400:]}"
                ),
            },
        )
        return 0

    context = f"{marker}\n{result.stdout}"

    # Claim the once-marker BEFORE emitting. If the claim cannot be written we
    # would re-run a state-mutating preload on the next chunk, so failing to
    # claim means declining to inject.
    try:
        records.mkdir(parents=True, exist_ok=True)
        once.write_text(marker, encoding="utf-8")
    except OSError as exc:
        _dump_payload._report_write_failure("skill inject once-marker", exc)
        _record(
            records,
            {
                **base,
                "preload_command": command_line,
                "exit_status": 0,
                "reason": "could not claim the once-marker; declined to inject",
            },
        )
        return 0

    # Suppressed mode is run G0's control: record the marker, inject nothing. It
    # beats unwiring the handler, because then the marker record would exist only
    # in the run where injection is also on — and a model that read the record
    # could report a byte-identical marker having received no injection at all.
    suppressed = bool(os.environ.get("XP_SPIKE_SUPPRESS_INJECT"))
    _record(
        records,
        {
            **base,
            "preload_command": command_line,
            "exit_status": 0,
            "context_bytes": len(context.encode("utf-8")),
            "injected": not suppressed,
            "suppressed": suppressed,
        },
    )
    if suppressed:
        return 0

    sys.stdout.write(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": payload.get("hook_event_name") or "PreToolUse",
                    "additionalContext": (
                        f"{context}\n\n"
                        f"(The block above is the preloaded state for the "
                        f"'{skill}' skill, delivered by its hook. The first line "
                        f"is a one-time marker; report it verbatim if asked "
                        f"which marker you were given.)"
                    ),
                }
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Throwaway spike probe: can a hook process resolve its roots?

Narrow on purpose. The env aliases were already observed and recorded, and
`_dump_payload.py` already writes them on every firing, so this probe imports
that key set rather than restating it — two spellings of one observation is how
a contradiction ends up recorded as evidence.

What is genuinely unobserved, and what this probe exists for:

1. **`init.sh`'s resolution outcome from inside a hook process.** The alias
   being present says nothing about whether the resolver run by a hook actually
   lands on a usable shared-model directory.
2. **The payload-vs-env session id pair.** The liveness heartbeat is WRITTEN
   keyed on the payload's `session_id` and READ from the environment. If those
   two disagree, a session whose hooks demonstrably ran reports "not live" —
   so the pair is recorded side by side, and the disagreement is stated rather
   than left to be inferred from a puzzling verdict downstream.
3. **The resolved plugin root, verbatim.** Later runs need an absolute path for
   in-session shell calls, because the root variable is not exported to agent
   shells; and its version segment is what says which cached copy actually ran.

Like the recorder: never stdout (that would be injected context, and this probe
is registered alongside the injector whose measurement it would contaminate),
never raises, always exit 0.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import _dump_payload

# The chain production consults, in production order. Named here rather than
# imported because the shipped module lives behind a sys.path dance this rig
# deliberately does not perform — but a drift between the two IS a finding, so
# the resolved values are recorded verbatim for comparison rather than trusted.
_SESSION_ID_ENV_CANDIDATES = (
    "XP_SESSION_ID",
    "CODEX_THREAD_ID",
    "CLAUDE_CODE_SESSION_ID",
)

_PLUGIN_ROOT_KEYS = ("CLAUDE_PLUGIN_ROOT", "PLUGIN_ROOT")

# What init.sh CONSULTS before it derives anything: a pinned SMM_DIR is honored
# verbatim and skips derivation entirely, and a named XP_AGENTS_DATA switches off
# legacy discovery and relocation. Recorded because without them a resolved path
# is ambiguous — "the hook derived it" and "the hook echoed a variable the runner
# exported" produce the same line, and one of them is not evidence for AC-1. Run
# D exports SMM_DIR by design, so this is the expected case, not a corner.
_RESOLUTION_INPUT_KEYS = ("SMM_DIR", "XP_AGENTS_DATA", "XP_SMM_MIGRATE")

# Matches production's own budget for the same script (30s in
# `smm/smm_dir_resolve._DERIVE_TIMEOUT_SECONDS`). A SHORTER budget here would
# record "cannot resolve" for a first run that copies the whole SMM to the new
# data root — a resolution production would have completed — which is a false
# observation on the one AC this probe exists to answer.
_INIT_SH_TIMEOUT_SECONDS = 30


def _payload_session_id(raw: bytes) -> str | None:
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    value = parsed.get("session_id")
    return value if isinstance(value, str) and value else None


def _resolve_plugin_root() -> tuple[Path | None, str | None]:
    """The plugin root and WHICH name supplied it — the name is the finding."""
    for key in _PLUGIN_ROOT_KEYS:
        value = os.environ.get(key, "").strip()
        if value:
            return Path(value), key
    return None, None


def _run_init_sh() -> dict:
    """Record the resolution outcome, whatever it is.

    Every branch writes a record. A probe that stays silent when it cannot
    resolve is indistinguishable from a hook that never fired, which is the one
    reading this whole milestone must never produce by accident.
    """
    root, source = _resolve_plugin_root()
    if root is None:
        return {
            "ran": False,
            "reason": f"no plugin root in env (tried {', '.join(_PLUGIN_ROOT_KEYS)})",
            "plugin_root": None,
            "plugin_root_source": None,
            "resolved_smm_dir": None,
            "smm_dir_exists": None,
            "exit_status": None,
            "stderr_tail": None,
        }

    init_script = root / "smm" / "init.sh"
    base = {
        "plugin_root": str(root),
        "plugin_root_source": source,
        "resolved_smm_dir": None,
        "smm_dir_exists": None,
        "exit_status": None,
        "stderr_tail": None,
    }
    if not init_script.is_file():
        return {**base, "ran": False, "reason": f"not a file: {init_script}"}

    try:
        result = subprocess.run(
            ["bash", str(init_script)],
            capture_output=True,
            text=True,
            timeout=_INIT_SH_TIMEOUT_SECONDS,
        )
    except Exception as exc:  # the failure text IS the finding
        return {**base, "ran": False, "reason": f"{type(exc).__name__}: {exc}"}

    resolved = result.stdout.strip() or None
    return {
        **base,
        "ran": True,
        "reason": None,
        "resolved_smm_dir": resolved,
        "smm_dir_exists": Path(resolved).is_dir() if resolved else False,
        "exit_status": result.returncode,
        # Tail, not head: bash reports the failing line last.
        "stderr_tail": (result.stderr or "")[-2000:] or None,
    }


def main() -> int:
    try:
        raw = sys.stdin.buffer.read()
    except Exception:
        raw = b""

    payload_session_id = _payload_session_id(raw)
    env_session_ids = {
        key: os.environ.get(key) or None for key in _SESSION_ID_ENV_CANDIDATES
    }
    distinct_env = {v for v in env_session_ids.values() if v}

    # Three-valued on purpose. False means "both sides answered and disagree",
    # which is the actionable case. None means there is nothing to compare, and
    # collapsing that to False would report a conflict that does not exist.
    if payload_session_id is None or not distinct_env:
        agree = None
    else:
        agree = distinct_env == {payload_session_id}

    entry = {
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "cwd": os.getcwd(),
        "env": {k: os.environ.get(k) for k in _dump_payload._ENV_KEYS},
        "payload_session_id": payload_session_id,
        "env_session_ids": env_session_ids,
        "session_ids_agree": agree,
        "resolution_inputs": {k: os.environ.get(k) for k in _RESOLUTION_INPUT_KEYS},
        "init_sh": _run_init_sh(),
    }

    try:
        root = _dump_payload._spike_dir()
        root.mkdir(parents=True, exist_ok=True)
        with (root / "resolve.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except Exception as exc:
        # Same bargain as the recorder: exit 0 so a probe never blocks the host
        # mid-observation, but state the failure on stderr — an absent record is
        # otherwise indistinguishable from a hook that never fired.
        _dump_payload._report_write_failure("resolve record", exc)

    return 0


if __name__ == "__main__":
    sys.exit(main())

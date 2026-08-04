#!/usr/bin/env python3
"""Throwaway spike probe: which ways of spelling a commit does the gate see?

No-go criterion 3 says "a commit gate with a bypass hole is not a gate". The
criterion as written asks whether the harness INTERCEPTS every shell path; this
probe answers the other half, which is just as decisive and needs no harness at
all: once intercepted, does our own detector RECOGNISE the command as a commit?
A gate that fires and then fails to recognise `sh -c "git commit"` is exactly as
bypassable as one that never fired.

It drives the REAL `scripts/pre_tool_bash.py` as a subprocess rather than
reimplementing the detector, so it cannot drift from what ships.

Two properties are load-bearing, each because its opposite fails in the SAME
direction the criterion is measured in — toward a false "bypass":

1. **The rig must be provably armed.** The commit gate skips itself entirely
   when the SMM fails to validate (`pre_tool_bash.py:240` guards the call on
   `smm_dir is not None`) and says nothing about it. An unarmed rig therefore
   reports every shape as not-blocked — 14 rows that read exactly like total
   bypass. A positive control is the only honest guard, so `assert_armed`
   refuses to let a matrix be produced without one, and requires the control to
   block with the REVIEW gate's reason: any other refusal (tier-1 secret scan,
   an unresolvable `-C`) means some other gate bit and says nothing about the
   one being measured.
2. **A crashing hook is not a permissive hook.** `blocked = (rc == 2)` folds a
   traceback, an import error and a missing interpreter into "allowed".

Never guesses: a status it cannot interpret is ERROR, not ALLOWED.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
_HOOK = _PLUGIN_ROOT / "scripts" / "pre_tool_bash.py"
_INIT_SH = _PLUGIN_ROOT / "smm" / "init.sh"

BLOCKED = "blocked"
ALLOWED = "allowed"
ERROR = "error"

# The shape whose answer we already know. If this does not block, the rig is
# broken and no other row can be trusted.
CONTROL_COMMAND = 'git commit -m "probe control"'

# The reason the REVIEW-cycle gate gives. Pinned so a block from any other gate
# in the same chain cannot be mistaken for this one being armed.
CONTROL_REASON_FRAGMENT = "/xp-quality-review"

_TIMEOUT_SECONDS = 60

# Env that would otherwise steer git or the SMM resolver out from under us. Same
# hygiene the test suite applies at import time, applied here because this probe
# runs from a developer shell rather than under conftest.
_STRIP = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_COMMON_DIR",
    "GIT_INDEX_FILE",
    "SMM_DIR",
    "XP_AGENTS_DATA",
    "XP_TEAMMATE_NAME",
    # Read by init.sh, which build_rig runs: a dev shell exporting `force` would
    # drive relocation past the guard the rig has no reason to exercise.
    "XP_SMM_MIGRATE",
    "XP_SESSION_ID",
    "CLAUDE_CODE_SESSION_ID",
    "CODEX_THREAD_ID",
)


class RigNotArmedError(RuntimeError):
    """The control shape did not block, so no row in this matrix means anything."""


# The shapes. `expect` records what research measured, so a change in the
# shipped detector shows up as a failing pin rather than a silently altered
# matrix. It is documentation of the finding, never an input to classification.
SHAPES: list[dict] = [
    {"name": "plain", "command": 'git commit -m "x"', "expect": BLOCKED},
    {"name": "env-prefix", "command": 'env FOO=1 git commit -m "x"', "expect": BLOCKED},
    {
        "name": "git-dir-env",
        "command": 'GIT_DIR=x git commit -m "y"',
        "expect": BLOCKED,
    },
    {
        "name": "absolute-path",
        "command": '/usr/bin/git commit -m "z"',
        "expect": BLOCKED,
    },
    {
        "name": "and-chain",
        "command": 'git add -A && git commit -m "x"',
        "expect": BLOCKED,
    },
    {
        "name": "dash-c-config",
        "command": 'git -c user.name=x commit -m "y"',
        "expect": BLOCKED,
    },
    {"name": "merge", "command": "git merge feature", "expect": BLOCKED},
    {"name": "sh-c-double", "command": 'sh -c "git commit -m x"', "expect": ALLOWED},
    {"name": "sh-c-single", "command": "sh -c 'git commit -m x'", "expect": ALLOWED},
    {"name": "bash-c", "command": 'bash -c "git commit -m x"', "expect": ALLOWED},
    {"name": "git-alias", "command": "git ci -m x", "expect": ALLOWED},
    {"name": "shell-alias", "command": "gc -m x", "expect": ALLOWED},
    {"name": "var-indirect", "command": "GIT=git; $GIT commit -m x", "expect": ALLOWED},
    {"name": "not-a-commit", "command": "ls -la", "expect": ALLOWED},
]


def classify(returncode: int, stderr: str) -> str:
    """BLOCKED, ALLOWED or ERROR — never a guess.

    Exit 2 with a reason is the hook's block contract
    (`pre_tool_bash.py:327-331`). Exit 0 is an allow. Exit 2 with no reason is a
    broken gate, not an enforced one: AC-1 asks for blocked-WITH-our-reason, and
    a silent refusal would be recorded as enforcement it cannot demonstrate.
    Anything else means the hook did not reach a decision, which must never
    read as permission.
    """
    if returncode == 2:
        return BLOCKED if stderr.strip() else ERROR
    if returncode == 0:
        return ALLOWED
    return ERROR


def hook_env(smm_dir: Path) -> dict:
    """The contained environment every hook subprocess here runs under.

    Public because `arm_gates` drives the Stop gate through the same
    containment: one definition, so the two rigs cannot disagree about which
    variables are allowed to steer git or the SMM resolver.
    """
    env = {k: v for k, v in os.environ.items() if k not in _STRIP}
    env["SMM_DIR"] = str(smm_dir)
    env["CLAUDE_PLUGIN_ROOT"] = str(_PLUGIN_ROOT)
    return env


def run_shape(command: str, *, repo: Path, smm_dir: Path) -> dict:
    """Feed one command through the real hook and record what it did."""
    payload = {
        "hook_event_name": "PreToolUse",
        "session_id": "spike-commit-shapes",
        "cwd": str(repo),
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }
    try:
        result = subprocess.run(
            [sys.executable, str(_HOOK)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            env=hook_env(smm_dir),
            cwd=str(repo),
        )
        returncode, stderr = result.returncode, result.stderr
    except subprocess.TimeoutExpired:
        # A hang is not an allow. Recorded as ERROR with the reason visible.
        returncode, stderr = -1, f"timeout after {_TIMEOUT_SECONDS}s"
    return {
        "command": command,
        "returncode": returncode,
        "stderr": stderr,
        "classification": classify(returncode, stderr),
    }


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(repo),
        check=True,
        capture_output=True,
        text=True,
        env={k: v for k, v in os.environ.items() if k not in _STRIP},
    )


def build_rig(
    root: Path, stage_files: bool = True, repo_name: str = "proj"
) -> tuple[Path, Path]:
    """A git repo with the gate armed, plus a real SMM resolved by init.sh.

    The SMM is created by `init.sh` rather than hand-assembled: it is the single
    canonical resolver, and a hand-rolled directory that merely looks valid
    today would drift from what `validate_smm_dir` accepts tomorrow — failing
    silently, as an unarmed rig.

    Armed means cadence `commit` (the default, so no marker is written), no
    recorded review, and >= REVIEW_CYCLE_THRESHOLD staged code files.
    """
    # `repo_name` matters: a `worktree-story-` segment makes the shipped code
    # treat this cwd as a CLI teammate, which changes both the SessionStart
    # branch and the test-signal reader's scope. Defaulting to "proj" keeps the
    # commit-shape checks on the lead path; the Stop-gate checks override it,
    # because the real runs are teammates and that scoping was what broke.
    repo = root / repo_name
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "spike@example.invalid")
    _git(repo, "config", "user.name", "spike")
    # A non-code first commit so HEAD exists without pre-loading the diff.
    (repo / "README.md").write_text("spike rig\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "init")

    if stage_files:
        for name in ("alpha.py", "beta.py"):
            (repo / name).write_text(f"# {name}\nVALUE = 1\n", encoding="utf-8")
            _git(repo, "add", name)

    data_root = root / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k not in _STRIP}
    env["XP_AGENTS_DATA"] = str(data_root)
    resolved = subprocess.run(
        ["bash", str(_INIT_SH)],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        env=env,
        check=True,
    )
    smm_dir = Path(resolved.stdout.strip())
    if not smm_dir.is_dir():
        raise RigNotArmedError(
            f"init.sh did not produce a directory: {resolved.stdout!r}"
        )
    return repo, smm_dir


def assert_armed(*, repo: Path, smm_dir: Path) -> dict:
    """Refuse to produce a matrix unless the known-blocking shape blocks.

    "Blocked" is not enough: the commit chain holds several gates, and a refusal
    from a different one (tier-1 secret scan, unresolvable `-C`) would leave the
    review gate released while the report said ARMED. So the reason is pinned
    too, and the control's verbatim stderr travels with the refusal so the gate
    that actually bit is readable.
    """
    result = run_shape(CONTROL_COMMAND, repo=repo, smm_dir=smm_dir)
    if result["classification"] != BLOCKED:
        raise RigNotArmedError(
            "control shape did not block, so every 'not blocked' row below "
            "would be meaningless. The gate skips itself silently on an SMM "
            f"that fails to validate.\n  smm_dir: {smm_dir}\n"
            f"  exit: {result['returncode']}\n  stderr: {result['stderr']!r}"
        )
    if CONTROL_REASON_FRAGMENT not in result["stderr"]:
        raise RigNotArmedError(
            "control shape blocked, but not on the review gate — some other "
            f"commit gate bit, so the one being measured is not proven armed.\n"
            f"  expected reason to name: {CONTROL_REASON_FRAGMENT}\n"
            f"  smm_dir: {smm_dir}\n  stderr: {result['stderr']!r}"
        )
    return result


def render(results: list[dict]) -> str:
    """The matrix, as markdown.

    Refuses an empty result set: a table with no rows reads as "no shape
    bypasses the gate", which is the same confident lie an empty payload corpus
    tells one story earlier.
    """
    if not results:
        raise ValueError(
            "no shapes measured — an empty matrix reads as 'nothing bypasses "
            "the gate' rather than as 'nothing was measured'"
        )
    lines = [
        "| shape | command | result | reason (verbatim) |",
        "|---|---|---|---|",
    ]
    for r in results:
        reason = " ".join((r.get("stderr") or "").split())[:120] or "—"
        command = r["command"].replace("|", "\\|")
        lines.append(
            f"| {r.get('name', '—')} | `{command}` | "
            f"**{r['classification']}** | {reason} |"
        )
    errors = [r for r in results if r["classification"] == ERROR]
    if errors:
        lines.append("")
        lines.append(
            f"**{len(errors)} shape(s) produced no decision** — these are "
            "instrument failures, not measurements, and must not be read as "
            "bypasses:"
        )
        for r in errors:
            lines.append(f"- `{r['command']}` → exit {r['returncode']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--keep", action="store_true", help="leave the scratch rig on disk"
    )
    args = parser.parse_args()

    tmp = tempfile.mkdtemp(prefix="xp-spike-shapes-")
    root = Path(tmp)
    try:
        repo, smm_dir = build_rig(root)
        control = assert_armed(repo=repo, smm_dir=smm_dir)
        print(f"rig armed: control blocked with {control['stderr'].strip()!r}\n")
        results = [
            {**shape, **run_shape(shape["command"], repo=repo, smm_dir=smm_dir)}
            for shape in SHAPES
        ]
        print(render(results))
        drift = [r for r in results if r["classification"] != r["expect"]]
        if drift:
            print("\n**Detector drift since research** — expectations no longer hold:")
            for r in drift:
                print(
                    f"- {r['name']}: expected {r['expect']}, got {r['classification']}"
                )
            # Non-zero, so the pin FAILS rather than printing a warning a piped
            # or tailed run never shows: the matrix in the findings doc is stale
            # the moment any row moves.
            return 1
        return 0
    finally:
        if args.keep:
            print(f"\nrig kept at {root}", file=sys.stderr)
        else:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())

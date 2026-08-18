#!/usr/bin/env python3
"""Backstop: no test may launch either harness's real agent binary.

Imported by conftest for its SIDE EFFECT — importing this module patches
subprocess.Popen for the whole test session. It lives apart from conftest only to
keep that file under the size ceiling; the guard is not optional.

spawn_teammate.main() ends in run_with_tee -> subprocess.Popen(["claude", ...]).
Every test that drives main() is supposed to stub run_with_tee — but a test that
expects main() to REFUSE (raise) before it spawns can look safe while stubbing
nothing, and it is safe only for as long as the refusal actually works. In a TDD
red phase the refusal does not exist yet, so main() falls through and launches a
REAL agent. That agent comes up in the repo with the plugin loaded, runs the test
suite as part of its own lifecycle, re-enters that same test, and spawns another:

    pytest -> claude -p -> zsh -c pytest -> pytest -> claude -p -> ...

run_with_tee uses a plain Popen with NO start_new_session, so the children are not
in a killable process group: they reparent to init and outlive the run. This
actually happened — ~20 real, billable, recursive agents, one alive 22 minutes.

The lesson is not "remember to stub run_with_tee". It is that a test's safety must
never depend on the correctness of the code it is testing. So the prohibition is
enforced at the one syscall that can start a process, for the whole suite, under
BOTH runners: pytest imports conftest automatically, and unittest test modules
import it for their fixtures (test_no_test_can_spawn_a_real_agent.py pins that
every main()-driving module does, which is what makes the unittest path airtight).

Scoped to argv[0]'s basename: the suite spawns real python, git and bash children
constantly (dead_pid/live_pid, the integration pipeline) and those are untouched.

One binary is not one thing, though. The second harness's CLI both runs models
and manages plugins, so the block is by (binary, subcommand) rather than by
binary — see `_NON_MODEL_SUBCOMMANDS` for which forms are exempt and why absence
of a subcommand fails closed.
"""

import os
import shlex
import subprocess
from pathlib import Path

# BOTH harnesses' binaries. The plugin ships for two, and the recursion below is
# not harness-specific: a child on either one comes up in the repo with the plugin
# loaded and can run this suite. The guard covered only the first until story-014's
# capstone began driving a real model on both, leaving the second's spawns backed
# by nothing but a subprocess timeout.
REAL_AGENT_BINARIES = ("claude", "codex")
ALLOW_REAL_AGENT_ENV = "XP_ALLOW_REAL_AGENT_SPAWN"

# The second harness's binary is BOTH a model runner and a package manager:
# `codex exec` runs a model, `codex plugin add` installs a plugin and runs none.
# Three suites legitimately drive the latter (`_codex_harness._harness`), and
# blocking the binary wholesale broke six of their rows — measured, not predicted.
#
# So a named subcommand is exempt and everything else is blocked: an unrecognised
# subcommand fails CLOSED, which is the direction that cannot leak a billable
# recursive agent. The first harness gets no exemptions because nothing in the
# suite drives it for anything but a model run.
#
# The list is deliberately the shortest one that keeps the suite running:
# `plugin` is the form three suites drive, and the version/help forms print and
# exit. Server forms (`mcp`, `app-server`) are NOT here — they are long-lived and
# serve model turns to whatever connects, so exempting them ahead of any test
# needing them would widen the hole this allowlist exists to narrow. A suite that
# needs one later gets a loud block naming itself, which is the cheap direction.
_NON_MODEL_SUBCOMMANDS: dict[str, frozenset[str]] = {
    "codex": frozenset({"plugin", "--version", "-V", "--help", "-h"}),
}


class RealAgentSpawnBlocked(RuntimeError):
    """A test tried to launch a real agent binary. See the module docstring."""


def _is_real_agent(args) -> bool:
    """True when `args` would exec the real agent binary.

    Popen's first argument has THREE shapes and the program sits in a different
    place in each, so a single basename check on it is not enough:

      - a list/tuple -> the program is element 0;
      - a bare string (no shell) -> the whole string IS the program;
      - a shell command line (shell=True) -> the program is its FIRST TOKEN.

    A check that only took the basename of the whole thing would let
    `Popen("claude -p", shell=True)` through, because "claude -p" is not
    "claude". So the first token is checked as well as the whole string.

    The basename is what is compared, so an absolute path (or a PATH-resolved
    argv[0]) cannot slip past either.

    NOT covered, and it cannot be at this layer: a wrapper that execs the agent
    itself (`bash -c 'claude -p ...'`) has argv[0] == "bash". Nothing in this
    repo spawns the agent that way — teammate_runner passes a list whose element
    0 is the binary — and over-reaching into shell-string contents would start
    blocking ordinary `bash -c` children the suite depends on.
    """
    argv0 = args[0] if isinstance(args, (list, tuple)) and args else args
    if not isinstance(argv0, (str, bytes, os.PathLike)):
        return False
    text = os.fsdecode(argv0)
    try:
        tokens = shlex.split(text)
    except ValueError:  # unbalanced quotes — not a command line we can parse
        tokens = []

    for candidate in (text, *tokens[:1]):
        binary = Path(candidate).name
        if binary not in REAL_AGENT_BINARIES:
            continue
        return not _is_non_model_invocation(binary, args, tokens)
    return False


def _is_non_model_invocation(binary: str, args, shell_tokens: list[str]) -> bool:
    """Whether this invocation of *binary* is a management command, not a model.

    The subcommand sits one token after the program, in whichever of Popen's
    three shapes was used — element 1 of a list, or the second shell token. A
    flagless invocation (`codex` alone) has no subcommand and is NOT exempt: bare
    `codex` opens an interactive model session, so absence must fail closed.
    """
    exempt = _NON_MODEL_SUBCOMMANDS.get(binary)
    if not exempt:
        return False
    if isinstance(args, (list, tuple)):
        rest = [
            os.fsdecode(a) for a in args[1:] if isinstance(a, (str, bytes, os.PathLike))
        ]
    else:
        rest = shell_tokens[1:]
    return bool(rest) and rest[0] in exempt


_RealPopen = subprocess.Popen


class _NoRealAgentPopen(_RealPopen):
    """subprocess.Popen that refuses to exec the real agent binary.

    A subclass rather than a wrapper function so `isinstance(p, subprocess.Popen)`
    and runtime type annotations keep working across the suite.
    """

    def __init__(self, args, *rest, **kwargs):
        if _is_real_agent(args) and os.environ.get(ALLOW_REAL_AGENT_ENV) != "1":
            raise RealAgentSpawnBlocked(
                f"a test tried to launch a real agent binary, one of "
                f"{REAL_AGENT_BINARIES} ({args!r}). Tests must stub "
                "spawn_teammate.run_with_tee — "
                "including tests that expect main() to refuse before spawning, "
                "because a test's safety must never depend on the correctness of "
                "the code it is testing. A real spawn recursively re-runs this "
                f"suite. Set {ALLOW_REAL_AGENT_ENV}=1 only for a deliberate, "
                "supervised end-to-end."
            )
        super().__init__(args, *rest, **kwargs)


def install() -> None:
    """Patch subprocess.Popen session-wide. Idempotent.

    teammate_runner does `import subprocess` then `subprocess.Popen(...)`, i.e. it
    resolves the name off the module object at CALL time, so patching the module
    attribute covers the real spawn path. (A `from subprocess import Popen` there
    would bind the original at import time and escape this —
    test_no_test_can_spawn_a_real_agent.py pins that it does not.)
    """
    subprocess.Popen = _NoRealAgentPopen  # type: ignore[misc]


install()

#!/usr/bin/env python3
"""Backstop: no test may launch the real `claude` agent binary.

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
"""

import os
import subprocess
from pathlib import Path

REAL_AGENT_BINARY = "claude"
ALLOW_REAL_AGENT_ENV = "XP_ALLOW_REAL_AGENT_SPAWN"


class RealAgentSpawnBlocked(RuntimeError):
    """A test tried to launch the real `claude` binary. See the module docstring."""


def _is_real_agent(args) -> bool:
    """True when `args` would exec the real agent binary.

    Matches on the BASENAME so an absolute path (or a PATH-resolved argv[0])
    cannot slip past, and tolerates the non-list forms Popen accepts.
    """
    argv0 = args[0] if isinstance(args, (list, tuple)) and args else args
    if not isinstance(argv0, (str, bytes, os.PathLike)):
        return False
    return Path(os.fsdecode(argv0)).name == REAL_AGENT_BINARY


_RealPopen = subprocess.Popen


class _NoRealAgentPopen(_RealPopen):
    """subprocess.Popen that refuses to exec the real agent binary.

    A subclass rather than a wrapper function so `isinstance(p, subprocess.Popen)`
    and runtime type annotations keep working across the suite.
    """

    def __init__(self, args, *rest, **kwargs):
        if _is_real_agent(args) and os.environ.get(ALLOW_REAL_AGENT_ENV) != "1":
            raise RealAgentSpawnBlocked(
                f"a test tried to launch the real {REAL_AGENT_BINARY!r} binary "
                f"({args!r}). Tests must stub spawn_teammate.run_with_tee — "
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

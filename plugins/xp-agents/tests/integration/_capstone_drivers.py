#!/usr/bin/env python3
"""Running a real model against the capstone fixture, and judging what came back.

Split from `_capstone_plugin.py`, which builds the plugin tree. The boundary is
the question each answers: that module says what the plugin IS, this one says how
a harness is driven and how its answer is classified. They also change for
different reasons — a manifest shape shifts with the plugin format, a driver with
a CLI's flags.

**These drivers spawn real, billable models**, so everything here is gated. The
asymmetry in `child_env` is the safety property and not a detail: the guard's
escape hatch is set on the TEST process for the duration of a spawn, and stripped
from what the child inherits, so the spawn is permitted here and impossible
there. `_spawn_guard` records what that prevents.
"""

import functools
import os
import shutil
import subprocess
import unittest
from pathlib import Path
from typing import NamedTuple
from unittest.mock import patch

from _capstone_plugin import CapstonePlugin

# Opt-in, because a live row costs real model calls on two harnesses and the
# suite runs on every commit and every push (customer answer af6d7b1b0c4d).
LIVE_ENV = "XP_CAPSTONE_LIVE"

# `_spawn_guard`'s escape hatch, read from the TEST process's os.environ. The
# test sets it; the CHILD must never see it. See `child_env`.
GUARD_ENV = "XP_ALLOW_REAL_AGENT_SPAWN"

# Every withheld row opens with this. "Not measured" and "measured and absent"
# are opposite findings and only one is evidence, so AC3 requires a withheld row
# to say which it is — in words, where a reader sees it.
NOT_MEASURED_PREFIX = "not measured:"


def live_gate_reason(harness: str) -> str | None:
    """None when *harness*'s live row may run; otherwise why it was NOT measured.

    Two conditions, and the reason distinguishes them, because they mean
    different things to a reader: the operator did not ask for a live run, versus
    the operator asked and the harness is not installed. Neither is a negative
    result about the mechanism — which is why both answers open with
    `NOT_MEASURED_PREFIX` and neither can be read as a pass.
    """
    if os.environ.get(LIVE_ENV) != "1":
        return (
            f"{NOT_MEASURED_PREFIX} {LIVE_ENV}=1 was not set, so no model was put "
            f"in the loop for {harness}"
        )
    if shutil.which(harness) is None:
        return f"{NOT_MEASURED_PREFIX} {harness} is not on PATH"
    return None


def requires_live(harness: str):
    """Skip the decorated row, with its not-measured reason, unless live.

    Evaluated at call time rather than import time: a module-level decorator
    computed once would bake in whatever the environment looked like when pytest
    collected, which is not necessarily what it looks like when the row runs.
    """

    def decorate(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            reason = live_gate_reason(harness)
            if reason is not None:
                raise unittest.SkipTest(reason)
            return func(self, *args, **kwargs)

        return wrapper

    return decorate


def child_env(fixture: "CapstonePlugin", **extra: str) -> dict:
    """The environment for a REAL harness child.

    Both opt-in variables are REMOVED. Environment is inherited, so a child that
    kept them could run the suite, re-enter the capstone, and spawn again — with
    `GUARD_ENV` inherited the backstop would already be disarmed. `_spawn_guard`
    records where that went: ~20 real, billable, recursive agents, one alive 22
    minutes.

    The seed and the firing-log path DO travel: a seedless child gets a refusing
    preload, which looks exactly like a delivery failure, and a probe with no log
    cannot tell "injected nothing" from "never fired".
    """
    env = os.environ.copy()
    for inherited in (LIVE_ENV, GUARD_ENV):
        env.pop(inherited, None)
    env.update(fixture.env())
    env.update(extra)
    return env


# A live row is bounded by this and nothing else: the first harness exposes no
# `--max-turns`, so an unbounded call would hang the whole suite instead of
# failing one row. `_codex_harness` records what that cost once (a 600s run).
LIVE_TIMEOUT_SECONDS = 300

DELIVERED = "delivered"
WITHHELD = "withheld"
NOT_MEASURED = "not-measured"


class ModelRun(NamedTuple):
    """What one real model invocation produced."""

    stdout: str
    firings: int
    timed_out: bool


def verdict(run: ModelRun, token: str) -> str:
    """Classify a live run into exactly one of three outcomes.

    A pure function, so AC3's not-measured branch is assertable WITHOUT paying
    for a model call — the branch that only appears when something went wrong is
    otherwise the one branch never exercised.

    The ordering is the substance. A run where the handler never fired, or which
    died on the clock, tells us nothing about delivery and must never be recorded
    as a negative: `NOT_MEASURED` is not a weaker `WITHHELD`, it is a different
    claim. Only once the probe confirms the skill really engaged does the
    presence of the token mean anything either way.
    """
    if run.timed_out or run.firings == 0:
        return NOT_MEASURED
    return DELIVERED if token in run.stdout else WITHHELD


def run_first_harness(
    fixture: "CapstonePlugin",
    prompt: str,
    *,
    timeout: int = LIVE_TIMEOUT_SECONDS,
) -> ModelRun:
    """Put a REAL model in the loop on the first harness.

    `--allowed-tools Skill` is the control that makes the measurement mean
    something: with no Read, Bash or Grep there is no channel to the token except
    the injected context. The digest is ungreppable anyway, but a model that
    cannot read at all removes the question.

    The guard's escape hatch is set on THIS process only, for the duration of the
    call — `_spawn_guard` reads it from `os.environ` at Popen time, while
    `child_env` strips it from what the child inherits. That asymmetry is the
    whole safety property: the spawn is permitted here and impossible there.

    Firings are counted by the skill they NAME, never in bulk: the probe sits on
    a matcher that other tool calls can reach, and a firing that is not this
    skill's confirms nothing about this skill.
    """
    fixture.child_cwd.mkdir(parents=True, exist_ok=True)
    env = child_env(fixture)
    argv = [
        "claude",
        "-p",
        "--plugin-dir",
        str(fixture.plugin_dir),
        "--allowed-tools",
        "Skill",
        "--dangerously-skip-permissions",
    ]
    with patch.dict(os.environ, {GUARD_ENV: "1"}):
        try:
            completed = subprocess.run(
                argv,
                input=prompt,
                capture_output=True,
                text=True,
                cwd=fixture.child_cwd,
                env=env,
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return ModelRun(
                stdout="",
                firings=fixture.firings(naming=fixture.skill_name),
                timed_out=True,
            )
    return ModelRun(
        stdout=completed.stdout,
        firings=fixture.firings(naming=fixture.skill_name),
        timed_out=False,
    )


# The second harness's fixture ships under its OWN name. Two reasons, both
# measured: its leg has no namespace check (5aaeb8d68cfe), and it must install
# beside the developer's real xp-agents without colliding with it.
SECOND_HARNESS_PLUGIN_NAME = "xp-capstone"

_INSTALL_TIMEOUT_SECONDS = 120


def _codex_plugin(*args: str, timeout: int = _INSTALL_TIMEOUT_SECONDS):
    """A `codex plugin ...` management call.

    Needs no spawn-guard escape hatch: the guard blocks that binary by
    (binary, subcommand) and `plugin` is a management form that runs no model.
    Only the `exec` below is a spawn.
    """
    return subprocess.run(
        ["codex", "plugin", *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def uninstall_second_harness(fixture: "CapstonePlugin") -> None:
    """Remove the fixture from the harness home. Safe to call when absent."""
    _codex_plugin("remove", fixture.plugin_id)
    _codex_plugin("marketplace", "remove", fixture.marketplace_name)


def install_second_harness(fixture: "CapstonePlugin", register_cleanup) -> Path:
    """Install the fixture and return the tree the harness copied it into.

    **This mutates the developer's real harness home**, and it is the only way:
    that harness has no `--plugin-dir`, and its credentials live in the home, so
    an isolated one authenticates nothing (401). The fixture ships under its own
    plugin and marketplace names so it cannot collide with a real install.

    *register_cleanup* is invoked BEFORE anything is installed — pass
    `self.addCleanup`. Registering after would leave a stray marketplace and
    plugin in the developer's config whenever the install itself fails partway.
    """
    register_cleanup(uninstall_second_harness, fixture)

    registered = _codex_plugin("marketplace", "add", str(fixture.root))
    if registered.returncode != 0:
        raise AssertionError(f"marketplace add failed: {registered.stderr}")
    added = _codex_plugin("add", fixture.plugin_id)
    if added.returncode != 0:
        raise AssertionError(f"plugin add failed: {added.stderr}")

    for line in added.stdout.splitlines():
        if line.startswith("Installed plugin root: "):
            return Path(line.removeprefix("Installed plugin root: ").strip())
    raise AssertionError(f"install reported no plugin root: {added.stdout!r}")


def run_second_harness(
    fixture: "CapstonePlugin",
    installed_root: Path,
    *,
    timeout: int = LIVE_TIMEOUT_SECONDS,
) -> ModelRun:
    """Put a REAL model in the loop on the second harness.

    Three flags each answer something measured rather than guessed:

    `--dangerously-bypass-hook-trust` — WITHOUT it a freshly installed plugin's
    hooks do not fire AT ALL. Measured by running the identical install and
    prompt twice: 0 firings without, 1 with. That is a property of the harness,
    not of this fixture, and it is filed as concern bb2d47396ba6 because a user
    installing this plugin there gets no gates until the hooks are trusted.

    `-s read-only` — the trigger IS a shell read, so the model must be allowed
    to run one; read-only is the narrowest policy that permits it.

    `input=""` — that CLI appends piped stdin to a prompt argument and waits on
    it, so an unclosed stdin hangs the call until the timeout.

    The read command is named EXACTLY, because `_READ_COMMANDS` whitelists eight
    and a read by any other means fires nothing — which would report
    not-measured for a reason unrelated to delivery.

    Firings are counted by the skill they NAME. Here that is load-bearing rather
    than tidy: the probe is registered on the SHELL matcher, so every command the
    model runs fires it, and a bulk count would let a run that never read the
    skill body report a confirmed engagement — turning the control row, which
    carries the weight on this harness, into a row that passes while measuring
    nothing.
    """
    fixture.child_cwd.mkdir(parents=True, exist_ok=True)
    body = installed_root / "skills" / fixture.skill_name / "SKILL.md"
    prompt = (
        f"Run exactly this shell command: cat {body}\n"
        "Then follow the instructions in the file you just printed."
    )
    argv = [
        "codex",
        "exec",
        "-C",
        str(fixture.child_cwd),
        "--skip-git-repo-check",
        "-s",
        "read-only",
        "--dangerously-bypass-hook-trust",
        prompt,
    ]
    env = child_env(fixture)
    with patch.dict(os.environ, {GUARD_ENV: "1"}):
        try:
            completed = subprocess.run(
                argv,
                input="",
                capture_output=True,
                text=True,
                cwd=fixture.child_cwd,
                env=env,
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return ModelRun(
                stdout="",
                firings=fixture.firings(naming=fixture.skill_name),
                timed_out=True,
            )
    return ModelRun(
        stdout=completed.stdout,
        firings=fixture.firings(naming=fixture.skill_name),
        timed_out=False,
    )

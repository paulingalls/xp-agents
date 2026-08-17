#!/usr/bin/env python3
"""The synthetic plugin the capstone loads into a real harness.

A purpose-built plugin rather than a shipped skill, for a measured reason: the
close preloads ARM a close cycle by running, which once left four orphaned cycles
behind. The capstone must be able to run repeatedly without side effects, so it
needs a preload of its own.

It resolves like any shipped skill because `skill_preload_map` discovers by
DIRECTORY (`_names_a_shipped_skill` stats `<root>/skills/<name>`, and
`_discover_preload_scripts` globs `skills/*/scripts/*.sh`) rather than from a
static table. `CLAUDE_PLUGIN_ROOT` is what selects it, and a real harness sets
exactly that per-plugin — measured, discovery 46f3b9ce1447.

Three properties are load-bearing and each was measured rather than assumed:

1. **The plugin is named `xp-agents`.** `tool_input.skill` arrives
   plugin-qualified (`xp-agents:<skill>`), and `target_routing.strip_our_namespace`
   returns None for any other namespace — so the handler would fall through, find
   no read, inject nothing, and report nothing. A differently-named fixture fails
   silently, which is the whole failure class this milestone exists to end.
2. **The token is COMPUTED, never stored.** The preload digests a seed, so the
   literal value is on no disk. A stored marker would be greppable, and a live
   pass would then be explainable without injection.
3. **A firing probe sits beside the handler.** It records that the skill really
   engaged, which is what tells *fired and injected nothing* apart from *never
   fired*. Only the second is AC3's not-measured verdict.

The preload digests with `python3` rather than `shasum`/`sha256sum`: those two
spellings differ across macOS and Linux, and this fixture must not carry a
platform assumption into a suite that runs on both.
"""

import hashlib
import json
import os
import secrets
import shutil
import stat
import subprocess
import unittest
from pathlib import Path
from typing import NamedTuple
from unittest.mock import patch

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

# The namespace `strip_our_namespace` accepts. Not a preference — see §1 above.
OUR_PLUGIN_NAME = "xp-agents"

# Deliberately not `xp-assign`, which carries an `_EXTRA_ARGS` entry in
# `skill_preload_map`: borrowing a name with special resolution would test that
# entry rather than the delivery chain.
SKILL_NAME = "xp-capstone-probe"

_TOKEN_KEY = "CAPSTONE_TOKEN"

# The seed lives ONLY here. Putting it in a file would make the token derivable
# from disk, and the token being underivable is the whole measurement.
SEED_ENV = "XP_CAPSTONE_SEED"
_SEED_ENV = SEED_ENV

FIRING_LOG_ENV = "XP_CAPSTONE_FIRING_LOG"

# Long enough that a model cannot land on it by chance, short enough to read in a
# transcript. 16 hex = 64 bits.
_TOKEN_CHARS = 16

_PRELOAD_BODY = f"""#!/usr/bin/env bash
set -euo pipefail
# Computes the token; stores it nowhere. See _capstone_plugin.py §2.
python3 - <<'PY'
import hashlib, os, sys

seed = os.environ.get({_SEED_ENV!r}, "")
if not seed:
    # REFUSE rather than digest the empty string. Digesting "" yields a CONSTANT,
    # and a constant is a silent-pass channel: every fixture would emit the same
    # token, so a row asserting "some token arrived" would pass with the seed
    # never delivered. A non-zero exit makes the handler inject nothing instead,
    # which is loud. Pinned by test_a_missing_seed_injects_nothing_not_a_constant.
    sys.stderr.write("capstone preload: no seed in env\\n")
    raise SystemExit(1)
digest = hashlib.sha256(seed.encode()).hexdigest()[:{_TOKEN_CHARS}]
print(f"{_TOKEN_KEY}={{digest}}")
PY
"""

_PROBE_BODY = '''#!/usr/bin/env python3
"""Records that the skill engaged, so a missing token can be attributed.

Appends one line and exits 0 without emitting context, so it can never be
mistaken for the delivery channel it exists to disambiguate from.
"""
import json
import os
import pathlib
import sys

try:
    payload = json.load(sys.stdin)
except Exception:  # noqa: BLE001 - a probe must never fail the tool call
    payload = {}
log = pathlib.Path(os.environ["XP_CAPSTONE_FIRING_LOG"])
log.parent.mkdir(parents=True, exist_ok=True)
with log.open("a") as fh:
    fh.write(json.dumps({"tool_name": payload.get("tool_name")}) + "\\n")
sys.exit(0)
'''

_SKILL_BODY = f"""---
name: {SKILL_NAME}
description: >-
  Capstone probe. Reports the value of {_TOKEN_KEY} from its injected state.
  Not a shipped workflow — it exists so the capstone can measure delivery
  without running a real preload's side effects.
---

# Capstone probe

Your injected context contains a line of the form `{_TOKEN_KEY}=<value>`.

Reply with that value and nothing else. If your context contains no such line,
reply `NO-TOKEN`.
"""


class CapstonePlugin(NamedTuple):
    """A built tree plus everything a caller needs to assert against it.

    `root` is a REPO-shaped marketplace root and `plugin_dir` the plugin inside
    it, mirroring this repository's own layout. Both are needed because the two
    harnesses load a plugin differently: the first takes a directory
    (`--plugin-dir <plugin_dir>`), the second has no such flag at all and can
    only install from a marketplace (`marketplace add <root>`).
    """

    root: Path
    plugin_dir: Path
    plugin_name: str
    marketplace_name: str
    skill_name: str
    seed: str
    expected_token: str
    skill_body: Path
    firing_log: Path
    injects: bool

    @property
    def plugin_id(self) -> str:
        """The `PLUGIN@MARKETPLACE` selector the second harness installs by."""
        return f"{self.plugin_name}@{self.marketplace_name}"

    def hook_entries(self, manifest_dir: str) -> list[dict]:
        """The PreToolUse entries the manifest in *manifest_dir* points at.

        Follows the manifest's own `hooks` key when it has one, so a caller reads
        what that harness would read rather than guessing the filename. The
        primary manifest omits the key and gets directory discovery, exactly as
        the shipped pair does.
        """
        manifest = json.loads(
            (self.plugin_dir / manifest_dir / "plugin.json").read_text()
        )
        named = manifest.get("hooks")
        hooks_file = (
            (self.plugin_dir / named.lstrip("./"))
            if named
            else self.plugin_dir / "hooks" / "hooks.json"
        )
        return json.loads(hooks_file.read_text())["hooks"]["PreToolUse"]

    def env(self) -> dict:
        """The two variables the built tree reads at run time."""
        return {SEED_ENV: self.seed, FIRING_LOG_ENV: str(self.firing_log)}

    @property
    def child_cwd(self) -> Path:
        """Where a real harness child runs: inside the fixture, never the repo.

        A child whose cwd is this checkout can reach the suite, and a child that
        can run the suite is the recursion `_spawn_guard` was written about.
        """
        return self.root / "child-cwd"

    def firings(self) -> int:
        if not self.firing_log.exists():
            return 0
        return len([line for line in self.firing_log.read_text().splitlines() if line])


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
        def wrapper(self, *args, **kwargs):
            reason = live_gate_reason(harness)
            if reason is not None:
                raise unittest.SkipTest(reason)
            return func(self, *args, **kwargs)

        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
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
            return ModelRun(stdout="", firings=fixture.firings(), timed_out=True)
    return ModelRun(stdout=completed.stdout, firings=fixture.firings(), timed_out=False)


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
            return ModelRun(stdout="", firings=fixture.firings(), timed_out=True)
    return ModelRun(stdout=completed.stdout, firings=fixture.firings(), timed_out=False)


def _write_executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _handler_path() -> Path:
    """The REPO's handler, absolute. A copy would prove a copy works."""
    return (
        Path(__file__).parent.parent.parent / "scripts" / "preload_injection.py"
    ).resolve()


def _hook_entries(probe: Path, *, inject: bool, shell_read: bool) -> list[dict]:
    """PreToolUse entries: the probe always, the handler only when injecting.

    The probe stays in the control so a run with no token still shows the skill
    engaged — dropping both would make the control indistinguishable from a run
    where nothing fired.
    """

    def hooks_for() -> list[dict]:
        entries = [{"type": "command", "command": f"python3 {probe}"}]
        if inject:
            entries.append({"type": "command", "command": f"python3 {_handler_path()}"})
        return entries

    matchers = ["Skill"] + (["Bash"] if shell_read else [])
    return [{"matcher": m, "hooks": hooks_for()} for m in matchers]


def build_capstone_plugin(
    root: Path,
    *,
    inject: bool = True,
    seed: str | None = None,
    plugin_name: str = OUR_PLUGIN_NAME,
) -> CapstonePlugin:
    """Build a repo-shaped marketplace at *root* and return a handle to it.

    *inject* False builds AC2's control: same tree, same skill, same probe, no
    handler. *seed* is generated when absent; a caller passes one only to assert
    that two different seeds yield two different tokens.

    *plugin_name* defaults to ours because the FIRST harness's Skill leg is
    namespace-locked and injects nothing under any other name. The second
    harness's leg is not (`_skill_name_from_path` returns a directory name), so
    its fixture ships under a distinct name — which is what lets it install
    beside a real xp-agents without colliding with it. Measured, 5aaeb8d68cfe.
    """
    seed = seed or secrets.token_hex(16)
    token = hashlib.sha256(seed.encode()).hexdigest()[:_TOKEN_CHARS]
    marketplace_name = f"{plugin_name}-capstone-market"
    plugin_root = root / "plugins" / plugin_name

    marketplace = root / ".claude-plugin" / "marketplace.json"
    marketplace.parent.mkdir(parents=True, exist_ok=True)
    marketplace.write_text(
        json.dumps(
            {
                "name": marketplace_name,
                "owner": {"name": "xp-agents capstone"},
                "plugins": [
                    {
                        "name": plugin_name,
                        "source": f"./plugins/{plugin_name}",
                        "description": "Capstone fixture.",
                    }
                ],
            },
            indent=2,
        )
        + "\n"
    )

    probe = plugin_root / "hooks" / "firing_probe.py"
    _write_executable(probe, _PROBE_BODY)
    _write_executable(
        plugin_root / "skills" / SKILL_NAME / "scripts" / "preload.sh", _PRELOAD_BODY
    )

    skill_body = plugin_root / "skills" / SKILL_NAME / "SKILL.md"
    skill_body.parent.mkdir(parents=True, exist_ok=True)
    skill_body.write_text(_SKILL_BODY)

    shared = {
        "name": plugin_name,
        "version": "0.0.0",
        "description": "Capstone fixture — does injected state reach a model?",
    }

    # Primary: directory discovery finds hooks/hooks.json, as the shipped pair does.
    primary = plugin_root / ".claude-plugin" / "plugin.json"
    primary.parent.mkdir(parents=True, exist_ok=True)
    primary.write_text(json.dumps(shared, indent=2) + "\n")
    (plugin_root / "hooks" / "hooks.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": _hook_entries(probe, inject=inject, shell_read=False)
                }
            },
            indent=2,
        )
        + "\n"
    )

    # Derived: names its hooks file explicitly, because on that harness a
    # component key REPLACES directory discovery rather than merging — and adds
    # the shell-read trigger, its only way in.
    derived = plugin_root / ".codex-plugin" / "plugin.json"
    derived.parent.mkdir(parents=True, exist_ok=True)
    derived.write_text(
        json.dumps(
            {**shared, "skills": "./skills/", "hooks": "./hooks/hooks.codex.json"},
            indent=2,
        )
        + "\n"
    )
    (plugin_root / "hooks" / "hooks.codex.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": _hook_entries(probe, inject=inject, shell_read=True)
                }
            },
            indent=2,
        )
        + "\n"
    )

    return CapstonePlugin(
        root=root,
        plugin_dir=plugin_root,
        plugin_name=plugin_name,
        marketplace_name=marketplace_name,
        skill_name=SKILL_NAME,
        seed=seed,
        expected_token=token,
        skill_body=skill_body,
        firing_log=root / "firings.jsonl",
        injects=inject,
    )

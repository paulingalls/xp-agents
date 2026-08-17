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
import secrets
import stat
from pathlib import Path
from typing import NamedTuple

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

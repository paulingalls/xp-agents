#!/usr/bin/env python3
"""story-005 instrument: what does Codex do with our SKILL.md frontmatter?

Throwaway spike code; deleted at sprint close with the rest of the rig.

Drives `codex app-server` over stdio JSON-RPC (`skills/list`) and reports, per
frontmatter key, whether the loader rejects it, ignores it, or cannot say.

TWO disciplines carried over from the rig, both load-bearing:

1. Refuse rather than emit a false-negative table (`tabulate_fields.py`). An empty
   skills list and a broken probe read identically on the page, so an empty result
   raises instead of reporting "no errors found".

2. Arm before measuring (`arm_gates.py`). `errors: []` proves nothing until a
   genuinely malformed skill has been shown to produce a non-empty `errors`. The
   arming control is a precondition of the AC-1 verdict, not a nicety: without it
   "Codex does not reject unknown keys" is indistinguishable from "this field is
   never populated". `main` enforces it — `assert_armed` runs on the live payload
   before anything is printed, because a precondition only pinned in the unit tests
   is a precondition the measurement never has to satisfy.

What this instrument CANNOT do, recorded so nobody reads more into its output than
is there: the loader surfaces no frontmatter keys at all (see `LOADER_ANSWERS`), so
it separates rejected from not-rejected and nothing finer. Warn-vs-silently-ignore
belongs to the session channel, and whether a key is HONOURED needs a model turn.
"""

from __future__ import annotations

import contextlib
import json
import subprocess
import time
from pathlib import Path

# --- key classification ------------------------------------------------------

DEFINED = "defined"
UNDOCUMENTED = "undocumented"

#: Frontmatter keys Codex documents itself, quoted from the skill-authoring
#: guidance embedded in the codex binary ("SKILL.md frontmatter (YAML between ---
#: markers)"). `effort` is deliberately absent — Codex documents `model` instead,
#: which is the whole point of AC-1.
CODEX_DOCUMENTED_KEYS = frozenset(
    {
        "name",
        "description",
        "argument-hint",
        "disable-model-invocation",
        "user-invocable",
        "allowed-tools",
        "context",
        "agent",
        "model",
    }
)

#: The allowlist in Codex's own bundled `skill-creator/scripts/quick_validate.py`.
#: Narrower than the documented set above — a contradiction inside Codex, and the
#: reason a user running Codex's own validator on our skills sees failures the
#: loader never raises.
BUNDLED_VALIDATOR_ALLOWLIST = frozenset(
    {
        "name",
        "description",
        "license",
        "allowed-tools",
        "metadata",
    }
)

#: Field names the loader emits for every skill regardless of frontmatter, so
#: their presence in a field set is not a frontmatter leak. `SkillMetadata` also
#: carries path/scope/enabled/dependencies/interface/shortDescription, none of
#: which collide with a frontmatter key; these two do.
LOADER_NATIVE_FIELDS = frozenset({"name", "description"})

#: Which AC-1 verdicts the loader channel can actually answer. Phase 0 measured
#: this: SkillMetadata carries name/description/path/scope/enabled (+dependencies,
#: interface, shortDescription) and no frontmatter key whatsoever.
LOADER_ANSWERS = {"rejects": True, "warns": False, "honoured": False}

LOADED_CLEAN = "loaded-clean"
REJECTED = "rejected"

PLUGIN_SKILL_PREFIX = "xp-agents:"


class ProbeRefusal(RuntimeError):
    """The probe cannot produce a trustworthy table and declines to produce one."""


class ProbeNotArmed(RuntimeError):
    """The loader never reported an error, so `errors: []` carries no information."""


def classify_key(key: str) -> str:
    return DEFINED if key in CODEX_DOCUMENTED_KEYS else UNDOCUMENTED


def shipped_frontmatter_keys(skills_dir: Path | None = None) -> frozenset[str]:
    """The keys we ship, read off disk — never a hand-typed list.

    A literal here drifts silently: it would put a key we do NOT ship into the
    validator-rejects table (or, worse, omit one we added), and both readings feed
    the findings doc.
    """
    return frozenset(shipped_key_census(skills_dir or repo_skills_dir()))


def bundled_validator_rejects(keys: frozenset[str] | None = None) -> set[str]:
    """Which of our shipped keys Codex's own bundled validator would reject."""
    return set(keys if keys is not None else shipped_frontmatter_keys()) - set(
        BUNDLED_VALIDATOR_ALLOWLIST
    )


def frontmatter_keys_in(
    field_names, known_keys: frozenset[str] | None = None
) -> set[str]:
    """Frontmatter keys leaking into a loader field set. Empty is the Phase 0 result.

    Matched against every key we ship UNION every key Codex documents, not just
    ours: an upgrade that starts surfacing `argument-hint` widens what this channel
    can prove just as much as one that surfaces `effort`, and a detector scoped to
    our own keys would miss it.
    """
    known = (
        known_keys
        if known_keys is not None
        else shipped_frontmatter_keys() | CODEX_DOCUMENTED_KEYS
    )
    return (set(field_names) & set(known)) - set(LOADER_NATIVE_FIELDS)


def loader_can_answer(verdict: str) -> bool:
    try:
        return LOADER_ANSWERS[verdict]
    except KeyError:
        raise ProbeRefusal(f"unknown verdict {verdict!r}") from None


# --- shipped census, read off disk ------------------------------------------


def repo_skills_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "skills"


def shipped_skill_names(skills_dir: Path) -> list[str]:
    return sorted(p.parent.name for p in skills_dir.glob("*/SKILL.md"))


def _frontmatter_keys(skill_md: Path) -> list[str]:
    """Top-level frontmatter keys. Refuses an unclosed block rather than reading on.

    Without the closing-delimiter check, an unclosed `---` walks into the body and
    every `## Step 1: …` heading lands in the census as a key — invented rows in the
    table AC-1's verdict is read off.
    """
    lines = skill_md.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return []
    keys: list[str] = []
    closed = False
    for line in lines[1:]:
        if line.strip() == "---":
            closed = True
            break
        if line[:1].isspace() or not line.strip():
            continue
        head, sep, _ = line.partition(":")
        if sep:
            keys.append(head.strip())
    if not closed:
        raise ProbeRefusal(f"{skill_md} opens frontmatter and never closes it")
    return keys


def shipped_key_census(skills_dir: Path) -> dict[str, int]:
    """How many shipped skills carry each frontmatter key. Read from disk, always."""
    census: dict[str, int] = {}
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        for key in _frontmatter_keys(skill_md):
            census[key] = census.get(key, 0) + 1
    if not census:
        raise ProbeRefusal(
            f"no shipped skills under {skills_dir} - refusing an empty census"
        )
    return census


# --- loader observation ------------------------------------------------------


def errors_naming(errors, skill_name: str) -> list:
    """The subset of a directory-level `errors` array that names ONE skill.

    `skills/list` reports errors per SCAN, not per skill, and the arming control is
    a skill of its own sitting in the same scan. So a non-empty `errors` in the run
    that reads our skills as clean is the loader's rejection path WORKING, not a
    rejection of ours — reading the array unfiltered conflates the two and turns the
    arming control into a self-inflicted false positive.
    """
    return [e for e in errors if f"/{skill_name}/" in str(e.get("path", ""))]


def classify_load_outcome(entry, errors) -> str:
    """Verdict for ONE skill. `errors` must already be attributed to it."""
    if errors:
        return REJECTED
    if entry is None:
        raise ProbeRefusal(
            "skill neither listed nor errored - the loader said nothing about it"
        )
    return LOADED_CLEAN


def assert_armed(loader_errors) -> None:
    """The loader's rejection path MUST have fired, or `errors: []` means nothing.

    Called on the live path with the whole run's `errors`, which is non-empty only
    while the malformed control is installed in the cache. A reinstall wipes the
    control, so this is also what stops a post-reinstall run from printing a clean
    table that proves nothing.
    """
    if not loader_errors:
        raise ProbeNotArmed(
            "the arming control (a malformed skill) produced no loader error, so an "
            "empty `errors` array cannot be read as 'no rejection' — the field may "
            "simply never be populated. AC-1's verdict is void until this passes. "
            "Re-inject the malformed control into the installed cache and re-run."
        )


def summarise_load(skills) -> dict:
    """Summarise `skills/list`. Refuses on the two indistinguishable empties."""
    if not skills:
        raise ProbeRefusal(
            "skills/list returned nothing - probe broken or plugin absent"
        )
    ours = [s for s in skills if str(s.get("name", "")).startswith(PLUGIN_SKILL_PREFIX)]
    if not ours:
        raise ProbeRefusal(
            f"skills/list returned {len(skills)} skill(s) but none under "
            f"{PLUGIN_SKILL_PREFIX!r} — the plugin is not installed; refusing to "
            "report 'no rejections' from a run that never loaded our skills"
        )
    return {
        "total": len(skills),
        "ours": len(ours),
        "names": sorted(s["name"] for s in ours),
        "disabled": sorted(s["name"] for s in ours if not s.get("enabled", False)),
    }


def app_server_skills(cwd: Path | None = None, timeout: float = 25.0) -> dict:
    """One `initialize` + `skills/list` round trip. Returns the raw result object."""
    proc = subprocess.Popen(
        ["codex", "app-server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        cwd=str(cwd) if cwd else None,
    )
    try:
        proc.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "clientInfo": {
                            "name": "xp-spike",
                            "title": "xp-spike",
                            "version": "0.0.1",
                        }
                    },
                }
            )
            + "\n"
        )
        proc.stdin.flush()
        time.sleep(1.0)
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "initialized"}) + "\n")
        proc.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "skills/list",
                    "params": {"forceReload": True},
                }
            )
            + "\n"
        )
        proc.stdin.flush()
        time.sleep(min(timeout, 8.0))
    finally:
        with contextlib.suppress(OSError, ValueError):
            proc.stdin.close()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        stdout = proc.stdout.read() or ""
        stderr = proc.stderr.read() or ""

    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("id") == 2 and "result" in msg:
            return {"result": msg["result"], "stderr": stderr}
    raise ProbeRefusal(f"no skills/list response on stdout (stderr: {stderr[:300]!r})")


def observed_loader_fields(cwd: Path | None = None) -> set[str]:
    """Union of field names the loader actually returned. The AC-1 measurement."""
    payload = app_server_skills(cwd=cwd)
    entries = payload["result"].get("data", [])
    fields = {k for e in entries for s in e.get("skills", []) for k in s}
    if not fields:
        raise ProbeRefusal(
            "skills/list returned no skill objects - refusing an empty field set"
        )
    return fields


def main() -> int:
    skills_dir = repo_skills_dir()
    census = shipped_key_census(skills_dir)
    payload = app_server_skills()
    entries = payload["result"].get("data", [])
    skills = [s for e in entries for s in e.get("skills", [])]
    errors = [er for e in entries for er in e.get("errors", [])]
    summary = summarise_load(skills)
    fields = {k for s in skills for k in s}

    assert_armed(errors)
    listed = {s.get("name", ""): s for s in skills}
    per_skill = {
        name: classify_load_outcome(
            listed.get(f"{PLUGIN_SKILL_PREFIX}{name}"), errors_naming(errors, name)
        )
        for name in shipped_skill_names(skills_dir)
    }
    rejected_ours = sorted(n for n, v in per_skill.items() if v == REJECTED)

    print("# story-005 — skill configuration surface\n")
    print("## Shipped frontmatter census (read from disk)\n")
    print("| key | skills | Codex classifies |")
    print("|---|---|---|")
    for key, count in sorted(census.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"| `{key}` | {count} | {classify_key(key)} |")

    print("\n## Loader outcome\n")
    print(f"- skills listed: {summary['total']} total, {summary['ours']} ours")
    print(f"- loader errors: {len(errors)} (arming control armed the channel)")
    print(f"- of those, naming a skill we ship: {rejected_ours or 'none'}")
    print(f"- disabled: {summary['disabled'] or 'none'}")
    print(f"- app-server stderr: {len(payload['stderr'])} bytes")
    print(
        f"- frontmatter keys leaked into loader output: "
        f"{sorted(frontmatter_keys_in(fields)) or 'none'}"
    )

    print("\n## What this channel can and cannot answer\n")
    for verdict, answerable in LOADER_ANSWERS.items():
        print(f"- `{verdict}`: {'answerable' if answerable else 'NOT answerable here'}")

    print("\n## Codex's own bundled validator\n")
    print(f"- would reject: {sorted(bundled_validator_rejects())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

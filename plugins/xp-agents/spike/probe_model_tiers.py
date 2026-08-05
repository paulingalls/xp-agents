#!/usr/bin/env python3
"""story-006 instrument: Codex's model catalog and per-model effort support.

Throwaway spike code; deleted at sprint close with the rest of the rig.

Two channels, because one cannot answer the question alone:

1. **`model/list` over `codex app-server`** — what each model *advertises*.
   `supportedReasoningEfforts` is a required per-model field, which is exactly the
   per-model shape the tier abstraction needs.

2. **The rollout session log** — what the harness *actually used*. Advertised is not
   enforced, and interface contract 3 forbids reporting a clamped substitute as if
   the requested pair worked. `~/.codex/sessions/**/rollout-*.jsonl` records
   `payload.model` and `payload.effort`; a headless `codex exec` writes one (verified
   on story-005's own AC-3b runs).

Why not `--strict-config`: it rejects an unrecognised or MISSING field, not a
well-formed value of a recognised one. `model_reasoning_effort=ultra` on a model
lacking `ultra` sails past it, so it cannot separate accepted from clamped.

**Isolate the operator by OVERRIDE, not by discarding config.**
`~/.codex/config.toml` may set `model` and `model_reasoning_effort` globally — this
machine's does. `--ignore-user-config` looks like the fix and is not: it also discards
`model_provider` and auth, which the arming control caught on its first live run
(401 Unauthorized against api.openai.com). Explicit `-m` and
`-c model_reasoning_effort=` already beat config.toml — verified: requesting `low`
against a config that says `high` yields an effective `low`. A run that OMITS the
effort flag is the control that measures the operator override.

**Arming is an instrument property, not the harness's verdict.** The control here is
that requested-vs-effective is READABLE. Whether Codex refuses or silently clamps is
the finding, and a clamp still emits the matrix (annotated). Arming on "the harness
refused" would let an adverse-but-valid measurement block story-007, which is
dep-blocked on this story alone.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

# The extracted transport. Reused rather than copied: a second client would
# duplicate the sleep budget and drift.
from probe_skill_surface import ProbeRefusal, app_server_call

CATALOG_METHOD = "model/list"

#: Fields a genuine `model/list` record carries. A row lacking them did not come
#: from the catalog, and the matrix refuses it — this is the provenance guard that
#: stops a hand-typed table entering as if it had been measured.
_CATALOG_KEYS = ("id", "supportedReasoningEfforts", "defaultReasoningEffort")

ACCEPTED = "accepted"
CLAMPED = "clamped"
REFUSED = "refused"

ADVERTISED_NOT_ENFORCED = "advertised-not-enforced"

_SESSIONS_ROOT = Path.home() / ".codex" / "sessions"


class ProbeNotArmed(RuntimeError):
    """Requested-vs-effective is unreadable, so no verdict can be trusted."""


# --- channel 1: the catalog ---------------------------------------------------


def model_catalog(cwd: Path | None = None, include_hidden: bool = True) -> list[dict]:
    """Live `model/list`. Never a literal — this is the only source of rows."""
    payload = app_server_call(
        CATALOG_METHOD, {"includeHidden": include_hidden, "limit": 100}, cwd=cwd
    )
    data = payload["result"].get("data")
    if data is None:
        raise ProbeRefusal(f"{CATALOG_METHOD} returned no data key")
    return data


def assert_catalog_usable(models) -> None:
    """Refuse an empty catalog, or one with no default model.

    Both are indistinguishable from a working probe on the page, and neither can
    support a tier mapping: the default model is the baseline every comparison and
    every plan-doc correction is stated against.
    """
    if not models:
        raise ProbeRefusal(
            f"{CATALOG_METHOD} returned zero models - probe broken or not "
            "authenticated; refusing to emit an empty matrix"
        )
    if not any(m.get("isDefault") for m in models):
        raise ProbeRefusal(
            f"{CATALOG_METHOD} returned {len(models)} model(s) but none marked "
            "isDefault - the record shape has changed and the matrix would be "
            "keyed off an assumption"
        )


def effort_matrix(models) -> dict[str, list[str]]:
    """model id -> advertised efforts, derived only from catalog records.

    Provenance guard: every record must carry the catalog's own required fields.
    A dict someone typed from the plan doc is rejected rather than tabulated, which
    is the difference between a measurement and a restatement.
    """
    matrix: dict[str, list[str]] = {}
    for record in models:
        missing = [k for k in _CATALOG_KEYS if k not in record]
        if missing:
            raise ProbeRefusal(
                f"record {record.get('id', '<no id>')!r} is missing catalog "
                f"field(s) {missing} - it did not come from {CATALOG_METHOD}, so it "
                "cannot enter the matrix"
            )
        efforts = [
            option["reasoningEffort"]
            for option in record["supportedReasoningEfforts"]
            if isinstance(option, dict) and "reasoningEffort" in option
        ]
        if not efforts:
            raise ProbeRefusal(
                f"{record['id']}: supportedReasoningEfforts is empty, which the "
                "schema marks required - refusing to record 'no efforts' as a fact"
            )
        matrix[record["id"]] = efforts
    return matrix


# --- channel 2: what the harness actually used --------------------------------


def effective_from_lines(lines) -> dict:
    """Pull the effective model and effort out of rollout JSONL lines.

    Returns None for anything absent rather than a default: an unread value must
    not resolve to the happy answer, which is what `assert_effective_readable`
    then refuses.
    """
    model = effort = None
    for line in lines:
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        model = model or payload.get("model")
        effort = effort or payload.get("effort")
    return {"model": model, "effort": effort}


def latest_rollout(after: float, sessions_root: Path | None = None) -> Path:
    """The newest rollout written after *after*. Refuses rather than guessing.

    Scoped by mtime so a stale rollout from an earlier run cannot be read as this
    run's evidence — the failure that would make every verdict a coincidence.
    """
    root = sessions_root or _SESSIONS_ROOT
    candidates = [
        p for p in root.rglob("rollout-*.jsonl") if p.stat().st_mtime >= after
    ]
    if not candidates:
        raise ProbeRefusal(
            f"no rollout under {root} newer than the run - cannot read effective "
            "values, so accepted and clamped are indistinguishable"
        )
    return max(candidates, key=lambda p: p.stat().st_mtime)


def assert_effective_readable(effective) -> None:
    """ARMING. The instrument must be able to see what the harness used.

    Deliberately not 'the harness refused an unsupported pair': that is the
    finding, and a clamp must still produce a matrix.
    """
    if not effective.get("model") or not effective.get("effort"):
        raise ProbeNotArmed(
            "effective model/effort unreadable from the rollout "
            f"({effective!r}), so a matching pair and a silently clamped pair are "
            "the same observation. Every verdict below would be unfalsifiable."
        )


def compare_requested(requested, effective) -> str:
    """ACCEPTED when the harness used what was asked for, CLAMPED when it did not."""
    assert_effective_readable(effective)
    same_model = requested["model"] == effective["model"]
    same_effort = requested["effort"] == effective["effort"]
    return ACCEPTED if (same_model and same_effort) else CLAMPED


def annotate_matrix(matrix, verdicts) -> dict:
    """Attach enforcement per advertised row. A clamp annotates, never suppresses."""
    rows: dict[str, dict] = {}
    for model_id, efforts in matrix.items():
        model_verdicts = [v for (m, _), v in verdicts.items() if m == model_id]
        clamped = [v for v in model_verdicts if v == CLAMPED]
        rows[model_id] = {
            "advertised": efforts,
            "enforced": not clamped,
            "note": ADVERTISED_NOT_ENFORCED if clamped else None,
        }
    return rows


# --- exercising a pair against the real harness -------------------------------


def build_exec_command(
    model: str,
    effort: str | None,
    *,
    prompt: str,
) -> list[str]:
    """The `codex exec` argv for one measured pair. Pure, so it is testable.

    **Isolation is by OVERRIDE, not by discarding the config.** An earlier draft
    passed `--ignore-user-config` to stop this machine's global
    `model_reasoning_effort = "high"` reading as a harness clamp. The arming control
    refused on its first live run and showed why that is wrong: the flag also discards
    `model_provider` and auth, so every request 401'd against `api.openai.com`.
    Explicit `-m` and `-c model_reasoning_effort=` already beat `config.toml`, so the
    operator's defaults can only reach a run that OMITS them.

    `effort=None` is the deliberate control: it leaves effort unpinned so the
    operator's own default shows through, which is how the override is measured.

    Effort travels on `-c model_reasoning_effort=` because **no `-e`/`--effort` flag
    exists** on `codex exec` — the plan doc claims one; it is wrong.
    """
    cmd = ["codex", "exec", "--sandbox", "read-only", "--skip-git-repo-check"]
    cmd += ["-m", model]
    if effort is not None:
        cmd += ["-c", f"model_reasoning_effort={effort}"]
    cmd.append(prompt)
    return cmd


def exercise_pair(
    model: str,
    effort: str | None,
    *,
    cwd: Path,
    prompt: str = "Reply with exactly: ok",
    timeout: float = 240.0,
) -> dict:
    """Run one pair and report accepted / clamped / refused, with the evidence."""
    started = time.time() - 1  # rollout mtime granularity
    cmd = build_exec_command(model, effort, prompt=prompt)
    completed = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
        stdin=subprocess.DEVNULL,
    )
    if completed.returncode != 0:
        return {
            "model": model,
            "effort": effort,
            "verdict": REFUSED,
            "effective": None,
            "detail": (completed.stderr or completed.stdout)[-300:],
        }
    effective = effective_from_lines(
        latest_rollout(started).read_text(encoding="utf-8").splitlines()
    )
    return {
        "model": model,
        "effort": effort,
        "verdict": compare_requested({"model": model, "effort": effort}, effective),
        "effective": effective,
        "detail": None,
    }


def arm_channel(cwd: Path, models) -> dict:
    """ARM ON THE LIVE PATH before any verdict is emitted.

    Runs one pair that must work — the default model at its own advertised default
    effort — and requires the effective values to be readable from its rollout. If
    they are not, every later accepted/clamped verdict would be unfalsifiable, so the
    probe refuses rather than tabulating.

    Deliberately NOT armed on "the harness refused an unsupported pair": that is the
    finding, and a clamp must still emit the matrix. Arming on the harness's verdict
    would let an adverse-but-valid result block story-007.
    """
    default = next((m for m in models if m.get("isDefault")), None)
    if default is None:
        raise ProbeRefusal("no default model to arm against")
    result = exercise_pair(default["id"], default["defaultReasoningEffort"], cwd=cwd)
    if result["verdict"] == REFUSED:
        raise ProbeNotArmed(
            f"the arming pair {default['id']}@{default['defaultReasoningEffort']} "
            f"was REFUSED, so the channel is unproven: {result['detail']!r}"
        )
    assert_effective_readable(result["effective"] or {})
    return result


# --- report -------------------------------------------------------------------


def main() -> int:
    cwd = Path(os.environ.get("XP_SPIKE_RUN_DIR") or Path(__file__).resolve().parent)
    models = model_catalog()
    assert_catalog_usable(models)
    matrix = effort_matrix(models)

    armed = arm_channel(cwd, models)
    print(
        f"Channel armed: requested {armed['model']}@{armed['effort']} -> effective "
        f"{armed['effective']['model']}@{armed['effective']['effort']} "
        f"({armed['verdict']})\n"
    )

    print("# story-006 — Codex model and effort tiers\n")
    print(f"Catalog read from `{CATALOG_METHOD}`; {len(models)} model(s).")
    print(
        "Measured runs pin model and effort EXPLICITLY, which overrides config.toml "
        "without discarding provider/auth the way --ignore-user-config does.\n"
    )
    print("| id | hidden | default | default effort | advertised efforts |")
    print("|---|---|---|---|---|")
    for record in models:
        print(
            f"| `{record['id']}` | {'yes' if record.get('hidden') else 'no'} "
            f"| {'yes' if record.get('isDefault') else 'no'} "
            f"| `{record['defaultReasoningEffort']}` "
            f"| {', '.join(matrix[record['id']])} |"
        )
    union = sorted({e for efforts in matrix.values() for e in efforts})
    print(f"\nUnion of advertised effort values: {union}")
    print(f"`minimal` advertised anywhere: {'minimal' in union}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

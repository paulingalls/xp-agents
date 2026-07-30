"""Budget enforcement helpers extracted from conftest.py (file-size cap)."""

import json
import os
import re
import subprocess
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path

from _bases import _PLUGIN_ROOT
from _emitter_fixtures import EMITTER_FIXTURES
from _preload_fixtures import PRELOAD_FIXTURES

_HISTORICAL_ID_RE = re.compile(r"\b[0-9a-f]{12}\b")

# Calibration: a budget is the measured size plus ~11% headroom, so a surface
# sits near 89% of its cap and can gain a clarifying clause without a bump.
_CALIBRATION = 1.125

# The band the assertions fail at. SEPARATE knob from _CALIBRATION: the
# multiplier decides where a freshly-ratcheted file lands (~89%), the band
# decides when creep becomes a failure (98%). Firing only ON breach is why
# nine skills, three agents and one guide drifted to 98-100% of cap across
# three sessions while every budget suite stayed green.
_BAND = 0.98


def ratchet(
    actual: int,
    current: int,
    granularity: int,
    *,
    rounding: Callable[[float], int] = round,
    floor: int = 0,
) -> int:
    """Recalculate a budget from a measured size — DOWNWARD only.

    `min(rounding(actual * 1.125 / granularity) * granularity, current)`.

    Two guards make this a ratchet rather than a re-baseline:

    **Monotonic.** The bare calibration rule RAISES a budget unless `actual`
    has fallen below `current / 1.125` — an 11.1% cut. Most files a prose
    audit trims are trimmed by less than that, so without the `min` the rule
    would hand back headroom on the majority of surfaces it touched. A budget
    may only ever come down.

    **Non-vacuity.** A measurement of 0 does NOT ratchet; `current` is
    returned unchanged. Zero means the fixture drove a no-trigger path and
    never exercised the surface, so encoding it as the bound would record
    "this measures nothing" as the budget — the same defect as a pin that
    scans less than it claims. Report those entries and fix the fixture; do
    not let the ratchet bake the gap in.

    `rounding`/`floor` carry the two families' recorded formulas: md surfaces
    use `round` at granularity 10, preload/emitter stdout uses `math.ceil` at
    granularity 100 with a floor of 100.
    """
    if actual <= 0:
        return current
    scaled = rounding(actual * _CALIBRATION / granularity) * granularity
    return min(max(scaled, floor), current)


def band_offender(name: str, actual: int, budget: int) -> str | None:
    """Offender line when `actual` is at or inside the 98% band, else None.

    Names the percentage as well as the char counts: "8730 chars (budget
    8900)" reads as comfortable, "98.1% of budget" reads as the warning it is.

    A measurement of 0 is never an offender, mirroring `ratchet`'s
    non-vacuity guard — `hook_io.py` carries a deliberate budget of 0 and
    emits no reason prose, and a bare `actual >= 0.98 * budget` reads
    `0 >= 0` as a breach on a surface that has not grown by one character.
    Prose ARRIVING at a zero budget still fails: 0 is a bound, not a pass.
    """
    if actual <= 0:
        return None
    if budget > 0 and actual < _BAND * budget:
        return None
    pct = f"{actual / budget * 100:.1f}% of budget {budget}" if budget else "budget 0"
    return f"{name}: {actual} chars, {pct}"


# A preload/emitter echoes absolute paths (e.g. CLAUDE_PLUGIN_ROOT). When the
# suite runs from a worktree (lefthook pre-commit), those paths carry an extra
# "/.claude/worktrees/<dir>" segment (~40 chars) that inflates the char count
# purely by checkout location. Budgets are calibrated against the main checkout,
# so strip that segment before measuring (concern 464de40cd905). Match any
# worktree dir name — not just the "worktree-story-*" prefix — so the
# normalization holds for every checkout layout under .claude/worktrees/.
_WORKTREE_SEGMENT_RE = re.compile(r"/\.claude/worktrees/[^/]+")


def _measured_len(stdout_bytes: bytes, normalize_paths: tuple[str, ...] = ()) -> int:
    """Char length of preload/emitter stdout for budget purposes, location-independent.

    Collapses the worktree path segment so a run from inside a teammate worktree
    measures the same as one from the main checkout — the budget governs the
    preload's content, not where the checkout happens to live.

    `normalize_paths`, when given, replaces each of those checkout-variable
    absolute paths with a fixed-width placeholder BEFORE the worktree-segment
    strip, so the base checkout path length (not just the worktree segment)
    stops leaking into the measurement. Longest paths first, so a path that
    is a prefix of another can't leave a dangling tail.
    """
    text = stdout_bytes.decode("utf-8", errors="replace")
    for path in sorted(normalize_paths, key=len, reverse=True):
        if path:
            text = text.replace(path, "<P>")
    return len(_WORKTREE_SEGMENT_RE.sub("", text))


def _md_files(dir_path: Path, pattern: str) -> dict[str, Path]:
    """Map {stem-or-parent-name: path} for shipped *.md files matching pattern.

    Two glob shapes used in this repo:
    - "*/SKILL.md" → key by parent dir name (skill name)
    - "*.md" → key by file stem
    """
    if pattern.endswith("/SKILL.md"):
        return {p.parent.name: p for p in dir_path.glob(pattern)}
    return {p.stem: p for p in dir_path.glob(pattern)}


def assert_md_budgets_match(
    testcase: unittest.TestCase,
    dir_path: Path,
    pattern: str,
    budgets: dict[str, int],
    label: str,
) -> None:
    """Every shipped .md must have a budget entry; every entry must match a .md."""
    on_disk = set(_md_files(dir_path, pattern))
    missing = on_disk - set(budgets)
    extra = set(budgets) - on_disk
    testcase.assertFalse(
        missing,
        f"{label} files without a budget entry: {sorted(missing)}",
    )
    testcase.assertFalse(
        extra,
        f"budget entries with no matching {label}: {sorted(extra)}",
    )


def assert_md_under_budgets(
    testcase: unittest.TestCase,
    dir_path: Path,
    pattern: str,
    budgets: dict[str, int],
    label: str,
) -> None:
    """Every shipped .md must stay clear of the 98% band of its budget."""
    files = _md_files(dir_path, pattern)
    offenders: list[str] = []
    for name, budget in budgets.items():
        actual = len(files[name].read_text(encoding="utf-8"))
        offender = band_offender(name, actual, budget)
        if offender:
            offenders.append(offender)
    testcase.assertFalse(
        offenders,
        f"{label} files at or inside the 98% band of their character "
        f"budget (trim, or take a deliberate bump):\n" + "\n".join(offenders),
    )


_LEAKY_GIT_ENV = (
    "SMM_DIR",
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_COMMON_DIR",
    "GIT_INDEX_FILE",
)


def _bootstrap_seeded_smm(tmp: Path) -> tuple[Path, Path]:
    """Create + seed an empty SMM with a git repo cwd. Returns (repo, smm).

    Production-like: scripts run from a git repo (many call `git rev-parse`
    or read repo state), against a seeded SMM. Bypasses init.sh because we
    own SMM_DIR — call seed_smm.py directly to write
    shared_mental_model.json.
    """
    repo = tmp / "repo"
    repo.mkdir()
    for cmd in (
        ["git", "init", "-b", "main"],
        ["git", "config", "user.email", "t@t"],
        ["git", "config", "user.name", "t"],
    ):
        subprocess.run(cmd, cwd=repo, capture_output=True, check=True)
    smm = tmp / "smm"
    (smm / "retrospectives").mkdir(parents=True)
    (smm / "events.jsonl").touch()
    (smm / "events.lock").touch()
    subprocess.run(
        ["python3", str(_PLUGIN_ROOT / "smm" / "seed_smm.py"), str(smm)],
        check=True,
        capture_output=True,
    )
    return repo, smm


def _run_emitter(
    script_name: str,
    scripts_dir: Path,
    smm_dir: Path,
    cwd: Path,
) -> tuple[bytes, str, int]:
    """Run an emitter via subprocess against a pre-seeded SMM.

    Caller owns smm_dir + cwd lifecycle so multiple emitter invocations
    can share one bootstrap (the budget test runs all 11 against the
    same empty SMM). XP_TEAMMATE_NAME="" forces solo-mode framing —
    `pop` would let a parent shell's leak through.
    """
    builder = EMITTER_FIXTURES.get(script_name)
    if builder is None:
        raise KeyError(f"no fixture builder registered for {script_name}")
    stdin_dict = builder()

    env = os.environ.copy()
    # Pop FIRST, set after — _LEAKY_GIT_ENV includes SMM_DIR, so the order
    # matters: setting before popping silently drops the seeded SMM and
    # subprocesses fall back to live ~/.claude/plugins/data/<id>/smm/.
    for ev in _LEAKY_GIT_ENV:
        env.pop(ev, None)
    env["SMM_DIR"] = str(smm_dir)
    env["CLAUDE_PLUGIN_ROOT"] = str(_PLUGIN_ROOT)
    env["XP_TEAMMATE_NAME"] = ""
    proc = subprocess.run(
        ["python3", str(scripts_dir / script_name)],
        input=json.dumps(stdin_dict).encode("utf-8"),
        capture_output=True,
        cwd=cwd,
        env=env,
        timeout=15,
    )
    return proc.stdout, proc.stderr.decode("utf-8", errors="replace"), proc.returncode


def assert_budgets_match(
    testcase: unittest.TestCase,
    fixtures: dict,
    budgets: dict[str, int],
    label: str,
) -> None:
    """Symmetric check: every fixture has a budget AND every budget has a fixture."""
    fixture_names = set(fixtures)
    budget_names = set(budgets)
    missing = fixture_names - budget_names
    extra = budget_names - fixture_names
    testcase.assertFalse(
        missing,
        f"{label} fixtures without a budget entry: {sorted(missing)}",
    )
    testcase.assertFalse(
        extra,
        f"budget entries with no matching {label} fixture: {sorted(extra)}",
    )


def assert_emitter_under_budgets(
    testcase: unittest.TestCase,
    scripts_dir: Path,
    budgets: dict[str, int],
    label: str,
) -> None:
    """Every emitter's stdout (run via fixture) must be at or below budget.

    Bootstraps one SMM per call and reuses it across all emitters.
    `subagent_stop.py` runs LAST because its xp-plan-reviewer fixture
    writes a real .assign-pending marker; running it last keeps the
    marker out of any sibling emitter's view.
    """
    offenders: list[str] = []
    items = sorted(
        budgets.items(),
        key=lambda kv: (kv[0] == "subagent_stop.py", kv[0]),
    )
    with tempfile.TemporaryDirectory() as tmp:
        repo, smm_dir = _bootstrap_seeded_smm(Path(tmp))
        for name, budget in items:
            stdout_bytes, stderr, rc = _run_emitter(name, scripts_dir, smm_dir, repo)
            if rc != 0:
                offenders.append(f"{name}: subprocess rc={rc} stderr={stderr[:200]!r}")
                continue
            actual = _measured_len(stdout_bytes)
            offender = band_offender(name, actual, budget)
            if offender:
                offenders.append(offender)
    testcase.assertFalse(
        offenders,
        f"{label} stdout at or inside the 98% band of its budget:\n"
        + "\n".join(offenders),
    )


def discover_emitter_scripts(scripts_dir: Path) -> list[str]:
    """Walk scripts_dir for .py files that emit context via _common.hook_output.

    Surface-scan helper: returns sorted basenames of every script that calls
    `_common.hook_output(...)` anywhere in its source. Catches the gap where
    a new emitter ships without a fixture/budget entry. Substring match —
    keep the literal `_common.hook_output(` out of non-emitter docstrings.
    """
    return sorted(
        path.name
        for path in scripts_dir.glob("*.py")
        if "_common.hook_output(" in path.read_text(encoding="utf-8")
    )


# Default preload script name is "preload.sh"; entries here override per skill.
_PRELOAD_SCRIPT_NAME_OVERRIDES: dict[str, str] = {
    "xp-kickoff": "check_session_needs.sh",
}


def _preload_script_name(skill_name: str) -> str:
    return _PRELOAD_SCRIPT_NAME_OVERRIDES.get(skill_name, "preload.sh")


def discover_preload_scripts() -> list[str]:
    """Walk skills/*/scripts/ for preload-emitter scripts.

    Surface-scan helper: returns sorted skill names for every preload-equivalent
    script under `_PLUGIN_ROOT/skills/<name>/scripts/`. Catches the gap where
    a new preload ships without a fixture/budget entry.
    """
    skills_dir = _PLUGIN_ROOT / "skills"
    return sorted(
        skill_dir.name
        for skill_dir in skills_dir.iterdir()
        if skill_dir.is_dir()
        and (skill_dir / "scripts" / _preload_script_name(skill_dir.name)).is_file()
    )


def _preload_script_path(skill_name: str) -> Path:
    return (
        _PLUGIN_ROOT
        / "skills"
        / skill_name
        / "scripts"
        / _preload_script_name(skill_name)
    )


def _run_preload(
    skill_name: str,
    smm_dir: Path,
    cwd: Path,
) -> tuple[bytes, str, int]:
    """Run a preload.sh via subprocess against a pre-seeded SMM.

    Caller owns smm_dir + cwd lifecycle so multiple preload invocations
    can share one bootstrap (the budget test runs all preloads against
    the same empty SMM). Builder returns env-var dict (preloads read
    env vars set by the orchestrator); base SMM_DIR + CLAUDE_PLUGIN_ROOT
    + XP_TEAMMATE_NAME are injected here, builder additions merge on top.
    """
    builder = PRELOAD_FIXTURES.get(skill_name)
    if builder is None:
        raise KeyError(f"no fixture builder registered for {skill_name}")

    env = os.environ.copy()
    # Pop FIRST, set after — see _run_emitter for the SMM_DIR ordering rationale.
    for ev in _LEAKY_GIT_ENV:
        env.pop(ev, None)
    env["SMM_DIR"] = str(smm_dir)
    env["CLAUDE_PLUGIN_ROOT"] = str(_PLUGIN_ROOT)
    env["XP_TEAMMATE_NAME"] = ""
    env.update(builder())
    proc = subprocess.run(
        [str(_preload_script_path(skill_name))],
        capture_output=True,
        cwd=cwd,
        env=env,
        timeout=15,
    )
    return proc.stdout, proc.stderr.decode("utf-8", errors="replace"), proc.returncode


def assert_preload_under_budgets(
    testcase: unittest.TestCase,
    budgets: dict[str, int],
    label: str,
) -> None:
    """Every preload's stdout (run via fixture) must be at or below budget.

    Bootstraps one SMM per call and reuses it across all preloads.
    """
    offenders: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        repo, smm_dir = _bootstrap_seeded_smm(Path(tmp))
        for name, budget in sorted(budgets.items()):
            stdout_bytes, stderr, rc = _run_preload(name, smm_dir, repo)
            if rc != 0:
                offenders.append(f"{name}: subprocess rc={rc} stderr={stderr[:200]!r}")
                continue
            actual = _measured_len(
                stdout_bytes,
                normalize_paths=(str(_PLUGIN_ROOT), str(smm_dir), str(repo)),
            )
            offender = band_offender(name, actual, budget)
            if offender:
                offenders.append(offender)
    testcase.assertFalse(
        offenders,
        f"{label} stdout at or inside the 98% band of its budget:\n"
        + "\n".join(offenders),
    )


def assert_no_12hex_ids_in_md(
    testcase: unittest.TestCase,
    dir_path: Path,
    pattern: str,
    label: str,
) -> None:
    """Shipped text files must not contain 12-hex SMM event IDs.

    Generic across file types — `_in_md` is the historical name (M-1
    skills, M-2 agents); M-3 emitters call this with a `*.py` glob.
    """
    offenders: list[str] = []
    for path in dir_path.glob(pattern):
        for line_no, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            if _HISTORICAL_ID_RE.search(line):
                rel = path.relative_to(_PLUGIN_ROOT)
                offenders.append(f"{rel}:{line_no}: {line.strip()[:100]}")
    testcase.assertFalse(
        offenders,
        f"12-hex IDs (decision/concern/event refs) in shipped {label} prose:\n"
        + "\n".join(offenders[:30]),
    )

#!/usr/bin/env python3
"""Lint concern resolution on commit and orphan sweep.

Extracted from bash_post_tool.py — these functions re-run linters on
committed files and auto-resolve matching lint concerns in the SMM.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import concerns
import lint_grouping
import resolution
import worktree
from event_schema import STATUS_ACTION_LINT_RESOLVED

_WATERMARK_ID = "lint-resolution"


def check_and_resolve_lint(
    smm_dir: Path,
    cwd: str,
    git_root: str,
    agent_id: str,
    normalized: str,
    label: str,
    events: list[dict] | None,
    resolutions: dict | None,
) -> None:
    """Re-run the linter for *normalized*; resolve matching concerns if clean.

    The per-file fallback: `_resolve_group` calls this once per path in a
    group whose batch run reported findings — a batch's exit code names no
    file, so the group's clean paths still deserve a look, and this is that
    look.
    """
    import lint_check

    config = lint_check.detect_linter_config(cwd, git_root, file_path=normalized)
    if config is None:
        return
    linter_name, config_path = config
    # Run the linter from the config file's dir (not git_root) so monorepo
    # subpackage binaries + cwd-relative configs resolve — symmetric with
    # lint_check.run(), or a concern raised there could never clear here.
    lint_cwd, file_arg = lint_check.lint_invocation_target(
        config_path, git_root, normalized
    )
    # config_path and root are threaded through: a checkstyle concern raised by
    # lint_check.run() with the project's config could NEVER clear here if this
    # re-run used a different one — and a clang-tidy concern in a project with no
    # compile database could never clear at all, because 'hdr.h not found' is not
    # fixable by editing the file the concern is attached to.
    if (
        lint_check.run_linter(
            linter_name,
            file_arg,
            cwd=lint_cwd,
            root=git_root,
            config_path=config_path,
        )
        is not None
    ):
        return
    concerns.resolve_concerns(
        smm_dir,
        lambda c, n=normalized: concerns.lint_concern_matches(c, n),
        agent_id,
        label,
        events=events,
        resolutions=resolutions,
        extra_metadata={"action": STATUS_ACTION_LINT_RESOLVED},
    )


def _batch_targets(
    config_path: str, git_root: str, paths: list[str]
) -> tuple[str, list[str], list[str]]:
    """(lint_cwd, batched_paths, file_args) for a group sharing *config_path*.

    lint_cwd is constant across the group by construction, not an assumption:
    it is Path(config_path).parent, and config_path is half the group key.

    A path whose ARG is flag-shaped is dropped from both returned lists.
    `run_linter_batch` refuses a whole batch over one such arg, and the arg is
    what it sees: the callers' project-relative filter cannot catch this one,
    because `apps/mobile/-x.ts` only becomes `-x.ts` once made relative to the
    config dir — so without this its whole subpackage's concerns would never
    clear, on this commit or any later sweep. Dropping it from the resolve set
    too is the point of returning both: batching a path but not resolving it
    is fail-closed, resolving one the linter never saw is not.
    """
    import lint_check

    lint_cwd = str(Path(config_path).parent)
    batched: list[str] = []
    file_args: list[str] = []
    for path in paths:
        lint_cwd, file_arg = lint_check.lint_invocation_target(
            config_path, git_root, path
        )
        if file_arg.startswith("-"):
            continue
        batched.append(path)
        file_args.append(file_arg)
    return lint_cwd, batched, file_args


def _resolve_group(
    smm_dir: Path,
    cwd: str,
    git_root: str,
    agent_id: str,
    linter_name: str,
    config_path: str,
    paths: list[str],
    label: str,
    events: list[dict] | None,
    resolutions: dict | None,
) -> None:
    """Lint one (linter, config) group in a single process; resolve by exit code.

    A batch's exit code names no file (see lint_check.run_linter_batch), so
    the disposition is three-way: clean resolves every concern in the group
    in one bulk append, findings falls back to one run per file in THIS
    group only, and unverified resolves nothing — a bad read is not a pass.
    """
    import lint_check

    lint_cwd, batched, file_args = _batch_targets(config_path, git_root, paths)
    if not batched:
        return
    run = lint_check.run_linter_batch(
        linter_name,
        file_args,
        cwd=lint_cwd,
        root=git_root,
        config_path=config_path,
    )
    match run.status:
        case "clean":
            concerns.resolve_concerns(
                smm_dir,
                lambda c: any(concerns.lint_concern_matches(c, p) for p in batched),
                agent_id,
                label,
                events=events,
                resolutions=resolutions,
                extra_metadata={"action": STATUS_ACTION_LINT_RESOLVED},
            )
        case "findings":
            for normalized in batched:
                check_and_resolve_lint(
                    smm_dir,
                    cwd,
                    git_root,
                    agent_id,
                    normalized,
                    label,
                    events,
                    resolutions,
                )
        case "unverified":
            pass


def resolve_lint_on_commit(
    smm_dir: Path,
    cwd: str,
    agent_id: str,
    files: list[str],
    events: list[dict] | None = None,
    resolutions: dict | None = None,
) -> None:
    """Run linter on committed files and resolve lint concerns for passing ones.

    Groups files by the (linter, config) that claims them and spawns at most
    one linter process per group — see `_resolve_group`. A caller-side filter
    runs first, before grouping: a path with no open lint concern has nothing
    this loop could ever resolve, so the common commit needs zero processes,
    not N. (Flag-shaped ARGS are dropped a layer down, in `_batch_targets`,
    which is where what the linter actually sees is known.)
    """
    if not files:
        return
    git_root = worktree.resolve_git_root(cwd) or cwd
    if events is None:
        events = _common.read_events_locked(smm_dir, _WATERMARK_ID)
    if resolutions is None:
        resolutions = resolution.compute_resolutions(events)

    normalized = [worktree.normalize_path(f, cwd) for f in files]
    normalized = [
        p
        for p in normalized
        if concerns.has_unresolved_concerns(
            smm_dir,
            lambda c, n=p: concerns.lint_concern_matches(c, n),
            events=events,
            resolutions=resolutions,
        )
    ]
    if not normalized:
        return

    groups = lint_grouping.group_paths_by_linter(normalized, cwd, git_root)
    for (linter_name, config_path), paths in groups.items():
        _resolve_group(
            smm_dir,
            cwd,
            git_root,
            agent_id,
            linter_name,
            config_path,
            paths,
            "Lint concern resolved on commit",
            events,
            resolutions,
        )


def sweep_orphan_lint_concerns(
    smm_dir: Path,
    cwd: str,
    agent_id: str,
    committed_files: list[str],
    events: list[dict] | None = None,
    resolutions: dict | None = None,
) -> None:
    """Resolve unresolved lint concerns whose file is now clean but isn't in
    this commit. Catches side-effect fixes (`ruff check --fix` from Bash,
    pre-commit reformatting, cross-file fixes) that don't show up as direct
    edits to the offending file. Files referenced by lint concerns but no
    longer on disk are skipped before grouping (manual triage) —
    group_paths_by_linter applies no eligibility filter of its own, so each
    caller brings its own."""
    if events is None:
        events = _common.read_events_locked(smm_dir, _WATERMARK_ID)
    if resolutions is None:
        resolutions = resolution.compute_resolutions(events)

    resolved_ids = resolutions["resolved_concern_ids"]
    committed_set = {worktree.normalize_path(f, cwd) for f in committed_files}

    orphan_paths: set[str] = set()
    for e in events:
        if e.get("type") != _common.CONCERN:
            continue
        if e.get("id", "") in resolved_ids:
            continue
        path_part = concerns.extract_lint_concern_path(e.get("content", ""))
        if path_part is None:
            continue
        normalized = worktree.normalize_path(path_part, cwd)
        if normalized not in committed_set:
            orphan_paths.add(normalized)

    if not orphan_paths:
        return

    git_root = worktree.resolve_git_root(cwd) or cwd
    # sorted: orphan_paths is a set, and an unordered batch would hand the
    # linter its file args in a different order run to run.
    eligible = sorted(p for p in orphan_paths if (Path(git_root) / p).exists())
    if not eligible:
        return

    groups = lint_grouping.group_paths_by_linter(eligible, cwd, git_root)
    for (linter_name, config_path), paths in groups.items():
        _resolve_group(
            smm_dir,
            cwd,
            git_root,
            agent_id,
            linter_name,
            config_path,
            paths,
            "Lint concern resolved on sweep",
            events,
            resolutions,
        )

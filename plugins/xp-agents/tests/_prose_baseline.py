#!/usr/bin/env python3
"""What the `scripts/` prose ratchet was measured over, and the two numbers.

A ratio compares a tree against a number recorded on ANOTHER tree, so the two
are comparable only over the same set of files. Keeping that set implicit is
what let the pin fire twice on work that rotted nothing:

  EXTRACTION. Splitting a file, which CLAUDE.md's 500-line rule demands, adds a
  module docstring and a header to the tree without adding the code they
  describe. The extracted module raises the ratio purely by existing.

  CLAIM-NARROWING. A true claim is usually longer than the false short one it
  replaces, so correcting prose RAISES this number — the ratio moves against
  exactly the work milestones 1 and 3 exist to produce.

Naming the set fixes only the first: a file outside it is not measured, so an
extraction cannot trip the pin. The second is inherent to measuring a ratio at
all and is recorded as debt; this module is the interim, not the answer.

A name here with no file in the tree is reported, never skipped — a set that
drifts away from the tree silently shrinks what is measured, and one that
drifted to nothing would measure 0/0 and read as clean.

The other direction is deliberately NOT checked, and the cost is real: a file
the tree gained after this set was recorded is exempt from the ratio for as
long as the set stands, so its prose can double while the pin reads green.
`session_start_banner.py` is one today. Reporting it instead would redden the
pin on every extraction — the false red the set exists to remove — so what
shrinks the hole is per-file absolute measurement, not a reverse leg.
"""

# Measured over BASELINE_FILES at the merge of story-012, re-anchored once from
# the pre-sweep 12602/31422. That number was recorded before a back-merge
# brought in 131 prose lines from a branch where this pin does not exist: 83 an
# extracted module, the rest claims narrowed to what the code actually does.
# Re-anchoring keeps the ratchet biting on regrowth in files it has measured;
# it does not forgive regrowth, which is why it happens once and is dated.
BASELINE_PROSE = 12726
BASELINE_TOTAL = 31647

# The 142 files the numbers above were measured over. A new file is NOT added
# here by anyone who merely wants the pin green — adding one re-anchors the
# numbers too, which is a deliberate, reviewable act.
BASELINE_FILES: frozenset[str] = frozenset(
    (
        "_common.py",
        "_subprocess_env.py",
        "accept_terminal.py",
        "acceptance_env.py",
        "assign_scope.py",
        "bash_failure.py",
        "bash_post_tool.py",
        "branch_lifecycle.py",
        "branch_names.py",
        "branch_queries.py",
        "branch_resolution.py",
        "branching.py",
        "branching_cli.py",
        "branching_cli_accept.py",
        "branching_cli_target.py",
        "branching_cli_worktree.py",
        "branching_core.py",
        "branching_stage.py",
        "cadence_cli.py",
        "cleanup_teammate.py",
        "close_archive_step.py",
        "close_common.py",
        "close_cycle_abandonment.py",
        "close_cycle_stop_gate.py",
        "close_gate_commands.py",
        "close_review_support.py",
        "close_verify_gate.py",
        "code_files.py",
        "commit_command.py",
        "commit_emit.py",
        "commit_event.py",
        "commit_handling.py",
        "commit_message.py",
        "commits.py",
        "commits_issues.py",
        "concern_conflicts.py",
        "concerns.py",
        "coordination.py",
        "dash_c_tokens.py",
        "duplicate_debt_probe.py",
        "framework_detect.py",
        "git_commits.py",
        "git_refs.py",
        "git_remote.py",
        "honesty_signals.py",
        "hook_heartbeat_scan.py",
        "hook_io.py",
        "hook_liveness.py",
        "housekeeping_flight.py",
        "housekeeping_stop_gate.py",
        "identity.py",
        "in_place_locks.py",
        "in_place_marker.py",
        "kickoff_gate.py",
        "known_installs.py",
        "lead_gates.py",
        "lint_budget.py",
        "lint_check.py",
        "lint_resolution.py",
        "lint_runners.py",
        "linter_invocation.py",
        "linter_tables.py",
        "linters.py",
        "markers.py",
        "merge_commit_event.py",
        "migrate_smm_root.py",
        "migration_lock.py",
        "plugin_loader.py",
        "post_tool_exit_plan.py",
        "post_tool_use.py",
        "pre_compact.py",
        "pre_tool_bash.py",
        "pre_tool_bash_branch_delete.py",
        "pre_tool_bash_commit_gates.py",
        "pre_tool_bash_reviewer_guard.py",
        "pre_tool_plan_mode.py",
        "pre_tool_skill.py",
        "pre_tool_write.py",
        "prompt_nugget.py",
        "question_answered.py",
        "result_counts.py",
        "retro_flags.py",
        "retro_history.py",
        "retro_metrics.py",
        "retrospective.py",
        "review_cycle_done.py",
        "review_flag_cli.py",
        "save_retrospective.py",
        "scaffold_apply.py",
        "scaffold_cli.py",
        "scaffold_cli_apply.py",
        "scaffold_detect.py",
        "scaffold_plan.py",
        "scaffold_post.py",
        "scaffold_verify.py",
        "security_patterns.py",
        "security_scanner.py",
        "session_end.py",
        "session_end_warning.py",
        "session_markers.py",
        "session_start.py",
        "shell_commands.py",
        "shell_exit_structure.py",
        "spawn_args.py",
        "spawn_branch_release.py",
        "spawn_command.py",
        "spawn_prompt.py",
        "spawn_teammate.py",
        "sprint_review_flight.py",
        "sprint_state.py",
        "sprint_stop_gate.py",
        "staged_lint.py",
        "story_metrics.py",
        "subagent_start.py",
        "subagent_stop.py",
        "surface_coverage.py",
        "target_routing.py",
        "task_completed.py",
        "tdd_check.py",
        "tdd_stop_gate.py",
        "teammate_config_cli.py",
        "teammate_idle.py",
        "teammate_output_filter.py",
        "teammate_runner.py",
        "teammate_stop_gate.py",
        "teammate_stream_reader.py",
        "test_attribution.py",
        "test_parsing.py",
        "trailer_gate.py",
        "user_prompt_log.py",
        "verify_acceptance.py",
        "verify_acceptance_record.py",
        "verify_deferred.py",
        "verify_paths.py",
        "work_signals.py",
        "worktree.py",
        "worktree_bootstrap.py",
        "worktree_create.py",
        "worktree_differential.py",
        "worktree_discovery.py",
        "worktree_teardown.py",
        "write_scope.py",
    )
)


def measure_named(
    prose_by_name: dict[str, tuple[int, int]], names: frozenset[str] | set[str]
) -> tuple[int, int]:
    """`(prose, total)` summed over the entries of *prose_by_name* in *names*.

    Takes already-counted `(prose, total)` pairs rather than a tree, so the
    selection rule is reachable from synthetic numbers. The real-tree caller
    can only ever be green, and would prove nothing about the rule.
    """
    kept = [pair for name, pair in prose_by_name.items() if name in names]
    return sum(p for p, _ in kept), sum(t for _, t in kept)


def missing_from(
    prose_by_name: dict[str, tuple[int, int]], names: frozenset[str] | set[str]
) -> tuple[str, ...]:
    """Names in *names* with no entry in *prose_by_name*, sorted."""
    return tuple(sorted(name for name in names if name not in prose_by_name))

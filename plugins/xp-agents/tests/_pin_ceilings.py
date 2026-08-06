#!/usr/bin/env python3
"""The band-ratchet ceiling table — data only, no test logic.

Split out of `test_file_size_pin.py` because the two grow for opposite
reasons. The pin module changes only when the RULE changes; this table changes
every time any file in the tree crosses 450 lines, which is routine. Kept
together, the pin file sat in its own band at exactly its own ceiling, so the
next routine entry — one added line — reddened pre-commit on a file unrelated
to the change that added it.

Entries are generated from measurement, never typed by hand: re-measure with
`test_file_size_pin._line_count` before editing. Retirement is manual — delete
an entry when its file drops to 450 or below, or the ratchet hands back the
ground the split just won.
"""

# Recorded ceilings for every file already above 450 lines, measured with
# `_line_count` on 2026-07-30. A file not in this table and at or under 500 is
# governed only by the tree-wide cap. Shrink a listed file to <=450 and delete
# its entry -- the table is self-retiring.
BAND_CEILINGS = {
    # shipped (15)
    # RETIRED (story-015): hook_liveness.py 469->371, by taking the extraction
    # its own ceiling note named — the per-session sibling scan moved to
    # scripts/hook_heartbeat_scan.py, which a second reader (coordination's
    # liveness leg) now imports without the verdict machinery.
    "plugins/xp-agents/smm/seed_smm.py": 499,
    "plugins/xp-agents/scripts/spawn_teammate.py": 457,  # ratcheted from 498 (split)
    "plugins/xp-agents/scripts/close_common.py": 470,  # ratcheted from 496 (split)
    "plugins/xp-agents/smm/sprint_cli_mutate.py": 496,
    "plugins/xp-agents/scripts/in_place_marker.py": 490,
    "plugins/xp-agents/scripts/retro_metrics.py": 490,
    "plugins/xp-agents/scripts/linter_tables.py": 482,
    "plugins/xp-agents/smm/event_schema.py": 480,
    "plugins/xp-agents/scripts/lint_runners.py": 477,
    "plugins/xp-agents/smm/_append_impl.py": 469,
    # Entered the band at sprint close: the start-time file_domain gate needed
    # an ABSOLUTE sister-expanded report alongside the this-write-only one.
    # sprint_save now carries four responsibilities (milestone transition,
    # sister include, collision attribution, save/run); collision attribution
    # is the cohesive group to extract next.
    "plugins/xp-agents/smm/sprint_save.py": 463,
    # RETIRED (story-015): teammate_output_filter.py 461->376. The stream
    # reading half — deadline, fd loop, stream-json parsing, terminal-event
    # detection — moved to scripts/teammate_stream_reader.py, leaving the host
    # to decide what the outcome MEANS and report it.
    "plugins/xp-agents/scripts/pre_tool_write.py": 463,
    "plugins/xp-agents/scripts/session_start.py": 462,
    "plugins/xp-agents/scripts/scaffold_detect.py": 459,
    # Entered the band with the caller's REFUSED_UNMERGED note.
    "plugins/xp-agents/scripts/worktree.py": 452,
    # tests (56)
    "plugins/xp-agents/tests/hooks/test_pre_tool_bash_reviewer_guard.py": 499,
    "plugins/xp-agents/tests/hooks/test_housekeeping_stop_gate.py": 495,
    "plugins/xp-agents/tests/integration/test_branching_delete.py": 494,
    "plugins/xp-agents/tests/hooks/test_branch_lifecycle.py": 494,
    "plugins/xp-agents/tests/hooks/test_teammate_runner.py": 493,
    "plugins/xp-agents/tests/hooks/test_retro_metrics.py": 493,
    "plugins/xp-agents/tests/hooks/test_story_metrics_attribution.py": 492,
    "plugins/xp-agents/tests/hooks/test_auto_resolve.py": 491,
    "plugins/xp-agents/tests/engine/test_sprint_store.py": 490,
    "plugins/xp-agents/tests/_close_fixtures.py": 488,
    "plugins/xp-agents/tests/hooks/test_spawn_teammate.py": 488,
    "plugins/xp-agents/tests/engine/test_compact.py": 488,
    "plugins/xp-agents/tests/smm/test_smm_store.py": 487,
    "plugins/xp-agents/tests/hooks/test_commits_issues.py": 486,
    "plugins/xp-agents/tests/hooks/test_lang_leak_scan.py": 486,
    "plugins/xp-agents/tests/smm/test_session_history.py": 484,
    "plugins/xp-agents/tests/hooks/test_lint_config_style_flags.py": 483,
    "plugins/xp-agents/tests/hooks/test_spawn_teammate_branch_release.py": 482,
    "plugins/xp-agents/tests/hooks/test_bash.py": 481,
    # RETIRED (close review): test_system_context_schema_fields.py 480->335, by
    # taking the extraction its own ceiling note named — `TestAcceptanceSurface*`
    # (two classes, one fixture) moved to test_system_context_surface_fields.py.
    # RETIRED (story-018), both now under the 450 floor so deleted, not
    # ratcheted: test_story_close_surface_gate.py 478->386 (three disagreeing
    # gate harnesses consolidated into tests/integration/_gate_harness.py), and
    # test_system_analyzer_prompt.py 468->445, which was AT its ceiling with
    # prose pins still to add (-> test_system_analyzer_surface_prose.py).
    "plugins/xp-agents/tests/hooks/test_retrospective.py": 479,
    "plugins/xp-agents/tests/hooks/test_branching_cli_detection.py": 479,
    "plugins/xp-agents/tests/integration/test_core_hooks.py": 478,
    "plugins/xp-agents/tests/hooks/test_spawn_prompt_guard.py": 477,
    "plugins/xp-agents/tests/engine/test_curation_prepare.py": 477,
    "plugins/xp-agents/tests/smm/test_event_schema.py": 476,
    "plugins/xp-agents/tests/hooks/test_story_attribution.py": 475,
    "plugins/xp-agents/tests/hooks/test_retro_save.py": 475,
    "plugins/xp-agents/tests/hooks/test_teammate_hooks.py": 475,
    "plugins/xp-agents/tests/hooks/test_branch_resolution.py": 474,
    # Entered the band with the close-review pins for the skill's runtime
    # break. Extract next: `_PreloadCase`, unused by its prose suites.
    "plugins/xp-agents/tests/skills/test_scaffold_worktree_skill.py": 475,
    "plugins/xp-agents/tests/engine/test_compact_concurrency.py": 473,
    "plugins/xp-agents/tests/smm/test_integration_branch_ref.py": 470,
    # RETIRED (story-019 follow-up): test_sprint_frontier.py 470->283. The
    # unscoped-verdict tests had already moved to test_frontier_unprovable.py;
    # the dependency-edge / treat_as_done group moved to
    # test_frontier_dependency_edges.py, leaving only the collision/glob/
    # shape tests the always-present `unscoped` key otherwise would have
    # pushed past the ceiling.
    "plugins/xp-agents/tests/integration/test_story_close.py": 468,
    # Entered the band with the close-cycle marker scrub: a close preload now
    # leaves state a sibling preload reacts to, so the shared measurement loop
    # has to clear it between runs. The cohesive group to extract next is the
    # preload family (`_run_preload` + `assert_preload_under_budgets` + this
    # scrub), which the emitter and md families do not use.
    "plugins/xp-agents/tests/_budget_helpers.py": 467,
    "plugins/xp-agents/tests/integration/test_maintenance.py": 466,
    "plugins/xp-agents/tests/hooks/test_session_start_core.py": 466,
    "plugins/xp-agents/tests/scaffold/test_scaffold_skill.py": 466,
    "plugins/xp-agents/tests/_bases.py": 465,
    "plugins/xp-agents/tests/skills/test_draft_summary.py": 465,
    "plugins/xp-agents/tests/scaffold/test_scaffold_record.py": 463,
    # RETIRED (close review): test_session_lifecycle.py 462->450, by moving the
    # summary's working_on aggregation to test_session_end_summary.py — a
    # separate question from the duration/unresolved behaviours left behind.
    "plugins/xp-agents/tests/hooks/test_retro_history.py": 462,
    "plugins/xp-agents/tests/hooks/test_spawn_teammate_markers.py": 462,
    "plugins/xp-agents/tests/smm/test_init_migration_lock.py": 462,
    "plugins/xp-agents/tests/smm/test_triage.py": 460,
    # RETIRED (back-merge): test_preload_liveness.py 459->363 on the sprint
    # branch, so main's carried entry would hand back ground already won.
    "plugins/xp-agents/tests/engine/test_sprint_cli.py": 458,
    "plugins/xp-agents/tests/hooks/test_subagent_tiers_sprint.py": 457,
    # Entered the band with the close review's refusal pin for a --smm-dir
    # that is not an SMM.
    "plugins/xp-agents/tests/hooks/test_close_common_archive.py": 455,
    "plugins/xp-agents/tests/hooks/test_sprint_stop_gate.py": 455,
    "plugins/xp-agents/tests/hooks/test_retrospective_signals.py": 455,
    "plugins/xp-agents/tests/scaffold/test_scaffold_plan.py": 455,
    "plugins/xp-agents/tests/engine/test_file_domain_lock.py": 454,
    "plugins/xp-agents/tests/hooks/test_close_common_verify_gate.py": 453,
    "plugins/xp-agents/tests/hooks/test_commits_git_helpers.py": 452,
    "plugins/xp-agents/tests/smm/test_append_safety.py": 452,
    "plugins/xp-agents/tests/scaffold/test_scaffold_cli_detect.py": 452,
    "plugins/xp-agents/tests/hooks/test_pre_tool_bash_branch_delete.py": 451,
}

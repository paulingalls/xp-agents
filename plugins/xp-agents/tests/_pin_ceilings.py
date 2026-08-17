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
    # shipped — deliberately uncounted, following main. A hand-maintained
    # count is drift-prone in exactly the way this table warns about: it read
    # 57 while carrying 58 before anyone noticed, and a back-merge combining a
    # branch that ADDS an entry with a main that RETIRES several leaves neither
    # side's number right. Count the entries if you need the number.
    # RETIRED (story-015): hook_liveness.py 469->371, by taking the extraction
    # its own ceiling note named — the per-session sibling scan moved to
    # scripts/hook_heartbeat_scan.py, which a second reader (coordination's
    # liveness leg) now imports without the verdict machinery.
    # RETIRED (sprint-001): seed_smm.py 499->250, detection split to
    # smm/seed_detect.py. Below the 450 floor, so the entry is gone rather
    # than dormant — a kept entry hands back the ground the split won.
    #
    # The first NON-Python entry. The band ratchet discovered only .py until
    # story-002, so every shipped shell file was ungoverned by a gate whose
    # docstring called itself tree-wide. Nothing about the ratchet itself is
    # language-specific -- `_line_count` is splitlines() -- only its discovery
    # was. Recorded at 492 on the story branch; re-measured at 468 here because
    # main shrank the file in parallel (story-016's once-per-session gate).
    # Carrying 492 across the merge would have handed back all 24 lines.
    "plugins/xp-agents/skills/_preload_base.sh": 468,
    "plugins/xp-agents/scripts/spawn_teammate.py": 457,  # ratcheted from 498 (split)
    # Ratcheted 470->471: the stderr-first relay helpers moved to
    # `_subprocess_env`, so this module imports both it and `branch_lifecycle`
    # (still needed for `push_source_no_verify`) where one import used to do.
    "plugins/xp-agents/scripts/close_common.py": 471,  # ratcheted from 496 (split)
    "plugins/xp-agents/smm/sprint_cli_mutate.py": 496,
    "plugins/xp-agents/scripts/in_place_marker.py": 490,
    "plugins/xp-agents/scripts/retro_metrics.py": 490,
    # NEW entry, not a ratchet: 443 -> 486, crossing the 450 floor for the first
    # time. `exit_reaches_shell_for` hoists the rewrite/walk/`sh -c`-recursion
    # composition that `exit_capture_gate` held a private second copy of, and
    # the shared escape marker moved here with it. A third copy was about to be
    # written for the git-write gate, so the file grew by taking duplication
    # OUT of the tree — `exit_capture_gate.py` fell 165 -> 131 in the same
    # commit.
    # Ratcheted 486 -> 491 at the close review: `exit_status_waived` reads the
    # marker off a data-stripped view, so a commit MESSAGE quoting the marker no
    # longer waives a gate, and it belongs beside the marker it reads. Nine
    # lines from the tree-wide cap now, so the next thing this file gains is an
    # extraction rather than another raise.
    "plugins/xp-agents/scripts/shell_exit_structure.py": 491,
    "plugins/xp-agents/scripts/linter_tables.py": 482,
    "plugins/xp-agents/smm/event_schema.py": 480,
    # Ratcheted 477->482 (story-011): the three single-stream sites now route
    # through `_subprocess_env.combine_streams`, the binary-mode one decoding
    # per-stream first, so a discarded stream can't drop half a linter's
    # diagnosis.
    "plugins/xp-agents/scripts/lint_runners.py": 482,
    # RETIRED (story-002): _append_impl.py 469 -> under the 450 floor, so the
    # entry is deleted rather than lowered. Whole-file rewriting (event_ids,
    # _preservable_id, replace_events_file) moved to _events_replace.py — the
    # appender adds one event under lock, that module replaces the file from a
    # caller's snapshot, and they were two responsibilities in one file.
    # No landing count quoted on purpose: two attempts at one (377, then 409)
    # were both stale within the same sprint, and the retirement's legitimacy
    # rests on "below 450", which `wc -l` answers at any time.
    #
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
    # RETIRED (story-016): pre_tool_write.py 463->379, by extracting the
    # schedule gate's exemption predicates to write_scope.py. Left in place, its
    # 463 would have handed back every one of the 84 lines the split just won.
    # RETIRED (sprint-005 story-002): session_start.py 462->382, by extracting
    # the user-facing banner block to scripts/session_start_banner.py. Below the
    # 450 floor, so the entry is deleted rather than re-recorded — kept at 462 it
    # would have handed back ~98 of the lines the split just won.
    "plugins/xp-agents/scripts/scaffold_detect.py": 459,
    # Entered the band with the caller's REFUSED_UNMERGED note.
    "plugins/xp-agents/scripts/worktree.py": 452,
    # Entered the band with `also_changed` on untouched_verify_paths: the
    # keyword-only parameter, the union, and the one sentence naming who may
    # pass it. The walk itself is unchanged, so this is the parameter's cost
    # and not a growing function.
    "plugins/xp-agents/scripts/verify_paths.py": 454,
    # RETIRED: verify_acceptance.py 455->434, under the 450 floor so the entry
    # is deleted rather than re-recorded. Deduping the sprint run to one
    # subprocess per DISTINCT command replaced the inline row-building loop
    # with `_run_one` plus two helpers in verify_acceptance_record.py, which
    # took out more lines than the dedup added.
    # tests (57)
    "plugins/xp-agents/tests/hooks/test_pre_tool_bash_reviewer_guard.py": 499,
    # Entered the band with the shell surface's own red proofs. Its own
    # self-coverage test caught the crossing, which is the design working. The
    # cohesive group to extract next is the synthetic red-proof classes
    # (TestCapOffenderDetection, TestBandRatchetRedProof, TestShellScanRedProofs,
    # TestShippedRootFloorRedProof) — they share a temp-tree idiom and touch no
    # real-tree state, unlike everything else in the file.
    "plugins/xp-agents/tests/test_file_size_pin.py": 474,
    "plugins/xp-agents/tests/hooks/test_housekeeping_stop_gate.py": 495,
    "plugins/xp-agents/tests/integration/test_branching_delete.py": 494,
    "plugins/xp-agents/tests/hooks/test_branch_lifecycle.py": 494,
    "plugins/xp-agents/tests/hooks/test_teammate_runner.py": 493,
    "plugins/xp-agents/tests/hooks/test_retro_metrics.py": 493,
    # RETIRED (this branch): test_story_metrics_attribution.py 492->383, by
    # splitting the merge-attribution cases into
    # test_story_metrics_merge_attribution.py. Below the 450 floor, so the entry
    # goes rather than sitting dormant — kept at 492 it would hand back all 109
    # lines the split just won, which is the manual step this table's docstring
    # says nothing enforces.
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
    # Entered the band on arrival (story-004). Recorded rather than split
    # because the obvious cut — the hook-wiring and E2E classes into a sibling
    # — would move AC5's only evidence out of the file this story's
    # acceptance_execution actually runs, which is the gap kickoff triage
    # raised against this story in the first place. Unchanged across review:
    # the duplicate runner-name scan left for the sibling suite that now
    # sweeps for it, and a declare() mixin replaced three copies of one
    # fixture write, which between them paid for the redirect shapes and the
    # masking-declaration case added alongside. The cohesive group to extract
    # when it next grows is `TestEndToEndThroughTheRealHook`, once a second
    # suite needs the same real-runner-with-a-sentinel fixture.
    # Ratcheted 470 -> 481 for the two honest shapes the close review found this
    # gate refusing: `<declared> && <read> | <pager>`, where `|` binds tighter
    # so a failed run short-circuits and its status still reaches the shell.
    # They go in _HONEST_SHAPES rather than a new class because that table IS
    # the statement of what must not be refused, and the refusal text has
    # recommended a trailing `&& <next>` since this gate shipped.
    "plugins/xp-agents/tests/hooks/test_exit_capture_gate.py": 481,
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
    # 452 -> 459 when the merged-range tests retargeted from `merged_range_bodies`
    # (deleted — the third emitter's convergence left it callerless) onto the
    # per-commit reader. The +7 buys two assertions the blob-returning helper could
    # not express: the incoming COUNT, and that the merge commit itself is filtered
    # out of its own range. Trimmed the prose first; the remainder is assertions.
    "plugins/xp-agents/tests/hooks/test_commits_git_helpers.py": 459,
    # 452 -> 472 for the trailing-newline pins on the agent-id allowlist (`$`
    # matched before a final newline; `\Z` does not). The file sat at exactly
    # its own ceiling, and the cheapest way to stay under it was to put the
    # pins in a file that does not test this validator — the relocation debt
    # 22abb3a8d214 names. Raised instead, because the two pins belong beside
    # the twelve rejection cases they extend.
    "plugins/xp-agents/tests/smm/test_append_safety.py": 472,
    "plugins/xp-agents/tests/scaffold/test_scaffold_cli_detect.py": 452,
    # Ratcheted 451 -> 478 at the v5.19.0 close review, for the one test that
    # covers the INTERSECTION of two shapes this file already pinned separately:
    # a heredoc body naming a delete (allowed) and a delete chained after a
    # quoted mention (blocked). `strip_heredocs` deleted the remainder of the
    # heredoc's introducing line along with the body, so a delete chained THERE
    # was invisible — and neither existing half could see it. Its docstring
    # carries the mutation check, because the first draft put the chain after the
    # terminator instead, where both the fixed and unfixed helper block it.
    "plugins/xp-agents/tests/hooks/test_pre_tool_bash_branch_delete.py": 478,
    # Entered the band with story-011's stream-relay proofs (both-streams +
    # tail-eviction) added to TestBootstrapFailure's sibling classes.
    "plugins/xp-agents/tests/hooks/test_spawn_teammate_bootstrap.py": 461,
    # RETIRED (story-011): test_worktree_differential.py 486->440. Its
    # stream-relay proofs went to test_worktree_differential_output.py rather
    # than taking a ceiling entry at 518, over the tree-wide cap. The
    # measurement (refusal, gap/no-gap, throwaway removal) and what each leg
    # RELAYS grow for unrelated reasons.
}

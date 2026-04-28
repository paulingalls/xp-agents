# Changelog

## v2.32.2 — Deterministic event emission doctrine + session_end goal resolution + retro_cli encapsulation

Four commits on `paulingalls/free-2026-04-28-retro-counting-and-goal-cleanup` addressing a downstream-reported retro counting bug, an unbounded-event-accumulation bug, and a CLI dead-arg cleanup. 3316 tests green at every commit.

- **Deterministic Event Emission doctrine** (`docs/ideas/deterministic-event-emission.md`). Specification for replacing the LLM-authored-content + regex-content-matching pattern (e.g., `_common.QUALITY_REVIEW_RE = "(?:Quality review|QR) complete"` matching agent-emitted "Quality review clean" — the bug class behind the downstream report at `docs/ideas/retro-quality-review-counting.md`) with hook-emitted events carrying `metadata.action` discriminators. Captures full producer/consumer audit (every regex in `_common.py` + `retro_metrics.py` + `honesty_signals.py`, every SKILL.md/agent.md emission instruction), the proposed `STATUS_ACTION_*` vocabulary additions to `event_schema.py`, and a 3-milestone phasing strategy for future implementation. Feeds `/xp-plan`.
- **`session_end` resolves session-scoped goal events** (`scripts/session_end.py`). Goal events from `/xp-kickoff` and `/xp-work-selection` accumulated forever in `events.jsonl` (79 in 12 days locally) because nothing emitted `metadata.resolves` against them. `session_end` now collects goal IDs the current session owns and writes them to `metadata.resolves`, letting compaction archive them. Ownership is agent-aware: goals from `teammate-*` agents belong to that specific teammate; everything else belongs to the main session — fixes a multi-teammate worktree bug where one session_end could claim a concurrent session's in-flight goals. New `identity.is_teammate_agent_id()` helper centralizes the prefix check. Drops the session-window restriction so cleanup also archives legacy backlog. Consolidated `_compute_summary`'s four passes over events into a single `match/case` loop.
- **`retro_cli` encapsulates retro lookup** (`smm/retro_cli.py`). `render` no longer takes a positional path argument; the CLI finds the latest retro in `<smm-dir>/retrospectives/*.json` itself (lex-max on ISO-timestamped filenames). Turns `--smm-dir` from "accepted for caller symmetry; not read" (a dead arg per the user-adopted concern `3416cda13661`) into a meaningful, required argument. Lifts the `"retrospectives"` subdir literal into a `marker_names.RETROSPECTIVES_DIR` constant; `retro_history.py` and `save_retrospective.py` migrated. `xp-kickoff/SKILL.md` invocation simplified — no more "locate the newly written retrospective JSON" step.
- **Test file split: `test_pre_compact.py` extracted from `test_session_lifecycle.py`** to keep both files focused (line-budget hygiene).

## v2.32.1 — Retro Try resolution loop + server-side [refs:...] hoist

Five commits on `paulingalls/free-2026-04-28-decision-resolves-try` fixing a confirmed silent-drop bug where retro Try items were re-proposed across sessions even when the user had explicitly dropped, deferred, or adopted them. Empirical: 15/15 historical disposition events that wired `metadata.resolves: [try_id]` were silently failing because Try IDs aren't top-level events in `events.jsonl`. 3305 tests green at every commit.

- **`compute_resolutions` indexes nested `retrospective.try[].id` into `by_id`.** New synthetic `{type: "retro_try", parent_retro_id, ...}` records added during the events loop, with `setdefault` so a colliding top-level event id wins on the rare collision case. Resolutions for retro_try targets land in `other_resolutions` (default match-case branch). 4 new tests pin nested resolve via status drop, decision adopt, top-level precedence, and unresolved-try negative case.
- **`annotate_try_status` reads `resolver_type`, not bucket label.** The auto-adopted-disposition elif checked `hit.get("type") == "decision"` — but `hit["type"]` was the bucket label (target type), not the resolver event's type. So adopt-via-decision tries never got `disposition='adopted'` unless the resolver carried explicit `metadata.disposition`. `build_resolutions_map` now writes `resolver_type` into each map entry; `annotate_try_status` reads that for the fallback. End-to-end pipeline tests cover drop-strips, adopt-keeps-and-marks-resolved, cascade-on-resolved-only.
- **Server-side `[refs: id1, id2]` extraction at construction time.** New shared helper `event_builder.extract_refs_suffix(event)` strips the trailing suffix from `event["content"]` and unions extracted 12-hex IDs into `event["metadata"]["resolves"]` (defensive copy; de-duped; preserves explicit caller resolves). Called unconditionally at the end of both event-construction entry points: `event_builder.build_event` (shell `append.sh` path, used by 8 agents) and `_common.make_event` (Python direct path, used by ~15 hooks + work_selection_decide). The `[refs:...]` convention now works for every event writer, not just `xp-work-selection`.
- **Drop redundant per-helper extraction in `work_selection_decide.py`.** 32 lines deleted: `_REFS_SUFFIX_RE`, `_SPLIT_RE`, `_extract_refs`, `_build_metadata`, `import re`. `run()` simplified to pass raw content to `_common.make_event`; the hoisted helper handles the suffix.
- **Disposition string constants lifted to `event_schema.py`.** New `DISPOSITION_ADOPTED/DEFERRED/DROPPED` and `METADATA_KEY_DISPOSITION`. Producer (`work_selection_decide`) and consumers (`retro_history`, `subagent_start`, `retro_metrics`) all use the constants — same drift-prevention pattern that `METADATA_KEY_RESOLVES` already follows.

## v2.32.0 — Remove echo-gate mechanism

Four commits on `paulingalls/free-2026-04-28-remove-echo-gates` deleting the `pre_tool_echo_gate` hook, its `.pending-render-{retro,smm}-<agent_id>` marker side effects, and the `RENDER_*_PHRASES` constants the gate used to match assistant text. Resolves SMM risk `bd4210828adc` (the gate re-fired after the first signature match because the marker was not consumed reliably; user-reported).

The render CLIs (`smm_cli.py render`, `retro_cli.py render`) still emit the same H1-headed markdown to stdout — only the side effect goes away. The kickoff SKILL.md still instructs the agent to render and show output to the user; the missing piece is the hook that nagged after the fact.

- **CLI marker writes removed.** `smm_cli.py _cmd_render` now reduces to `print(render_markdown(smm))`; the now-redundant `_cmd_dump` is deleted (three internal callers — `xp-housekeeper.md`, `_preload_base.sh` ×2 — migrated to `render`). `retro_cli.py _cmd_render` drops the `markers.marker_write` block; `--agent-id` is removed; `--smm-dir` flips to optional with honest help text ("accepted for caller symmetry; not read") because the shared `run_cli` test helper passes it uniformly. Test suites pruned: `TestRenderDropsMarker`, `TestMarkerDrop`, `TestDumpPureOutput`, `TestOtherCommandsDoNotDrop`. The integration test `tests/integration/test_kickoff_flow.py` is deleted — it was structured around the echo-gate chain; surviving CLI tests cover the markdown contract.
- **Kickoff prose tightened.** `xp-kickoff/SKILL.md` Step 1 and Step 7 lose the "Terminal action of this step" / "echo-gate hook blocks the next tool call" / "drops the .pending-render-* marker" paragraphs. Replaced with a single sentence per step: "Output the render CLI's stdout to the user." `PROCESS_GUIDE.md` likewise scrubbed: "render and echo the signature line verbatim" → "render and show the result"; "All CLIs require `--smm-dir DIR`" → "CLIs accept `--smm-dir DIR`" (now factually true after retro_cli flipped to optional).
- **Hook + tests deleted.** `scripts/pre_tool_echo_gate.py` (160 lines) gone. `tests/hooks/test_echo_gate.py` (457 lines) gone. The `PreToolUse(Agent|Write|Edit|MultiEdit|Bash|Skill)` entry registering the hook removed from `hooks/hooks.json`. `TestEchoGateHookRegistration` class removed from `test_validation.py`. Resolves `bd4210828adc`.
- **Marker registry trimmed.** `PENDING_RENDER_RETRO` and `PENDING_RENDER_SMM` `MarkerDef`s removed from `scripts/markers.py` (and from `_AGENT_SCOPED_MARKERS`). `PENDING_RENDER_*` filename constants and `RENDER_RETRO_PHRASES` / `RENDER_SMM_PHRASES` tuples removed from `smm/marker_names.py`. `RENDER_*_SIGNATURE` constants retained — still consumed by the render CLIs as the rendered markdown's H1 heading. The `TestPendingRenderMarkers` class in `test_markers_review.py` deleted alongside.

Net: ~700 lines deleted across the chain, all tests green at every commit, the noisy advisory is gone.

## v2.31.4 — Carry-over debt cleanup: helper extractions

Four commits on `paulingalls/free-2026-04-28-carry-over-debt-cleanup` closing seven helper-extraction debts that had been carried over from the M-5 handoff. No behavior changes; 3326 tests green at every commit.

- **`now_iso()` in `_append_impl.py` + promote `_expand_plugin_root` → `expand_plugin_root`.** Single canonical source for the `datetime.now(timezone.utc).isoformat()` pattern that previously appeared at 9 sites across `scripts/` and `smm/`. Re-exported from `_common` for scripts/ callers; smm/ callers import directly from `_append_impl`. The 10th site (`event_builder.build_event`) keeps its inline call — `_append_impl` imports `event_builder` at top level (line 111+), so a top-level `from _append_impl import now_iso` in `event_builder` would close the cycle. Documented in the `now_iso` docstring with the exact cycle path. The `expand_plugin_root` rename drops a leading underscore; the function had a cross-module caller in `tests/hooks/test_validation.py` that was reaching for the underscore-prefixed name. Resolves 631b216984e2, 275dd47cdbf6.
- **`_common.truncate(text, max_len)`** consolidates two file-local `_truncate` helpers (`prompt_nugget.py` default 120, `question_answered.py` default 500) into a single shared function. Required `max_len` (no default) — callers differ 4× and a silent default would change behavior on a future shared use. Each caller binds a module-level `_NUGGET_CONTENT_MAX` / `_ANSWER_CONTENT_MAX` constant that names the cap's intent. `_common._truncate_for_log` is preserved as a separate variant — it uses `"...[truncated]"` to make the cap machine-readable in `hook_errors.jsonl`. Resolves f6a4f3dd522e.
- **`tests/_lock_helpers.py`** consolidates the events.lock contention pattern previously duplicated across 6 test sites. Two contextmanagers: `held_events_lock(smm_dir, *, budget=1)` for "raises LockTimeoutError" tests (4 sites), and `briefly_held_lock(smm_dir, *, hold=0.3, budget=2)` for "completes within budget" tests (2 sites, including the integration regression test that composes with `patch_commits`). The threaded helper validates `budget > hold` (`ValueError` on misuse) and asserts the holder thread exits cleanly within the join timeout (`RuntimeError` on flock leak — the original inline pattern would have leaked silently). Watchdog timeouts hoisted to module-level constants with explanatory comments. Net stats: -133 / +95 (the +95 is the new module). Resolves 555c1c7e99d8, c68464a35cfe, and the in-flight 87ebb566b99c.
- **`tests/_commit_helpers.py`** consolidates the `commits.get_committed_files` / `get_commit_message_body` / `get_head_commit_hash` patch trio that `bash_post_tool`'s commit-handling path stubs in tests. Single contextmanager `patch_commits(*, files, body, head_sha)` replaces the 3-line `with (patch, patch, patch)` block at 16 sites across 4 test files. `head_sha: str | None` (the production call legitimately returns None on missing repo). Default body is the neutral `"commit"` rather than `"[story-001] commit"` — the implicit story-id pattern was a coupling smell; story-aware tests now declare it explicitly at the call site. The class-local `_patch_commit_lookups` in `test_bash_commit.py` delegates to the shared helper while preserving leak-path-specific defaults at the call boundary. Partial-trio sites (1-of-3 or 2-of-3) intentionally not migrated — the helper would force unused patches and weaken the test signal. Resolves 338b5c5a22a2.

## v2.31.3 — SessionStart kickoff scoping + parallel test runner + lru_cache footgun fixes

Three commits on `paulingalls/free-2026-04-28-session-start-compact-no-kickoff`. One UX nit, one test-speedup, and one production bug fix that surfaced while wiring up the parallel runner. Pre-commit lefthook wall: ~48 s → ~10.5 s (78% reduction).

- **`session_start.py` skips the `/xp-kickoff` nudge on `compact` and `resume`.** The hook's GUPP body was already source-aware (GUPP_STARTUP for fresh, GUPP_RESUME for continuations), but the `__main__` block's `systemMessage` always appended "Run /xp-kickoff" — even after a compact, where re-running kickoff would redo the retro + work selection + housekeeping that just ran. New `_is_fresh_start(source)` helper centralizes the partition that was triplicated across the marker-write block, GUPP selection, and the new `_system_message(source, version)` helper. Kickoff nudge fires only on `startup` (new session) and `clear` (mid-session reset). 4 unit tests cover all four sources.
- **Test runner switch: `unittest discover` → `pytest -n auto -q`.** `lefthook.yml` now runs one parallel `pytest` invocation instead of four parallel `unittest discover` commands; `pytest-xdist` parallelism is finer-grained than lefthook's per-command parallelism. New `pytest.ini` declares `testpaths` + `pythonpath` so pytest can resolve `_bases`/`scripts`/`smm` without per-file `sys.path.insert`. Sequential `unittest` fallback retained for environments without `pytest`. CLAUDE.md scoping note (already merged) explicitly permits external runners for tests; new README "Development setup" section documents the `pipx install pytest && pipx inject pytest pytest-xdist` pattern (clean per-tool venv, no `--break-system-packages`).
- **Five flock tests patched to short timeouts.** `_append_impl.LOCK_TIMEOUT_SECONDS` is the production budget (10 s after v2.31.1). Five tests held a real flock and waited for it to fire — the assertions are about the timeout MECHANISM (raises `LockTimeoutError`) or RELEASE-WITHIN-BUDGET semantic, not the specific 10 s wait. Patching down to 1-2 s preserves the contract and shaves ~33 s of cumulative runtime. Sites: `test_parse.TestParseEvents.test_raises_on_lock_timeout`, `test_resolutions.TestReadEventsFrom.test_raises_on_lock_timeout`, `test_common.TestAppendSafeErrorLogging` (class-wide setUp), `test_attribution_regression`, `test_append_safety.TestLockBudgetTolerance`. Same pattern already in use at `tests/smm/test_append_safety.py:88` (TestLockTimeout).
- **Production bug: removed `@functools.lru_cache(maxsize=1)` from four env-dependent loaders.** `_common.{load_xp_values, load_process_guide, load_teammate_guide}` read `CLAUDE_PLUGIN_ROOT` via `resolve_plugin_root()`. `_append_impl._derive_smm_dir` runs `init.sh` which reads `cwd`. All four were keyed on nothing — so any test that called the loader under a bad env (e.g. `TestSessionStartPathValidation` patches `CLAUDE_PLUGIN_ROOT="/nonexistent/path"`) cached an empty result and poisoned every subsequent in-process call. The bug hid under unittest's alphabetical-by-class ordering (PathValidation tests happened to run after the XP-values tests in some files); pytest's source-order discovery + xdist worker reuse exposed it as 22 failures. **In production, every hook is a fresh `python3` process, so the cache never had a hit anyway** — pure dead weight on top of a real test-isolation hazard. Three `cache_clear()` calls in test setUp/tearDown (which were a band-aid signal) become invalid by construction once the decorators are gone — removing them is the courageous cleanup, not a patch.
- **Regression test pins the contract.** `test_loader_re_reads_after_env_changes` patches `CLAUDE_PLUGIN_ROOT` to a bad value, asserts empty, then calls again with normal env and asserts non-empty. Re-introducing any of the four caches will fail this test. CLAUDE.md gains a "Test isolation gotcha" paragraph documenting the trap so future contributors don't recreate it.

All 3326 tests green under both `python3 -m unittest discover` (89 s) and `pytest -n auto -q` (~13 s on 16 cores).

## v2.31.2 — M-5 polish bundle + bash_post_tool side-effects narrowing

Six commits on `paulingalls/free-2026-04-28-m5-polish-bundle-and-side-effects` close the close-reviewer concern from v2.31.1's PR #19 and fold in the M-5 try-#2 polish bundle. Two correctness changes (side-effects narrowing, atomicity gap) plus three contract/convention tightenings, one doc clarification, and one pin test. SMM constraint and 10 already-resolved concerns swept up via per-concern closure events.

- **`bash_post_tool._handle_commit` side-effects gated behind `is_xp_agent_leak`.** Closes the close-reviewer concern from v2.31.1: hoisting `is_git_commit` above the `is_xp_agent` skip preserved commit-event recording but let a leaked-type Bash drive `_handle_commit` to completion — including `_resolve_lint_on_commit`, `security.consume_security_triaged`, `markers.reset_review_cycle`, and the QR-warning return. Under leaked `agent_id="main"` that would consume main's security marker, overwrite review-cycle state, and resolve lint concerns under the wrong identity. The fix narrows the exemption: a new keyword-only `is_xp_agent_leak: bool = False` parameter, set from `_common.is_xp_agent(input_data)` in `run()`, short-circuits side effects after `bulk_append_safe` lands the commit event. 4-of-4 negative tests in `TestCommitRecordingDespiteXpAgentType` cover security marker, review cycle, lint resolution, and QR-warning suppression.
- **`record_scaffold(commit_sha)` is now required.** Previously `commit_sha: str | None = None` — the 3-stage HEAD-advancement gate ran only `if commit_sha:`, so any caller (test, future entry point, SKILL drift) that omitted the kwarg silently bypassed sha-existence + HEAD-match + scaffold-prefix checks and could flip a surface to covered with no commit-landed verification. Production was safe (`scaffold_cli.py:264` already supplied the arg), but the function-level optionality was the gap. The fix makes `commit_sha` required at the signature; the gate runs unconditionally; the previously-vestigial `if commit_sha:` guards are removed. `TestRecordScaffoldRequiresCommitSha` pins the contract — `# type: ignore[call-arg]` tests the runtime contract past the type checker. The 9 existing record_scaffold tests that didn't exercise the gate are migrated to a `_RecordTestBase._seed_commit()` helper so the now-required arg stays visible at every site.
- **`scaffold_cli` `--repo-root` required on apply-install / apply-verify / apply-revert.** Brings the three remaining apply-* subcommands in line with the rest of the CLI: apply-write, apply-commit, apply-record, detect-surfaces, find-introducing-commit, and detect-monorepo were already `required=True`, but apply-install/verify/revert defaulted `--repo-root` to `Path.cwd()`. Mixed contract risked silent surprise when a caller invoked from an unexpected cwd. Zero churn for existing tests — every apply-install/verify/revert test in `test_scaffold_cli.py` already passed `--repo-root` explicitly. New `TestApplyRequiresRepoRoot` pins the contract via `run_cli` subprocess (matches the 40+ uses in this file).
- **SHA abbreviation drift `[:12]` → `[:7]`.** `record_scaffold` HEAD-advancement gate diagnostic strings used 12-hex; `branching.py` used `[:7]` (git short-sha convention). Standardized on `[:7]` to match git and reduce reader cognitive load. `test_head_mismatch_reason_uses_git_short_sha` pins both directions: `assertIn(scaffold_sha[:7], reason)` AND `assertNotIn(scaffold_sha[:12], reason)` — guards against a refactor that drops the SHA from the diagnostic entirely.
- **SKILL.md add-complementary loopback clarification.** The Step 1c "Add complementary tool" branch loops back to Step 3 and keeps Step 1b's `$REPO_ROOT` scope. The existing loopback note documented `$REPO_ROOT` persistence but was silent on whether the Step 1d re-invocation probe re-runs. Doctrine answer added: re-invocation does NOT re-run; Step 1b's monorepo path selection persists.
- **Multi-pyproject false-positive contract pinned.** `detect_monorepo` flags any subdir containing `pyproject.toml` as a "package" — including `examples/`, `docs/`, and `vendor/` subdirs. Doctrine accepts this risk because the SKILL agent negotiates with the customer downstream about which detected "package" actually deserves a scaffold. New `test_detect_multi_pyproject_includes_examples_docs_and_vendor` seeds 4 pyprojects and asserts all 4 appear; docstring cites concern `828ea567ff55` so a future reader doesn't 'fix' the test by adding an exclude-list. Helper extraction: `_mk_pyproject(parent, name)` consolidates the 3-line `_mkpkg` + write_text pattern duplicated 5 times across multi-pyproject tests.
- **SMM Constraint scaffold-commit-subject updated to doctrine wording.** Was 3-slot but using `<surface>`; now matches doctrine `<category> <target> via <tool>`. Code at `scaffold_post.py:62` already produced this form — data-only update. 10 already-resolved concerns from M-5 + the plan-reviewer's bulk-closure concern (`7a6cb4af8b7e`) all closed via per-concern status events with one-line WHY each, per the medium plan-reviewer guidance against bundling 9+ resolves into a single audit-trail entry.

## v2.31.1 — events.jsonl write-path: silent failures made loud

Fixes the sprint-040 attribution gap: 14 of 15 git commits silently dropped from `events.jsonl` because three failure surfaces stacked in the `bash_post_tool` PostToolUse hook chain — oversize stdin exited 0 silently, `bulk_append_safe` swallowed `LockTimeoutError`/`ValueError` via `contextlib.suppress`, and the 2-second flock budget lost the race against parallel async-hook traffic. A separate finding: `async: true` on `bash_post_tool.py` (since `1b1d4b2`, March 19) silently discarded the QR-warning and session-end-checklist nudges that `run()` returns. Six commits on `paulingalls/free-2026-04-28-sprint-040-attribution-gap` make every silent-drop path loud, give the flock budget realistic headroom, and restore the agent-facing nudges. New regression test pins the end-to-end invariant under flock contention.

- **`_common._log_hook_error` helper (new).** Best-effort diagnostic log: appends one JSON line per silent failure to `${SMM_DIR}/hook_errors.jsonl` and mirrors to stderr. Each line capped at 2 KB; written via single `os.write` to a file opened with `O_APPEND | O_NOFOLLOW | 0o600`, matching the `_safe_open_nofollow` symlink-safety convention. Never raises — failure traces don't crash the parent. Field-level truncation (200/500-char) keeps lines well under the cap; paranoid backstop drops context if the full entry still exceeds.
- **`read_hook_input` instrumented.** Both silent branches (`JSONDecodeError`/`ValueError`, oversize stdin) call `_log_hook_error` before `sys.exit(0)`. `_MAX_STDIN_SIZE` raised 1 MB → 10 MB so realistic lefthook output (parallel test suites + pyright + ruff + shellcheck) doesn't trip the cap.
- **`append_safe` + `bulk_append_safe` instrumented.** Replaced `contextlib.suppress(LockTimeoutError, ValueError)` with explicit try/except that calls `_log_hook_error`. External behavior unchanged on the success path; lossy paths now leave a structured trace naming the dropped event(s) and the suppressed exception. Symmetric `try/except/else` shape across both helpers.
- **Flock budget bumped 2 s → 10 s.** Public `LOCK_TIMEOUT_SECONDS` constant in `_append_impl.py` threads through all four alarm sites (`read_with_lock`, `append_event`, `bulk_append`, `replace_events_file`) and the `_on_alarm` error message. Public (no underscore) because cross-module references via docstrings + tests already reference it — de-facto contract is now de-jure.
- **`async: true` dropped on `bash_post_tool`.** Restores the QR-warning nudge ("No quality review found since previous commit. Run /xp-quality-review before committing.") and session-end-checklist nudge that `run()` returns — both unreachable since `1b1d4b2`. Added `TestAsyncHooksHaveNoStructuredReturn` integrity guard: AST-walks every `async: true` script and asserts none calls `_common.hook_output` or `_common.block_output`. Escape valve: a script may opt out by including the line `async-output-ok` (line-anchored — substring matches in prose are rejected) in its module docstring. Reuses `_common._expand_plugin_root` for `${CLAUDE_PLUGIN_ROOT}` substitution; single `ast.parse` covers the call walker and the marker check.
- **Defensive: `is_git_commit` hoisted above `is_xp_agent` skip in `bash_post_tool.run()`.** A `git commit` Bash tagged with leaked `agent_type="xp-..."` would previously hit the early-return and drop the commit event silently. Recording is not recursion-inducing — every git commit must leave a trace regardless of which agent's stack the Bash call originated from. Same shape as `subagent_stop.py:162-182`. Exemption is narrow: non-commit Bash from xp-agents still skips.
- **Regression test (new).** `tests/integration/test_attribution_regression.py` holds an external flock on `events.lock` for ~3 s and asserts `bash_post_tool.run()` with a valid git-commit input still records the commit event. Stood up first as `@unittest.expectedFailure` so the team witnessed the silent-drop reproducing under the original 2 s budget; the marker was retired in the same commit that bumped the budget — keeps `git bisect` honest. Required-green guard going forward.
- **Cross-cutting test cleanup.** `TestLockTimeout` and `TestLockBudgetTolerance` migrated onto `_SMMTestCase` + `make_event` (was: inline tempfile + dict literal). `TestLockTimeout` patches `LOCK_TIMEOUT_SECONDS` to 1 s for itself so the suite doesn't pay the new 10 s budget on the timeout-mechanism test — the assertion is "raise on timeout", not "wait 10 s". Module-level `_read_hook_error_log(smm_dir)` helper deduped between the two error-logging test classes in `test_common.py`.

Carry-over debts surfaced and recorded for future cleanup: `patch_commits()` extraction (16+ test sites duplicate the same `commits.get_*` patch trio), threaded flock-hold helper (2 sites with the same `threading.Event`/`LOCK_EX`/release pattern), `now_iso()` helper (6+ `datetime.now(timezone.utc).isoformat()` call sites), `_truncate` consolidation (two near-duplicates in `prompt_nugget.py` + `question_answered.py`), ruff batching in `_resolve_lint_on_commit` (now-sync hook spawns one ruff per file), runtime-budget test for sync `bash_post_tool`, `_expand_plugin_root` rename (now has cross-module callers), `coordination.py` SIG_DFL vs `_on_alarm` doctrine question. None blocking; all filed as `debt`/`question` events for retrospective triage.

**Cross-session verification deferred.** `hooks.json` changes take effect at the next Claude Code restart per platform constraints. Post-restart, the next commit on this repo should land its `commit` event in `events.jsonl` reliably under any contention realistic for the workload, and a `${SMM_DIR}/hook_errors.jsonl` will appear if any silent-failure path fires — making future regressions visible at the seam where they originate.

## v2.31.0 — `/xp-scaffold-acceptance` ships (Scaffolding doctrine v1)

Plan `paulingalls/plan-scaffold-acceptance-v1` lands on `main` after five sprints (M-1..M-5, sprint-036..sprint-040). New skill `/xp-scaffold-acceptance`: agent-driven acceptance test harness setup. Detects active teammates and existing tooling, asks the customer to pick a surface and tool (with monorepo path placement when relevant), web-refreshes the tool's latest version, plans + previews the scaffold for explicit yes/show-files/no confirmation, then atomically writes + installs + verifies + commits and flips the system_context surface to covered. Re-running on a scaffolded repo offers add-complementary / redo-via-revert / cancel.

- **New skill `xp-scaffold-acceptance`** at `plugins/xp-agents/skills/xp-scaffold-acceptance/SKILL.md`. 9-step inline flow (1→3→2→4→5→6→7→8→9) — Step 3 picks tool before Step 2 web-refreshes its version. Refuses to run while teammate worktrees are live (verbatim doctrine refusal text). All entrypoints route through `scripts/scaffold_cli.py`; no inline `python3 -c` in SKILL.md.
- **Stage-aware commit + atomicity gate.** Stage 0 commits on HEAD with `[chore] Scaffold <category> <surface> via <tool>` subject + hyphenated trailers (Tool-version / Files-created / Files-modified / Verification / Resolves-Event). Stage 1+ creates `<user>/scaffold-<surface>` off primary, refuses on protected branches. `apply-record` requires `--commit-sha` and gates the surface flip on a 3-stage check: existence (`git cat-file -e`) + HEAD == sha + HEAD subject prefix `[chore] Scaffold `. Closes the atomicity gap where state could lie about what landed.
- **Snapshot + revert pipeline.** `apply-write` snapshots affected files into TMPDIR (uuid4 hex prefix) before any write; `apply-install` and `apply-verify` auto-revert on failure; `apply-revert` is the explicit cancel between phases. Revert restores both file bodies and added-file deletions.
- **Monorepo path placement.** New `detect-monorepo` CLI subcommand; priority-ordered detection across pnpm / turbo / nx / lerna / npm-workspaces / yarn-workspaces (yarn.lock differentiation) / cargo (`tomllib` — see Python 3.11 floor below) / multi-pyproject. Step 1b in SKILL.md asks the customer where the scaffold should land before detection runs at the chosen scope. No silent path assumptions: missing-on-disk picks re-prompt rather than falling back to repo root.
- **Re-invocation flow.** New `find-introducing-commit` CLI subcommand walks `git log --diff-filter=A --follow` per config file and returns the OLDEST commit (sorted by `%ct` UNIX timestamp — robust across timezone boundaries). SKILL.md Step 1d offers `add-complementary` (loops to Step 3 with the existing tool excluded from canonical options), `redo-via-revert` (emits the introducing-commit revert pointer), and `cancel`.
- **Bun first-class.** Added to `_CANONICAL_TOOLS["http_websocket"]`, `["cli"]`, `["sdk"]` at end of each list (intentional fall-through priority — established tools win over bun when both configs coexist; locked by `test_bun_yields_to_earlier_canonical_when_both_configured`). `bunfig.toml` registered as the config-file signal.
- **Concern auto-resolution wired.** When the customer-chosen surface had a missing-acceptance concern raised by `xp-system-analyzer`, `apply-record` appends a `decision` event with `metadata.resolves=[concern_id]` so the gap-surface concern cascades closed. The decision event also carries `metadata.snapshot_id` and `metadata.commit_sha` for provenance.
- **Web-refresh + decline.** Step 2 uses `WebSearch` to pin `tool_version` before plan finalization. Customer-named non-canonical tools route through `scaffold_cli.py assess-tool`: agent passes gathered guidance via stdin heredoc; CLI returns `{decline: bool, reason}` and the skill exits cleanly when guidance is unreliable rather than guessing.
- **`branching.create_scaffold_branch` honest errors.** New `_try_checkout` helper returns `(ok, stderr)`. `_create_or_resume_branch` gained `honest_errors=True` (scaffold-only) so checkout/create failures map to `None` instead of `sys.exit(1)`, feeding into `commit_scaffold`'s `CommitResult(ok=False, reason=...)` contract. Story/sprint/free helpers keep their legacy sys.exit behavior.
- **Python floor raised 3.10 → 3.11.** `tomllib` (stdlib in 3.11+) required for Cargo / multi-pyproject monorepo parsing. Updated `.github/workflows/tests.yml` matrix, `CLAUDE.md`, `README.md`, `plugins/xp-agents/pyrightconfig.json`. Pre-commit and CI both run 3.11+.
- **`SCAFFOLDING_DOCTRINE.md` moved `docs/ideas/` → `docs/completed/`.** Parallels `ACCEPTANCE_TESTING_DOCTRINE.md`. Doctrine prose reconciled with implementation: hyphenated trailer keys (was: spaces) and canonical 3-slot subject example (was: 2-slot "with Playwright" form). Added `Resolves-Event:` to the canonical trailer block.
- **`apply-* --repo-root` standardized to required.** Was: `cwd()` default on apply-write/install/verify/revert; required on apply-commit/apply-record. Now required across all six. Caller must explicitly say where; no silent cwd fallback. Same change made `apply-record --commit-sha` required.
- **Capstone E2E.** `tests/scaffold/test_scaffold_m5_e2e.py` drives the full apply pipeline against a fixture pnpm monorepo with `packages/web/playwright.config.ts` (HEAD-1) + `packages/api/` (gap). Validates that `find-introducing-commit` pin-points the scaffold introducer and that `--repo-root <repo>/packages/api` flows through Steps 4-9 with the test file landing under `packages/api/`, NOT the repo root (asserted both positively and negatively).
- **Test count.** ~3300 tests across `tests/scaffold/`, `tests/hooks/`, `tests/integration/`, `tests/engine/`, `tests/smm/`. Pre-commit lefthook runs all suites + ruff + pyright on every commit.

Known carry-over debt: `_PLAN_INPUT/_setup_smm/_run` duplicated across `test_scaffold_e2e.py` and `test_scaffold_m5_e2e.py` (event `ac18375ca048`) — extract to `_helpers.py` + a `_ScaffoldCLITestCase` base in conftest before a third E2E variant lands.

## v2.30.8 — Sprint-acceptance criteria aligned with BDD doctrine

`ACCEPTANCE_TESTING_DOCTRINE.md §"BDD Prose as the Universal Acceptance Format"` has required Given/When/Then for every story's `acceptance_criteria` since it shipped, but the `xp-sprint-start` skill template never reflected it — so 12+ sprints drifted to bullet-list criteria. Customer caught the drift at sprint-038 retro. (Note: the scaffold-acceptance Milestone 3 work referenced in early drafts of this entry lives on `paulingalls/plan-scaffold-acceptance-v1` and ships when the plan branch lands on main after M-4 + M-5.)

- **`xp-sprint-start/SKILL.md` Acceptance Criteria aligned with BDD doctrine.** Universal bullet (not just the optional capstone) now requires Given/When/Then prose with `And`/`But` continuations, the canonical `E2E:` prefix made explicit per "make implicit explicit," and a BDD-runner recommendation: when `system_context.json`'s `acceptance_surfaces` lists Cucumber/behave/SpecFlow, criteria are written as executable Gherkin `.feature` scenarios pointed at via `acceptance_execution.type`; otherwise prose GWT plus the project's native test runner is the default. Step 6 JSON example carries 3 criterion strings modeling basic, And-continuation, and E2E shapes plus a caption pointing BDD-runner readers at Gherkin substitution.
- **No CLI validation added.** The codebase has no `stderr-warn + exit 0` precedent — every existing CLI exits non-zero on stderr output, so a soft check would be misread as failure. The skill prose is the forcing function; drift gets caught at review/retro the same way every other prose convention does.

## v2.30.7 — Probe-adoption miss decomposition

Sprint-036's retro reported `probe_adoption_rate=0% (0/2)` and the author wrote two follow-up Tries to investigate. Reading the code with the customer surfaced two issues: Try #4's framing was confused (the metric already filters to "probe fired with candidates" — adding a population-level concern count measures something tangential), and the existing "any code commit anywhere has any candidate ID" matcher was sloppy enough to attribute hits across agents. The fix replaces the loose match with strict per-agent pairing and decomposes adoption misses into named sub-buckets so future retros can diagnose *why* adoption was low rather than just observing the rate.

- **Strict per-agent pairing in `_compute_probe_adoption`.** Each probe pairs with the next-by-`agent_id` COMMIT in the sprint window. A `consumed: set[int]` index tracks already-paired commits so two probes by the same agent before a single commit don't both claim it (the original implementation had this double-pairing bug — caught in /xp-quality-review).
- **Four-way classification.** Each probe lands in exactly one bucket: `hit` (paired commit's `metadata.resolves` overlaps the probe's candidates), `escape` (paired commit had `Resolves-Event: none`), `divert` (paired commit referenced a different ID), or `silent` (no paired commit followed). `hits + escape + divert + silent == probe_total` by construction.
- **Backward-compatible digest fields.** Existing `probe_adoption_rate` / `probe_adoption_hits` / `probe_adoption_total` keys remain unchanged. New `probe_escape` / `probe_divert` / `probe_silent` fields are added alongside.
- **Retrospective agent reads the buckets.** `xp-retrospective.md` §Resolution-Link Adoption keeps the existing 0.50 flat-rate Fix threshold and now names the dominant miss bucket(s) alongside it. Doctrinal interpretation: escape dominance reads "agent declined the suggestion to clear the gate" (suggestions aren't trusted); divert dominance reads "agent had its own context the probe didn't see" (candidate set is noisy). Ties are listed and read as themselves diagnostic. `silent` is informational only — non-zero counts surface but do not by themselves trigger a Fix.
- **Test guards added.** Seven new cases in `TestProbeAdoptionRate`: each miss bucket gets a dedicated test, plus `test_two_probes_same_agent_pair_with_distinct_commits` (locks in the consumed-set fix), `test_strict_pairing_ignores_other_agent_commits` (locks in same-agent matching), `test_strict_pairing_hit_with_distinct_agents`, and `test_probe_outside_sprint_window_is_excluded`. Helpers `_probe_event` and `_code_commit` gained an optional `agent_id` parameter (default `"main"` so existing single-agent tests stay green).

Try #1 (event `858dc6a51be5`) is resolved by this commit. Try #4 (event `66ed8f4aea82`) is dropped via a separate decision event — the same investigation is answered better by this decomposition.

## v2.30.6 — Close-reviewer records concerns as SMM events

The xp-close-reviewer agent previously returned Keep/Concern/Block as text prose; the close skill displayed it once and moved on. Concern and Block items were ephemeral — visible in chat output but never persisted as SMM events. Multiple times this session, valuable concerns from PR #6 / #7 close-reviews would have vanished into the scrollback if I hadn't manually filed them.

- **`xp-close-reviewer.md` Step 4 added.** Before returning the prose summary, the agent now files an SMM `concern` event for each Block (severity `high`) and Concern (severity `medium`) bullet via `${CLAUDE_PLUGIN_ROOT}/smm/append.sh --type "concern"`. Keep bullets remain prose-only. Mirrors the xp-plan-reviewer pattern.
- **`--files` discipline.** When a bullet cites concrete file paths, the agent attaches them via `--files '[...]'` so the commit-auto-link hook can nudge a future fix commit to add `Resolves-Event: <id>`. Same STRUCTURAL link wiring xp-plan-reviewer uses.
- **Recording happens BEFORE the prose summary.** If the user picks "Abort — fix concerns first" at the merge confirmation, the concerns stay filed for the next session.
- **`metadata` fields.** Each event carries `close_mode`, `source_branch`, `target_branch` for downstream filtering.
- **Test guard added.** `test_close_reviewer_records_concerns_as_smm_events` in `tests/integration/test_sprint_close_chain.py` regex-asserts the agent prompt contains both severity-paired `--type "concern"` blocks, the `--files` discipline, and the before-prose ordering. Catches drift if any of those guarantees disappears.

## v2.30.5 — Close skills push target branch after merge

Fix surfaced when verifying sprint-036's PR #6 status on GitHub: the local merge happened (`branching.py merge-branch` produced commit `e63e5e9`) but the target branch was never pushed back, so GitHub kept the PR open indefinitely. Same gap in all three close skills.

- **All three close-skill SKILL.md files** now insert `git push origin <TARGET_BRANCH>` between the merge and the cleanup step (delete for sprint/free, archive+delete for plan). The `&&` chain guarantees push only runs after a clean merge and cleanup only runs after a clean push — push failure leaves the source branch alive for retry; merge failure halts before push as before.
- **Local-only fallback documented.** When `git remote` returned no remote in Step 2, the push line is omitted (no PR to close).
- **Test guard added.** New `test_pushes_target_after_merge` mixin in `_close_fixtures.py` asserts `git push origin <TARGET_BRANCH>` appears in the close skill body, after `merge-branch` and before `delete --branch`. Runs across all three close skills.

## v2.30.4 — Drop REVIEW_INPUT file from close skills

Removes the `REVIEW_INPUT` JSON-file pattern from all three close skills (xp-sprint-close, xp-plan-close, xp-free-close). Discovered while dogfooding `/xp-sprint-close` for the first time: the preload's `mktemp` creates an empty file, then SKILL.md tells the LLM to `Write` to that path — but Claude Code's Write tool rejects existing files unless they're read first. The Write call failed silently while the Agent call ran in parallel, falling through using the SubagentStart-style context already in the prompt. The reviewer flagged the 0-byte file in its Concerns block.

Every field the JSON file carried (`mode`, `source_branch`, `target_branch`, `diff_command`) was already in the Agent prompt anyway. The file was a redundant indirection layer copied from forked-skill patterns that DO use SubagentStart injection (xp-housekeeper, xp-retrospective). For close skills there is no SubagentStart injection — the path-passing happens manually through the Agent prompt — so the file added no value and created a deterministic LLM-tool-failure mode.

- **Remove tempfile pattern from 3 preloads.** `xp-{sprint,plan,free}-close/scripts/preload.sh` no longer creates `${SMM_DIR}/.close-review-input.XXXXXX` via mktemp. One fewer subprocess per close invocation.
- **Inline prompt sections in 3 SKILL.md files.** Replaced the "write JSON file" Step 4 with a direct Agent invocation that embeds `## Mode`, `## Source Branch`, `## Target Branch`, `## Diff Command` as inline prompt sections. Prompt template split into two clean blocks gated by `When GH_AVAILABLE=true:` / `When GH_AVAILABLE=false:` headings (avoids the inline `# or:` comment that the LLM might transcribe verbatim).
- **xp-close-reviewer agent reads from prompt context.** Step 1 now reads four prompt sections directly. No Read tool call. Failure mode is "section missing" rather than "file missing or malformed JSON."
- **Cleanup.** `_preload_base.sh` sweep glob no longer matches `.close-review-input.*`. `marker_names.CLOSE_REVIEW_INPUT_PREFIX` removed. Stale `subagent_start.py` docstring updated.
- **Test contract.** New mixin assertions in `_close_fixtures.py`: `test_does_not_emit_review_input` (preloads no longer echo REVIEW_INPUT), `test_prompt_template_carries_close_review_fields` (four section headings appear with actual command values, regex-guarded against heading-without-value regressions, plus per-branch `assertIn` for both `gh pr diff` and `git diff` forms). Two obsolete tests deleted.

Net change: −90 lines across 15 files. Zero new attack surface; reduced filesystem operations; one fewer Read tool call in the reviewer per close invocation.

## v2.30.3 — Trailer rate metric fix

Fixes the 3-retro declining trailer rate (73%→62%→60%). Root cause: `Resolves-Event: none` (valid discipline — developer explicitly declares nothing to resolve) was counted as "no trailer" because "none" isn't a valid hex ID. Fix: `extract_resolves_trailer` now returns a `has_trailer` boolean; `bash_post_tool` records `metadata.has_resolves_trailer`; `retro_metrics` counts both `metadata.resolves` and `has_resolves_trailer` for the discipline rate.

## v2.30.2 — System-analyzer branching_strategy fix

Fixes the root cause of branching stage reading as 0 instead of 2: the system-analyzer agent's `create` command does a full file replace, wiping `branching_strategy` that was written by the earlier `edit-branching` step. Fix: agent prompt now instructs including `branching_strategy` and `acceptance_surfaces` directly in the create JSON. `edit-branching` and `edit-acceptance-surfaces` are reserved for update-mode patches only.

## v2.30.1 — Try item ID stamping (try_status fix)

Fixes a 3-retro-old gap where `try_status[*].resolved_this_session` always showed `false` for Try items without `event_refs` (process improvements like "wire metadata.resolves"). Root cause: `annotate_try_status` only matched by hex IDs in content/refs — Try items with no referenced events had nothing to match against.

- **Stamp Try items with unique IDs at save time.** `save_retrospective.run()` assigns a 12-char hex `id` (via `secrets.token_hex(6)`) to each Try item that doesn't already have one. Existing IDs are preserved.
- **Match Try items by own ID.** `annotate_try_status` includes `item.get("id")` in the token set, so a Try item whose ID appears in the resolutions map is correctly flagged as resolved.
- **Include Try item ID in preload refs.** `get_try_items()` prepends the Try item's `id` to the `[refs: ...]` suffix, so the adopt command's `_extract_refs` wires it into `metadata.resolves`.
- **Review-input filename constants.** `CLOSE_REVIEW_INPUT_PREFIX` and `SPRINT_REVIEW_INPUT_PREFIX` consolidated in `marker_names.py`. 20+ Python callers updated. Resolves debt `2b3680f59e6c`.

## v2.30.0 — Team-scenario branching doctrine (M-5) + burn-down

Sprint-035 delivers Milestone 5 of the branch-lifecycle plan: branching doctrine now covers team scenarios. All 5 milestones of the Branch Lifecycle execution plan are complete. Session also paid down retro Tries (test file splits, review-input constant consolidation) and the plan's refactor debt.

- **Pre-existing branch detection on `create-sprint` and `create-plan`.** CLI now outputs `created: <branch>` or `resumed: <branch>` so skills can detect pre-existing branches and prompt the user interactively. Added public `plan_branch_name()` function (mirrors `sprint_branch_name()`). Updated `xp-sprint-start` and `xp-plan` SKILL.md with resumed-branch handling instructions.
- **Plan-branch divergence detection.** New `check_plan_divergence(cwd, smm_dir, threshold=10)` counts how far a plan branch has fallen behind primary. At >= threshold commits behind, outputs a warning with suggested `git merge` action (not rebase -- safer for shared branches). New `check-divergence` CLI subcommand. Wired into `xp-sprint-start` step 8 to record a concern event when divergence exceeds threshold.
- **Team Scenarios section in BRANCHING_DOCTRINE.md.** Documents four team-scenario decisions: pre-existing branch detection (detect + interactive prompt), divergence handling (concern + suggest merge), rebase discipline (no auto-rebase, `--no-ff` everywhere), remote push timing (push at close only). Three open questions marked resolved with cross-references.
- **Capstone integration tests.** 8 E2E tests in `test_branching_team_scenarios.py` covering pre-existing sprint/plan branch detection (created/resumed output) and divergence detection (below/at/above threshold, custom threshold, merge-not-rebase assertion).

### Pre-sprint burn-down

- **Split `test_subagent.py` (500 -> 409 lines).** Extracted `TestSprintReviewerDone` into `test_subagent_sprint_reviewer.py` (112 lines). Resolves concern `426a8155be98`.
- **Split `branching.py` CLI into `branching_cli.py` (553 -> 414 lines).** Extracted CLI dispatch (`_cmd_*`, `_print_or_skip`, `main`/argparse) into `branching_cli.py` (164 lines). Renamed `_BRANCH_MIN_STAGE` -> `BRANCH_MIN_STAGE` (public cross-module constant).
- **Consolidate review-input filename constants.** Added `CLOSE_REVIEW_INPUT_PREFIX` and `SPRINT_REVIEW_INPUT_PREFIX` to `marker_names.py`. Updated 20+ Python callers to use constants instead of hardcoded strings. Resolves debt `2b3680f59e6c`.

## v2.29.1 — Backfill story_id reconciler (post-M-4)

Closes the deferred sprint-034 retro Try #1: a one-shot reconciler for historical commit events whose `metadata.story_id` was either missing (file-overlap fallback returned ties → `None`) or wrong (file-overlap attributed to a different story than the commit message named). The Tier-0 `[story-NNN]` prefix parser shipped in v2.28.1 fixed forward; this script corrects the historical record so retros that look back across multiple sprints get accurate per-story metrics.

- **Add `scripts/backfill_story_id.py`.** Walks `events.jsonl`, finds `commit` events whose content starts with `[story-NNN]`, and writes the prefix value into `metadata.story_id` when it differs (or is missing). Default is dry-run; `--apply` rewrites atomically via `_append_impl.write_text_atomic`. `--smm-dir` is optional and falls back to `resolve_smm_dir()` — matches the operator-script convention shared by `smm/repair.py` and `smm/compact.py`. Returns a `Report` dataclass with `commits` / `with_prefix` / `changed` counters. Idempotent: a second run reports zero changes. 8 unit tests under `tests/smm/` covering dry-run vs apply, missing/wrong/matching `story_id`, no-prefix commits, non-commit events, counter semantics, and metadata-preservation.

## v2.29.0 — Free-session branch lifecycle (M-4) + Pre-M-4 burn-down

Sprint-034 implements Milestone 4 of the branch-lifecycle plan: free sessions never commit to protected branches, orphans surface at every kickoff, and `/xp-free-close` closes a free branch with PR + review + merge. 3/4 stories delivered (story-003 deliberately dropped after platform analysis). Sprint also paid down a six-item retro burn-down before M-4 work started, and consolidated the third copy of close-skill SKILL.md guard tests into a shared mixin.

- **Add `/xp-free-close` inline skill (mode=free).** Eight-step orchestration mirroring `/xp-plan-close` with the plan-archive step omitted (free branches aren't tracked in `execution_plan.json`). `TARGET_BRANCH` resolves via `branching.py get-primary` so free-close always targets the integration branch even when a plan branch is recorded. Mode token is `"free"`; the close-reviewer's `### free` section (shipped in v2.27.0) provides standard-quality-review focus rather than sprint/plan-level cross-cutting analysis. `&&` chain runs `merge-branch && delete` — branch survives if the merge fails.
- **Kickoff Step 2.5: auto-create `<user>/free-YYYY-MM-DD-<slug>` on protected.** When the user picks "Free session" at branching stage `>= 1` AND HEAD is `main`/`master`, kickoff runs `branching.py create-free` with a slug derived from the session goal and checks out the resulting branch before Work Selection. Stage 0 short-circuits (no branch discipline at that stage); already-on-non-protected short-circuits (don't nest branches). Free sessions never commit directly to a protected branch at Stage 1+.
- **Kickoff Step 2.6: orphan free-branch triage at every kickoff.** New `### ORPHAN_FREE_BRANCHES` preload section lists branches returned by `branching.py list-free` (excluding HEAD). For each orphan the skill asks merge/keep/delete via `AskUserQuestion`; "merge" routes through `/xp-free-close`, "delete" gates on user confirmation and on git's own unmerged-branch refusal in `branching.py delete`. Runs regardless of session mode — orphan detection is the safety net for free sessions ended without `/xp-free-close`. New `_preload_base.sh` helper `branching_list_free` mirrors the `sprint_exists`/`plan_count` thin-wrapper convention.
- **Capstone integration test (`test_free_session_lifecycle.py`).** Single end-to-end test on a hermetic repo (no mocks): kickoff #1 → `create_free_branch` + 2 commits → switch back to main → kickoff #2 (orphan section surfaces) → `merge_branch` into primary with `--no-ff` → `delete_branch` → kickoff #3 (no orphan again). Asserts the cross-cutting invariants from the milestone's done-state: `--no-ff` merge produces 2 parents pointing at primary-tip + free-tip, both files from the free branch end up in primary's working tree, the branch is gone, and the orphan section appears/disappears across kickoffs.
- **Story-003 (`session_end` advisory nudge) dropped.** Per Claude Code docs, `SessionEnd` cannot block — only stderr-to-user. The user can't act in-session because Claude Code is exiting; story-002's orphan-detection at next kickoff is the actionable safety net. Recorded as a deliberate scope cut, not a deferral. M-4's `done` field doesn't list `session_end` as a deliverable.

### Pre-M-4 burn-down (Pass 1)

Six items adopted from sprint-033's retro and shipped before M-4 work started so M-4 stories inherit the cleanup:

- **Consolidate `git init -b main` test fixtures onto `_branching_fixtures.init_repo`.** 12 inline blocks across `test_worktree.py` (9), `test_identity.py` (2), and `test_coordination.py` (1) collapsed onto the existing `init_repo` helper. `_bases.py` sites stayed inline — different shapes (one seeds README, one deliberately omits the initial commit). Resolves debt `7a1b15c8d81f`.
- **Extract `_ClosePreloadCommonTests` mixin BEFORE `/xp-free-close` lands as the third consumer.** 8 shared preload assertions moved into `tests/_close_fixtures.py`; subclasses inherit the mixin plus `_IntegrationTestCase` and supply `_PRELOAD`. Skill-specific `TARGET_BRANCH` test stays per-subclass. `/xp-free-close` (story-001) inherits cleanly. Resolves debt `ed8a876ac3c1`.
- **Migrate `prepare_review_data.py` to per-invocation tempfile.** Closes the multi-worktree race that v2.28.0 fixed for `xp-close-review-input` — `xp-sprint-review` was using the same fixed `<smm_dir>/.sprint-review-input.json` shape. New `--target` CLI arg is required; preload mktemps and passes the path; `_preload_base.sh`'s stale-tempfile sweep extends to `.sprint-review-input.*`; `subagent_stop` cleanup globs the new pattern (covers both legacy and per-invocation files). Resolves debt `0d9fda3d3b5b`.
- **Soften kickoff echo-gate from hard block to advisory `additionalContext`.** Per constraint `2e84b909ee0d` (hook nudges via `hookSpecificOutput.additionalContext`, not stderr+exit-2). `pre_tool_echo_gate.run()` now returns `str | None`; `main()` emits `hook_output("PreToolUse", advisory)`, exit 0. Marker stays in place when phrases are missing so the nudge re-fires until the agent surfaces the rendered block. Authorized at sprint-034 kickoff via debt `f9859a959064` adoption + a `metadata.supersedes` decision.
- **Pin release-commits security-triage contract.** Three integration tests assert `[release]` and `[chore]` prefixes still route through `xp-security-triage` for code commits (the prefix bypasses only the protected-branch warning, not the triage gate) and that docs-only `[release]` commits auto-exempt via the no-code-files path. Closes recurring retro Try (`commit_without_security_check` flagged on two consecutive sprints).
- **Risk reframe + cascade-drop no-op concerns.** A superseding decision reframes the misdiagnosed compaction-archives risk (`4378589d50d7`) — the actual cause was `metadata.story_id` file-overlap fallback, fixed by v2.28.1's Tier-0 prefix parser. Five concerns adopted-for-burn-down were already addressed in code; recorded as resolved via status events with `metadata.resolves` rather than touching the code.

### Refactor (post-M-4)

- **Extract `_CloseSkillTextCommonTests` mixin** from sprint/plan/free SKILL.md guard tests once `/xp-free-close` made it the third consumer. Nine shared guards (refusal prose, gh-conditional PR, REVIEW_INPUT keys, agent-prompt literals, merge+delete ordering, AskUserQuestion) parameterized by `_MODE: str` and `_SKILL_MD: Path`. Mode-specific tests stay on the subclasses (sprint→plan-close chain, plan archive ordering, plan/free `current==target` refusal). Net `-96` LOC across the three test files; 65 close-test count unchanged. Mirrors the Pass-1 `_ClosePreloadCommonTests` pattern.

## v2.28.1 — Retro investigation fixes + CI hermeticity (post-M-3)

Six follow-up fixes that landed after sprint-033's release. Four close adopted retro Try items; one closes a pre-existing risk; one fixes CI fragility surfaced by the v2.28.0 push. No new features — all bug fixes and behavior corrections.

- **Tier-0 story attribution: parse `[story-NNN]` from commit message.** Retro investigation (Try #1) for the 4-retro-old "compaction archives commits" risk (`4378589d50d7`) falsified the original hypothesis: live `events.jsonl` retained every sprint-032 + sprint-033 commit with correct `metadata.sprint_id`. The actual gap was `metadata.story_id` — when multiple stories were in-progress, `_resolve_story_id` fell back to fragile file-domain overlap and either tied (returning `None`) or attributed to the wrong story. The `[story-NNN]` prefix in commit messages is authoritative ground truth; this commit makes it the new Tier 0 in the resolver, sitting between Tier 1 (teammate marker) and Tier 2 (file overlap). The risk text was honestly reframed via a superseding decision recording the misdiagnosis.
- **Trailer probe: escalate from advisory nudge to BlockedError.** Retro investigation (Try #4) for the teammate trailer-rate gap falsified hypotheses about hooks being disabled in `claude -p` contexts: live events show `resolves_probe_shown` events from `teammate-step-B`, hooks fire correctly, candidates are found. The real root cause was the advisory `parts.append` arriving too late — by the time the LLM saw the additionalContext, the commit had landed. Risk `a47dda9f00bd` had pre-mandated escalation to a blocking gate ("4th mechanism attempt"). Now: when probe finds candidates AND no `Resolves-Event:` trailer is present, raise BlockedError carrying the candidate IDs + remediation. `Resolves-Event: none` is the universal escape; any trailer (even with mismatched IDs) is treated as good-faith discharge — the gate cares about consideration, not ID correctness. Audit trail (the probe status event) writes before the block.
- **Story branches fast-forward on resume when behind base.** Retro Try #3 sub-fix (concern `dc0340ac5582`). Sprint-start scaffolds story branches off pre-iter HEAD; resuming mid-sprint left the branch on the stale base when the sprint base had advanced (e.g., a prior story merged in) — exactly what happened in this session when story-002 had to be manually rebased onto story-001's commits. New `_fast_forward_if_safe(cwd, branch, base)` runs `git merge-base --is-ancestor` then `git merge --ff-only` and prints a stderr note `note: fast-forwarded <branch> to <base> (<old>..<new>)` so the SHA move is visible. Branches with unique commits or diverged history are left alone — the ancestor gate refuses silently.
- **Sprint-branch direct-commit gate honors `[release]/[chore]` escape hatch.** Retro Try #3 sub-fix (concern `ef916d0f3c65`). Legitimate post-merge cleanup work (`/xp-accept` Step 0 cross-teammate review fixups) is inherently sprint-scope but used to trigger the advisory nudge. Same convention as the protected-branch gate: prefix bypass via `[release]` or `[chore]`. Hoists `is_escape_hatch_commit(command)` into a single local so both gates share one regex match.
- **`/xp-accept` SKILL.md documents ACCEPT-marker auto-consumption.** Retro Try #3 sub-fix (concern `1180c31dd1ae`). The preload's `consume_marker ACCEPT` was undocumented; agents hitting the marker gate elsewhere had no signal that the preload already cleared it. Single-sentence doc add plus a regex guard test (`preload ... consume|clear|remove ... .accept`) that pins the substantive claim.
- **CI test fixtures: pin `git init -b main` for hermeticity.** v2.28.0's CI failed on a runner whose `init.defaultBranch` defaulted to `master`; `branching.get_primary_branch` returns `"main"` at Stages 0-2 and tests creating story branches off `main` failed with `fatal: 'main' is not a commit`. Fixed in 14 fixture sites across 5 test files. Reproduced locally with `GIT_CONFIG_KEY_0=init.defaultBranch GIT_CONFIG_VALUE_0=master` before fixing. Requires git ≥ 2.28 (July 2020) for the `-b` flag — documented in the canonical fixture's docstring.

## v2.28.0 — /xp-plan-close skill + sprint-close→plan-close chain (M-3)

Sprint-033 implements Milestone 3 of the branch-lifecycle plan: the plan-branch close pipeline. When the last milestone of a plan-branch plan ships, `/xp-sprint-close` now chains automatically into `/xp-plan-close` — push, fork the close-reviewer in plan-mode, present, merge plan branch into primary, archive the plan, clean up. 3/3 stories delivered.

- **Add `/xp-plan-close` inline skill.** Eight-step orchestration mirroring `/xp-sprint-close` with plan-specific deltas: `TARGET_BRANCH` resolves via `branching.py get-primary` (not `get-target`, which would return the plan branch when called from the plan branch and trip the self-target refusal); mode is `"plan"` in the close-review-input JSON; Step 8 archives the plan via `plan_cli.py archive` immediately after a successful merge. Plan-mode focus list in the close-reviewer Agent prompt covers architectural coherence, accumulated debt, security posture of the cumulative diff, and decisions whose rationale weakened across the plan.
- **Auto-invoke chain in `/xp-sprint-close`.** New Step 9 gate: a single `&&`-chained command runs `plan_cli.py get-branch` (must be non-empty) AND `plan_cli.py is-plan-complete` (must exit 0). When both succeed, sprint-close invokes `/xp-plan-close`. When either fails, sprint-close ends with the existing complete message — chain skipped.
- **Both close skills now use explicit `&&` chains in Step 8.** Sprint-close (`merge-branch && delete`) and plan-close (`merge-branch && archive && delete`) — short-circuit on failure so plan stays intact and branch survives if any step fails. Replaces the prior split-block pattern that relied on the LLM reading prose between blocks.
- **Close-review-input handoff: per-invocation tempfile, not agent-scoped marker.** v2.27.0 shipped sprint-close with a fixed `<smm_dir>/.close-review-input.json` path injected by SubagentStart, which raced when concurrent close skills ran in different worktrees against the shared SMM_DIR. The handoff now uses `mktemp "${SMM_DIR}/.close-review-input.XXXXXX"` (joining the `.smm-rendered.XXXXXX` / `.sprint-rendered.XXXXXX` tempfile family swept on every preload by `_preload_base.sh`) and the close skill embeds the path plus `SMM_DIR` directly in the Agent prompt — the SubagentStart `xp-close-reviewer` injection is removed entirely. Resolves the multi-worktree race flagged in sprint-032 review. An agent-scoped marker was added in step 1.1 and reverted in step 1.3 once it became clear the parent→subagent agent_id boundary made marker-scoping the wrong tool — tempfile + prompt-passing is the correct shape.
- **Branching primitive rename + collapse: `merge-sprint`/`merge_sprint_branch` → `merge-branch`/`merge_branch`.** Generic primitive accepts any source branch + target. `merge_story_branch` and the legacy `merge` CLI subcommand collapsed into `merge_branch` / `merge-branch` — they were 1-line aliases of the same `_merge_into_target` call. `xp-accept` SKILL.md updated to use `merge-branch` for story merges. Net -29 LOC.
- **Capstone integration test.** `tests/integration/test_plan_close.py::TestPlanMergeAndArchiveEndToEnd` creates a real single-milestone plan with `status=delivered`, asserts `is-plan-complete` exits 0 (the exact gate Step 9 keys off), then exercises `branching.merge_branch` + `plan_cli.py archive` on a real git tree. Verifies primary HEAD is a `--no-ff` merge with deterministic parent ordering (parents[1]=prior-tip, parents[2]=plan-tip) and `execution_plan.json` lands in `plans/` with a timestamped filename. Honest about scope: pins the primitives the LLM-driven SKILL.md instructs, not the LLM execution path itself. Companion `TestSprintCloseToPlanCloseChainIntegrity` pins the chain wiring (skill+preload exist, sprint-close has the gate, close-reviewer agent declares a plan-mode focus section).

## v2.27.0 — /xp-sprint-close skill + xp-close-reviewer agent (M-2)

Sprint-032 implements Milestone 2 of the branch-lifecycle plan: the post-review merge pipeline. After `/xp-sprint-review` surfaces findings, the main agent now invokes `/xp-sprint-close` to push, fork a holistic close-reviewer, ask for confirmation, merge the sprint branch into its target, and clean up. 5/5 stories delivered.

- **Add `xp-close-reviewer` read-only agent.** New mode-aware reviewer (sprint / plan / free) that the three close skills fork before merging. Sprint mode focuses on cross-cutting changes, duplication across stories, and API coherence between commits. Frontmatter restricts tools to `Read, Grep, Glob, Bash` — never mutates the repo. SubagentStart auto-injects `SMM_DIR` and `REVIEW_INPUT` (`<smm_dir>/.close-review-input.json`) so the agent always has the diff command + branch context the close skill wrote.

- **Add `/xp-sprint-close` inline skill.** Eight-step orchestration: pre-flight (refuse on dirty tree or when current branch IS the target), push, gh-aware PR creation, write the close-review input, fork `xp-close-reviewer`, present findings, `AskUserQuestion` to confirm, then `branching.py merge-sprint --target` followed by `delete --branch` only when the merge succeeds. Degrades gracefully when `gh` is missing — no PR, no push beyond local, reviewer diffs locally via `git diff <target>...HEAD`.

- **Strip PR creation from `xp-sprint-reviewer`.** Step 3b moved to `/xp-sprint-close`; the reviewer agent + skill are now review-only, with `gh` and `branching.py` removed from `allowed-tools`. Sprint-review SKILL.md now chains into `/xp-sprint-close` after surfacing findings.

- **Branching primitives: explicit merge target, slug-drift fallback, idempotent re-record.** `merge_story_branch` and `merge_sprint_branch` drop their `target="main"` defaults — Stage-3 plan branches must merge to integration_branch, not main. `_cmd_merge` and `_cmd_merge_sprint` route through `get_merge_target` when `--target` is omitted. `_recorded_plan_branch` falls back to a `<branch>-*` prefix scan when the recorded plan branch isn't found locally and emits a stderr note so drift discovery is visible. `create_plan_branch` resume now re-records the branch into `execution_plan.json` (mirroring `create_sprint_branch`) so a regenerated plan with a still-existing branch keeps the linkage. `_BRANCH_MIN_STAGE` registry prevents the inner `_create_or_resume_branch` enforcement and the outer `_print_or_skip` skip message from drifting on stage-threshold changes.

- **Shell helper extractions in `_preload_base.sh`.** New `worktree_clean` and `gh_available` helpers (POSIX `command -v` over `which`) so the three close skills (sprint, plan, free) all share one implementation. `_extract_preload_var` promoted to `tests/conftest.py` (was duplicated in `test_assign_preload.py`). `_branching_fixtures.py` gains `get_head_sha` + `make_commit` helpers used by the capstone E2E and ready to replace inline rev-parse calls in sibling tests.

- **Capstone integration test pins the chain.** `test_sprint_close_chain.py` exercises chain integrity (close skill + preload + read-only close-reviewer agent all wired) and a real-git merge+cleanup E2E (sprint branch one commit ahead → `merge_sprint_branch(target=...)` then `delete_branch` → target HEAD is a `--no-ff` merge whose 2nd parent is the sprint tip and the sprint branch is gone). Per-step contracts live in `test_sprint_close.py` and `test_subagent_tiers_sprint.py`.

## v2.26.7 — Branch lifecycle design, sprint-review fix

- **Design branch lifecycle for sprint-close and plan-close.** New `docs/ideas/BRANCH_LIFECYCLE.md` defines `/xp-sprint-close`, `/xp-plan-close`, `/xp-free-close` skills, `xp-close-reviewer` agent, plan branch support, and free session branch management. Three review levels (commit, sprint, plan) with holistic code review at each integration point.

- **Fix sprint-reviewer allowed-tools for PR creation.** Step 3b (Create Sprint PR) silently failed because the skill's `allowed-tools` didn't include `branching.py`, `plan_cli.py`, `which gh`, or `gh pr create`. Added all four — PR creation now works at Stage 2+.

- **Add `acceptance_execution` producer to `/xp-plan`.** Plan skill now populates `acceptance_execution` on milestones when `system_context.json` has a matching covered acceptance surface. Activates the previously inert milestone acceptance gate in sprint-reviewer.

- **Move acceptance testing doctrine to completed.** All 14 design claims verified against codebase — schema, CLI, skill workflows, and validation all implemented.

- **Update branching doctrine status.** Core branching is implemented (stages, detection, gates, story/sprint branches, escape hatches, namespacing). Open questions updated with current state — team scenarios remain for future work.

## v2.26.6 — Acceptance testing doctrine, deterministic hooks

- **Add `acceptance_execution` schema to sprint stories.** Optional field with `type` (runner name) and `command` (exact invocation), plus optional `setup` and `notes`. Schema validates structure when present; backward compatible when absent. Sprint store renders the field in markdown output.

- **Surface acceptance type in accept preload.** New `acceptance_types.py` script outputs each in-progress story's runner type (defaulting to "manual") so `/xp-accept` can route between automated execution and manual walkthrough.

- **Rewrite `/xp-accept` with automated runner.** Non-manual stories run `setup` then `command` via Bash; exit 0 = pass. On failure: three options (debug and re-run, override with concern, defer). No auto-retry — flaky acceptance is information. Manual type preserves current walkthrough behavior.

- **Update `/xp-sprint-start` to write `acceptance_execution`.** Story decomposition template now includes the optional field with guidance on determining runner type from the project's acceptance surface.

- **Move QR resolves probe to PreToolUse:Skill hook.** The resolves-trailer probe now runs deterministically before `/xp-quality-review` loads, injecting results via `additionalContext`. Removes manual Step 1 from the skill. Deleted dead `probe_candidates.py`.

- **Strip dropped Tries from retro input deterministically.** `annotate_try_status` now removes dropped Try items from both `try` and `try_status` lists so the retro agent never sees them. Previously relied on an LLM instruction ("do not re-propose") which was not reliably followed.

- **Always remind about Resolves-Event trailer.** Pre-commit hook now nudges `Resolves-Event: <id>` or `Resolves-Event: none` on every commit with staged files, not just when open concerns overlap. Builds the habit of explicit resolution tracking.

- **Remove dead `assign-story` CLI subcommand.** Solo agents use file-domain matching for story attribution; the `--name main` marker path was dead code.

## v2.26.5 — Teammate diagnostics, QR counting fix

- **Surface Python tracebacks and git fatals in teammate diagnostics.** When `spawn_teammate.py` crashes before `claude -p` starts, `extract_diagnostics` now scans non-JSON lines for error signals (`Error:`, `fatal:`, `Traceback`) and reports them as `"Spawn failed: <details>"` instead of the opaque `"No result event in N stream-json lines"`. Closes AC4 from the spawn-teammate bug report.

- **Broaden QR completion regex.** `QUALITY_REVIEW_RE` now matches both `"Quality review complete"` and `"QR complete"` (case-insensitive). The old regex missed LLM-abbreviated phrasings, causing false "0 quality reviews" retro flags in the AJE PoC project for 4 consecutive sprints. Fixes both retro counting (`retro_metrics._classify_status_events`) and the advisory nudge (`bash_post_tool._check_qr_linkage`).

## v2.26.4 — Marker cleanup fix, batch threshold tuning, CI updates

- **Fix SECURITY_TRIAGED marker cleanup.** `SECURITY_TRIAGED` was defined with `agent_scoped=True` but missing from `_AGENT_SCOPED_MARKERS`, so `cleanup_agent_markers()` never removed it. Stale markers persisted after session end.

- **Raise batch-size threshold from 50 to 75.** The review cycle generates ~20 status events per commit, so 50 was noise for normal workflows. Prior sessions flagged at 50, 57, 67, 75 — the new threshold filters noise while still catching genuinely large batches.

- **Fix `decisions` variable shadowing in retro_flags.py.** Parameter `decisions: list[str]` was reassigned to an `int` on line 98. Renamed to `decisions_total` to prevent latent type-safety bugs.

- **Bump GitHub Actions to Node.js 24.** `actions/checkout` v4 → v5, `actions/setup-python` v5 → v6. Node.js 20 deprecated June 2026.

## v2.26.3 — Probe metrics, nudge improvements, CI fix

- **Add `code_free` flag to sizing analysis.** `per_story` output now distinguishes investigation-only stories (0 commits, 0 files) from attribution gaps. Helps retro avoid miscalibrating on stories that were intentionally code-free.

- **Move probe status event from post-commit to pre-commit.** Probe status emission now happens alongside the resolves-trailer nudge in `pre_tool_bash.py`, removing the dead `find_probe_candidates()` call from post-commit.

- **Improve nudge format.** Grouped header with ready-to-copy `Resolves-Event:` trailer so agents can paste it directly into commit messages.

- **Add `probe_adoption_rate` metric to retro.** Tracks what fraction of commits carry `Resolves-Event:` trailers when open concerns overlap changed files. Surfaces adoption trends across sprints.

- **Fix CI: branching lifecycle tests.** `_init_repo()` now sets repo-level git config (`user.name`, `user.email`) so `branching._git()` merge operations work in CI without global git config. Added `check=True` to all test setup subprocess calls.

## v2.26.2 — Pre-commit resolves-trailer nudge + staged file helper

- **Move resolves-trailer nudge from post-commit to pre-commit.** Agents now see overlapping open concerns/debts *before* committing via `additionalContext`, so they can include `Resolves-Event:` trailers in the original commit message instead of needing `git commit --amend`. Advisory only, not a hard block. Removes the post-commit nudge, fingerprint dedup mechanism (`REVIEW_FINGERPRINT` marker, `compute_fingerprint()`), and 11 dead tests. Net -215 lines.

- **Add `get_staged_files()` to commits.py.** Returns unfiltered staged file paths via `git diff --cached --name-only` for the pre-commit probe's file overlap detection.

## v2.26.1 — Fix spawn_teammate --story-id import error

- **Fix ModuleNotFoundError in worktree.py.** `write_story_assignment()` imports `write_text_atomic` from `_append_impl` (in `smm/`), but `worktree.py` never added `smm/` to `sys.path`. Fails when `spawn_teammate.py` runs with `--story-id` since it only adds `scripts/` to the path. Fixed by adding `smm/` path at module level, matching the pattern used by 20+ sibling scripts.

## v2.26.0 — Branching Doctrine: progressive branching stages 1-2

Sprints 024-027 deliver the complete Branching Doctrine execution plan (4 milestones). Projects can now declare a branching stage (0-3) and the plugin enforces stage-appropriate discipline.

- **Stage detection and schema (M1, sprint-024).** `branching_strategy` field in system_context.json with stage, user namespace, protected branches. `xp-system-analyzer` detects contributor count, CI presence, and branch patterns to propose a stage. `identity.user_namespace()` derives branch namespaces from git config.

- **Story branch lifecycle (M2, sprint-025).** `branching.py` module with `create_story_branch()`, `merge_story_branch()`, `delete_branch()`. Story branches auto-created on story start at Stage 1+, merged on acceptance, deleted after merge. Branch naming: `<user>/story-NNN-<slug>`.

- **Main-branch commit gate (M3, sprint-026).** PreToolUse:Bash gate raises advisory concern when committing directly to main/master at Stage 1+. Escape-hatch prefixes `[release]`/`[chore]` bypass the gate. Sprint-scoped commit attribution via `metadata.sprint_id` (fixes 0% resolves-trailer rate). Direct trailer counting replaces probe-based methodology.

- **Sprint integration branches (M4, sprint-027).** `create_sprint_branch()`, `get_story_base_branch()`, `is_sprint_branch()` for Stage 2. Sprint branches: `<user>/sprint-NNN-<slug>`. Stories branch off sprint branch at Stage 2+, merge back on acceptance. Sprint branch commit gate (advisory, no escape hatch). Sprint reviewer opens PR from sprint branch to main via `gh` on milestone delivery.

- **Test infrastructure.** Branching tests split across 3 files (unit, story lifecycle, sprint lifecycle). Dead `_probe()` helpers removed from retro tests. Test helper deduplication via shared `_make_bash_input`. 2722 tests total.

## v2.25.0 — Refactor-mode TDD metric + sizing_metrics rename

Sprint-023 delivers both milestones: refactor-mode-aware TDD gap metric and sizing_metrics rename. 4/4 stories, 100% velocity.

- **Refactor-mode exclusion in honesty signals.** `build_honesty_signals()` detects assumption events matching "refactor mode" or "refactor-mode", excludes file writes within those spans from `max_unique_files_without_test`. Spans reset on commit. New signal key `refactor_mode_excluded_files` provides transparency.

- **Refactor-mode annotation in retro flags.** TDD gap flag message now includes ", N excluded as refactor-mode" when exclusions exist. Backward compatible — message unchanged when key absent or zero. `_flag()` type hints narrowed from `object` to `int`.

- **Refactor-mode convention in PROCESS_GUIDE.** New "Refactor Mode" subsection under Common Patterns instructs agents to emit an assumption event with "refactor mode:" prefix before behavior-preserving changes. Idea doc moved to `docs/completed/`.

- **sizing_metrics renamed to story_metrics.** `sizing_metrics.py` → `story_metrics.py`, `compute_sizing_analysis` → `compute_story_analysis`. All imports and 3 test files renamed. Docstring and variable shadowing fixed by code reviewer. Closes debt `9eac0f57ecbb`.

- **Tests.** 2607 total (down from 2609 at v2.24.0 — sizing removal dropped 2 size-specific tests, added 8 new). 5 refactor-mode exclusion tests, 3 retro flags annotation tests.

## v2.24.0 — Risk lifecycle: resolution, verification, and discoverability

Risks in the SMM pillar now have a full resolution lifecycle — they can be targeted by `Resolves-Event:` trailers and `metadata.resolves`, and the housekeeper verifies remaining risks are still relevant.

- **Resolved risk annotation.** `materialize.prepare_curation_data` cross-references risk item IDs and `source_event_id` against resolution targets. Resolved risks get `resolved: true` in the curation data (copies before mutating to avoid persisted SMM corruption).

- **Risk ID rendering.** `smm_cli.py render` now shows risk entries as `- content [id]`, making IDs visible for `Resolves-Event:` targeting. Other pillars render without IDs. Uses `PILLAR_RISKS` constant.

- **Housekeeper verification.** Agent prompt updated to remove `resolved: true` risks and verify remaining unresolved risks are still relevant by checking the codebase.

- **PROCESS_GUIDE updated.** Resolution Discipline section documents that `metadata.resolves` targets risk pillar item IDs. "Linking Commits to Events" notes `Resolves-Event:` works for risk items.

- **Tests.** 2609 total (up from 2603 at v2.23.1). 6 new tests: 4 for resolved risk annotation (by item ID, by source_event_id, unresolved negative, no-mutation guard), 2 for risk ID rendering (risk shows ID, constraint does not).

## v2.23.1 — Thread resolutions through _handle_commit

Sprint-021 delivers Milestone 3 of the Consolidation Refactor plan (2/2 stories, 100% delivery). All 3 milestones now complete — consolidation refactor finished.

- **Single resolution computation in _handle_commit.** `_handle_commit` now calls `load_events_with_resolutions` once and threads the `resolutions` dict to all downstream consumers: `_resolve_lint_on_commit`, `find_probe_candidates`, and `open_issues_matching_commit`. Multi-file commits with lint concerns previously called `compute_resolutions` up to 3x — now exactly 1x.

- **`_resolve_lint_on_commit` resolutions kwarg.** New optional `resolutions: dict | None = None` parameter threads pre-computed resolutions to `concerns.resolve_concerns`, which passes them to `_find_unresolved` to skip internal recomputation.

- **`find_probe_candidates` resolutions kwarg.** New optional `resolutions` parameter threads to `commits.open_issues_matching_commit`, which already accepted it but was never called with it from the post-commit path.

- **Test mixin extraction.** `_LintTmpDirMixin` extracted from `TestAutoResolveLintConcerns` setUp/tearDown, shared with new `TestResolutionsThreading` class. `shutil` import moved to module level.

- **Tests.** 2603 total (up from 2581 at v2.23.0). New tests: `test_precomputed_resolutions_skip_recomputation` (unit), `test_multi_file_commit_computes_resolutions_once` (E2E).

## v2.23.0 — Consolidation refactor + concern auto-link support

Sprint-020 delivers Milestones 1 and 2 of the Consolidation Refactor plan (6/6 stories, 100% delivery). Post-sprint: concern events now carry file paths for auto-link detection.

- **`load_events_with_resolutions` helper.** New `_common.load_events_with_resolutions(smm_dir)` consolidates the scattered `read_events_raw` + `compute_resolutions` two-step prologue into a single call returning `(events, resolutions)`. 7 call sites migrated: `pre_tool_bash.py`, `commits.py`, `prompt_nugget.py`, `concerns.py`, `session_end.py`, `retrospective.py`, `retro_metrics.py` (indirect).

- **Import normalization.** All `compute_resolutions` imports normalized to module-qualified `import resolution` style. Stale `_append_impl.py` re-export removed. 3 import styles collapsed to 1 across 14+ files.

- **Optional `resolutions` threading.** `concerns._find_unresolved`, `resolve_concerns`, `has_unresolved_concerns`, `commits.open_issues_matching_commit`, `session_end._compute_summary`, and `retrospective._build_retro_input` accept optional `resolutions` kwarg to skip redundant computation.

- **Concern `files` field.** `make_concern()` gains optional `files` param. Populated at 4 call sites: lint concerns (`lint_check.py`), commit-size concerns (`bash_post_tool.py`), write-conflict concerns (`pre_tool_write.py`), and overlapping-working_on concerns (`concerns.py`). Enables `triage_preload` file-overlap detection for "LIKELY ADDRESSED" annotation.

- **Test file splits.** `test_session_start.py` split (756→406+362 lines), `test_markers.py` split (531→284+268 lines). Both under 500-line max.

- **Tests.** 2581 total (up from 2576 at v2.22.0). 5 new tests for `load_events_with_resolutions` helper, `make_concern` files param, and overlap concern files field.

## v2.22.0 — System context migrated to JSON

Sprint-019 delivers Milestones 2 and 3 of the System Context JSON Migration plan (3/3 stories, 100% delivery). All 3 milestones now delivered — migration complete.

- **system_context.json replaces system_context.md.** System context is now JSON with schema validation and CLI (`system_context_cli.py`), matching the execution_plan/sprint pattern. No migration script — kickoff triggers `/xp-system-context` which creates fresh `.json` when none exists.

- **Shell preload migration.** All 4 preload scripts (`_preload_base.sh`, `check_session_needs.sh`, `xp-system-context/preload.sh`, `xp-plan/preload.sh`) check for `.json`. Shared `SYSTEM_CONTEXT_FILE` constant in `_preload_base.sh` eliminates hardcoded filename duplication.

- **Python consumer migration.** `session_start.py` uses `system_context_store.load_system_context()` + `render_markdown()` for teammate context injection (was raw `.md` read). `sprint_state.py` delegates to `system_context_store.system_context_exists()`. `sprint_store.py` render updated.

- **Agent output format.** `xp-system-analyzer` agent now emits JSON via `system_context_cli.py` (create/edit-field/add-module/add-decision) instead of piping markdown to `save_planning_doc.py`. Skill allowed-tools updated.

- **Dead code removed.** `save_planning_doc.py` and `test_save_planning_doc.py` deleted. Tests relocated: `TestMarkerNames` → `test_markers.py`, `TestSprintStateFileChecks` → `test_sprint_state.py`.

- **Tests.** 2572 total (down from 2581 at v2.21.1). 6 `save_planning_doc` tests removed, 9 tests relocated (2 marker + 7 sprint_state file checks). Duplicate `execution_plan_exists` tests deduplicated during relocation.

## v2.21.1 — Fix: status-only updates skip budget enforcement

- **Budget enforcement fix.** `update_milestone_status` and `update_story_status` now pass `enforce_budget=False` to `save_plan`/`save_sprint`, matching the load-path grandfathering from v2.19.1. Status changes don't modify content fields, so budget validation on pre-existing over-budget milestones/stories was a false rejection. Same root cause as `d041e77` but the update-status path wasn't covered.

- **Test extraction.** Sprint budget tests extracted from `test_sprint_store.py` (530→421 lines) into `test_sprint_budgets.py` (131 lines) to stay under the 500-line convention.

- **Tests.** 2481 total (up from 2478 at v2.21.0). 3 new tests for status-update grandfathering on over-budget plans and sprints.

## v2.21.0 — Verbosity Audit M10: Prompt tightening (5 files)

Sprint-017 delivers Milestone 10 of the Verbosity Audit execution plan (5/5 stories, 100% delivery). All 10 milestones now delivered — Verbosity Audit complete.

- **M10: Prompt tightening.** Applied §8 bloat-pattern checklist to 5 untouched agent/skill files. Consolidated repeated code blocks, compressed role framing, replaced verbose templates with minimum-viable shapes. Total: 581→415 lines (29% average reduction). Per file: xp-code-reviewer 107→68 (36%), xp-sprint-reviewer 89→62 (30%), xp-assign 151→100 (34%), xp-quality-review 143→108 (24%, constrained by 800-token floor), xp-accept 91→80 (12%).

- **Signal-loss review.** Independent fan-out review of all 5 diffs caught two losses: architecture-level file examples in sprint-reviewer were project-specific (fixed to generic phrasing), done/deferred definitions in accept were decision criteria (restored). All other compressions confirmed safe.

- **Tests.** 2478 total (unchanged). No code changes — prompt-only refactoring.

## v2.20.0 — Retro false positive fix + concern auto-resolution

- **Quality review flag fix.** The `quality_reviews_missing` retro flag now compares quality review count against `review_required_commits` (commits with >= 2 code files) instead of all `code_commits`. Commits with <2 code files only require security triage, not quality review — the old comparison produced false positives. Commit metadata now records `code_file_count` for accurate threshold splitting.

- **Concern auto-resolution at triage.** Work selection triage now detects file overlap between open concerns and subsequent commits. Concerns with overlapping commits are annotated as "LIKELY ADDRESSED" with commit messages, allowing the triage agent to auto-resolve them via LLM judgment instead of asking the user.

- **Tests.** 2478 total (up from 2467 at v2.19.2). 11 new tests: 2 for review_required_commits counting, 2 for retro flag threshold behavior, 7 for concern-commit overlap detection and annotation.

## v2.19.2 — Fix: Sprint budget validation crashes hooks on read

- **Read-path budget grandfathering for sprint.json.** `load_sprint` now calls `validate_sprint(enforce_budget=False)`, skipping field-length budget checks on read. Sprints with story contexts exceeding the 600-char budget no longer crash SessionStart and Stop hooks. Budgets remain enforced at write time (`save_sprint`). Matches the `execution_plan_store` fix from v2.19.1.

- **Tests.** 2467 total (up from 2462 at v2.19.1). 5 new tests for `enforce_budget` flag behavior and `load_sprint`/`save_sprint` asymmetry.

## v2.19.1 — Fix: SessionStart crash on pre-budget execution plans

- **Read-path budget grandfathering.** `load_plan` now calls `validate_plan(enforce_budget=False)`, skipping field-length budget checks on read. Plans written before budget limits were added no longer crash the SessionStart hook. Budgets remain enforced at write time (`save_plan`). Matches the existing `smm_schema.py` precedent.

- **Tests.** 2462 total (up from 2457 at v2.19.0). 5 new tests for `enforce_budget` flag behavior and `load_plan`/`save_plan` asymmetry.

## v2.19.0 — Verbosity Audit M9: Nudge Dedup + Kickoff Gate UX

Sprint-016 delivers Milestone 9 of the Verbosity Audit execution plan (2/2 stories, 100% delivery). Ninth consecutive sprint at 100% delivery rate.

- **M9: Open-questions nudge dedup cache.** `_open_questions_context` now tracks per-(question_id, agent_id) fire count via agent-scoped QUESTION_NUDGED marker. After 2 fires, the question is muted for that agent until SessionEnd clears markers. Saves ~60% on repeat injection (5 decisions × 3 questions = 2.2 KB).

- **M9: SubagentStart docstring fix.** Module docstring updated from stale `~200 tokens` to measured sizes from VERBOSITY_AUDIT §6.3 (Explore ~5 KB, Default ~10 KB, retro ~1.6 KB, housekeeper ~1.5-3 KB, xp-* ~1.4 KB).

- **Kickoff gate UX: block once, then pass.** The `.needs-kickoff` marker is now consumed on first block/nudge instead of persisting until `/xp-kickoff` runs. Users who skip kickoff for casual Q&A sessions can proceed after the initial reminder. SMM compaction is safely a no-op when the curation watermark hasn't advanced.

- **Tests.** 2457 total (up from 2425 at v2.18.0). 7 new tests: 5 for nudge dedup cache, 2 for kickoff gate consume-on-block behavior.

## v2.18.0 — Verbosity Audit M7: Retro Fixes + Probe Widening

Sprint-014 delivers Milestone 7 of the Verbosity Audit execution plan (3/3 stories, 100% delivery). Seventh consecutive sprint at 100% delivery rate.

- **M7: MAX_RETRO_HISTORY reduced from 2 to 1.** Only `previous_retros[0]` was annotated by `annotate_try_status` — the second retro was dead weight (~5 KB per `.retro-input.json`). `analysis_notes` now included in the slim so cross-session trends carry forward.

- **M7: Retro schema validation.** New `retro_schema.py` validates K/F/T structure at save time: `keep[].content` ≤ 250, `fix[].content` ≤ 300, `try[].content` ≤ 300, `analysis_notes` ≤ 600, `try` maxItems 4. Wired into `save_retrospective.py` with actionable error messages showing current vs allowed length.

- **M7: Retro agent prompt directives.** Three coordinated directives: read-side (`previous_retros[0].analysis_notes`), write-side (populate ≤ 600 chars with cross-session trends), Try-cap (max 4 items with merge/promote/reclassify/drop strategies). Budget constraints block documents limits so agents produce valid output on first attempt.

- **S-size ceiling enforcement.** `sprint_schema.py` rejects S stories with > 20 `file_domain` entries at creation time. Plan-review preload checks the same ceiling. Addresses third consecutive sprint with S > M sizing inversion.

- **smm_schema.json maxLength sync.** Per-pillar `maxLength` added to JSON schema matching `PILLAR_CONTENT_MAX_LENGTH` (intent=200, constraints=150, risks=200, wisdom=150). Drift-guard test ensures JSON and Python stay in sync. Content budget concern resolved (grandfathering already in place).

- **Resolves probe widened to match debts.** `open_concerns_matching_commit` renamed to `open_issues_matching_commit` — now matches both concern and debt events with file overlap. Previously debts with `files` fields were silently skipped by the pre-commit probe. Nudge text shows actual event type.

- **Housekeeping.** `test_plugin_integrity.py` split (488→439 lines) with agent prompt tests extracted to `test_agent_prompts.py`. PROCESS_GUIDE.md sprint_cli listing expanded with `add-story`, `assign-story`, `velocity` subcommands.

- **Tests.** 2425 total (up from 2395 at v2.17.0). 30 new tests across 6 files covering retro schema validation, retro history bugs, S-size ceiling, smm_schema.json drift guard, and probe debt matching.

## v2.17.0 — Verbosity Audit M5+M6: SMM Purpose Audit + Triage Surfaces

Sprint-013 delivers Milestones 5 and 6 of the Verbosity Audit execution plan (4/4 stories, 100% velocity). Sixth consecutive sprint at 100% delivery rate.

- **M5: Per-pillar content maxLength enforcement.** `PILLAR_CONTENT_MAX_LENGTH` in `smm_schema.py` (intent=200, constraints=150, risks=200, wisdom=150) enforced at write time via `validate_entry`. Read path grandfathers existing over-budget entries. Coverage assertion ensures all pillars have a budget. Two seed wisdom items tightened to fit.

- **M5: Housekeeper purpose-filter rewrite.** Each pillar curation section now has a purpose filter with good/bad examples: Intent (project-level north-star), Constraints (binds every instance in domain), Risks (systemic, not tactical), Wisdom (applies in 3 months). Items failing the filter stay as events — they surface via work-selection triage instead of pillar promotion.

- **M6: Triage preload.** New `triage_preload.py` scans `events.jsonl` for unresolved debt/concern/question events, outputs formatted triage sections with aging info (sessions since creation). Replaces the Risks-pillar question display in work-selection preload with direct event scanning.

- **M6: Triage decide subcommands.** `work_selection_decide.py` gains `triage-adopt`, `triage-defer`, `triage-drop` subcommands with `--event-id` flag. Collapsed to a single match case with disposition lookup. Event ID validated against `EVENT_ID_RE`. SKILL.md updated with Steps 2-4 for Open Debts, Open Concerns, Open Questions triage.

- **M5: Retro aging decoupled from Risks pillar.** `xp-retrospective.md` no longer references Risks pillar emoji markers for debt aging. Aging is now computed from event timestamps at consumption time.

- **Fix: story-assignment marker writes.** New `sprint_cli.py assign-story` subcommand and shared `worktree.write_story_assignment()` helper with symlink rejection + atomic writes. Replaces raw `echo`/`path.write_text()` in spawn_teammate.py and xp-assign SKILL.md. Resolves debt 7af3d53bdba9.

- **Tests.** 2395 total (up from 2345 at v2.16.0). 50 new tests across 8 files covering maxLength validation, triage preload scanning, triage decide subcommands, purpose filter assertions, and assign-story CLI.

## v2.16.0 — Verbosity Audit M2+M3: Curation Input Fixes + CLI --help + PROCESS_GUIDE Tightening

Sprint-010 delivers Milestone 2 (3/3 stories, 100% velocity) and Sprint-011 delivers Milestone 3 (2/2 stories, 100% velocity). Four consecutive sprints at 100% delivery rate.

- **M2: Curation input structural fixes.** Resolutions dict-to-list in `materialize.prepare_curation_data` cuts 82 KB to 3 KB (96%). AskUserQuestion customer_inputs re-serialized as compact Q/A pairs (73% cut). Adopted tries capped at 10 most recent (77% cut). New `smm_cli.py get-event` subcommand for on-demand deep reads when truncated content needs full body.

- **M3: CLI --help enrichment.** All four Python CLIs (smm_cli, plan_cli, sprint_cli, retro_cli) and append.sh now have compact example-rich --help output showing stdin pipe patterns and common invocations.

- **M3: PROCESS_GUIDE.md tightened 49%.** 196 lines to 99 lines. CLI Tools section cut to 1-line pointers (--help now carries details). Practicing the Values compressed to bullet list. Common Recording Patterns reduced to 4 one-liner shapes. Token budget test tightened from 2000 to 1000 tokens.

- **Fix: resolves-trailer probe checks all changed files.** `probe_candidates.py` now scans staged, unstaged, and untracked files instead of only staged. The probe runs before staging during quality review, so the old staged-only check always returned empty.

- **Refactor: test file splits.** `test_lint.py` split into `test_lint.py` + `test_lint_detection.py`. `test_curation.py` split at 500 lines during story work.

- **Tests.** 2345 total (up from 2326 at v2.15.0). 19 new tests across 7 files covering CLI --help output, curation input normalization, and probe file detection.

## v2.15.0 — Verbosity Audit M1: Per-Type Content Budgets + Bug Fixes

Sprint-009 delivers Milestone 1 of the Verbosity Audit execution plan (3/3 stories, 100% velocity). Events now have per-type character budgets enforced at write time, governance prose teaches agents to write tight, and hook producers comply. Plus four maintenance bug fixes.

- **Per-type content budgets.** `CONTENT_BUDGETS` dict in `event_schema.py` maps each event type to a max character count (status=200, decision=400, concern=400, commit=uncapped, etc.). `validate_event()` rejects over-budget events with actionable error showing current length, budget, and trim suggestion. CLI `--help` epilog generated from the dict (single source of truth). `schema.json` description updated as documentation. Sync test guards against drift between dict and schema.

- **Governance prose + whiteboard discipline.** PROCESS_GUIDE.md gains content budget section with compression worked example (1099->370 chars, 66% reduction). Four agent prompts (xp-retrospective, xp-housekeeper, xp-code-reviewer, xp-plan-reviewer) gain budget-discipline worked examples + section 8 tightening: -77 lines net across prompt files. xp-retrospective gets "sticky notes, not paragraphs" whiteboard framing for K/F/T output.

- **Hook budget compliance.** Three producers fixed: `session_end.py` truncates reason to fit 50-char budget, `bash_failure.py` uses dynamic prefix-aware truncation for 200-char status budget, `concerns.py` truncates assumption+discovery concatenation for 400-char concern budget. All truncation limits derived from `CONTENT_BUDGETS`.

- **Fix: stale worktrees suppress accept stop gate.** `has_live_teammates()` now parses porcelain output as blocks and skips prunable entries. `remove_worktree()` runs `git worktree prune` unconditionally to clean orphaned nested worktree registrations.

- **Fix: dropped Tries keep reappearing.** `annotate_try_status` was using unanalyzed-scoped resolutions, so drop decisions referencing old event IDs outside the retro boundary were invisible. Now uses full-scope `compute_resolutions(events)`.

- **Fix: lead agent story attribution.** `_resolve_story_id` now falls back to `.story-assignment-main` for non-worktree agents. `/xp-assign` writes this marker when solo mode is chosen during a sprint.

- **Fix: lint concern duplication.** `lint_check.py` now checks for existing unresolved lint concerns before appending via shared `has_unresolved_concerns()` helper extracted to `concerns.py`. `_find_unresolved()` + `has_unresolved_concerns()` replace duplicated resolution logic. `_build_resolutions_map` renamed to `build_resolutions_map` (public API).

- **Tests.** 2326 total (up from 2312 at v2.14.9). 16 new tests across 6 files covering budget validation, budget compliance, prunable worktree filtering, dropped Try resolution, lead story attribution, and lint dedup.

## v2.14.9 — Retro Try Debt Cleanup: File Splits, Dedup, Exception Narrowing

Free session addressing all four adopted retro Tries from the retrospective. Pure refactoring and code quality improvements -- no new features.

- **Split oversized test files.** `test_retrospective.py` (1788 lines) split into 4 files by feature area: core run() behavior, sprint sizing/link rates, honesty signals/security counting, and digest resolutions/try annotation. `test_bash.py` (1138 lines) split into 3 files: core commit handling, post-commit behaviors (probe dedup, review cycle, nudge, QR linkage), and failure handling/compat. `_ProbeTestHelpers` mixin extracted to `conftest.py` (review feedback -- avoids creating duplication across split files). All files under 500 lines except `test_retrospective.py` at 647 (session stats tests are cohesive with the core class).

- **Extract `retro_metrics.py` from `retrospective.py`.** Split 600-line file into orchestration (282 lines: `run()`, sprint detection, watermark, retro input building) and pure computation (307 lines: session stats, status classification, concern grouping, resolutions map, digest building, resolves link rate). Removed dead `MAX_EVENTS_IN_RETRO` constant. Fixed stale `event_schema.py` comment referencing old module.

- **Deduplicate concern-matching logic.** Added `events=` parameter to `commits.open_concerns_matching_commit()` so callers with pre-loaded events skip the disk read. Removed 39-line `_open_concerns_from_events()` from `resolves_probe.py` (was near-verbatim copy). `find_probe_candidates()` now always delegates -- no if/else branch.

- **Narrow bare exception handlers.** `duplicate_debt_probe.run_probe_and_append`: `except Exception` narrowed to `except (OSError, json.JSONDecodeError, ValueError, KeyError)`. `_common._run_duplicate_debt_probe`: `except Exception` narrowed to `except ImportError`. Tests verify unexpected exceptions (AttributeError, TypeError) now propagate instead of being silently swallowed.

- **Tests.** 2319 total (up from 2304 at v2.14.8). 5 new tests for `events=` parameter and exception narrowing. CLAUDE.md test layout updated to reflect new file structure.

## v2.14.8 — Pre-Commit Resolves-Trailer Probe; Post-Commit Dedup; Retro Metric Safeguard

Closes Milestone 3 of the Mechanical-Discipline-Closure execution plan. Sprint-007 delivered two stories solo (linear dependency chain, both touching `bash_post_tool.py`). The resolves-trailer auto-link probe now runs INSIDE `/xp-quality-review` before the commit, so the `Resolves-Event:` trailer lands on the first commit without needing `git commit --amend`. Post-commit hook consumes the same probe's fingerprint to suppress a duplicate nudge and — critically — a duplicate status event that would double-count in the retro `resolves_link_rate` metric.

- **`resolves_probe.py` — pure probe-candidate module extracted from `bash_post_tool._handle_commit`.** Refactor-mode per decision `refactor-mode-explicit`: `tests/hooks/test_bash.py` was the executable spec, 53/53 passed unchanged through the extraction. New module exports `find_probe_candidates(smm_dir, commit_files, resolves, cwd) -> list[dict]` (open concerns whose files intersect the commit, minus already-resolved, capped at `PROBE_CANDIDATE_LIMIT=5`), `build_nudge_lines(candidates) -> list[str]` (auto-link nudge with full `git commit --amend --trailer` command), `build_probe_status_event(candidates, commit_hash, agent_id) -> dict | None` (the `resolves_probe_shown` status event payload), and the new `compute_fingerprint(files, concern_ids, cwd) -> str` helper (sha256 over sorted normalized files + sorted concern ids; order-invariant; silently skips paths that fail `worktree.normalize_path` to mirror `commits.open_concerns_matching_commit` so pre/post-commit fingerprints agree on file identity). 11 unit tests cover empty/matching/cap/already-resolved paths + 7 fingerprint stability/distinctness/normalization tests.

- **`REVIEW_FINGERPRINT` marker — agent-scoped json + cleanup-swept.** New `MarkerDef(".review-fingerprint-{agent_id}", "json", agent_scoped=True)` in `scripts/markers.py`, filename constant in `smm/marker_names.py`, registered in `_AGENT_SCOPED_MARKERS` so `cleanup_agent_markers` sweeps it on SessionEnd / teammate shutdown. Agent-scoped per decision `agent-scoped-markers` to prevent worktree teammate races. Written via `marker_write` per convention `marker-write-discipline`. Test coverage follows the `TestPendingRenderMarkers` pattern: agent-scoped+json registration, filename format via `marker_path`, and round-trip write→cleanup→missing through `TestCleanupAgentMarkers`.

- **Three-way dedup branch in `bash_post_tool._handle_commit`.** Consumes `REVIEW_FINGERPRINT` (one-shot; re-running `/xp-quality-review` drops a fresh marker) and branches:
  - **no marker** → emit nudge + status event (prior behavior preserved)
  - **marker + fingerprint match** → skip both (pre-commit probe already covered this surface)
  - **marker + fingerprint mismatch** → emit nudge as safety net, **skip the status event** — this is the mechanism that closes plan concern `a97778074415` (double-count risk in `retro._compute_resolves_link_rate`, which pairs each probe with the NEXT commit by the same agent; a second probe from the post-commit path would inflate the denominator). `marker_consume` precedes `compute_fingerprint` so the common no-marker case skips sha256 work entirely. Shared test helper `_ProbeTestHelpers` mixin deduplicates `_seed_auth_concern` and `_probes` between `TestBashPostTool` and the new `TestResolvesProbeDedup` (5 dedup tests: match-suppresses, files-mismatch, ids-mismatch, no-marker, marker-consumed).

- **`/xp-quality-review` skill script + SKILL.md wiring.** New `skills/xp-quality-review/scripts/probe_candidates.py` — args `--smm-dir` and `--cwd`, derives `agent_id` via `identity.resolve_agent_id_from_cwd(cwd)` (the explicit skill-script API, not the hook-input-based `resolve_agent_id`). Reads staged files via `git diff --cached --name-only`, calls `find_probe_candidates` with `resolves=[]` (pre-commit has no trailer yet), writes the marker, emits the `resolves_probe_shown` status event with `commit_hash=None` (retro pairs by `probe_candidates` intersection, not commit hash — verified). Prints candidate IDs + trailer guidance to stdout. SKILL.md gains a new Step 1 before the reviewer spawn; existing steps renumbered 2–5. Documentation names the why: "prevents the probe from double-counting in the retro `resolves_link_rate` metric". New `test_quality_review_probe.py` integration test exercises the full pipeline: seed concern, stage, run probe script, assert marker + status event, then real git commit, run `bash_post_tool.py`, assert exactly ONE status event (dedup worked) and marker consumed.

- **Plan reviewer concerns closed in-sprint.** All three flagged during `/xp-review-plan` — double-count risk (`a97778074415`), two trivial-but-required marker imports (`d6d8ae145f3d`), and `resolve_agent_id` vs `resolve_agent_id_from_cwd` (`4fcea0762713`) — were resolved by the implementation commits with explicit `Resolves-Event:` trailers. Zero plan concerns carried forward.

- **Tests.** 2265 total (up from 2236 at v2.14.7). Story-001: 11 new `test_resolves_probe.py` unit tests. Story-002: 7 `compute_fingerprint` tests + 4 `REVIEW_FINGERPRINT` marker tests + 5 `TestResolvesProbeDedup` unit tests + 2 `test_quality_review_probe.py` integration tests.

## v2.14.7 — Retire domain_accuracy; Cross-Cutting Attribution Fix; Echo-Gate Scope Correction

Closes Milestone 2 of the Mechanical-Discipline-Closure execution plan. Sprint-006 delivered two stories in parallel via CLI teammates with zero merge conflicts; the front-loaded cross-story E2E test written by the main agent during the teammate in-flight window passed on the first run post-merge — first sprint where adopted retro Try 4 (failing-test-first across parallel teammates) was exercised end-to-end.

- **`domain_accuracy` retired; informational `cascade_size` replaces it.** The ratio metric was flagged misleading for six consecutive retros: dominated by story size and by cross-cutting commit attribution, neither correlating with planning quality. `sizing_metrics._attribute_commits` now returns per-story dicts containing only `{commits, files_changed, cascade_size}` — the three retired keys (`domain_accuracy`, `in_domain_files`, `out_of_domain_files`) are gone, not renamed. `cascade_size` is an integer count of committed files outside the declared `file_domain` with no threshold and no flag; judgment stays with the retro agent. The `_attribute_commits` refactor also moved domain overlap computation from per-commit to once-over-deduped `all_files` per story — algorithmic win when commits repeat files. `agents/xp-retrospective.md` Per-Story Metrics Table column renamed to "Cascade Size" (disambiguates from WEAK-link cascade terminology); the `< 0.5` flagging branch is deleted; the descriptor frames `cascade_size` as informational planning-drift signal. `PROCESS_GUIDE.md` gains a one-sentence File Domain Discipline subsection: declare `file_domain` per planner intent, over-declaring defeats the metric.

- **Multi-way domain tie in `_resolve_story_id` returns `None`.** Tier-2 attribution previously picked the first in-progress story with the highest `file_matches_domain` overlap — ties on equal non-zero overlap resolved arbitrarily to whichever story iterated first, polluting one story's sizing with cross-cutting commits. New `tied: bool` flag tracks whether a strict winner exists; when multiple in-progress stories tie at the best overlap, returns `None` so the caller writes `story_id=null` and the commit aggregates at sprint level. Strict-winner semantics preserved: a later story with strictly greater overlap resets `tied=False`. Zero-overlap commits still return `None` via the existing path. `_resolve_story_id(smm_dir, cwd, committed_files)` signature unchanged. New `test_tier2_multi_way_tie_returns_none` plus the two existing tier-2 tests continue passing.

- **Echo-gate unregistered from `UserPromptSubmit`.** `pre_tool_echo_gate.py` was registered on both `PreToolUse` (correct — blocks agent tool calls) AND `UserPromptSubmit` (wrong — blocks the user's next prompt when the agent forgot to echo a rendered retrospective or SMM block). Penalized the wrong actor. Removed from `UserPromptSubmit`; `PreToolUse` enforcement is sufficient — the moment the agent tries to act on any prompt without echoing, its tool call is blocked. Docstrings updated in `pre_tool_echo_gate.py` and `docs/ideas/INLINE_AGENT_MIGRATION.md` (4 stale references noted as "removed in later revision"). `test_echo_gate_registered_for_user_prompt_submit` flipped to `test_echo_gate_not_registered_for_user_prompt_submit` with rationale docstring.

- **Cross-story E2E test (adopted retro Try 4 validated).** `plugins/xp-agents/tests/integration/test_cascade_and_tie_e2e.py` seeds a sprint with two in-progress stories on disjoint `file_domain`, creates a real git commit touching one file from each domain (the tie scenario), runs `bash_post_tool.py` via `_run_script`, asserts commit metadata has no `story_id` (validates the tie → None fix), then seeds a sprint-end event, runs `retrospective.py`, and asserts `sizing_analysis.per_story` dicts contain `cascade_size` and none of the retired keys (validates the retirement). Written locally during the teammate in-flight window per adopted retro Try 4 — failed against unmerged main, passed once both teammates' branches landed. Front-loading discipline now proven: intent is to repeat on every future parallel-teammate sprint.

- **Tests.** 2236 total (up from 2234 at v2.14.6). 1 new `test_tier2_multi_way_tie_returns_none` (story-002). 1 new cross-story integration E2E. 1 flipped echo-gate registration test. ~10 `test_sizing_metrics` assertion flips from retired-keys to `cascade_size`. 1 `test_retrospective` assertion flip.

## v2.14.6 — Resolves-Trailer Feedback Loop: Actionable Nudge, Retro Metric, Echo-Gate Loosening

Closes Milestone 1 of the Mechanical-Discipline-Closure execution plan. Sprint-005 delivered three stories in parallel via CLI teammates, plus post-merge refactors that retired two carry-forward debts. The resolves-trailer nudge from v2.14.5 is now actionable and measurable; the echo-gate stops policing markdown.

- **Actionable auto-link nudge + resolves_probe_shown status event (PostToolUse:Bash).** `bash_post_tool._handle_commit` now emits nudge lines containing the exact `git commit --amend --trailer "Resolves-Event: {id}"` command instead of a vague "consider adding" hint. Candidates are capped at 5 per commit (`PROBE_CANDIDATE_LIMIT`) to prevent flood. On any commit where the probe surfaces candidates, a `status` event is appended with `content="resolves_probe_shown: N candidates"`, `metadata.probe_candidates=[ids]`, `metadata.commit_hash=<hash>`. No noise when no candidates match. Three event appends (commit + probe + size-concern) consolidated into one `bulk_append_safe` call. Full pipeline exercised by a new integration test that seeds an open concern, commits a matching file, and asserts both the nudge text and the probe event.

- **`resolves_link_rate` retro metric under Sprint Analysis.** New `_compute_resolves_link_rate(events, sprint_start_ts)` helper in `retrospective.py` iterates `resolves_probe_shown` status events in the sprint window and pairs each with the NEXT commit by the same `agent_id`; counts a hit if `commit.metadata.resolves` intersects `probe.metadata.probe_candidates`. Emits `resolves_link_rate` (float), `resolves_probe_hits` (int), `resolves_probe_total` (int) into `sizing_analysis` when probes exist; fields are absent when total is 0 (no crash). `agents/xp-retrospective.md` gains a Resolution-Link Adoption subsection that flags adoption < 0.80. Target: ≥ 0.80 for three consecutive sprints → convention stops being flagged. Docstring honestly names the pairing heuristic's amend-commit limitation so future retros read the metric correctly.

- **Bare 12-hex event ID in commit body counts as implicit resolution link.** New pure helper `commits.extract_implicit_event_ids(body, known_ids) -> list[str]` scans commit-body prose for word-bounded 12-hex substrings matching `EVENT_ID_RE` and filters against a caller-supplied open-event allowlist — intentional design: without the allowlist, any hex-looking string would match. Deduped first-seen. `extract_resolves_trailer`'s signature stays the 2-tuple (plan-reviewer-directed: avoids cross-worktree API coupling with the nudge story during parallel delivery). Caller wiring deferred to a future M3 sprint; the function ships standalone with 13 unit tests.

- **Echo-gate loosened to plain-text phrase check.** `pre_tool_echo_gate` used to require the exact markdown heading (`# Shared Mental Model — Curated View`) to appear verbatim. Paraphrases, dropped `#`, ASCII dashes, or changed heading levels all tripped the gate repeatedly even after the content was visible to the user. New design: `marker_names.RENDER_*_PHRASES` tuples define required plain-text phrases (SMM: `"Shared Mental Model"` + `"Curated View"`; retro: `"XP Retrospective"` + `"Keep / Fix / Try"`). All phrases must appear in assistant text; two-phrase-both-required retains drive-by defense (verified by test — single mention of "Shared Mental Model" still blocks). Block-reason message updated to "Show the block — the content you were asked to render, not a one-line summary" so the loosening doesn't invite gaming. Render CLIs still emit the H1 signature; only the gate's match criterion changed. Decision `echo-gate-policy` records the trade-off.

- **Test-run detection expanded for JS/TS ecosystem.** `is_test_run` now recognizes `playwright test` (with optional `npx` / `bunx` / `pnpm exec` / `yarn` prefix), `bun run test:*` script aliases, `npm run test:*`, `pnpm run test:*` / `pnpm test:*` (pnpm's implicit-run shorthand), and `yarn test:*` / `yarn run test:*`. Playwright routes to a new framework tag with its own parser case that shares the jest/vitest `N passed / N failed` pattern via a new `_parse_n_passed_n_failed` helper — dedups three existing parser bodies while adding the fourth. Ordering matters: `playwright test` is checked BEFORE generic script aliases so `yarn playwright test` resolves to playwright, not the yarn script-alias route. A priority test enforces this.

- **Cross-module metadata-key constants.** Two post-merge refactors moved the stringly-typed cross-module event spelling out of the call sites and into `event_schema.py`: `STATUS_CONTENT_RESOLVES_PROBE`, `METADATA_KEY_PROBE_CANDIDATES`, `METADATA_KEY_COMMIT_HASH`, `METADATA_KEY_RESOLVES`. Producers (`bash_post_tool`, `concerns`, `work_selection_decide`) and consumers (`pre_tool_bash`, `retrospective`, `materialize`, `resolution`) now read the same names. Tests deliberately keep the string literals so accidental constant-value changes fail loudly. Block comments colocate the producer/consumer map with the constants so the coupling is visible at the definition.

- **Carry-forward debt retired in `resolution.py` + `materialize.py`.** Both modules were importing `EVENT_TYPE_*` constants at the top and then using string literals (`"question"`, `"concern"`, `"goal"`, `"debt"`, `"decision"`, `"assumption"`, `"answer"`) in their adjacent match/dispatch blocks — mixed conventions within one file, flagged for multiple sprints as debts `182584eecff0` and `924ad2756dfa`. Replaced with the existing constants; `resolution.py` also picks up `PRIORITY_BLOCKING` for the blocking-question notification. Courage-over-debt: files were open, pattern-identical to the cross-module refactor above, so fixed now rather than deferred again.

- **Tests.** 2234 total (up from 2187 at v2.14.5). 13 new is_test_run detection tests + 2 playwright parser tests. 5 story-001 nudge/probe tests. 13 story-002 implicit-ids tests. 5 story-003 retro-metric tests. 2 new E2E integration tests. 3 new echo-gate plain-text-phrase tests. Plus refactor-mode updates to a handful of existing tests.

## v2.14.5 — Resolution-Link Discipline: Decision Nudge, Commit Auto-Link, Attribution Anomaly

Closes Milestone 3 of the Inline-Agent-Migration execution plan. Three stories shipped in parallel via CLI teammates (first full multi-teammate delivery since the feature landed). Together they push the resolution-link conventions from agent judgment into deterministic nudges and surface a latent sizing bug.

- **Decision-time open-questions nudge (PreToolUse:Bash).** `pre_tool_bash.run` gains a branch that fires when a Bash command invokes `append.sh --type decision` without `--metadata '{"resolves":[...]}'`. It loads currently-open questions from `events.jsonl`, builds a list of `id (topic): first-80-chars` lines, and injects them via `hookSpecificOutput.additionalContext` so the agent sees the candidate STRONG-link targets before the decision lands. Non-blocking — the agent can re-run with `--metadata` or proceed knowingly. New pure helper `_common.parse_append_sh_args(command) -> dict[str, str]` provides shlex-based flag parsing (robust against quoting shape). A JSON-parse helper `_decision_metadata_has_resolves` avoids the substring false-positives of naïve regex. 12 new tests (5 in `test_pre_tool_bash.py`, 7 in `test_common.py`). Closes a 6-retro-consecutive discipline gap.

- **Commit auto-link nudge + reviewer-concern files contract (PostToolUse:Bash).** New pure helper `commits.open_concerns_matching_commit(smm_dir, commit_files) -> list[dict]` returns unresolved concerns whose `files=[...]` list intersects the commit's changed files. `bash_post_tool._handle_commit` calls it after recording the commit event; for any matching concern NOT already covered by the `Resolves-Event:` trailer, it emits an `Auto-link nudge: concern <id> — <first-80-chars>. Consider adding \`Resolves-Event: <id>\` trailer.` line to stderr. Complementary to the existing `Resolves-Event:` STRONG-resolve trailer — never replaces it. `PROCESS_GUIDE.md` gains a new `## Resolution Discipline` section naming the three link strengths explicitly: **STRONG** (`metadata.resolves`), **WEAK** (top-level `references` for cascade-close), **STRUCTURAL** (top-level `files` for commit auto-link). `agents/xp-plan-reviewer.md` gains a one-line requirement that concerns/debt must carry `--files '[...]'`. `xp-code-reviewer.md` already required this; documented consistency across reviewers. 9 new tests (6 in `test_commits.py`, 3 in `test_bash.py`).

- **Story-deferral attribution anomaly flag (sizing_metrics).** Per-story sizing records gain a new `attribution_anomaly: bool` field, true iff `status == "deferred" AND commits > 0`. Surfaces two possible causes deterministically: commits mis-attributed (wrong `metadata.story_id`) or a story functionally complete but never marked done. `agents/xp-retrospective.md` is updated to document the field and add an "Attribution Anomalies" subsection in Sprint Analysis that lists flagged stories with an investigation prompt. Additive schema — no existing consumer breaks. Collapsed four per-case unit tests into one subTest truth-table at `/simplify`'s prompting (repo norm).

- **Platform surface unchanged.** No schema changes, no new markers, no new dependencies. Three hooks extended (`PreToolUse:Bash` gains a branch; `PostToolUse:Bash` gains a nudge), two agent prompts updated, one process doc updated. Full suite: 2187 tests green after integration.

## v2.14.4 — Resolves-Event Commit Trailer

- **`Resolves-Event:` commit trailer auto-links commits to SMM events.** Commits can now declare which recorded events they close (debt, concern, question, goal, assumption, decision, discovery) via a git trailer at the bottom of the commit body, mirroring the `Co-Authored-By:` mechanism:

  ```
  Fix the thing

  Rationale.

  Resolves-Event: 4eb35ddcd24e, a55290ae79b9
  ```

  New `commits.extract_resolves_trailer(body) -> (event_ids, body_without_trailers)` parses the trailer (case-insensitive key, line-anchored, comma-separated or repeated lines, dedup preserving first-seen order, 12-hex-char ID validation) and returns both the extracted IDs and the cleaned body in a single scan. `bash_post_tool._handle_commit` calls the extractor before the Co-Authored-By strip and adds `metadata.resolves = [...]` to the commit event when IDs are present; the trailer lines are stripped from the stored body so `metadata.resolves` is the sole home for the linkage. This dovetails with the existing `metadata.resolves` plumbing used by adoption decisions and auto-resolution, so retros and housekeeping walk one convention across commit events, status events, and other resolvers.

- **Event-ID regex consolidated as public `smm_schema.EVENT_ID_RE`.** Renamed from the private `_ID_RE` so `commits.py` can import the same pattern it validates against. Internal `_is_valid_id()` still uses it.

- **Doctrine added to `PROCESS_GUIDE.md` and `TEAMMATE_GUIDE.md`.** New "Linking commits to SMM events" section under Recording Events in the process guide covers format, example, and case/hex rules. TEAMMATE_GUIDE.md's Commit Conventions gets a matching bullet. Both guides list the full set of resolvable event types (`debt`, `concern`, `question`, `goal`, `assumption`, `decision`) to match what the resolution engine actually supports.

- **Kickoff SKILL.md step 6/7 duplication removed.** Step 6 previously repeated step 7's "output both as text" directive. Step 7 is already the terminal-action step for housekeeping output — dropped the duplicate.

- **Tests.** 11 new unit tests cover `extract_resolves_trailer` (single ID, comma-separated, multiple lines, case-insensitive, dedup-preserving-order, inline-mention rejection, non-hex rejection, wrong-length rejection, no-trailer, empty, None). 2 integration tests assert the wire-in populates `metadata.resolves` when present and omits the key when absent.

## v2.14.3 — Preserve Review State on Failed Commits; Kickoff Retro Surfacing

- **Failed commits no longer wipe the review cycle.** `bash_post_tool._handle_commit` was running three post-commit side effects unconditionally: lint-concern resolution, `.security-triaged` marker consumption, and review-cycle flag reset. Only the commit event recording was gated on `parse_commit_message` returning a non-None value. When a pre-commit hook rejected the commit, stdout had no `[branch hash] msg` signal so the parse returned None, but the fallback `get_head_commit_hash()` still returned the previous HEAD — so `reset_review_cycle` would clear `simplify_done`, `quality_review_done`, and `security_review_done` with the old hash as the new baseline. Agents had to re-run the full `/simplify` → `/xp-quality-review` → `/xp-security-triage` sequence before retrying the same commit. Fix: early-return when `parse_commit_message` returns None, since that's the reliable success signal (git only emits `[branch hash] msg` on success). Also dropped the now-unreachable fallback hash refetch and pre-declaration of `committed_files` / `commit_hash`. Three new TDD tests: `test_failed_commit_preserves_review_cycle` (pre-commit failure stdout), `test_failed_commit_preserves_security_marker` (same, asserting the security marker), and `test_empty_stdout_preserves_markers` (content-agnostic guard proof).
- **Kickoff step 1 retro display instruction strengthened.** `/xp-kickoff` step 1 ended with "Proceed to step 2." — the display directive for the forked retrospective result sat before that closing cue, which occasionally pulled focus toward step 2's AskUserQuestion before the main agent echoed the retro text. Since forked-subagent results aren't visible to the user, skipping the echo meant the retrospective was lost. Removed "Proceed to step 2." and reframed the display as the terminal action of step 1 ("output the full retrospective verbatim before calling any other tool"). Resolves the recurring "Needs blocking gate, visible skill output, or enforced check" risk.

## v2.14.2 — Retro Credits /security-review as Triage

- **Retro now counts `/security-review` as a security check.** When a session ran `/security-review` directly (not wrapped in `/xp-security-triage`), `review_cycle_done.py` recorded the status string "Security review complete — full review performed", but the retro pattern only matched "Security triage (complete|started)". Every commit preceded by a direct `/security-review` was falsely flagged as "triage skipped." Widened the shared pattern to match either triage or review, consolidated the previously-duplicated regex (was defined identically in `honesty_signals.py` and `retrospective.py`) into `_common.SECURITY_CHECK_RE` alongside `TEST_RUN_RE` / `LEGACY_COMMIT_RE`. New regression test `test_commit_event_with_security_review_not_counted`.
- **Signal field and dict-key renames for semantic accuracy.** Following the regex widening, the signal field `commits_without_triage` → `commits_without_security_check` (cascading through `honesty_signals.py`, `retro_flags.py`, and both affected test suites), and the status-classification counts key `status_summary["security_triages"]` → `status_summary["security_checks"]`. Variable `last_triage_seen` → `last_security_check_seen`. Retro flag message is now "N code commit(s) without a security check (triage or review)." `agents/xp-retrospective.md` updated to match. No migration needed — the signal is computed fresh each retro, not persisted.

## v2.14.1 — XP Values Additions; Acceptance Testing Doctrine

- **XP Values updates.** Added "Be direct and concise — say the thing, don't pad it." to the Communication value. Prepended "Be honest!" as a leading imperative to the Honesty value. Small but deliberate — codifying the direct-communication stance this plugin already expects from agents.
- **Acceptance Testing Doctrine (design doc).** New `docs/ACCEPTANCE_TESTING_DOCTRINE.md` defines how acceptance testing fits the XP loop: two loops on two clocks (TDD commit loop stays fast, story acceptance runs at story boundary), six acceptance surfaces for detecting tooling gaps (HTTP/WebSocket, Browser, CLI, SDK, Automation, Message/event), BDD Given/When/Then as the universal story-acceptance format, the `acceptance_execution` schema for declaring runner + command per story, automation-first `/xp-accept` policy (no retry; override-with-concern preserves agency while surfacing flake), milestone-level cross-cutting acceptance via capstone stories and a `/xp-sprint-review` gate, and analysis-vs-scaffolding separation (`/xp-system-context` raises actionable concerns but never scaffolds harnesses). This is the design source for a forthcoming six-milestone execution plan to integrate acceptance testing into the plugin; no code changes land in this release.

## v2.14.0 — Fix Teammate SMM Divergence; Init.sh Hot-Path Speedup

- **Teammate SMM divergence fixed.** Spawned CLI teammates now write events to the lead's SMM regardless of plugin loading mode. `init.sh` honors `$SMM_DIR` as the single canonical handle — if the env var is set (as `spawn_teammate.py` does), derivation is skipped and the path is used verbatim. Teammate hooks inherit `$SMM_DIR` from the spawn env.
- **Single source of truth for SMM path derivation.** `init.sh` is now the only place that computes SMM paths from `git-common-dir` + `CLAUDE_PLUGIN_DATA`. `smm/_append_impl.resolve_smm_dir()` and `scripts/_common.resolve_smm_dir()` are now thin delegators: honor `$SMM_DIR` env or subprocess-call `init.sh`. Previously the three sites duplicated derivation logic and could drift. Signature changed from `-> Path` to `-> Path | None`; callers (`compact.py`, `migrate.py`, `repair.py`, `prepare_curation.py`) now handle `None` cleanly instead of crashing on `AttributeError`.
- **Ancestor `chmod` leak fixed.** `init.sh`'s `chmod 700 "${BASE_DIR}" "${BASE_DIR}/${PROJECT_ID}"` was previously guarded by a loose `[[ -n "${BASE_DIR:-}" ]]` check that would fire if a caller had `BASE_DIR` exported for unrelated reasons. Now scoped inside the derivation branch where `BASE_DIR` was actually computed. New regression test `test_inherited_base_dir_is_not_chmodded` locks down the boundary.
- **`init.sh` warm-path 113ms → 33ms (71% reduction).** Three wins: (1) `hash12()` prefers native `shasum` / `sha256sum` over `python3 -c` hashing (-20ms); (2) removed preflight Python version check (-19ms) — every critical module uses PEP 604 syntax and fails loudly at parse time on wrong Python; (3) gated `seed_smm.py` invocation on existing `shared_mental_model.json` (-48ms Python startup) and dropped `|| true` so first-run failures surface. Also collapsed paired `touch`/`chmod` calls. Over a 50-hook session: ~5.6s → ~1.65s cumulative overhead.
- **Test hygiene: `$SMM_DIR` scrubbed at conftest import.** Stripped alongside existing `GIT_*` vars so a stray dev-shell export can't silently redirect test writes. `_IntegrationTestCase` and `_TempRepoTestCase` now inject `$SMM_DIR` into `_test_env` after the initial `init.sh` run, so subsequent subprocess calls take the short-circuit path. Full test suite runtime 60s → 49s (18% faster). `TestInit.test_init_succeeds` / `test_init_idempotent` now explicitly pass `extra_env={"SMM_DIR": ""}` to keep exercising the derivation branch.
- **Dead code removed.** Deleted `detect_plugin_mode()` and the `--plugin-dir` CLI arg from `scripts/spawn_teammate.py`. `detect_plugin_mode` read `CLAUDE_PLUGIN_DATA` which Claude Code strips from Bash-tool env, so it always returned `None` in practice; `--plugin-dir` was never passed by any caller. Teammate SMM continuity now comes solely from `$SMM_DIR` env inheritance.

## v2.13.6 — Stop Gate and Marker-Helper Fixes

- **Sprint stop gate now defers while teammate worktrees are live.** `sprint_stop_gate._deferred` previously only consulted `.coordination.json` for active teammates, but coordination entries aren't written until a teammate's first file write. Between spawn and first write, the gate fired on the lead with "Stories are in-progress. Run /xp-accept" — exactly when the lead should be idle and waiting for `TaskCompleted` notifications. Added `worktree.has_live_teammates(cwd)` using `git worktree list --porcelain` as a second deferral signal. Cost is bounded to rare block-pending moments (~8ms subprocess), not every Stop hook.
- **Marker-helper shell interpolation fragility fixed.** `write_marker` / `consume_marker` in `_preload_base.sh` string-interpolated bash variables directly into a double-quoted `python3 -c` body. Content containing a single quote broke Python syntax silently (suppressed by `2>/dev/null || true`), and a backslash was shell-interpreted as an escape. Switched to a single-quoted Python body with values passed via `sys.argv` so quotes, backslashes, and newlines round-trip unchanged.
- **Expanded `kickoff_gate` test coverage.** Collapsed the single qualified-name test into a parameterized `subTest` loop covering bare `/xp-kickoff`, `/xp-kickoff --verbose`, fully-qualified `/xp-agents:xp-kickoff`, `/xp-agents:xp-kickoff help`, and other-plugin namespace forms.

## v2.13.5 — Fix Housekeeping Stop Gate Blocking Mid-Kickoff

- **Housekeeping stop gate no longer blocks during early kickoff steps.** `.needs-housekeeping` was set in `kickoff_gate.py` at kickoff start (step 1), causing the stop gate to block any time the agent needed to pause for user input during steps 2-5 (retro, session mode, plan, sprint start, work selection). Moved the marker write to the work-selection preload (step 5), so the gate only activates right before housekeeping runs (step 6). The ASKING_USER deferral remains for the work-selection → housekeeping window.

## v2.13.4 — Expanded Code Reviewer + Migration Design Doc

- **xp-code-reviewer expanded with 5 new review items.** Added language-agnostic checks across XP values: multiple code paths for the same outcome and orphaned code from refactors (Simplicity), weak/lazy types (Communication), legacy fallback code (Courage), defensive programming that hides errors and circular dependencies (Honesty). Total review items increased from 10 to 15.
- **Inline agent migration design doc.** New `docs/INLINE_AGENT_MIGRATION.md` documents the plan to replace forked skills with inline skills + Agent tool + SubagentStart injection. Covers problem statement, current vs target architecture, per-agent data requirements, phased migration strategy, and tradeoffs. Decision: preloads are eliminated in favor of importable Python functions called from SubagentStart handlers.

## v2.13.3 — Fix Process Guide and SMM Injection After Housekeeping

- **SubagentStop `additionalContext` doesn't work.** The platform silently drops `additionalContext` from SubagentStop hooks — only `decision`/`reason` are supported. Our `_handle_housekeeping_done` in `subagent_stop.py` was building SMM + PROCESS_GUIDE.md + sprint nudge and returning it as `additionalContext`, but it never reached the agent. The process guide and curated SMM were never injected via this path.
- **Process guide now injected via PostToolUse:Skill.** `review_cycle_done.py` detects when the xp-housekeeping skill completes and injects PROCESS_GUIDE.md as `additionalContext` — PostToolUse supports this field.
- **SMM returned by housekeeper agent.** The xp-housekeeper agent now renders the full curated SMM (via `smm_cli.py dump`) and returns it alongside the change summary. The main agent receives both in the Skill tool result and displays them to the user.
- **Kickoff skill updated.** Steps 6-7 now instruct the agent to output both the rendered SMM and the housekeeping summary to the user.
- **`additionalContext` support matrix added to CLAUDE.md.** Documents which hook events support `additionalContext` and which don't, to prevent this class of silent failure.
- **Plan review cross-session leak fixed.** `post_tool_exit_plan.py` was reading `tool_response.planFilePath` which doesn't exist — the correct field is `tool_response.filePath`. When the marker had no valid path, the review preload fell back to `ls -t ~/.claude/plans/*.md | head -1`, which could grab a plan from a different session. Fixed the field name and removed the glob fallback. Preload now outputs `PLAN_FILE_ERROR=` with a clear message when no plan is found.

## v2.13.2 — Fix Kickoff Gate for Qualified Skill Names

- **Qualified skill name fix.** `kickoff_gate.py` checked for `"/xp-kickoff"` in the prompt, but marketplace installs send the fully-qualified form `/xp-agents:xp-kickoff` which doesn't contain that substring. Changed to `"xp-kickoff"` (no leading slash) to match both forms.
- **Removed duplicate marker clearing.** The kickoff preload script (`check_session_needs.sh`) was also removing `.needs-kickoff` via `rm -f`, racing with `kickoff_gate.py`. Removed the preload's `rm -f` so `kickoff_gate.py` is the single source of truth for clearing `.needs-kickoff`.

## v2.13.1 — Housekeeping Stop Gate

- **Housekeeping stop gate.** New Stop hook blocks session end if housekeeping hasn't run. When kickoff starts, `.needs-kickoff` is consumed and `.needs-housekeeping` is written. The stop gate blocks until the housekeeper subagent completes and clears the marker. Defers when ASKING_USER is set so "Chat about this..." on AskUserQuestion works without trapping the user.
- **Marker lifecycle.** Work-selection preload writes `.needs-housekeeping` before housekeeping runs (moved from `kickoff_gate.py` in v2.13.5), `subagent_stop.py` consumes it on housekeeper completion. New `NEEDS_HOUSEKEEPING` constant in `marker_names.py` and `MarkerDef` in `markers.py`.
- **SMM init failure surfaced.** When `init.sh` fails (not in a git repo, timeout, permission denied), `session_start.py` now returns "SMM init failed — xp-agents disabled." instead of the misleading "Run /xp-kickoff" prompt.

## v2.13.0 — Independent Code Reviewer Subagent

- **xp-code-reviewer agent.** New subagent spawned by `/xp-quality-review` for independent code review. The quality review skill previously ran inline — the same agent reviewed its own code. Now it spawns `xp-code-reviewer` with fresh context to evaluate changes through 4 review areas: simplify accountability (holding skipped findings accountable), drift management (checking code against SMM Constraints), debt awareness (evaluating existing debt for changed files), and XP-lens code review (covering 10 gaps /simplify misses: premature generalization, naming quality, test quality, workarounds, dead code, hidden assumptions, silent failures, and more).
- **SubagentStart dispatch override.** `xp-code-reviewer` gets full SMM injection (overriding the xp-* default of values-only) so it can independently check for drift against Constraints.
- **Quality review skill restructured.** Reduced from 7 inline steps to 4-step orchestrator: spawn subagent, resolve plan concerns, act on findings, record summary. Agent tool added to allowed-tools.
- **Duplicate tests removed.** Removed 2 duplicate test methods from `TestPluginIntegrity` (agent file existence + skill file existence already tested in dedicated classes) and 1 near-duplicate test from `TestSubagentStart`. Consolidated code reviewer dispatch tests using `subTest`.

## v2.12.4 — Remove xp-simplify, Test Split, Debt Cleanup

- **xp-simplify skill removed.** CLI teammates run as independent `claude -p` processes with full tool access, so they use the built-in `/simplify` (3 review subagents) instead of the inline single-pass xp-simplify. Updated teammate_stop_gate, tests, README, and ARCHITECTURE.
- **test_bash.py split.** Extracted `TestResolveStoryId` (9 tests) into `test_story_attribution.py`, reducing test_bash.py from 766 to 592 lines.

## v2.12.3 — Review Scope Fixes and Debt Cleanup

- **Cross-teammate simplify scoped via Skill args.** xp-accept Step 0 now passes `args` to `/simplify` scoping the review to merged teammate changes, so it reviews the merge diffs instead of finding an empty working tree.
- **Security review scoped to working tree.** `xp-security-reviewer` agent now passes args to `/security-review` to scope to uncommitted changes (staged, unstaged, and new untracked files) instead of diffing the entire branch history. xp-accept Step 0 similarly calls `/security-review` directly with args scoped to the merged teammate changes.

## v2.12.2 — Retro Try Items: Metrics, CI Tests, Stop Gate Fix

- **Event gap metric fixed.** `_has_code_changes()` in `work_signals.py` now uses `security.is_code_file()` to filter, so only source code writes (not sprint.json, plan .md files) start the events-to-commit counter. The metric was inflated by 80% status events from hook-generated writes to non-code files.
- **CI-environment test coverage.** Both `xp-review-plan` and `xp-assign` preload scripts now have tests that set `HOME` to a temp dir where `~/.claude/plans/` doesn't exist, verifying graceful degradation. Also covers stale `.last-plan-path` and missing marker scenarios.
- **Sprint stop gate bypass fixed.** `teammate_output_filter.py` now clears the teammate's `.coordination.json` entry immediately after recording completion. Previously, stale entries (within 30-min TTL) from finished teammates caused the sprint-review nudge to defer indefinitely.

## v2.12.1 — Fix Domain Accuracy: Three-Tier Story Attribution

- **Three-tier commit-to-story attribution.** Commits are now attributed to stories using `metadata.story_id` set at commit time, replacing the broken file-overlap heuristic that caused 10-50% domain accuracy for 4 consecutive sprints. Tier 1: teammates use `.story-assignment-{name}` file written by `spawn_teammate.py --story-id`. Tier 2: solo sprint work infers from in-progress stories (single story auto-assigns, multiple tiebreak by file domain overlap). Tier 3: non-sprint commits get no attribution.
- **File deduplication in sizing metrics.** `_attribute_commits()` now uses set union per story instead of summing per-commit file counts, eliminating double-counting when the same file appears in multiple commits.
- **spawn_teammate.py --story-id flag.** New optional `--story-id` argument writes a `.story-assignment-{name}` file to the SMM directory for commit attribution. `cleanup_teammate.py` removes it during cleanup.
- **Dead code removed.** `TEAMMATE_ID` environment variable (set but never read by any hook) removed from `spawn_teammate.py`.
- **Private functions made public.** `identity.extract_worktree_name()`, `sizing_metrics.file_matches_domain()`, and `sizing_metrics.extract_file_domain_paths()` renamed from private to public for cross-module use.

## v2.12.0 — Merge + Accept + Cleanup + Documentation

### Sprint-018: Milestone 5 (Documentation Update)
- **CLAUDE.md slimmed to project-only content.** Removed "XP Practices", "Event Appending" usage, and "Resolving Events" sections (duplicated by plugin-injected PROCESS_GUIDE.md and XP_VALUES.md). Replaced per-file listings with directory-level structure. Added "Further Reading" section. Makes the repo a proper test environment for the plugin.
- **README.md updated for CLI teammates.** All "Agent Teams" references updated. Skills table expanded from 8 to 14. SMM directory listing corrected (shared_mental_model.json, sprint.json, execution_plan.json). "behavioral guide" → "process guide" throughout. Test count updated to 2014.
- **ARCHITECTURE.md modernized.** Replaced per-file plugin structure with directory-level descriptions. All "behavioral guide" / BEHAVIORAL_GUIDE.md references updated to "process guide" / PROCESS_GUIDE.md. Hook map verified against hooks.json. Component inventory updated.
- **Design docs finalized.** CLI_TEAMMATE_DESIGN.md marked as fully implemented (M1-M4, Sprints 014-017). AGENT_TEAMS_DESIGN.md marked as superseded. SMM_DESIGN.md injection model updated (teammates use SessionStart, not SubagentStart).
- **CHANGELOG v2.12.0 entry.** Documents Sprint-017 and post-sprint refactoring.
- **First CLI teammate test.** All 5 stories executed in parallel by CLI teammates. Uncovered and fixed two spawn_teammate.py bugs before teammates could run.

### Sprint-017: Milestone 4
- **cleanup_teammate.py.** New script verifies a teammate's branch is fully merged (`git merge-base --is-ancestor`), removes the git worktree and branch, and cleans up agent-scoped markers and report files from the SMM dir. Called by `/xp-accept` after stories pass acceptance criteria.
- **xp-accept teammate workflow.** Detects teammate worktrees and prompts for branch merge before acceptance. Runs cross-teammate review cycle (`/simplify` + `/xp-quality-review` + `/xp-security-triage`) on the merged result to catch inter-story integration issues. After acceptance, calls `cleanup_teammate.py` for each verified story's worktree.
- **spawn_teammate.py fix.** Replaced non-existent `--input-file` flag with stdin piping for prompt delivery. Added `--plugin-dir` argument for explicit plugin path passing — env var detection doesn't work outside hook execution context.

### Post-Sprint Refactoring
- **identity.py extracted from _common.py.** Agent identity resolution: `resolve_agent_id()`, `is_worktree_teammate()`, `get_current_branch()`. 48 lines.
- **worktree.py extracted from _common.py.** Git/path operations: `resolve_git_root()`, `resolve_smm_dir()`, `worktree_path()`, `remove_worktree()`. 104 lines.
- **_common.py reduced** from 533 to 384 lines. Both new modules are under 110 lines each.

## v2.11.0 — CLI Teammate Spawning

### Sprint-016: Milestone 3
- **spawn_teammate.py.** New launcher script creates git worktrees and starts independent `claude -p` processes for CLI teammates. Pre-spawn cleanup removes stale worktrees/branches for idempotent spawning. Uses `_common.resolve_git_root()` (cached). Detects plugin mode (inline vs marketplace) for correct `--plugin-dir` flag.
- **teammate_output_filter.py.** New filter script captures `type:result` events from `--output-format stream-json` output. Writes report files to SMM dir, appends cost/duration/turns events for velocity tracking and retro analysis.
- **xp-assign rewritten for CLI spawning.** SKILL.md replaced Agent tool `xp-teammate` spawning with `Bash run_in_background` calling `spawn_teammate.py | teammate_output_filter.py`. Mode selection logic preserved. Preload exports `PLUGIN_ROOT`.
- **xp-accept next steps.** Accept skill now directs to `/xp-sprint-review` when sprint is complete, rather than relying solely on the stop gate.
- **Documentation debt cleared.** All stale references to removed `is_teammate_by_agent_type()`, `TEAMMATE_AGENT_TYPES`, and `xp-teammate` agent updated across CLAUDE.md, ARCHITECTURE.md, SMM_DESIGN.md, PROCESS_GUIDE.md, README.md, and CLI_TEAMMATE_DESIGN.md. Terminology updated from "Agent Teams" / "worktree subagents" to "CLI teammates".

### Sprint-015: Milestone 2
- **CLI teammate session lifecycle.** TEAMMATE_GUIDE.md rewritten for CLI teammates with full review cycle. SessionStart detects worktree teammates via `is_worktree_teammate()` and injects XP Values + guide + rendered SMM. SessionEnd records completion event with branch name. SubagentStart teammate injection and xp-teammate agent definition removed.
- **resolve_agent_id consolidation.** Duplicate `get_current_branch()` helpers consolidated into `_common.get_current_branch()`.

## v2.10.0 — Teammate Review Cycle

### Sprint-013: Milestones 3 + 4
- **Teammate-compatible review cycle.** Stop gate and nudge messages updated from `/simplify` → `/xp-simplify` and `/xp-security-triage` → `/security-review`. Teammates can now complete the full review cycle without spawning sub-agents.
- **Agent definition updated.** `xp-teammate.md` Review Cycle section references inline-compatible skills (`/xp-simplify`, `/security-review`). `xp-assign/SKILL.md` spawn prompt template updated to match.
- **Review nudge consistency.** `review_cycle_done.py` `_NEXT_STEP` dict now nudges `/security-review` (works for both main agent and teammates) instead of `/xp-security-triage`.

### Sprint-012: Milestones 1 + 2
- **xp-simplify inline skill.** Single-pass code review covering reuse, quality, and efficiency without spawning sub-agents. No "skip if false positive" escape hatch — every finding must be applied or recorded as debt.
- **Plan archive command.** `plan_cli.py archive` moves completed execution plans to `plans/` directory. `xp-plan` SKILL.md update flow includes "Archive and start fresh" option.

### Tests
- **xp-simplify detection tests.** Characterization tests verify `review_cycle_done.py` handles `xp-simplify` and `xp-agents:xp-simplify` via substring matching.
- **E2E review cycle test.** Integration test walks through the full 5-step stop gate sequence: `/xp-simplify` → `/xp-quality-review` → `/security-review` → commit → stop.

## v2.9.0 — Plan-Driven /xp-assign + Teammate Gates

### Sprint-011: Milestone 4
- **Plan cycle documented.** PROCESS_GUIDE.md defines the plan cycle (EnterPlanMode → /xp-review-plan → /xp-assign → execute) as a named hook-enforced sequence alongside the review cycle. Marker flow documented: `.plan-awaiting-review` → `.assign-pending`.
- **Plan-driven /xp-assign.** SKILL.md rewritten to read plan file steps for mode selection instead of sprint stories. Works identically in sprint and free session modes. preload.sh outputs PLAN_FILE as primary input, SPRINT_FILE as optional context.
- **Plan reviewer updated.** Section 9 (execution mode) uses plan-step terminology, Agent Team option removed per SMM constraint (Solo + Worktree subagents only).
- **Terminology sweep.** All references to "sprint stories" in the context of /xp-assign updated across kickoff SKILL.md, subagent_stop.py, README.md, ARCHITECTURE.md, CHANGELOG.md.

### New Gates
- **Teammate stop gate.** New `teammate_stop_gate.py` blocks xp-teammate agents from stopping with uncommitted changes. Enforces review cycle in order: /simplify → /xp-quality-review → /xp-security-triage → commit. `TEAMMATE_AGENT_TYPES` extracted to `_common.py` (shared with subagent_stop.py).
- **Accept gate.** New gate in `pre_tool_bash.py` blocks `update-story done` when ACCEPT marker exists — prevents bypassing /xp-accept acceptance criteria verification. Uses regex detection (`update-story\s+\S+\s+done\b`). /xp-accept SKILL.md updated to clear marker before updating status.

### Fixed
- **xp-plan preload permission.** Added `Bash(*/skills/*/scripts/*)` to xp-plan allowed-tools, matching all other skills. Preload script was being blocked by permission system.
- **Pyright type narrowing.** Fixed `str | None` → `Path()` warnings in test_assign.py by using `assert` instead of `self.assertIsNotNone` for type narrowing.

## v2.8.1 — Close Retro Fix/Try Feedback Loop

### Fixed
- **Defer/drop now have downstream effect.** Work-selection skill records defer/drop with `metadata.resolves` and a `disposition` field, so `annotate_try_status()` can distinguish adopted/deferred/dropped. Previously both were generic status events that nothing read.
- **Dropped Try items are never re-proposed.** Retro agent prompt uses `try_status[i].disposition` to decide: `dropped` = never re-propose, `deferred` = may re-propose with deferral count, `adopted` = don't repeat verbatim.
- **Decision-aware flag suppression.** `evaluate_flags()` accepts a `decisions` parameter. `_FLAG_SUPPRESSIONS` mapping suppresses flags when a matching decision topic is active (e.g., `max_events_to_commit` suppressed by `retro-try-kickoff-exemption`). Closes the Adopt→Fix loop where adopting a Try created a decision but the same Fix kept firing.
- **Commit-to-story attribution.** `_file_matches_domain()` handles path suffix matching (`plugins/xp-agents/scripts/foo.py` matches domain `scripts/foo.py`) and test-to-source mapping (`test_foo.py` matches `foo.py`). Previously strict set intersection missed all prefixed and test file paths.

### Changed
- **`_build_resolutions_map()`** propagates `disposition` from resolver event metadata into the resolutions map.
- **`retrospective.py`** extracts decision topics from events and passes them to `evaluate_flags()`.

## v2.8.0 — Merge Sprint Retro into Session Retro

### Sprint-010: Milestone 3
- **Sprint sizing metrics.** New `sizing_metrics.py` computes per-story and per-size metrics by attributing commit events to stories via file_domain overlap. Shared attribution — a commit matching multiple stories counts for all. Metrics: commits, files_changed, in_domain_files, out_of_domain_files, domain_accuracy.
- **Session retro handles sprint analysis.** When a sprint has ended, `retrospective.py` enriches `.retro-input.json` with a `sizing_analysis` block. The xp-retrospective agent prompt includes a conditional Sprint Analysis section (goal assessment, per-story metrics table, per-size calibration). Sprint end bypasses the 5-event retro threshold.
- **Unified kickoff flow.** `check_session_needs.sh` and `xp-kickoff/SKILL.md` no longer check for `.sprint-retro-input.json` or route to `/xp-run-sprint-retro`. All retro work flows through `RETRO_NEEDED` → `/xp-run-retrospective`.
- **`needs_sprint_retro()` inlined.** Detection function moved from `sprint_retro_detection.py` into `retrospective.py`. Renamed from `_needs_sprint_retro` to public API.

### Removed
- **`agents/xp-sprint-retro.md`** — sprint retro agent definition.
- **`skills/xp-run-sprint-retro/`** — sprint retro skill + preload script.
- **`scripts/prepare_sprint_retro_data.py`** — sprint retro data prep script.
- **`scripts/sprint_retro_detection.py`** — detection module (inlined into retrospective.py).
- **`_handle_sprint_retro_done`** function, constants, and call site from `subagent_stop.py`.
- **Test files:** `test_sprint_retro.py`, `test_sprint_retro_detection.py`, `TestSprintRetroDone` class, sprint retro integration tests, sprint retro tier test.

## v2.7.0 — Housekeeper Migration to Item-Level CLI

### Sprint-009: Milestone 2
- **xp-housekeeper agent rewritten for item-level API.** Agent now expresses SMM mutations as individual `add-item`, `update-item`, `remove-item`, and `complete-curation` CLI commands instead of assembling a full JSON document and piping to `smm_cli.py save`. The CLI handles identity (UUIDs, timestamps) server-side, eliminating UUID drift risk entirely.
- **Allowed tools updated.** `xp-housekeeping` SKILL.md patterns changed from `Bash(cat *| python3 */smm_cli.py *)` to `Bash(echo *| python3 */smm_cli.py *)` and `Bash(python3 */smm_cli.py *)` for the two command forms.
- **Merge rules simplified.** Agent prompt no longer contains UUID preservation instructions, full-doc JSON assembly templates, or entry schema requirements. Mutation verbs (add/update/remove) replace the monolithic output format.

### Removed
- **`settings.json`** deleted. The sole config value (`commit_size_threshold`) is now a hardcoded constant (`COMMIT_SIZE_THRESHOLD = 12`) in `bash_post_tool.py`, consistent with all other thresholds in the codebase.
- **`load_commit_threshold()`** function removed from `bash_post_tool.py`.
- **Tautological constant test** removed — asserting a constant equals a literal validates nothing.

### Changed
- **Retro metric thresholds moved to Python.** `retro_flags.py` now owns threshold definitions and comparisons instead of delegating judgment to the LLM.

## v2.6.0 — Item-Level SMM API + Retro Try Fixes

### Sprint-008: Milestone 1 (partial — 2/6 stories)
- **`validate_entry(entry, pillar)`** in `smm_schema.py`. Per-item schema validation extracted from `_validate_pillar()`. Enables add/update operations to validate entries before insertion without full-document validation. `_PILLAR_SPEC_MAP` for O(1) pillar lookup.
- **`complete_curation(smm_dir)`** in `smm_cli.py`. Extracted watermark update + compaction from `save()` into standalone function with CLI subcommand. The bookend call after item-level mutations finalize a curation cycle.
- **`watermark_updated`** field in `compact_after_curation()` return dict. Eliminates redundant events.jsonl double-read: `complete_curation` now skips `parse_events` when compact already updated the watermark.

### Fixed
- **SessionStart hook "some events" fallback.** Sprint retro branch returned a string without a numeric count, so the regex fell back to "some." Now reports meaningful sprint-specific counts (stories and sessions). Regex updated to match both "events" and "stories."
- **Try-item resolution wiring.** `get_try_items()` in `_preload_base.sh` now outputs `event_refs` as `[refs: id1, id2]` suffix. Work-selection SKILL.md instructs the LLM to include `--metadata '{"resolves": [...]}'` when adopting Try items. Closes the retro Try → adoption → resolution detection loop.
- **Security triage exemption for non-code commits.** Gate auto-sets triage marker with `exempt_reason="no-code-files"` for doc-only/config-only commits. Prevents false "commits without triage" flags in retro honesty signals. `write_security_triaged()` gains optional `exempt_reason` parameter.

### Changed
- **Below-threshold commit gate restructured.** Single `security_triaged_exists` check with nested `if has_code` / `else` instead of two independent if-blocks (per simplify review finding).

## v2.5.0 — Worktree Integration + GIT_DIR Safety

### Milestone 3: Integration + Documentation (Sprint-007)
- **22 integration tests** for xp-assign/teammate workflow: preload with multi-story sprints, xp-teammate agent frontmatter validation, WorktreeCreate hook subprocess, edge cases (missing file domains, all-S stories, dependency chains).
- **ARCHITECTURE.md** updated: xp-assign moved from forked subagents to inline skills, xp-teammate.md added to agents, team spawn flow rewritten for two-mode model (solo/worktree subagents).
- **PROCESS_GUIDE.md** updated: `/xp-assign` documented as inline skill that auto-runs after planning.
- **README.md** updated: Agent Teams section replaced with Sprint Execution (solo + worktree subagents).
- **AGENT_TEAMS_DESIGN.md** updated: Worktree Subagent Findings section with empirical testing results, comparison table, platform constraints.
- **spawn-team-refactor.md**: All 6 open questions resolved with M1/M2 implementation answers.
- **CLAUDE.md**: Added worktree subagents key decision and git env safety documentation.

### Fixed
- **WorktreeCreate hook input format.** Platform sends `{session_id, transcript_path, cwd, hook_event_name, name}` — not `{worktree_path, branch}` as originally assumed. Hook now generates path under `.claude/worktrees/<name>` and branch `worktree-<name>` from the current branch.
- **SubagentStart dispatch for plugin-prefixed agent_type.** Platform sends `"xp-agents:xp-teammate"` but dispatch only had `"xp-teammate"`, routing teammates to the xp-agent skip path (zero context injection). Added both entries.
- **GIT_DIR/GIT_INDEX_FILE leakage in tests.** During `git commit`, git sets `GIT_INDEX_FILE`; in worktrees, git sets `GIT_DIR`/`GIT_COMMON_DIR`. Test subprocesses that create temp git repos inherited these, operating on the parent repo instead — corrupting `.git/config`, leaking `tmp*` branches, and causing `core.bare=true` inference. Known issue: [pre-commit#3032](https://github.com/pre-commit/pre-commit/issues/3032), [lefthook#1265](https://github.com/evilmartians/lefthook/issues/1265). Fixed with two-layer defense: `env -u` in `lefthook.yml` (infrastructure) + `os.environ.pop` in `conftest.py` (defense-in-depth).

### Changed
- **`lefthook.yml`**: All test runner commands wrapped with `env -u GIT_DIR -u GIT_WORK_TREE -u GIT_COMMON_DIR -u GIT_INDEX_FILE` to prevent git environment leakage into test subprocesses.
- **`.gitignore`**: Added `.claude/worktrees/` to prevent worktree directories from appearing in `git status`.

## v2.4.0 — Worktree Teammates + Inline Work Assignment

### Architecture
- **xp-teammate agent.** New worktree-isolated subagent for parallel story implementation. Spawned with `isolation: worktree`, runs full TDD + review cycle independently, commits to its own branch. The lead merges branches after completion.
- **xp-assign inline skill.** Renamed from xp-spawn-team and converted from forked agent to inline skill. Analyzes the plan's steps, decides execution mode (Solo vs Worktree subagents), and spawns xp-teammate agents via the Agent tool. Auto-runs after plan review completes.
- **Assign-pending gate.** When plan review completes, SubagentStop sets `.assign-pending` marker and nudges the agent to run `/xp-assign`. PreToolUse:Write blocks implementation until the marker is cleared. Mirrors the plan-review gate pattern.

### Added
- **`xp-teammate.md` agent definition.** Worktree-isolated teammate with `isolation: worktree` frontmatter, full review cycle instructions, file domain boundaries, and SMM event recording. Story-specific context comes from the spawn prompt.
- **`worktree_create.py` WorktreeCreate hook.** Branches worktrees from the current branch (not main/master), so teammates work on top of the lead's latest code. Registered in hooks.json.
- **xp-teammate dispatch in `subagent_start.py`.** Dedicated `_inject_xp_teammate()` handler provides SMM + system context without the teammate guide (instructions are in the agent .md).
- **`ASSIGN_PENDING` marker** in `marker_names.py` and `markers.py`. Gate constant for the plan-review → assign flow.
- **`_handle_plan_review_done()` in `subagent_stop.py`.** Sets assign-pending marker and returns additionalContext nudge when xp-plan-reviewer completes.
- **`edit-milestone` command in `plan_cli.py`.** Accepts JSON on stdin to update milestone status and delivered_sprint.
- **`SAMPLE_SPRINT_MD` shared fixture** in `conftest.py`. Eliminates duplication across test_subagent_tiers.py and test_teammate_guide.py.

### Changed
- **xp-spawn-team → xp-assign.** Skill directory, agent file, test file, and all references renamed atomically across CLAUDE.md, PROCESS_GUIDE.md, ARCHITECTURE.md, plan-reviewer, kickoff, plugin integrity tests, subagent tier tests, and 3 design docs.
- **xp-assign converted to inline.** Removed `context: fork` and `agent:` from frontmatter. Agent file deleted. Mode selection heuristic (dependency chains → Solo, all S-sized → Solo, overlapping domains → Solo, independent M/L → Worktree) and spawn instructions now live in SKILL.md.
- **Kickoff step 7** auto-invokes `/xp-assign` after plan review instead of listing manual options.
- **Sprint CLI for status updates.** Work-selection and accept skills now use `sprint_cli.py update-story` instead of direct file writes.
- **Preload rendering via CLI.** Sprint and SMM data rendered to tempfiles via CLI for read-only preload consumers, reducing token overhead.
- **Status keys standardized to hyphenated format** across all sprint stores (in-progress, not in_progress).
- **TEAMMATE_GUIDE.md** rewritten for Agent Teams focus (DO/DON'T/SKIP/KEEP rules).
- **`max_events_between_commits` → `max_events_to_commit`.** Metric renamed for clarity.

### Removed
- **`agents/xp-assign.md`** (formerly xp-spawn-team). Logic moved to inline skill.
- **`test_spawn_team.py`** renamed to `test_assign.py`.

### Stats
- 1778 tests (up from 1747), all passing
- Pre-commit wall time: ~25s
- 19 commits in this release (sprint-005 + sprint-006)

## v2.3.1 — Bug Fixes, SMM CLI Consolidation, Four-Pillar Cleanup

### Fixed
- **TDD stop gate teammate bug** (debt f38222aa). Gate now defers when `coordination.has_active_teammates()` finds other agents, preventing the lead from being blocked when teammates are in TDD red phase. Extracted shared `has_active_teammates()` into `coordination.py`.
- **Sprint stop gate false deferral.** Completed review cycles (all 3 flags True) were incorrectly suppressing sprint-complete blocks. Now only defers when mid-cycle (some flags True, not all).
- **Auto-archive completed execution plans** (debt e304b0d2). `session_start.py` now calls `execution_plan_store.archive()` when all milestones are delivered, preventing stale file-existence checks.
- **Plan reviewer blocking free sessions** (debt ce871882). Agent now checks Intent pillar for "Free session" goal before raising sprint-scope blocking questions.
- **Forked skill visibility.** All 9 forked skills clarified that subagent results are NOT visible to the user — agent must output text explicitly.
- **Test noise.** Suppressed stderr from oversized JSON rejection test that was confusing grep-based result scanning.

### Added
- **`smm_cli.py` — unified SMM CLI.** Consolidates `smm_view.py` (read-only rendering) and `save_smm.py` (housekeeping writes) into one CLI following the `sprint_cli.py`/`plan_cli.py` pattern. Dispatch table, `--smm-dir` as top-level arg, `save` command with watermark update and compaction.
- **Session mode as Intent goal.** Kickoff Step 2 now emits a `goal` event ("Free session" or "Sprint session: <id>") after user chooses. Flows into Intent pillar via housekeeping curation.
- **`pre-commit-autofix` decision.** Run `ruff check --fix` and `ruff format` before committing to catch errors before the pre-commit hook rejects them.

### Removed
- **Sprint pillar concept.** The "five-pillar" SMM is now consistently four pillars (Intent, Constraints, Risks, Wisdom). Sprint data lives in `sprint.json` — it was never persisted in the curated SMM. Removed `_render_sprint_section()`, sprint param from `render_markdown()`, `_read_sprint_data()` from `materialize.py`.
- **`smm_view.py` deleted.** Replaced by `smm_cli.py`.
- **`save_smm.py` deleted.** Absorbed into `smm_cli.py save` command.

### Changed
- **Integration tests 45% faster.** Moved git repo creation to `setUpClass` in `_IntegrationTestCase` (32.6s → 17.8s for 129 tests).
- **PROCESS_GUIDE.md** — added test output guidance, fixed `/xp-product-spec` → `/xp-plan` reference.
- **SMM_DESIGN.md** — updated for four-file architecture (.json extensions), renamed Sprint section to "Project Files", updated materializer role.
- **ARCHITECTURE.md** — updated `save_smm.py` references to `smm_cli.py save`.

### Stats
- 1747 tests (all passing, down from 1754 — removed redundant Sprint/session_mode tests)
- Pre-commit wall time: ~25s (down from ~35s)
- 27 commits in this release

## v2.3.0 — Context Gradient Planning System

### Architecture
- **Four-file architecture replaces three-file.** `product_spec.md` replaced by `system_context.md` (stable product/system description) + `execution_plan.md` (ordered milestones with change/impact zones). Decision reversal: product_spec was too monolithic for change-request workflows.
- **Context gradient model.** Sprint stories now carry layered context: broad (system context), medium (milestone design details), deep (per-story file domains + interface contracts). Subagents receive self-contained execution context for parallel work.

### Added
- **`/xp-system-context` forked skill + `xp-system-context` subagent.** Autonomous codebase analysis that produces `system_context.md` — thorough product description complementary to CLAUDE.md. Reads project structure, CLAUDE.md, and key source files.
- **`/xp-plan` inline skill.** Replaces `/xp-product-spec`. Collaborative planning that transforms external design sources into ordered milestones with change zones, impact zones, and design details.
- **`save_planning_doc.py` parameterized atomic writer.** Single script handles both `system_context.md` and `execution_plan.md` via `--type` parameter.
- **Enhanced sprint format.** Stories include Milestone reference, Design Sources, Context (inlined design rationale), File Domain (exclusive file ownership), and Interface Contracts (shared boundaries). Enables parallel subagent execution.
- **`sprint_parser.py` extended** for new fields: `milestone` (sprint-level), per-story `milestone_ref`, `design_sources`, `context`, `file_domain`, `interface_contracts`. Backward-compatible with old format.
- **System context injection for teammates.** `subagent_start.py` reads `system_context.md` and injects it before SMM content for teammates.
- **`check_system_context()` helper** in `_preload_base.sh` for shared preload use.
- **Spawn-team pre-computed file domains.** Agent uses File Domain from enriched stories when available, falls back to plan-based analysis.

### Removed
- **`/xp-product-spec` skill deleted.** Replaced by `/xp-plan`.
- **`save_product_spec.py` deleted.**
- **`NEEDS_PRODUCT_SPEC` marker removed** from `marker_names.py` and `markers.py`.
- **All `product_spec.md` references** removed from scripts, skills, tests, and docs.

### Changed
- **Kickoff flow** references `/xp-plan` and `/xp-system-context` instead of `/xp-product-spec`.
- **Sprint review** marks `execution_plan.md` milestones as `[delivered: sprint-NNN]` instead of product_spec features.
- **Sprint-start preload** checks for `execution_plan.md` (no legacy fallback).
- **CLAUDE.md, ARCHITECTURE.md, AGENT_TEAMS_DESIGN.md** updated for four-file architecture.
- **Spawn-team design doc** updated with Agent Teams session learnings: two-mode model (Solo + Worktree Subagents), subagent autonomy, updated mode selection heuristic.

### Stats
- 1663 tests (all passing)
- 66 new tests added
- Net -236 lines in cleanup commit (more deleted than added)

## v2.2.1 — Skill Invocation Guidance

### Added
- **"Invoke via /skill-name, not directly" in all 7 agent descriptions.** Prevents agents from bypassing the Skill tool and missing preload data + cleanup hooks.
- **"Forked skills" section in PROCESS_GUIDE.md.** Lists all skill-to-agent mappings and explains why direct Agent launches are incorrect.

## v2.2.0 — Free-Mode Sessions & AskUserQuestion Fix

### Added
- **Free-mode session choice in `/xp-kickoff`.** After retro, kickoff always asks "Free session or Sprint session?" via AskUserQuestion. Free mode skips product-spec creation and sprint-start, falling through to work-selection's goal-collection path. Sprint mode proceeds through product-spec/sprint-start as needed. The choice is stateless — re-running kickoff presents it again.
- **Kickoff preload file-existence detection.** `check_session_needs.sh` now checks for `product_spec.md` and `sprint.md` file existence in addition to marker files. NEEDS_PRODUCT_SPEC and NEEDS_SPRINT flags appear even after markers are consumed by housekeeping, supporting re-runs of `/xp-kickoff` in the same session.
- **`customer_input` logging for AskUserQuestion responses.** Non-gate answers (success without question gate, and failure with partial answers) are now logged as `customer_input` events so user responses aren't lost when no blocking question was pending.
- **`PostToolUseFailure:AskUserQuestion` hook registration.** `question_answered.py` now fires on both success and failure paths, enabling proper handling of "Chat about this..." interactions.

### Fixed
- **Stop gate false deferral after AskUserQuestion success.** ASKING_USER marker was set on every successful AskUserQuestion, causing the sprint stop gate to defer even when the agent had its answer and was legitimately stopping. The marker now only sets on failure ("Chat about this..."), where the agent needs to engage in clarification dialogue before the stop gate should fire.

### Stats
- 1565 tests (all passing)

## v2.1.0 — Curated SMM as Structured JSON

### Fixed
- **Seed-wipe regression: housekeeping silently destroyed seeded Constraints and Wisdom on first run.** `seed_smm.py` wrote 7 default constraints + 8 wisdom entries directly to `SHARED_MENTAL_MODEL.md`, but `materialize.prepare_curation_data()` derived `current_smm` purely from events — the seeded content had no matching events, so the housekeeper saw `current_smm == empty`, emitted an empty-pillar SMM, and wiped everything. Every fresh install lost its seeded defaults on the first kickoff.

### Architecture
- **Curated SMM persisted as `shared_mental_model.json`** (was `SHARED_MENTAL_MODEL.md`). Schema-validated four-pillar JSON document with per-entry stable UUIDs, typed metadata (`source: seed|event|curated`, `type`, `topic`, `severity`, `source_event_id`), and cross-pillar id uniqueness enforced at write time. The old markdown file is never written by any script.
- **New `smm/smm_schema.{json,py}` — schema + hand-rolled validator.** Mirrors the `event_schema.py` pattern: pillar/source/type/severity constants, `validate_smm(data) -> list[str]` returning an error list. No external `jsonschema` dep. Accepts UUID v4 (runtime) and v5 (deterministic seed).
- **New `smm/smm_store.py` — load/save I/O.** `load_smm(smm_dir)` returns `empty_smm()` on missing file, raises `ValueError` on corrupt or schema-invalid JSON (fail-loud by design — silent degradation would reproduce the seed-wipe bug). `save_smm(smm_dir, data)` validates then atomic-writes via `write_text_atomic`.
- **New `smm/smm_view.py` — pure dict→markdown rendering + shell CLI.** `render_markdown(smm, sprint=...)` generates four-pillar markdown for LLM context injection. `extract_pillar` / `extract_pillars` subset the view for Explore-tier injection. CLI subcommands `dump` / `section <name>` / `has-section <name>` consumed by `_preload_base.sh` helpers.
- **`prepare_curation_data` reads `current_smm` from the JSON file.** The ~100 lines that derived intent/constraints/risks/wisdom from events are gone. `new_since_last_curation` still comes from events after the watermark — the housekeeper's job shifts from "re-derive pillars from raw events" to "merge new events into current pillars, preserve by id, drop resolved items."
- **`seed_smm.py` emits a dict.** Deterministic UUID v5 per entry (`uuid5(namespace, f"seed:{pillar}:{content}")` — stable across test runs). Each seed entry has `source: "seed"` and sentinel `ts: "1970-01-01T00:00:00+00:00"` so aging never fires on them.
- **`save_smm.py` (housekeeping writer) accepts JSON on stdin.** Parses, validates via `smm_store.save_smm`, updates watermark, compacts event log. Malformed JSON or schema-invalid data raises `ValueError` — tempfile never renamed, existing file survives.
- **`xp-housekeeper.md` prompt rewritten for JSON output with merge rules.** Preserve existing entries unchanged unless (a) `source_event_id` in resolutions, (b) superseded by same-topic decision, (c) judgment pruning. Seeded entries removable only by judgment, never by resolution. First-ever curation path documented.
- **Readers switch to JSON + render-on-read.** `session_start.py` (compact branch), `subagent_start.py` (tier dispatch), `subagent_stop.py` (housekeeping-done), `pre_compact.py` (backup filename), and 5 shell preloads all go through `smm_store.load_smm` + `smm_view.render_markdown`. The regex-based `_extract_pillars()` in `subagent_start.py` is deleted — `smm_view.extract_pillars` handles it.
- **Shell preload helpers delegate to `smm_view.py` CLI.** `dump_smm`, `smm_has_section`, `smm_section` in `_preload_base.sh` now shell out to the Python CLI. `smm_render_to_tempfile` (new) writes a rendered markdown tempfile via `mktemp -p` for forked agents that `Read` the SMM file via the Read tool — unique path per call avoids concurrent-preload races.

### Migration
- No automated migration. `seed_smm.py`'s "don't seed if exists" guard now checks for `shared_mental_model.json` specifically. A stale `SHARED_MENTAL_MODEL.md` left on disk from a prior install is a harmless orphan — seeding still fires, and the old file is never read. Users who want to migrate historical markdown content can ask the agent manually.
- **First housekeeping pass after upgrade loses any pre-watermark events that were contributing to `current_smm` under the old derivation.** Events after the watermark will be merged by the housekeeper as normal. Acceptable for test installs. Production migrations (if any) should manually curate historical events into the JSON file first.

### Developer-facing changes
- New `tests/conftest.py::write_smm_fixture(smm_dir, intent=..., constraints=..., risks=..., wisdom=...)` helper — use this instead of `.write_text("# Shared Mental Model\n...")` in test fixtures.
- `save_smm.py` test contract: `run(content, smm_dir)` now takes JSON on stdin (was markdown).
- UUID regex in `smm_schema` accepts both v4 and v5 (was v4 only).

## v2.0.14 — Retro Digest Visibility, Explicit Overrides, Interactive Dialogue

### Fixed
- **Retro analyst false-positive "Try not honored" loop.** Debt `9cdd4617` (preload integration tests) was adopted as a retro Try and flagged as "not honored" across 3+ consecutive sessions, even though it was formally resolved via `metadata.resolves` within the same session each time. Root cause: `_build_retro_digest` computed the full 6-type resolution map via `compute_resolutions` but only extracted `resolved_concern_ids`. Status events with `metadata.resolves` closing debt/goals/questions/assumptions were invisible to the xp-retrospective agent because they weren't in `signal_events` (status events are summary-only). The agent saw "Adopted Try" decisions but not the resolution evidence, so it re-flagged the Try every session.
- **Superseded-decision detector false positives on additive topics.** `concerns.py` pattern #5 fired "Superseded decision: topic 'X' has multiple decisions without an intervening concern" for legitimate multi-decision patterns like retro Try adoption, kickoff redesign facets, and proposal→implementation pairs. Four such false positives (`10cade72`, `725f1b02`, `b18a56a6`, `13eb9e42`) had polluted the SMM for 9+ sessions. The dedup logic couldn't help — content-keyed dedup + `resolved_content_counts` escalation meant resolving a false positive re-fired it with bumped severity.
- **Sprint stop gate blocking interactive dialogues.** Interactive skills (`xp-sprint-start`, `xp-product-spec`, `xp-work-selection`, `xp-accept`) use `AskUserQuestion` for multi-turn dialogues. When the main agent stopped to wait for more user input mid-dialogue, `sprint_stop_gate._deferred()` had no signal distinguishing "mid-dialogue" from "done with work" — it blocked the Stop with `_REVIEW_MESSAGE` (or `_RETRO_MESSAGE` in older plugin versions) and cut off the interaction.

### Architecture
- **New `digest.resolutions` field in `.retro-input.json`.** `scripts/retrospective.py::_build_retro_digest` now exposes the full resolution map to the xp-retrospective agent: `{target_short_id: {type, resolver_id, resolver_content}}` for every debt, goal, question, concern, assumption, and decision resolved this session. Uses `_common.*` event-type constants. `resolver_content` truncated to 200 chars to honor token-optimization intent. Single-bucket invariant from `compute_resolutions`' `match/case` locks out key collisions.
- **`previous_retros[*].try` shape migration.** Each retro's `try` list is now `{content, event_refs}` dicts instead of content-only strings. Legacy list-of-strings retros from prior sessions are migrated on read. The old shape dropped `event_refs`, which the annotation step needs to cross-reference against the current session's resolutions.
- **`previous_retros[0].try_status` annotation.** Parallel list attached to the most recent retro (older retros already went through a retro cycle). For each Try item, extract 8+ char hex tokens from content via `\b[0-9a-f]{8,}\b` and union with `event_refs`; if any token's 8-char prefix matches a key in the session's resolutions map, the Try is flagged as `{resolved_this_session: True, resolver_id}`. The xp-retrospective agent's "Cross-Session Trends" section now treats `try_status[i].resolved_this_session == True` as the authoritative "Try honored" signal.
- **New `scripts/retro_history.py` module.** Extracted `gather_retro_history` and related constants from `retrospective.py` (which was at the 500-line cap) to create headroom for the digest/annotation feature work. Annotation logic (`annotate_try_status`, `_HEX_ID_RE`, `_slim_try_item`) lives here alongside the gatherer — both prepare retro-history data for the digest.
- **Explicit override semantics via `metadata.supersedes`.** Decisions that intentionally override a prior same-topic decision can now set `metadata.supersedes: [<prior_decision_id>]` (full ID or 8-char prefix, mirroring `resolve_prefix`'s convention). Pattern #5 skips the concern when the current decision references the actual same-topic predecessor. Bogus references (nonexistent or cross-topic) still fire — you can't silence the check with a wrong reference. Documented in `PROCESS_GUIDE.md` Honesty section and `agents/xp-housekeeper.md`.
- **"Resolved topic = accepted as additive" skip condition.** Once a superseded-decision concern on topic X is resolved via `metadata.resolves`, pattern #5 never re-fires for X. Permanent, topic-scoped acceptance — the human's explicit acknowledgment that the topic is intentionally multi-decision (retro Try adoption, proposal-implementation pairs, redesign facets). Folded into the existing concern-scan loop; no second pass. Narrow to pattern #5 only — convention violation (pattern #3) and assumption contradiction (pattern #2) retain their re-detection semantics.
- **New `.asking-user` marker for interactive dialogue state.** Parallels `.question-gate` in the opposite direction. `PostToolUse:AskUserQuestion` (`question_answered.py`) writes the marker unconditionally; `UserPromptSubmit` (`user_prompt_log.py`) clears it via `marker_consume`. Both gated behind `is_xp_agent` so only main-agent activity affects the marker. `sprint_stop_gate._deferred()` checks the marker first (cheapest check) alongside existing review-cycle and teammates deferrals. The fix is in the generic `_deferred()` path, so it resolves the same pattern for older plugin versions that still have sprint-retro in the Stop cascade.

### Migration
- The 4 historical superseded-decision false positives (`10cade72`, `725f1b02`, `b18a56a6`, `13eb9e42`) were resolved post-commit via `append.sh` with `metadata.resolves`. Under the new skip-2 rule their topics (`kickoff-redesign`, `retro-try-answer-recording`, `retro-try-adopted`, `retro-try-topic-validation`) are marked as "accepted as additive" — pattern #5 won't re-fire on them.

### Stats
- 1460 tests (all passing) — 30 new tests: 6 for `digest.resolutions`, 9 for `try_status` annotation + legacy shape compat, 8 for `metadata.supersedes` + resolved-topic acceptance, 7 for the `.asking-user` marker write/clear/defer cycle.

## v2.0.13 — Move Sprint Retro to Session Start

### Fixed
- **Sprint-retro watermark poisoning.** `save_retrospective.py` wrote `type: "retrospective"` events for both session and sprint retros, and the session-start watermark scanner (`_find_unanalyzed_start`) stopped at any retro regardless of kind. A sprint retro at end of session silently starved the next session's regular retro (empirically verified: 473 events, last retro at line 472, 1 unanalyzed → below threshold → retro skipped). Retrospective events now carry `metadata.action` (`session_retro_done` vs `sprint_retro_done`) so the scanner only stops at session retros. Legacy retros without the discriminator are treated as session retros for backwards compat.

### Architecture
- **Sprint retro runs at session start**, not end of session. Previously `sprint_stop_gate.py` had a 3-step cascade (accept → sprint-review → sprint-retro) that blocked Stop until the user ran `/xp-run-sprint-retro`. Now the cascade ends at sprint-review. At the next `SessionStart`, `retrospective.py` checks for a dangling `sprint_end` event with no matching `sprint_retro_done` and branches to sprint-retro prep, writing `.sprint-retro-input.json` instead of `.retro-input.json`. `check_session_needs.sh` reports `SPRINT_RETRO_NEEDED` vs `RETRO_NEEDED`; `xp-kickoff` Step 1 invokes the right skill. Sprint retro leverages the same session-start retro-prep infrastructure.
- **New `scripts/sprint_retro_detection.py`** — `_needs_sprint_retro(events)` and `maybe_run_sprint_retro_branch(smm_dir, events)` handle the detection + prep short-circuit. Kept out of `retrospective.py` to stay under the 500-line cap. Scoped by `sprint_id`: the most recent `sprint_end` is the candidate; if a newer `sprint_start` follows (abandoned sprint), detection returns None and the session retro handles the events.
- **`prepare_sprint_retro_data.py` relocated** from `skills/xp-run-sprint-retro/scripts/` to `scripts/` so the SessionStart hook can import it. Skill preload remains as an idempotent fallback that emits the existing file's path when SessionStart has already prepared it.
- **`sprint_retro_done` status events carry `sprint_id`** — required by detection scoping. `_handle_sprint_retro_done` reads `sprint.md` via `sprint_parser`, mirrors `_handle_sprint_review_done` fallback.
- **Sprint-id-paired compaction retention** — `compact.py _classify_pre_watermark` retains `sprint_retro_done` events whose `sprint_id` matches a retained `sprint_end`. Without this, a stale retro_done would be archived and detection would incorrectly re-fire after compaction.
- **Reverses decision `62a35600`** from v2.0.12 ("sprint retro replacing session retro at sprint boundary is out of scope"). That reasoning was backwards — shared prep is exactly why session-start placement is clean.

### Removed
- `_RETRO_MESSAGE` and `_SPRINT_RETRO_NUDGE` constants from `sprint_stop_gate.py` / `subagent_stop.py` — cascade no longer nudges for retro at Stop.
- `_scan_sprint_lifecycle_events` helper — replaced by simpler `_has_sprint_end_event` (no more dead `has_retro_done` tracking).

### Stats
- 1430 tests (all passing) — 26 new tests covering watermark filter, detection logic, prep-script relocation, idempotence, schema equivalence, wiring, kickoff branching, cascade simplification, and compaction retention.

## v2.0.12 — Replace PostToolUse:Skill with Reliable Signals

### Fixed
- **Sprint lifecycle nudges now fire reliably.** `PostToolUse:Skill` fires at unpredictable times — sometimes when the Skill tool loads its content (before any work happens), sometimes after. For inline skills like `/xp-accept` this meant the old `accept_done.py` nudge fired ~5 minutes BEFORE stories were actually marked done, so it never saw the completed sprint and never suggested `/xp-sprint-review`. Every critical state transition now uses a reliable trigger.
- **SessionEnd hook race condition** — Changed `session_end.py` to `async: false` so the event write completes before the process exits. Fixes the oscillating `final_status_recorded` flag that had persisted for 9+ sessions.

### Architecture
- **Unified Stop gate cascade** — New `sprint_stop_gate.py` replaces `accept_gate.py` with a single Stop hook that handles the full sprint lifecycle: in-progress + accept marker → run `/xp-accept`, sprint complete + no sprint_end → run `/xp-sprint-review`, sprint_end + no retro_done → run `/xp-run-sprint-retro`. Common deferral logic (review cycle active, teammates active) shared across all three states.
- **Forked subagent completion via SubagentStop** — New handlers in `subagent_stop.py` (`_handle_housekeeping_done`, `_handle_sprint_review_done`, `_handle_sprint_retro_done`) run BEFORE the is_xp_agent skip, same pattern as `_update_review_cycle_flags`. Replaces `kickoff_done.py` and `sprint_review_done.py`.
- **File-write triggers for inline skills** — `save_smm.py` now calls `compact.compact_after_curation()` directly; `save_sprint.py` handles the acceptance flow (clear `.accept` marker, record `iteration_complete` event, nudge sprint-review); `save_product_spec.py` clears `.needs-product-spec`. Covers both forked and inline execution paths.
- **Shared marker name constants** — New `smm/marker_names.py` module with zero imports, importable from both `scripts/` and `skills/*/scripts/` across the sys.path boundary. Eliminates filename drift.
- **Status event action discriminators** — `STATUS_ACTION_ITERATION_COMPLETE` and `STATUS_ACTION_SPRINT_RETRO_DONE` in `event_schema.py` alongside `SPRINT_ACTION_END`. New events use canonical agent_ids + `metadata.action` instead of non-standard agent_id substrings.

### Removed
- `scripts/kickoff_done.py` — logic moved to `subagent_stop._handle_housekeeping_done` + `save_smm.py` compaction
- `scripts/accept_done.py` — logic moved to `save_sprint.py` acceptance flow
- `scripts/accept_gate.py` — replaced by `sprint_stop_gate.py`
- `scripts/sprint_review_done.py` — logic moved to `subagent_stop._handle_sprint_review_done`

### Stats
- 1401 tests (all passing) — 15 new cascade tests, 18 handler tests, 8 accept-flow tests, 2 compaction tests

## v2.0.11 — Security Reviewer Simplification & Skill Guard Consistency

### Fixed
- **Security reviewer no longer triages** — Removed diff preloading and triage decision entirely. The built-in `/security-review` command does its own diff analysis; the agent just invokes it and records the result. Fixes the root cause of security review being skipped (agent would read diff, decide it was trivial, skip the review).
- **Simplified security reviewer agent** — Reduced from Read/Grep/Glob/Bash/Skill to just Bash/Skill. No file reading needed since `/security-review` is self-contained.

### Improved
- **Consistent forked skill guards** — All 7 SKILL.md bodies now use identical pattern: "This skill should run as a forked subagent. Your agent definition contains all instructions — follow them, record the result, and report back." Generic "do not do this work yourself" guard reinforces the agent can't proceed without the subagent.
- **Security triage preload minimized** — Only outputs `SMM_DIR` and writes triage marker. No diff file, no XP values (injected via SubagentStart).

### Stats
- 1397 tests (all passing)

## v2.0.10 — File-Based Preloads & Universal XP Values

### Architecture
- **File-based preloads for all forked skills** — Preloads now output file paths (`SMM_FILE=`, `PLAN_FILE=`, `SPRINT_FILE=`, `DIFF_FILE=`) instead of dumping full content to stdout. Subagents read files via Read tool. Reduces main agent context bloat when `context: fork` fires in the main agent.
- **Universal XP values via SubagentStart** — XP values (~250 tokens) injected for ALL subagents (xp-*, Explore, Plan, teammates, general-purpose). Removed `dump_values` from all 6 forked preloads. Clean separation: preloads provide skill-specific data paths, SubagentStart provides universal values.
- **Security triage diff to file** — `dump_diff full` redirected to `.security-triage-diff.txt`; agent reads via `DIFF_FILE=` path.

### Improved
- **XP Values rewritten** — Tighter, directive language (~250 tokens, down from ~470). Values address the agent directly as guideposts. Value priority reordered: Honesty > Courage > Simplicity > Feedback > Communication.
- **Agent definitions updated** — All 7 forked agents updated to read files via Read tool instead of assuming content is in context. Consistent "XP Values — injected automatically" across all agents.

### New Tests
- `test_review_plan.py` — 7 tests for path-based preload output
- `test_security_triage.py` — 5 tests for diff-to-file preload

### Stats
- 1398 tests (all passing)

## v2.0.9 — Critical Debt Resolution & V2 Testing Fixes

### Fixed (10-session and 8-session critical debt)
- **Topic validation** — `event_schema.py` now rejects bare `retro-try-adopted` topic at write time. Decisions must use `retro-try-<slug>` format (e.g., `retro-try-answer-recording`). Prevents superseded-decision concern noise from generic topic collisions. (10 sessions deferred)
- **Unified question resolution** — Questions can now be resolved via `metadata.resolves` (same as goals, concerns, debt), not just answer events. Answer events still work and take precedence. Fixes 8-session streak of `questions_answered=0`. (8 sessions deferred)

### Improved
- **Housekeeping summary visibility** — Kickoff skill now explicitly instructs the agent to wait for housekeeping (do not background) and display the housekeeper's structured summary (Added/Removed/Resolved/Health) to the user.
- **Housekeeper return format** — Structured summary template ensures consistent output the lead agent can relay directly.
- **Review cycle threshold lowered** — `REVIEW_CYCLE_THRESHOLD` reduced from 3 to 2 code files. One production file + its test file now triggers the full review cycle (`/simplify` → `/xp-quality-review` → `/xp-security-triage`).
- **Removed trivial constant test** — Deleted `TestReviewCycleThreshold` (asserted a constant's value).

### Fixed
- **Forked skills executing inline** — All 7 forked skill SKILL.md bodies replaced with dual-audience pattern: instructions for the forked agent to follow its agent definition, and an explicit "do not do this yourself" guard for the main agent. Prevents the main agent from executing curation/review/triage logic inline when `context: fork` isn't enforced by the platform.

### Docs
- **Spawn team refactor** — Three spawn modes (Sequential, Agent Teams, Worktree Subagents) with mode selection heuristic based on file domain analysis. Community findings documented: Agent Teams + worktree isolation bug (anthropics/claude-code#33045), WorktreeCreate stdout fragility, shared SMM across worktrees, branch base configuration.

### Stats
- 1386 tests (all passing, +2 new)

## v2.0.8 — Token Optimization (Phases 3-5)

Complete token optimization across all skill preloads, hook injections, and data files. Every injection point audited and optimized.

### Phase 3: Inline Skill Preloads (M10-M17)
- **Path-based preloads** — product-spec, sprint-start, and accept preloads now output file paths (`PRODUCT_SPEC=`, `SPRINT_FILE=`) instead of embedding full content. Agents read on demand via Read tool.
- **Kickoff SMM read** — Kickoff reads SMM before product-spec/sprint-start steps so inline skills have constraint/wisdom context without duplicate injection.
- **Merged xp-smm-protocol into PROCESS_GUIDE.md** — Full event recording protocol (event types, pillars, priority guide, working_on, references, common patterns) merged into process guide. Removed xp-smm-protocol skill entirely. All plugin users get event recording guidance without needing CLAUDE.md.
- **Added Project Files section** to PROCESS_GUIDE.md — documents SMM_DIR, sprint.md, product_spec.md locations so agent can find them after compaction.

### Phase 4: Hook Injection Audits (M18-M29)
- **Removed sprint.md from compact re-injection** (M18) — SMM Sprint pillar summary is sufficient; agent reads full sprint on demand. Saves ~700-1,700 tokens per compact.
- **Filtered test/lint concerns from prompt nuggets** (M19) — Test failures and lint errors are already visible in tool output. Nuggets now only surface concerns the agent hasn't seen (commit size, plan review concerns, debt).
- **Centralized concern prefix constants** — `TEST_COMMAND_FAILED_PREFIX`, `TEST_FAILURES_PREFIX`, `LINT_RESOLVED_PREFIX` added to concerns.py. Producers and filters use shared constants.
- **M20-M29 confirmed optimal** — All hook injections verified minimal and appropriately gated. No unnecessary injections found.

### Phase 5: Data Optimization (M30-M31)
- **Fixed TDD tracker false positives** (M31) — `check_tdd_order()` now skips non-code files (md, json, yaml, etc.) via `security.is_code_file()`. No more false nudges on product_spec.md, sprint.md, or plan files.
- **Fixed dotfile classification bug** — `.gitignore`, `.env`, `.dockerignore`, `.editorconfig`, `.prettierignore`, `.eslintignore` were misclassified as code because `Path(".gitignore").suffix == ""`. Moved from `_NON_CODE_SUFFIXES` to `_NON_CODE_NAMES`.
- **Sprint input JSON** (M30) — Already completed in Phase 2 (M4/M5). Both prep scripts use `sprint_md_path` references.

### Other Improvements
- **Consolidated dump_diff helper** — `dump_diff` and `get_changed_files` in `_preload_base.sh` now correctly show uncommitted changes (`git diff HEAD` + untracked) instead of previous commit (`HEAD~1`). Security triage's 30 lines of inline git commands replaced with `dump_diff full`.
- **Removed dead `dump_guide()` function** from `_preload_base.sh`.
- **Fixed `count_sprint_status` bug** — `grep -c || echo 0` produced `"0\n0"` when count was 0. Fixed with `|| true` + default.
- **Added Design Quality section** to xp-plan-reviewer checklist — DRY, SRP, unnecessary abstraction, over-engineering.
- **Simplified `post_tool_exit_plan.py`** — replaced manual JSON with `_common.hook_output()`.
- **Expanded `is_code_file` test coverage** — 25+ languages (Python, JS/TS, Go, Rust, Java, Kotlin, Scala, Ruby, C/C++, C#, Swift, PHP, Dart, Elixir, Shell) + non-code exclusions.
- **Consolidated test fixtures** — `_run_preload()` extracted to `_IntegrationTestCase` (removed from 11 files). `SPRINT_MIXED` and `SPRINT_MIXED_IN_PROGRESS` added to conftest.py (removed from 4 files). Net -250 lines of test code.
- **Removed SKILLS_TEXT** from session_start.py — no longer needed after xp-smm-protocol merge.

### Stats
- 1380 tests (all passing, +34 new)
- 13 skills (was 14 — xp-smm-protocol removed)
- Token optimization plan: all 31 milestones complete

## v2.0.7 — Accept Gate Root Cause Fix & Post-Team Checklist

### Fixed
- **Accept gate permanent deferral** — Review cycle marker persists after commit with all flags reset to false. Gate was checking `marker_exists` (always true) instead of whether any review flag is actively set. Root cause of accept never blocking after team iterations.

### Improved
- **Post-team checklist in spawn-team output** — Spawn instructions now include explicit steps for after teammates finish: commit work, run `/xp-accept`, then `/xp-sprint-review` if all stories complete.

### Stats
- 1346 tests (all passing)

## v2.0.6 — Pyright, Language Coverage & SMM Seed Improvements

### Added
- **Pyright in lefthook pipeline** — Basic type checking for scripts/ and smm/. Runs in parallel with other pre-commit checks (~1s).
- **Separate linter and formatter detection** — SMM seed now distinguishes linting (catches bugs) from formatting (consistent style) with separate constraints and risk messages.
- **18 linter ecosystems** — Python (ruff, flake8, pylint, mypy), JS/TS (eslint), Rust (clippy), Go (golangci-lint), Ruby (rubocop), C/C++/Objective-C (clang-tidy), Java (checkstyle, pmd, spotbugs), Kotlin (detekt, ktlint), PHP (phpcs, phpstan), Dart/Flutter, Elixir (.credo.exs), C# (stylecop), Swift (swiftlint), Scala (scalafix), Lua (luacheck), Haskell (hlint), plus Gradle content checks and biome.
- **16 formatter ecosystems** — Python (ruff format), JS/TS (prettier), Rust (rustfmt), C/C++/Objective-C (clang-format), PHP (php-cs-fixer), Ruby (rubocop), Swift (swift-format), Kotlin (editorconfig), Elixir (.formatter.exs), Scala (scalafmt), Lua (stylua), Haskell (ormolu/fourmolu), Go/Dart/Zig (built-in via source detection), plus Gradle spotless and biome.
- **22 test patterns** — Added Objective-C/C++ (XCTest), Lua, Scala, Haskell, Zig.
- **Design principles in seed wisdom** — SRP/DRY, fail fast/fail loud, descriptive naming, test behavior not implementation.
- **Code smells step** in quality review skill.

### Fixed
- **10 Pyright type errors** — isinstance narrowing for marker_read returns in pre_tool_write.py, kickoff_gate.py, and TypeError guard in markers.py.

### Stats
- 1345 tests (all passing)

## v2.0.5 — Accept Gate, Preload Dedup & Agent Teams Flow

### Fixed
- **Accept gate defers for active teammates** — Checks coordination.json for running agents. No more false blocking when main agent waits for background teammates.
- **Teammate race condition** — Teammates registered in coordination.json at SubagentStart spawn, closing the window before first file write.
- **Accept gate defers during review cycle** — No longer blocks when /simplify spawns background agents.
- **Forked skill permissions** — Added missing `Bash(*/skills/*/scripts/*)` to xp-spawn-team, xp-sprint-review, xp-sprint-retro. Fixes preload permission errors.
- **Session-end final_status** — session_end event always records true. Stop warning nudges user-facing summary. Removed from retro agent checks.
- **Retro agent file management** — Removed misleading "cleans up .retro-input.json" instruction.

### Improved
- **Preload deduplication** — Added xp-spawn-team, xp-sprint-reviewer, xp-sprint-retro to SubagentStart dispatch table. Removed duplicate SMM/guide/sprint dumps from 4 preload scripts (spawn-team, sprint-review, sprint-retro, review-plan).
- **Kickoff story branching** — Step 6 now evaluates story count and dependencies: 1 story → solo, 2+ independent → spawn team, 2+ dependent → plan first in order.
- **Teammate guide** — Corrected review cycle instructions (teammates must invoke skills themselves).

### Stats
- 1345 tests (all passing)

## v2.0.4 — Guides, SMM Seed & Quality Review Updates

### Improved
- **Behavioral guide updated for v2** — Added sprint iteration flow (product-spec, sprint-start, accept, sprint-review, sprint-retro), Agent Teams (spawn-team, teammate guide), and accept gate to stop hook section. 87 lines total.
- **Teammate guide** — Fixed incorrect "automatic" review cycle wording. Teammates must invoke `/simplify` → `/xp-quality-review` → `/xp-security-triage` → commit themselves; hooks nudge but don't run skills for them.
- **SMM seed constraints** — File size limits now explicit: target 300 lines, max 500.
- **SMM seed wisdom** — Added design principles: SRP/DRY for file organization, fail fast/fail loud, descriptive naming over comments, test behavior at boundaries not implementation.
- **Quality review** — New Step 5 code smells quick scan catches what /simplify missed: functions doing too much, deep nesting, magic values, unclear names, copy-paste patterns.

### Stats
- 1345 tests (all passing)

## v2.0.3 — Accept Gate & Agent Behavior Fixes

### Fixed
- **Accept gate defers during review cycle** — No longer blocks when /simplify spawns background agents and the main agent pauses. Checks for active review cycle marker.
- **Retro agent file management** — Removed "Cleans up .retro-input.json" instruction that caused the agent to improvise an `mv` command. Cleanup is handled by save_retrospective.py.

### Stats
- 1345 tests (all passing)

## v2.0.2 — Stop Hook Schema Fix

### Fixed
- **Session-end warning Stop hook** — Was outputting `hookSpecificOutput`/`additionalContext` which Stop hooks don't support. Now uses top-level `reason` field per the Stop hook schema.

### Stats
- 1344 tests (all passing)

## v2.0.1 — v2 Testing Fixes

### Fixed
- **Accept gate premature blocking** — Inverted accept marker semantics: `.accept` now means "needs acceptance" (set by pre_tool_write on code writes, cleared by accept_done). Fixes gate blocking after kickoff when no work had been done.
- **Kickoff story selection after sprint creation** — Step 5 now handles sprints created during Step 3 (stale preload data). Previously fell through to goal collection.
- **Kickoff Step 6** — Agent now enters plan mode immediately after story selection instead of stopping.

### Improved
- **Product spec source references** — Skill now includes `Sources:` lines pointing back to original docs when bootstrapping from existing documentation.
- **Sprint story source references** — Stories include `Source:` field linking to product_spec.md feature. Traceable chain: story → product_spec → source docs.
- **Sprint confirmation UX** — Compact summary table in AskUserQuestion preview (avoids truncation). Full sprint.md and product_spec.md output inline after writing.
- **Story title flexibility** — Technical titles allowed when backing docs exist; user-story format for conversation-built specs.
- **Sprint test fixtures** — Deduplicated to conftest.py shared module.

### Stats
- 1344 tests (all passing)
- 7 commits since v2.0.0

## v2.0.0 — Agent Teams & v2 Complete (M10–M16)

### Added
- **M10: Tiered sprint context injection** — SubagentStart dispatch table routes xp-* agents, Explore/Plan agents, and sprint-context agents to different injection tiers. Sprint data injected for sprint-aware subagents.
- **M11: Sprint Review** — `/xp-sprint-review` skill with agent, preload, and `sprint_review_done.py` hook. `prepare_review_data()` assembles sprint data for review. Hook records sprint end event with deterministic velocity.
- **M12: Sprint Retrospective** — `/xp-sprint-retro` skill with agent and preload. Sprint retro prep script collects session retro history. `save_retrospective.py` parameterized for both session and sprint retros. Per-story data with sizes added to sprint parser.
- **M13: Teammate TDD Hooks** — `TeammateIdle` and `TaskCompleted` hooks enforce TDD for Agent Team teammates. Shared `tdd_check.py` module extracted. `get_validated_smm_dir()` helper adopted across all 22 hook scripts.
- **M14: Teammate Behavioral Guide** — `is_teammate_by_agent_type()` detection function (custom agent_type, excludes built-in and xp-*). `TEAMMATE_GUIDE.md` injected via SubagentStart for detected teammates.
- **M15: Spawn Team Skill** — `/xp-spawn-team` skill with agent and preload. Domain analysis and team sizing delegated to LLM judgment (no prep script).
- **M16: v2 Documentation** — Architecture, SMM design, and CLAUDE.md updated for v2. Iteration/session vocabulary corrected. `iteration_complete` marker added. `iterations_completed` in session stats for retrospective.
- **v2 test plan** — Comprehensive test plan for v2 plugin validation.

### Fixed
- **Prompt nugget** — Resolved concerns no longer shown as new in prompt nuggets.
- **Assigned stories metadata** — Removed undocumented `metadata.assigned_stories` dependency from teammate injection. Teammates get story context from spawn prompt.
- **Iteration/session vocabulary** — Fixed conflation of iterations and sessions throughout docs and code. Multiple iterations can occur within a single session.
- **Session-end checklist** — Added nudge on git push for unresolved items.
- **PLUGIN_TOOLS.md** — Consolidated platform findings into existing sections instead of appending.

### Stats
- 1337 tests (all passing)
- M10–M16 shipped — All v2 milestones complete
- 27 commits since v1.13.0

## v1.13.0 — M9: Sprint Pillar in Housekeeping

### Added
- **M9: Sprint pillar in curated SMM** — Housekeeping now curates a Sprint section showing sprint goal, story counts by status, and blockers. Sprint appears first in the SMM for immediate visibility.
- **M9: `sprint_parser.py`** — New `smm/` module that parses sprint.md into structured data (sprint_id, goal, started, stories_by_status, blockers). Used by `prepare_curation_data()`.
- **M9: Sprint in curation preload** — `prepare_curation_data()` returns a `sprint` key alongside existing pillars. Missing/malformed sprint.md returns empty data gracefully.
- **Session-end soft warning** — New `session_end_warning.py` Stop hook surfaces unresolved concerns and missing final status as `additionalContext` before session ends. Soft warning, not a block.
- **Shared utilities** — `count_unresolved_concerns()` and `has_final_status()` extracted to `_common.py`, deduplicating `session_end.py`.

### Fixed
- **Triage coverage measurement** — `bash_post_tool.py` now adds `metadata.code_commit` to Committed events. Retrospective skips non-code commits (docs, config) when counting untriaged commits, fixing the false ~43% coverage gap in high-commit sessions.
- **Premature marker consumption** — Removed `pre_tool_bash.py` lines that consumed `.security-triaged` marker for non-code commits before the commit succeeded. Marker consumption now happens exclusively in `bash_post_tool.py` after commit success.
- **Integrity test coverage** — `test_plugin_integrity.py` now covers all 12 shipped skills via `_ALL_SKILL_NAMES` and `_CONTENT_SKILL_NAMES` constants.

### Stats
- 1215 tests (all passing)
- M9 shipped — All 7 acceptance criteria met
- 3 retro Try items addressed (triage root cause, session-end warning, integrity debt)

## v1.12.0 — M8c: Accept Skill + Gate

### Added
- **M8c: `/xp-accept` skill** — Guides lead through acceptance criteria verification for in-progress stories. Presents criteria, supports e2e test execution, marks stories done or deferred, updates sprint.md.
- **M8c: `accept_gate.py`** — Stop hook that blocks when sprint.md has in-progress stories and accept marker not set. Graceful degradation for missing/corrupt sprint.md.
- **M8c: `accept_done.py`** — PostToolUse:Skill hook that sets accept marker when /xp-accept completes. Detects sprint completion (all done/deferred) and nudges /xp-sprint-review.
- **M8c: `is_sprint_complete()` + `has_ready_stories()`** — Pure helpers in sprint_state.py for accept gate and done hooks.
- **M8c: Accept marker lifecycle** — Cleared by session_start (M8a), set by accept_done, read by accept_gate.

### Stats
- 1187 tests (all passing)
- M8c shipped — Sprint iteration loop complete (M8a detection → M8b kickoff → M8c accept)

## v1.11.0 — M8b: Sprint-Aware Kickoff Skill

### Added
- **M8b: Sprint-aware kickoff** — `/xp-kickoff` SKILL.md rewritten with 6-step flow: retro → product spec check → sprint check → housekeeping → story selection. Reads M8a markers to orchestrate sprint setup.
- **M8b: Sprint-aware preload** — `check_session_needs.sh` outputs `NEEDS_PRODUCT_SPEC`, `NEEDS_SPRINT`, and `SPRINT_ACTIVE` sections based on markers and sprint.md state.
- **M8b: Story selection** — When sprint is active, kickoff displays ready stories and lets the lead pick stories to mark `in-progress`, replacing goal collection.
- **M8b: Backward compatibility** — First-time projects without sprint files fall back to question triage + goal collection (existing behavior).

### Stats
- 1158 tests (all passing)
- M8b shipped — M8c (Accept Skill + Gate) is next

## v1.10.0 — M7/M8a: Sprint Start Skill & Sprint State Detection

### Added
- **M7: `/xp-sprint-start` skill** — Conversation-driven sprint planning skill that decomposes product_spec.md features into user stories with IDs, sizes, dependencies, and acceptance criteria. Customer confirms scope before writing sprint.md.
- **M7: `save_sprint.py`** — Atomic writer for sprint.md (stdin, symlink rejection, tempfile + rename).
- **M7: Sprint preload** — `preload.sh` detects existing sprint state, deferred stories, and calculates next sprint ID.
- **M8a: Sprint state detection** — `session_start.py` writes `.needs-product-spec` and `.needs-sprint` markers on startup when resources are missing. `.accept` marker cleared for new iterations.
- **M8a: `sprint_state.py`** — Pure helper module for sprint/product_spec state detection (has_active_stories, has_in_progress_stories, read_sprint_content, product_spec_exists).
- **M8a: Enhanced kickoff gate** — `kickoff_gate.py` block message now includes resource-specific guidance (product spec or sprint needed).
- **M8a: Sprint validation nudge** — `kickoff_done.py` nudges when sprint.md exists but no stories are in-progress after kickoff.
- **M8a: New markers** — `NEEDS_PRODUCT_SPEC`, `NEEDS_SPRINT`, `ACCEPT` marker definitions in `markers.py`.

### Stats
- 1145 tests (all passing)
- M7 and M8a shipped — M8b (Sprint-Aware Kickoff) is next

## v1.9.0 — M5/M6: Sprint Events & Product Spec Skill

### Added
- **M5: Sprint event type** — New `sprint` event type in `event_schema.py` and `schema.json` with `sprint_id`, `action` (start/end), optional `goal` and `velocity` metadata. Compaction rules retain active sprint starts and recently ended sprints.
- **M5: `EVENT_TYPE_*` constants** — All 15 event types now have named constants in `event_schema.py`. Production code uses constants; test fixtures keep string literals.
- **M5: `_classify_pre_watermark()` extraction** — Refactored `compact.py` to extract retention classification into a focused helper, reducing `compact_after_curation()` complexity.
- **M6: `/xp-product-spec` skill** — Conversation-driven requirements gathering skill that creates/refines `product_spec.md` with `[planned]`/`[delivered]` feature markers. Supports create mode, update mode, and document ingestion.
- **M6: `save_product_spec.py`** — Atomic writer for `product_spec.md`, mirroring the `save_smm.py` pattern (stdin, symlink rejection, tempfile + rename).
- **M6: Product spec preload** — `preload.sh` detects existing spec (with planned/delivered counts) or indicates create mode.

### Fixed
- **Session aging duplication** — Extracted `sessions_since_event()` utility to `event_schema.py`, replacing 4 identical `bisect.bisect_right` patterns across `compact.py` and `materialize.py`.
- **Stale comments in compact.py** — Comments said "3 sessions" for thresholds that are actually `_ASSUMPTION_MAX_AGE` (5).

### Stats
- 1102 tests (all passing)
- M5 and M6 shipped — M7 (Sprint Start) is next on the critical path

## v1.5.14

### Fixed
- **Subagent cleanup on stop** — `SubagentStop` now clears `.coordination.json` entry and agent-scoped markers (TDD tracker, review cycle) when a subagent completes. Previously these lingered until the 30-minute staleness timeout or forever (markers had no expiry).
- **Session end marker cleanup** — `SessionEnd` now removes the main agent's TDD tracker, review cycle, and `.lint-warned` flag. Agent-scoped markers no longer accumulate across sessions.
- **Lint nudge instead of question event** — no-linter warning is now delivered as `additionalContext` (immediate nudge) instead of a question event in the SMM. Re-fires each session since `.lint-warned` is cleaned up at session end.
- **Lint nudge skips non-code files** — edits to `.md`, `.txt`, `.yml`, `.gitignore`, etc. no longer trigger the "no linter configured" nudge. Only files with lintable code extensions trigger it.

### Stats
- 1078 tests (all passing)

## v1.5.13

### Fixed
- **Cross-worktree path normalization** — `normalize_path()` now resolves non-existent files correctly across git worktrees. On macOS, `normpath` doesn't resolve symlinks (`/var` vs `/private/var`), so prefix stripping against `realpath(git_root)` failed silently. Fix: walk up to the nearest existing ancestor, resolve its symlinks, and retry. This makes `.coordination.json` conflict detection work across worktrees.

### Stats
- 1069 tests (all passing)

## v1.5.12

### Added
- **Security triage as forked subagent** — converted `/xp-security-triage` from inline skill to `context: fork` with a dedicated `xp-security-reviewer` agent. The subagent's sole job is to invoke `/security-review` — no classification needed since the commit gate already confirmed code files changed. Preload shows staged diffs, unstaged diffs, and new untracked files. Marker/flag flow unchanged — commit gate clears during preload as before.

### Stats
- 1062 tests (all passing)

## v1.5.11

### Added
- **Security triage subagent conversion** — initial conversion of `/xp-security-triage` to forked subagent architecture (M4b). Renamed agent to `xp-security-reviewer` and simplified instructions in v1.5.12.

### Stats
- 1062 tests (all passing)

## v1.5.10

### Fixed
- **Review cycle nudges now delivered to agent** — `review_cycle_done.py` was registered with `async: true`, which meant its `additionalContext` output (TaskCreate nudge after plan review, review cycle continuation nudges) was never seen by the agent. Removed `async: true` so nudges are delivered synchronously.

### Stats
- 1062 tests (all passing)

## v1.5.9

### Changed
- **TDD metric counts unique files, not raw writes** — `max_writes_without_test` replaced with `max_unique_files_without_test`. Multiple writes to the same file (normal iteration) no longer inflate the metric. On a real session: 6 → 4.
- **Seed SMM updated for commit-gated review cycle** — removed stale wisdom items that referenced old Stop-hook gates and pre-commit triage flow. Added correct review cycle sequence. Moved "small files" from wisdom to constraints.
- **Small files constraint** — "Small files — single responsibility, one concern per file" added to seed constraints alongside small commits and TDD.

- **Resolved concerns excluded from curation preload** — `prepare_curation_data()` now filters resolved concerns from `new_since_last_curation` and reports a count. Housekeeping preload dropped from 132KB to 61KB on a real session.

### Stats
- 1062 tests (all passing)

## v1.5.8

### Changed
- **Resolved concerns excluded from retro input** — resolved concerns are rolled up to a count (`resolved_concern_count`) instead of including full text in signal_events and concern_groups. On a real session with 60 concerns (48 resolved), retro-input.json dropped from 155KB to 21KB (86% reduction).
- **Lint concerns are concise** — concern events now record `"Lint errors in app.py: 3 errors (F401, I001)"` instead of dumping full linter output. Supports ruff, pylint, flake8, and eslint (including scoped plugin rules like `@typescript-eslint/no-explicit-any`). The agent already sees full output via additionalContext.
- **Test failure concerns are concise** — concern events now record `"Test command failed (pytest): Exit code 1"` instead of full traceback. Works for all six supported test frameworks.

### Stats
- 1055 tests (all passing)

## v1.5.7

### Changed
- **Task creation nudge after plan review** — `review_cycle_done.py` now detects `/xp-review-plan` completion and injects `additionalContext` telling the agent to use `TaskCreate` to break the plan into tasks before implementing. Each task should be one red-green-commit cycle.
- **Removed task decomposition from plan reviewer** — section 7 (task decomposition) removed from `xp-plan-reviewer.md`. Plans already have steps; the plan reviewer's job is catching strategic issues, not re-deriving tasks. Task creation is now nudged at the right moment (after review) rather than embedded in review prose.

### Stats
- 1043 tests (all passing)

## v1.5.6

### Fixed
- **Post-green context confirms prior failure resolution** — when tests pass after a prior failure, `additionalContext` now says "All prior test failures resolved — tests are green." Prevents the agent from reacting to stale failure context in its conversation history.
- **`resolve_concerns()` returns bool** — callers can now check whether any concerns were actually resolved.

### Stats
- 1040 tests (all passing)

## v1.5.5

### Added
- **Quality review resolves addressed plan review concerns** — new Step 3 in `/xp-quality-review` checks open plan reviewer concerns against code changes and resolves ones that were addressed. Preload now includes `open_plan_concerns.py` output alongside debt. Prevents plan review concerns from accumulating as noise when the underlying issues were fixed.

### Stats
- 1039 tests (all passing)

## v1.5.4

### Fixed
- **Security triage always runs /security-review for code changes** — replaced judgment-based classification (which the agent always skipped) with a simple rule: any commit with code files runs `/security-review`.
- **Security triage event is neutral** — records "Security triage started — reviewing staged changes" instead of pre-emptively claiming "changes classified as non-security-relevant."
- **Triage-only no longer records false "review complete" event** — `review_cycle_done.py` only records "Security review complete" when `/security-review` (the built-in) actually ran, not when `/xp-security-triage` completed without it.
- **Removed phantom `xp-security-review` agent_id** — events now use actual skill names: `"xp-security-triage"` for triage, `"security-review"` for the built-in review command.
- **Retro classification updated** — `_SECURITY_TRIAGE_RE` matches new "started" wording, `_TEST_RUN_RE` matches neutral "Tests ran" format.

### Stats
- 1039 tests (all passing)

## v1.5.2

### Changed
- **Plan reviewer recommends task decomposition** — new checklist item 7 outputs a structured task list with dependencies and parallel groups. Each task identifies files touched, depends-on relationships, and parallelization opportunities. The main agent uses this to create its task list immediately after review. Foundational for v2 Agent Teams spawn-team analysis.
- **Linter detection walks from file directory** — `detect_linter_config()` starts from the file's parent directory instead of `cwd`, finding configs in subdirectories (e.g., `pyproject.toml` with `[tool.ruff]` in `apps/agent/`). Previously only found configs at or above the working directory.
- **Linter detection filters by file extension** — skips linters that can't handle the file type. A `.py` file in a project with both eslint and ruff now gets ruff, not eslint.

### Stats
- 1037 tests (all passing)

## v1.5.1

### Fixed
- **Linter detection walks from file directory** — `detect_linter_config()` now starts from the file's parent directory and walks up, not from `cwd`. Finds `pyproject.toml` with `[tool.ruff]` in subdirectories (e.g., `apps/agent/`). Previously only found configs at or above the working directory.
- **Linter detection filters by file extension** — skips linters that can't handle the file type. A `.py` file in a project with both eslint and ruff now gets ruff, not eslint.
- **Linter runs from correct cwd** — `run_linter()` passes `cwd` (git root) to `subprocess.run()`. Eliminates phantom `E902 No such file or directory` lint concerns that drowned real signals (~40 per session).
- **TDD stop gate recognizes fallback pass format** — `_TEST_PASS_RE` now matches `"Tests passed (framework)"` in addition to `"Tests: N passed, 0 failed"`. Prevents stale test concerns from blocking stop.
- **TDD stop gate skips resolved concerns** — `_find_last_test_signal()` now checks `compute_resolutions()` and ignores resolved test failure concerns.
- **Ambiguous test results no longer claim success** — when parser extracts 0 passed / 0 failed (truncated output, wrong directory), records `"Tests ran (framework) — counts not extracted"` instead of false `"Tests passed"`.

### Stats
- 1037 tests (all passing)

## v1.5.0

### Changed
- **Commit-after-green nudge** — `bash_post_tool.py` returns `additionalContext` after green tests when uncommitted code files exist: "Commit now to trigger the review cycle." Reinforces the red → green → commit → simplify rhythm.
- **Review cycle continuation nudges** — `review_cycle_done.py` returns next-step guidance after each review skill: `/simplify` → "Run /xp-quality-review", `/xp-quality-review` → "Run /xp-security-triage", `/xp-security-triage` → "Commit your changes now."
- **Seed SMM updated** — TDD constraint now reads "red, green, commit, refactor". New wisdom item: "Commit after every green test run — commits trigger /simplify and review gates."
- **Plan reviewer checks commit cadence** — section 2 split into 2a (tests before implementation) and 2b (commit cadence). Flags plans with multiple red/green cycles and no commits between them.

### Added
- **`get_uncommitted_code_files()`** in `commits.py` — checks staged + unstaged changes, filters to non-test code files. Used by the post-green nudge.

### Stats
- 1033 tests (all passing)

## v1.0.14

### Changed
- **Project-relative paths in events** — `normalize_path()` now strips the git root prefix, producing paths like `src/app.ts` instead of `/Users/paul/project/src/app.ts`. Reduces event log size (~40% smaller status events) and enables worktree-safe coordination for Agent Teams. Backward-compatible: old absolute paths in events are normalized to relative on read.
- **Retro-input slimmed** — customer_input signals truncated to 100 chars (was full prompts ~1k each). Concern groups store key+count+ids instead of full event objects. Reduces `.retro-input.json` from ~50k to ~33k on real sessions.
- **Lint concern matching handles mixed path formats** — new `lint_concern_matches()` resolves concerns correctly during the absolute-to-relative path transition.

### Added
- **GitHub Actions CI** — runs full test suite on Python 3.10 and 3.12, plus ruff lint. Safety net for cases where lefthook is bypassed.
- **`resolve_git_root(cwd)`** — cached per-cwd helper for git root resolution. Replaces ad-hoc `git rev-parse --show-toplevel` calls in lint_check.py and bash_post_tool.py.

### Fixed
- **Stale goal gate tests removed** — two tests referenced `_BLOCK_GOALS` and `_GOAL_NUDGE_TRACKER` which were removed in v1.0.13 but the tests were not cleaned up.

### Stats
- 975 tests (all passing)

## v1.0.13

### Removed
- **Goal collection gate in user_prompt_log.py** — blocked `/xp-kickoff` on fresh projects because no goals existed yet. Redundant: kickoff includes goal collection as step 3, and the kickoff gate already blocks non-kickoff prompts.

### Stats
- 965 tests (all passing)

## v1.0.12

### Added
- **Honesty signals in retro digest** — sequence-based analysis: longest streak of production code writes without a test run, commits without security triage, code-write-to-concern ratio, assumption count, and final status check. Gives the retro concrete data to flag honesty gaps.
- **Retro agent honesty checklist** — specific thresholds: 5+ writes without test = Fix, any commit without triage = Fix, 10+ code writes with 0 concerns = question, 0 assumptions with significant work = Fix.

### Changed
- **TDD streak excludes test file writes** — writing test files before running them isn't a TDD gap. `max_writes_without_test` now tracks only production code writes.
- **README honesty section updated** — replaced vague "analyzes honesty patterns" with concrete signals we actually provide.

### Stats
- 965 tests (all passing)

## v1.0.11

### Fixed
- **Test run regex missed "Tests passed" format** — the status classifier only matched `Tests: N passed` but not `Tests passed (framework)` (our new format from v1.0.6). Retro falsely reported "zero test runs" for sessions that had tests passing.
- **Security triage invisible to retro** — triage status events were classified as "other" and the retro couldn't see them. Now tracked as a separate `security_triages` count.

### Added
- **Richer status classification for retro digest** — now tracks commits, quality reviews, and lint events alongside file writes, test runs, and security triages. Gives the retro accurate session activity data.
- **SessionEnd compaction** — event log is compacted at session end in addition to kickoff and context compaction. Reduces the one-session lag for cleanup.

### Removed
- Unused `_MAX_STATUS_SAMPLES` constant and status sample collection (samples were already dropped at write time).

### Stats
- 965 tests (all passing)

## v1.0.10

### Changed
- **Prompt nuggets: prioritized, fewer, longer** — top 3 signals by priority (concern > question > assumption > discovery > debt > decision) instead of 5 most recent. Truncation increased from 60 to 120 chars. Added `assumption` and `discovery` types, removed `goal` (already in SMM Intent). Most recent wins within same priority.

### Stats
- 965 tests (all passing)

## v1.0.9

### Changed
- **Security triage: single preload does everything** — merged diff display, marker write, and event logging into one `!` preload command. Running the skill IS the triage — the preload shows the diff and clears the gate, the agent's job is just to decide if `/security-review` is also needed.

### Stats
- 962 tests (all passing)

## v1.0.8

### Fixed
- **Security triage marker validates JSON content** — `security_triaged_exists` now verifies the marker contains valid JSON with a `ts` field, not just that the file exists. Prevents the agent from bypassing triage by touching the file directly instead of running `mark_triaged.py`.

### Changed
- **Cleaned up allowed-tools** — removed unnecessary entries from xp-run-retrospective (materialize.py, direct save_retrospective.py) and xp-security-triage (git diff --cached, handled by preload).

### Stats
- 962 tests (all passing)

## v1.0.7

### Changed
- **Assumptions and questions age after 5 sessions** — previously retained forever if unresolved, causing event log bloat (22 unresolved assumptions in one project). Housekeeping now instructed to resolve them when curating into Risks. Compaction ages them out after 5 sessions as a safety net.

### Stats
- 962 tests (all passing)

## v1.0.6

### Changed
- **Retro preload slimmed** — outputs just paths + behavioral guide (~500 tokens). Subagent reads `.retro-input.json` itself. Data slimmed at write time (no `events_since_last_retro`, signal events trimmed, status samples dropped). Saves ~30KB in main agent context when fork fails.
- **init.sh fallback path corrected** — default changed from `~/.claude/xp-agents` to `~/.claude/plugins/data/xp-agents-xp-agents` (matches actual platform plugin data path).

### Fixed
- **Test parser "0 passed, 0 failed"** — when test output is truncated and the parser can't extract counts, records "Tests passed (framework)" instead of the misleading zero counts. Exit 0 means tests passed.

### Stats
- 962 tests (all passing)

## v1.0.5

### Changed
- **All skill/agent instructions use `--smm-dir <SMM_DIR>` instead of `CLAUDE_PLUGIN_DATA` prefix** — ~20 references replaced across 6 skill files and the behavioral guide. SMM_DIR comes from preload output. Reduces tokens, eliminates env var dependency in instructions, consistent with subagent pattern.
- **Retro preload slimmed** — outputs just paths + behavioral guide (~500 tokens). Subagent reads `.retro-input.json` itself. Retro data slimmed at write time (no events_since_last_retro, signal events trimmed).
- **init.sh fallback path corrected** — default changed from `~/.claude/xp-agents` to `~/.claude/plugins/data/xp-agents-xp-agents` (matches actual platform plugin data path).

### Stats
- 962 tests (all passing)

## v1.0.4

### Added
- **Behavioral Guide: plan before multi-file changes** — encourages `EnterPlanMode` for work touching 3+ files, followed by `/xp-review-plan` before writing code.

### Fixed
- **Security triage preload shows both staged and unstaged diffs** — when `git add && git commit` is blocked before `git add` executes, nothing is staged. Preload now shows both so the agent can always triage.
- **Simplify nudge counts test files** — the PostToolUse nudge was filtering out test files, but test code benefits from simplify too. Now consistent with the Stop hook gate which already counted tests.

### Stats
- 963 tests (all passing)

## v1.0.3

### Fixed
- **Security triage now visible in event log** — `mark_triaged.py` and `security_review_done.py` write status events so the retro can track triage compliance (fixes 7-session recurring Fix item about undetectable triage).
- **Superseded decision concern dedup** — only flags the most recent pair per topic, not every historical pair. Reduces noise from duplicate concerns accumulating.

### Changed
- **Plan review output shown to user** — three layers (PostToolUse nudge, skill content, agent prompt) all instruct showing the full review. Prevents the agent from silently acting on review findings.

### Stats
- 963 tests (all passing)

## v1.0.2 — Remove Draft Decision Concept

### Removed
- **Draft decisions eliminated** — all decisions are final when created. The draft/final distinction caused 7+ consecutive retro Fix items about draft accumulation. Plans are always executed immediately after review, so drafts were never meaningfully tentative.

### Changed
- **Housekeeping Constraints curation** — no longer asks user to confirm/reject drafts. Instead, uses judgment to decide which decisions are architectural constraints (technology choices, design patterns, conventions that bound future work). Prunes superseded, absorbed, and stale constraints automatically. Only asks user if still over cap after pruning.
- **Compaction** — all decisions follow 3-session aging (drafts were previously skipped and immediately compactable).
- **Materialize** — all unresolved decisions go into Constraints (drafts were previously filtered out).
- **Retrospective** — removed `decisions_draft` stat and health signal.
- **Plan reviewer** — records decisions without `metadata.draft`.

### Stats
- 963 tests (all passing)

## v1.0.1 — Fix Security Triage Preload Quoting

### Fixed
- **Security triage preload failed** — inline `!` command with quoted `echo "---FULL DIFF---"` triggered "Command contains quoted characters in flag names" permission error. Moved to a preload script (`preload_diff.sh`) to avoid the quoting issue.

### Stats
- 963 tests (all passing)

## v1.0.0

### Added
- **Behavioral Guide: Process section** — explicit instructions for when to run /simplify, /xp-security-triage, /xp-quality-review, /xp-review-plan, and how to respond to Stop hook blocks
- **Seed SMM wisdom items** — new projects get process guidance from day one
- **PostToolUse:Bash /simplify nudge** — after commits with 3+ code files, additionalContext tells agent to run /simplify immediately
- **Plan content injected into plan review preload** — PostToolUse:ExitPlanMode captures planFilePath, preload dumps plan into subagent prompt (fixes context:fork not including conversation history)
- **Agent tool schema loaded at kickoff** — ensures plugin subagents are discoverable for skill delegation
- **Preloaded staged diff in security triage** — eliminates extra tool call for trivial classification
- **--smm-dir for save_retrospective.py** — subagents can pass path directly instead of relying on CLAUDE_PLUGIN_DATA

### Changed
- **Subagent commands use --smm-dir instead of CLAUDE_PLUGIN_DATA** — forked subagents don't have the env var, so xp-retrospective and xp-plan-reviewer now use the SMM_DIR from their preload
- **Quality review: "courageous senior engineer"** — simplified skip criteria (only public API breaks), "fix it now" for worsening debt
- **Security triage: security-relevant case first** — reordered for the important path

### Removed
- Obsolete docs: MILESTONES.md, SMM_REFACTOR_MILESTONES.md, MANUAL_TEST_PLAN.md
- Stale "agent hooks broken" claim from ARCHITECTURE.md

### Fixed
- ARCHITECTURE.md file structure updated with all current files (event_schema.py, event_builder.py, test_parsing.py, seed_smm.py, xp-security-triage, etc.)
- SMM_DESIGN.md: removed constraint graduation, updated compaction rules to match implementation
- CLAUDE.md: removed Build Order section, updated file structure and test layout

### Stats
- 963 tests (all passing)

## v0.9.118 — Nudge /simplify After Commits with 3+ Code Files

### Added
- **PostToolUse:Bash nudge after commits** — when a commit touches 3+ production code files (excluding tests and docs), `bash_post_tool.py` returns additionalContext telling the agent to run /simplify immediately. Two-layer enforcement: nudge right after commit (PostToolUse), gate if agent tries to stop without running it (Stop hook).

### Stats
- 963 tests (all passing)

## v0.9.117 — Behavioral Guide: Process Section + Seed SMM Wisdom

### Added
- **Behavioral Guide: "Process — When to Run XP Skills"** — explicit instructions for when to run /xp-security-triage (after git add, before commit), /simplify (after each 3+ code file commit), /xp-quality-review (after simplify), /xp-review-plan (after plan mode), and how to respond to Stop hook blocks (run the skill, don't dismiss).
- **Seed SMM wisdom items** — new projects get process guidance from day one: simplify after commits, proactive security triage, plan review after planning, honor Stop hooks.

### Stats
- 963 tests (all passing)

## v0.9.116 — Security Triage Gate: Code Files Only

### Changed
- **Security triage gate skips test-only and docs-only commits** — `has_staged_code_files()` checks staged (and about-to-be-staged) files against `is_code_file()` and `is_test_file()`. Commits with only tests, docs, config, or images skip the triage requirement.
- **Handles combined commands** — `git add . && git commit` and `git commit -am` check both staged and unstaged files since staging hasn't happened yet at PreToolUse time.
- **Consumes stale markers** — non-code commits consume any leftover `.security-triaged` marker to prevent it from carrying over and letting a future code commit skip triage.

### Stats
- 963 tests (all passing)

## v0.9.115 — Plan Reviewer: Stop Re-reading Preloaded Data

### Changed
- **Plan reviewer told not to re-read SMM or events.jsonl** — both are already in the preload context. Reviewer was wasting 10+ tool calls exploring files it already had. Explicit "do NOT read" list added.
- **Source file reads scoped** — only read project files to verify specific decision conflicts, not speculatively.
- **Assumptions filtered** — only record assumptions that matter (wrong assumption = rework). Don't re-record obvious defaults.
- **Decisions filtered** — don't re-record decisions already in the SMM Constraints pillar.
- **README updated** — fixed outdated hook table (added PostToolUse:ExitPlanMode, PostCompact, PostToolUseFailure; removed phantom Notification hook), added Skills table, documented plan review two-entry-point mechanism, added compaction section.

### Stats
- 940 tests (all passing)

## v0.9.114 — Courage in Reviews: Tighter Skip Criteria

### Changed
- **Quality review: explicit valid-skip list** — only two reasons to skip a simplify recommendation: breaks an external API contract, or requires coordinated multi-module changes. Everything else gets fixed. Explicitly called out "consistent with existing code", "design choice", "pre-existing code", and "not our change" as invalid skip reasons.
- **Plan reviewer: courage over comfort** — replaced "focus on strategic issues, not tactical details" with "flag it or record as debt, don't rationalize skips."

### Stats
- 940 tests (all passing)

## v0.9.113 — Behavioral Guide: Concrete append.sh Examples

### Changed
- **Behavioral Guide now shows concrete examples** for assumption, decision, and concern events — including correct flags. Prevents the agent from using invalid values like `--severity "uncertainty"` (should be `high/medium/low`, and assumptions don't take severity at all).

### Stats
- 940 tests (all passing)

## v0.9.112 — Allow Plan File Writes During Plan Review Gate

### Fixed
- **Plan review gate blocked plan file writes** — after a Plan subagent completed, the `.plan-awaiting-review` marker blocked all writes including the plan file itself (`.claude/plans/*.md`). Plan files are now exempt from the gate since writing the plan is part of planning, not implementation.

### Stats
- 940 tests (all passing)

## v0.9.111 — Fix is_git_commit Heredoc False Positive

### Fixed
- **Security triage gate blocked heredoc commands** — `is_git_commit` matched "git commit" inside heredoc content (e.g., `cat <<'SMMEOF' | python3 save_smm.py` with "before git commit" in the body). `_strip_quoted` now strips heredoc content (`<<DELIM...DELIM` and `<<'DELIM'...DELIM`) in addition to quoted strings.

### Stats
- 939 tests (all passing)

## v0.9.110 — Fix is_git_commit False Positive on Quoted Strings

### Fixed
- **Security triage gate blocked all Bash commands** — `is_git_commit` regex matched "git commit" inside quoted arguments (e.g., `append.sh --content "before git commit"`). Now strips quoted strings before matching, so only actual `git commit` commands trigger the gate.

### Stats
- 937 tests (all passing)

## v0.9.109 — Fix Plan Review Gate, Block Writes Until Reviewed

### Fixed
- **Plan review gate never fired** — `EnterPlanMode`/`ExitPlanMode` are regular tools, not subagents. The `SubagentStop` hook that wrote `.plan-awaiting-review` never triggered because no `SubagentStop` event is emitted for plan mode. Root cause confirmed via transcript analysis.

### Changed
- **Three-layer plan review enforcement:**
  1. `PostToolUse:ExitPlanMode` — nudges agent via `additionalContext` to run `/xp-review-plan`
  2. `SubagentStop:Plan` — writes marker for the Agent-tool plan flow (belt and suspenders)
  3. `PreToolUse:Write|Edit|MultiEdit` — **blocks** writes while marker exists (was: nudge)
- **Marker cleared only by `/xp-review-plan`** preload — agent cannot skip the review
- **Removed dead `PreToolUse:ExitPlanMode` hook** — blocking ExitPlanMode trapped the agent in plan mode where it couldn't run skills

### Stats
- 934 tests (all passing)

## v0.9.108 — Try Items Folded into Question Triage

### Changed
- **Try item review moved into `/xp-question-triage`** — no longer a separate kickoff step. Question triage now handles open questions, assumptions, AND previous retro Try items. Adopted items become decisions, deferred/dropped recorded as status.
- **Kickoff back to 4 steps** — retro → question triage (+ try review) → goals → housekeeping.
- **`check_session_needs.sh` detects Try items** — triggers QUESTIONS_NEEDED when the latest retro has Try items, even if no open questions.
- **Question triage preload includes Try items** — `check_questions.sh` extracts them from the latest retro file.

### Stats
- 927 tests (all passing)

## v0.9.106 — Simplify Kickoff + Status working_on Default

### Changed
- **Kickoff simplified** — removed retro verification/fallback (18 lines, reliable since v0.9.75), cleaned up duplicate "proceed to step N" text, added ToolSearch for Skill tool, added Try item review step.
- **Status events default `working_on` to `[]`** — previously required, now optional via CLI. Process-related status events (e.g., Try item dispositions) don't have files. Schema validation still requires the field but the CLI defaults it.
- **smm-protocol updated** — status event docs show working_on as optional.

### Stats
- 927 tests (all passing)

## v0.9.106 — Simplify Kickoff + ToolSearch + Try Review

### Added
- **ToolSearch before kickoff steps** — loads Skill tool schema to prevent first-call failure
- **Step 2: Review Previous Try Items** — extracts Try items from latest retro, reviews as adopted/deferred/dropped

### Removed
- **Retro verification grep + fallback save** — retro save via subagent has been reliable since v0.9.75. Removed 18 lines of defensive code.
- **"Don't use Write tool" warning** — Write removed from retro agent in v0.9.68

### Stats
- 927 tests (all passing)

## v0.9.105 — Review Previous Try Items at Kickoff

### Added
- **Step 2 in kickoff: Review Previous Try Items** — extracts Try items from the most recent retrospective and presents them for review. Each item is marked adopted, deferred, or dropped. Closes the feedback loop from retro → next session that was flagged as a recurring Fix.
- **Preload extracts PREVIOUS_TRIES** — `check_session_needs.sh` reads the latest retro JSON file and outputs Try items.
- Kickoff is now 5 steps: retro → try review → questions → goals → housekeeping.

### Stats
- 927 tests (all passing)

## v0.9.104 — Seed Default SMM for New Projects

### Added
- **Default SHARED_MENTAL_MODEL.md on first init** — `seed_smm.py` scans the project for linter config, test files, git hooks, and CI setup. Writes initial SMM with:
  - **Constraints**: XP defaults (TDD, plan before execute, small commits, strict linting, commit hooks)
  - **Risks**: flags for anything missing (no linter, no tests, no hooks, no CI)
  - **Wisdom**: run /xp-kickoff at session start
- Only runs when SMM doesn't exist (idempotent). Housekeeping curates from there.

### Stats
- 918 tests (all passing, +24 new)

## v0.9.103 — Lint: systemMessage + Commit-Time Resolution

### Changed
- **Lint errors show as systemMessage** — "Lint errors found — fix before committing." now visible in the UI, not just additionalContext that the agent may ignore.
- **Lint concerns resolve on successful commit** — after a commit, the linter runs on committed files. Files that now pass lint get their concerns resolved. Fixes the gap where lint fixes via Bash commands (e.g., `swiftlint --fix`, `bun run lint:fix`) didn't trigger the Write/Edit-based resolution path.

### Stats
- 894 tests (all passing)

## v0.9.102 — Slim Previous Retros in Retro Input

### Changed
- **Previous retros slimmed to content strings only** — stripped event_refs, values, xp_value metadata. The retro agent only needs content for trend detection (recurring fixes, adopted tries). Saves ~37% per retro file.
- **Retro history limited to 2** (was 3) — combined with slimming, reduces previous_retros from ~4,400 tokens to ~1,800 tokens (59% savings).

### Stats
- 894 tests (all passing)

## v0.9.101 — Fix Retro Cap and Remove Debug Logging

### Fixed
- **Retro cap counts across all events, not just pre-watermark** — post-watermark retro events (written during the current kickoff) weren't counted toward the cap of 2, resulting in 3 retro events surviving compaction. Now counts globally and only keeps the last 2.
- **Removed debug logging** from `kickoff_done.py` (was writing to `/tmp/kickoff-done-debug.json`).

### Stats
- 894 tests (all passing)

## v0.9.99 — Retro Agent: Use Task Prompt Data Only

### Fixed
- **Retro agent told to use task prompt data, not browse filesystem** — the subagent was reading cached tool-results files (40KB) instead of using the slimmed preload data (~1,500 tokens) already in its task prompt. Updated prompt: "Do not read any files. Analyze only the data provided in your task prompt."
- **Field descriptions match slimmed preload** — removed references to `samples` and `events_since_last_retro` which the preload strips.

### Stats
- 894 tests (all passing)

## v0.9.98 — Recurring Concerns Escalate in Severity

### Changed
- **Recurring concerns escalate instead of duplicating** — when a concern is resolved but the underlying condition persists, the next detection bumps severity: low → medium (1 prior), medium → high (2+ prior). Concerns get louder, not noisier.

### Stats
- 894 tests (all passing)

## v0.9.97 — Decision Aging in Compaction

### Changed
- **Decisions age out of the event log after 3 sessions** — same pattern as debt aging. Unresolved non-draft decisions are retained for 3 sessions (giving housekeeping and the retro time to analyze them), then become compactable. Draft decisions still compact immediately. Important decisions that housekeeping promotes to Constraints persist in the SMM regardless.

### Stats
- 894 tests (all passing)

## v0.9.96 — Add Bun Test Detection

### Added
- **`bun test` detection and result parsing** — matches "N pass, M fail" output format. The retro kept flagging "test runs not tracked" because `bun test` wasn't in `is_test_run()`.

### Stats
- 894 tests (all passing, +3 new)

## v0.9.95 — Show Plugin Version at Startup

### Added
- **Plugin version in startup message** — "XP agents (v0.9.95) active. Run /xp-kickoff." Reads from plugin.json.

### Stats
- 891 tests (all passing)

## v0.9.94 — Draft Promotion Resolves, Doesn't Create New Events

### Fixed
- **Promoting a draft decision just resolves it** — housekeeping was creating new decision events with generic "Promoted from draft" content, adding noise (9 empty events in one session). Now: resolve the draft, add the text to Constraints in the SMM. The original draft event already has the content.

### Stats
- 891 tests (all passing)

## v0.9.93 — Show Full Retrospective to User

### Changed
- **Kickoff shows full retrospective output** — was summarizing the subagent's Keep/Fix/Try analysis, losing event references and XP value tags. Now instructs: "Show the full retrospective output to the user. Do not summarize it."

### Stats
- 891 tests (all passing)

## v0.9.92 — Compaction: Limit Retros, Drop Draft Decisions

### Fixed
- **Compaction keeps only last 2 retrospective events** — was keeping all retro events unconditionally. Full archive lives in `retrospectives/` directory. Last 2 kept for trend detection.
- **Draft decisions no longer prevent compaction** — only non-draft unresolved decisions are retained as SMM-referenced.
- **Commits record status, not draft decisions** — `bash_post_tool.py` was auto-drafting a decision from every commit message. These aren't architectural decisions — they're activity. Now recorded as `status` events which compact freely. Real decisions should be recorded deliberately by the agent.

### Stats
- 891 tests (all passing)

## v0.9.91 — Slim Retro Context Injection

### Changed
- **Main agent no longer gets event details at SessionStart** — only counts and health signals (~100 tokens). Previously injected key events (~2,000+ tokens) which the agent would analyze itself instead of delegating to kickoff.
- **Retro subagent preload slimmed** — signal events stripped to `{type, content, short_id}`, status samples dropped (counts sufficient). Cuts subagent context from ~5,500 to ~1,500 tokens.
- **Removed `_summarize_key_events`** — dead code after removing event details from main agent context.

### Stats
- 891 tests (all passing)

## v0.9.90 — Source-Dependent GUPP + Kickoff Framing

### Changed
- **GUPP differentiates by source** — startup/clear: "Run /xp-kickoff before doing anything else, and start immediately." Resume/compact: "Check the Shared Mental Model for pending work. Resume immediately."
- **SessionStart context reframed** — "Retrospective: N unanalyzed events" → "Kickoff preparation complete. N events ready for review." Inline K/F/T instructions replaced with "Run /xp-kickoff, do NOT analyze yourself."
- **systemMessage updated** — "SMM initialized" → "Run /xp-kickoff" for startup, "Kickoff data prepared" for retro prep.

### Stats
- 891 tests (all passing)

## v0.9.89 — Reframe Retro Prep as Kickoff Prep

### Changed
- **SessionStart context reframed from "retrospective" to "kickoff preparation"** — the agent was seeing "Retrospective: N unanalyzed events" with inline K/F/T instructions and doing its own analysis before invoking the skill. Now says "Kickoff preparation complete" and directs to `/xp-kickoff`. All session data (health signals, key events, type counts) preserved.

### Stats
- 891 tests (all passing)

## v0.9.88 — Completed Goals Must Be Resolved and Pruned

### Fixed
- **Housekeeping must record resolution events for completed goals** — was marking goals ✅ in the SMM text but not writing resolution events, so goals lingered forever. Now: record resolution, remove from SMM, keep only the most recently completed one for context.

### Stats
- 891 tests (all passing)

## v0.9.87 — Fix Compaction Skipping When Watermark Ahead

### Fixed
- **Compaction no longer bails when watermark exceeds event count** — housekeeping writes the curation watermark including its own events, but compaction runs before all events are flushed. The watermark (73) was ahead of the actual event count (68), causing `wm_count > len(events)` to skip compaction entirely. Now clamps watermark to actual count.

### Stats
- 891 tests (all passing)

## v0.9.86 — Stop Main Agent Doing Inline Retro Before Skill

### Fixed
- **Kickoff explicitly says "do NOT analyze events yourself"** — the main agent was doing its own retrospective analysis before invoking the skill, wasting tokens. The subagent then redid the work. Now the instruction is clear: invoke the skill immediately, don't analyze.

### Stats
- 891 tests (all passing)

## v0.9.85 — Security Review Is a Built-in Skill

### Fixed
- **Security triage clarifies `/security-review` is built-in** — the agent was prefixing it with `xp-agents:` (plugin namespace), causing "Unknown skill" error. The triage skill now explicitly says it's a built-in Claude Code command and not to prefix it.

### Stats
- 891 tests (all passing)

## v0.9.84 — Rename smm-protocol to xp-smm-protocol

### Changed
- **`/smm-protocol` → `/xp-smm-protocol`** — consistent `xp-` prefix across all skills.

### Stats
- 891 tests (all passing)

## v0.9.83 — Rename Skills to Active Voice

### Changed
- **Skills use active voice, agents use nouns** — eliminates confusion between skill and subagent invocation:
  - `/xp-review-plan` (skill, action) wraps `xp-plan-reviewer` (agent, actor)
  - `/xp-run-retrospective` (skill, action) wraps `xp-retrospective` (agent, actor)
- All hook nudges, kickoff references, and test assertions updated to new skill names.

### Stats
- 891 tests (all passing)

## v0.9.82 — Plan Review Nudge Specifies Skill Invocation

### Fixed
- **Plan review nudge says "invoke as a skill, not a subagent"** — the agent was running the plan reviewer as a subagent (Agent tool), which doesn't trigger the skill preload that clears the `.plan-awaiting-review` marker. The nudge now explicitly says to use the Skill tool.

### Stats
- 891 tests (all passing)

## v0.9.81 — Remove Redundant SMM Read-Back

### Changed
- **Housekeeping no longer reads back the SMM file** — the agent just wrote it via the cat heredoc, so the content is already in context. Saves one Read tool call per kickoff.

## v0.9.80 — Remove Duplicate Behavioral Guide Loading

### Changed
- **Housekeeping no longer loads behavioral guide manually** — `kickoff_done.py` injects it deterministically via `additionalContext`. Removed `load_context.sh` step from housekeeping to avoid ~500 token duplication. Agent still reads the SMM file directly.

### Stats
- 891 tests (all passing)

## v0.9.79 — Fix Kickoff Done Hook + Compaction Diagnostics

### Fixed
- **`kickoff_done.py` matches both namespaced and plain skill names** — plugin skills may arrive as `"xp-housekeeping"` or `"xp-agents:xp-housekeeping"`. The hook was only matching the plain name, so it likely never fired for marketplace installs. Same fix applied to `security_review_done.py`.
- **Compaction failures now logged** — instead of `contextlib.suppress(Exception)`, compaction errors are recorded as concern events for diagnosis.
- **Kickoff completion logged** — `kickoff_done.py` now writes a status event with compaction stats ("Kickoff complete. Compacted: N archived, M retained.") so we can verify the hook fired.

### Stats
- 891 tests (all passing)

## v0.9.78 — Auto-Wrap String Items in Retrospective Save

### Fixed
- **`save_retrospective.py` accepts strings in keep/fix/try arrays** — LLMs commonly simplify `[{"content": "..."}]` to `["..."]`. Now auto-wraps strings as `{"content": "string"}` before validation instead of rejecting them.

### Stats
- 891 tests (all passing)

## v0.9.77 — Block ExitPlanMode Until Plan Review Runs

### Added
- **PreToolUse hook for ExitPlanMode** — blocks exiting plan mode when `.plan-awaiting-review` marker exists. Previously the plan review nudge only fired on Write/Edit, so the agent could exit plan mode and end its turn without ever triggering the review.

### Stats
- 891 tests (all passing)

## v0.9.76 — Verify Retro Event in Log After Subagent Returns

### Changed
- **Kickoff verifies retrospective event in event log** — after the retro subagent returns, kickoff greps the last 5 events for a `retrospective` event. If missing, runs `save_retrospective.py` as fallback. More reliable than checking `.retro-input.json` existence.
- **Kickoff preload emits SMM_DIR** — `check_session_needs.sh` now outputs `SMM_DIR=<path>` for use in verification and fallback commands.

### Stats
- 891 tests (all passing)

## v0.9.75 — Ensure Retrospective Saves via Script

### Fixed
- **Retro subagent must save via `save_retrospective.py` before returning** — strengthened agent prompt with mandatory save instruction. Previously the subagent returned analysis as text and the main agent used `Write` to save, bypassing the event log, structured JSON format, and `.retro-input.json` cleanup.
- **Kickoff has fallback save** — if `.retro-input.json` still exists after the retro subagent returns, kickoff runs `save_retrospective.py` itself. Belt and suspenders.

### Stats
- 891 tests (all passing)

## v0.9.74 — Clean Up Retro Input After Consumption

### Fixed
- **`.retro-input.json` deleted after retrospective saves** — the file was left on disk after the retro agent consumed it, creating confusing stale state. Now `save_retrospective.py` cleans it up after writing the retro event and file.

### Stats
- 891 tests (all passing)

## v0.9.73 — Multi-Language Test & Lint Support

### Added
- **Test file detection** for Rust (`*_test.rs`), Kotlin (`*Test.kt`), C# (`*Test.cs`), C/C++ (`test_*.cpp`, `*_test.cc`), PHP (`*Test.php`), Dart (`*_test.dart`), Elixir (`*_test.exs`), Scala (`*Test.scala`), Maven/Gradle (`src/test/`), and `spec/` directory.
- **Test result parsing** for Rust (`cargo test`), Java/Kotlin (`mvn test`, `gradle test`), Ruby (`rspec`, `minitest`/`rake test`), PHP (`phpunit`), C# (`dotnet test`), Dart (`dart test`, `flutter test`), Elixir (`mix test`), C/C++ (`ctest`), and JS (`vitest`).
- **Linter detection** for Rust (clippy via `Cargo.toml`), Go (`golangci-lint`), Ruby (rubocop), C/C++ (clang-tidy, clang-format), Java (checkstyle), Kotlin (detekt), PHP (phpcs, php-cs-fixer), Dart (dart analyze), Elixir (credo), C# (dotnet-format), and Swift (swiftlint).

### Stats
- 891 tests (all passing, +37 new)

## v0.9.72 — Swift/Xcode Test File Detection

### Fixed
- **Swift test files recognized by TDD order check** — `*Tests.swift` files and `*Tests/` directories (Xcode convention) now detected as test files. Previously the TDD hook flagged test file writes as implementation-before-tests.

### Stats
- 854 tests (all passing, +3 new)

## v0.9.71 — CLAUDE_PLUGIN_DATA in All Bash Commands

### Fixed
- **All `append.sh` and `save_retrospective.py` calls now inject `CLAUDE_PLUGIN_DATA`** — the env var is inline-substituted in skill/agent content but not exported to Bash tool processes. Every bash code block in skills, agents, and the behavioral guide now prefixes commands with `CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}"` so the actual path is baked into the command.
- **`_append_impl.py` accepts `--smm-dir`** — optional argument for direct path override, bypassing env var resolution.

### Stats
- 851 tests (all passing)

## v0.9.70 — Housekeeping Asks User About Goal Completion

### Fixed
- **Housekeeping now asks the user which goals are complete** — previously it said "mark delivered intents (check if code was shipped)" but had no way to check. Now it presents existing goals and asks the user to mark items done, then records resolutions. Goals no longer linger indefinitely.

### Stats
- 851 tests (all passing)

## v0.9.69 — Deterministic Compaction After Housekeeping

### Fixed
- **Event log compacts deterministically after housekeeping** — previously compaction only ran on `PostCompact` (context window compaction), which barely fires with 1M context. Now `kickoff_done.py` runs `compact_after_curation()` after housekeeping completes, ensuring the event log stays manageable every session.

### Stats
- 851 tests (all passing)

## v0.9.68 — Retrospective Must Use save_retrospective.py

### Fixed
- **Removed `Write` tool from retrospective agent and skill** — the agent was using `Write` to create the retro file directly, bypassing `save_retrospective.py` which handles atomic writes, event creation, and materialization. Without `Write` access, the agent must use the script.

### Stats
- 851 tests (all passing)

## v0.9.67 — Kickoff Reorder + Lightweight Question Detection

### Changed
- **Question triage now runs before goal collection** — answers may inform goals. Kickoff order: retro → questions → goals → housekeeping.
- **Question detection uses grep instead of full JSON parse** — `check_session_needs.sh` greps `events.jsonl` for question events instead of loading and iterating all events. Question triage handles resolution checking itself.

### Fixed
- **Kickoff detects questions from raw events** — questions written directly to `events.jsonl` (like the linter question) were missed because housekeeping hadn't curated them into the SMM Risks pillar yet.

### Stats
- 851 tests (all passing)

## v0.9.66 — Question Detection from Raw Events

### Fixed
- **Kickoff now detects unresolved questions in raw events, not just the curated SMM** — questions written to `events.jsonl` (like the linter question) weren't detected by `check_session_needs.sh` because housekeeping hadn't curated them into the Risks pillar yet. Now checks both the SMM file and raw events for unresolved blocking questions.

### Stats
- 851 tests (all passing)

## v0.9.65 — Xcode and Swift Test Detection

### Added
- **Xcode and Swift test result parsing** — `xcodebuild test` and `swift test` commands now detected and parsed. Matches "Executed N tests, with M failures" output format. Test pass/fail events are recorded to the SMM, enabling TDD stop gate enforcement for iOS/macOS projects.

### Stats
- 851 tests (all passing, +5 new)

## v0.9.64 — Fix load_context.sh SMM Path

### Fixed
- **`load_context.sh` accepts SMM_DIR as argument** — when called by the agent via Bash during housekeeping, the script couldn't resolve `CLAUDE_PLUGIN_DATA` and fell back to the wrong path. Now accepts the preloaded SMM_DIR as `$1`, with init.sh as fallback.
- **Housekeeping SKILL.md updated** — step 8 instructions tell the agent to pass the SMM_DIR from the preload output.

### Stats
- 846 tests (all passing)

## v0.9.63 — Fix Subagent SMM Path Resolution

### Fixed
- **Subagents no longer construct their own SMM paths** — retrospective and plan reviewer agents were told to run `init.sh` themselves, which failed to resolve `CLAUDE_PLUGIN_DATA` and fell back to wrong paths (e.g., `{project}/.smm/`). Preloads now emit `SMM_DIR=<path>` and agent prompts say "use that exact path, do not construct your own."
- **All preloads emit SMM_DIR** — retrospective, plan-reviewer, and quality-review preloads now output the resolved path for agents/skills to use.

### Stats
- 846 tests (all passing)

## v0.9.62 — Lint Check: Blocking Question

### Changed
- **Missing linter config now emits a blocking question** — "No linter configured. Want me to set one up?" as a blocking question instead of a low-severity concern. Coding standards are a core XP practice — the user should consciously decide, not passively ignore.

### Stats
- 846 tests (all passing)

## v0.9.60 — Plugin Data Path Fix for Skill Preloads

### Fixed
- **Skill `!` preloads now use correct SMM path** — `CLAUDE_PLUGIN_DATA` is inline-substituted in skill content but not exported as an env var to `!` preload commands. All 8 skill preloads now pass `CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}"` explicitly so `init.sh` resolves the correct plugin data path instead of falling back to `~/.claude/xp-agents/`.

### Stats
- 846 tests (all passing)

## v0.9.59 — Kickoff Must Complete Before Work Begins

### Fixed
- **Agent no longer starts working on goals before housekeeping completes** — added explicit instruction: "Do NOT start working on the user's goal until ALL steps are done." The agent was collecting goals, then immediately executing on them before running housekeeping.

### Stats
- 846 tests (all passing)

## v0.9.58 — Shell Compatibility Fix

### Fixed
- **Quality review preload works in zsh** — replaced `mapfile` (bash-only) with portable shell in `xp-quality-review/scripts/preload.sh`. The `!` preload mechanism may not honor shebangs, running through the user's default shell instead.

### Stats
- 846 tests (all passing)

## v0.9.57 — Kickoff Sequencing Fix

### Fixed
- **Housekeeping now reliably runs after goal collection** — strengthened `/xp-kickoff` skill instructions. The agent was stopping after goal collection without proceeding to housekeeping (step 4). Instructions now use imperative language: "You MUST complete ALL steps", "Housekeeping MUST always run", "Kickoff is not complete until housekeeping finishes."

### Stats
- 846 tests (all passing)

## v0.9.56 — SMM Path Fix

### Fixed
- **SMM directory now uses `CLAUDE_PLUGIN_DATA`** — `resolve_smm_dir()` in Python was hardcoded to `~/.claude/xp-agents/`, ignoring the `CLAUDE_PLUGIN_DATA` environment variable that the plugin platform provides. `init.sh` already used it correctly. Now both are in sync, placing the SMM at `${CLAUDE_PLUGIN_DATA}/{project-id}/smm/` when installed via marketplace.

### Stats
- 846 tests (all passing)

## v0.9.55 — Kickoff Gate Fix

### Fixed
- **Kickoff gate no longer blocks AskUserQuestion during kickoff sub-skills** — the `.needs-kickoff` marker is now cleared when `/xp-kickoff` starts, not when housekeeping finishes. Previously, goal collection's `AskUserQuestion` triggered `UserPromptSubmit` which hit the gate mid-kickoff.

### Added
- **Agent Teams design doc** (`docs/AGENT_TEAMS_DESIGN.md`) — maps XP sprint practices to Claude Code Agent Teams. Documents sprint lifecycle, role separation (lead as coach, teammates as developers), hook compatibility analysis, and required changes for teammate awareness.

### Stats
- 848 tests (all passing)

## v0.9.54 — Question Pipeline, Effort Tuning, Legacy Cleanup

### Added
- **Plan reviewer emits `question` events** — new section 6 in the agent prompt distinguishes assumptions (can proceed with reasonable default) from questions (need user input, significant rework risk). Questions surface first in the subagent's output so the main agent sees them immediately.
- **`/xp-question-triage` wired into kickoff** — step 3 (between goals and housekeeping), conditional on open questions/assumptions in the Risks pillar.
- **`smm_has_section()` and `smm_section()` utilities** — shared functions in `_preload_base.sh` for extracting markdown sections from the SMM. Replaced 12 duplicate `grep -A N | sed` patterns across 4 preload scripts.
- **Effort frontmatter on all skills** — `effort: high` for analytical skills (retrospective, housekeeping, quality-review, plan-reviewer, security-triage), `effort: low` for mechanical skills (goal-collection, question-triage, smm-protocol). Kickoff left at default.

### Removed
- **All navigator references** — stale docs, negative tests, and test fixtures. Navigator was removed as a functional component in v0.9.47 but references lingered.
- **Legacy SMM format fallbacks** — `Project Goals`, `Blocking Questions`, `Customer Intent`, `Unacknowledged Concerns`, `Technical Debt` section patterns removed from all preload scripts. Four-pillar format (Intent, Constraints, Risks, Wisdom) is the only supported format.
- **4 dead navigator negative tests** — `TestPreToolWriteNoNavigatorNudge` class, integration navigator nudge test.

### Changed
- **`check_open_items.sh` uses four-pillar headings** — Intent, Constraints, Risks instead of legacy section names.
- **Question detection keywords tightened** — `question|assumption|blocking` instead of `question|unknown|assumed|blocking` to reduce false positives.
- **Docs updated** — ARCHITECTURE.md (kickoff flow, plan reviewer events, question triage step), PLUGIN_TOOLS.md (subagent examples), SMM_DESIGN.md (retro example), CLAUDE.md (removed navigator decision).

### Stats
- 844 tests (all passing)

## v0.9.53 — Replace Push Gate with Commit-Time Security Triage

### Changed
- **Security gate moved from `git push` to `git commit`** — earlier feedback (XP Feedback value). Blocks commit without triage instead of blocking push without review.
- **New `/xp-security-triage` inline skill** — reads `git diff --cached`, classifies changes as trivial (auto-clear) or security-relevant (requires `/security-review`).
- **Simple marker replaces hash-based tracker** — `.security-triaged` marker written by triage skill or `/security-review`, consumed after each successful commit. No more commit-hash tracking or carry-forward logic.
- **`is_git_commit` deduplicated** — single definition in `security.py`, imported by both `pre_tool_bash.py` and `bash_post_tool.py`.

### Removed
- **`/security-clear` skill** — no more bypass. Triage skill replaces it with proper classification.
- **`security_review_requested` event type** — removed from schema, `_append_impl.py`, and `_common.py`. Push gate no longer writes events.
- **Security detection in `user_prompt_log.py` and `subagent_stop.py`** — pattern-matching heuristics for security review output removed. Triage is now explicit via skill invocation.
- **Hash-based tracker functions** — `get_head_hash`, `security_tracker_path`, `write_security_tracker`, `find_last_reviewed_hash`, `diff_has_code_changes` all removed from `security.py`.

### Stats
- 848 tests (all passing)

## v0.9.52 — Remove xp-values Skill, Absorb into Behavioral Guide

### Changed
- **Behavioral guide absorbs xp-values content** — added "answer open questions promptly" (Communication), "if you can remove something, remove it" (Simplicity), and value conflict priority: Courage > Simplicity > Feedback > Communication > Respect.

### Removed
- **`/xp-values` skill** — 80% redundant with the behavioral guide. Unique content (conflict priority, concise additions) absorbed into the guide. Saves ~125 lines of skill description budget.
- **`xp-values` preload** from plan reviewer and retrospective subagents — XP values now delivered via behavioral guide at SubagentStart.
- **`/xp-values` reference** from session start skills list.

### Stats
- 869 tests (all passing)

## v0.9.51 — Lint Feedback, Async Hooks, Plugin Data Storage

### Changed
- **Lint errors inject additionalContext** — `lint_check.py` now returns lint errors as `additionalContext` so the agent sees them immediately after writing the file, not deferred to the next prompt via nuggets. Synchronous (was async) since context injection must complete before the agent continues.
- **Removed lint debounce** — the 1-second mtime debounce skipped files the agent just wrote, which is every file. Now always lints immediately after write.
- **4 hooks now async** — `bash_post_tool.py`, `bash_failure.py`, `security_review_done.py`, and `session_end.py` run with `async: true` (fire-and-forget, no context injection).
- **SMM storage uses `CLAUDE_PLUGIN_DATA`** — respects plugin ecosystem conventions and sandbox customization.
- **Both user and project scope supported** for installation.

### Stats
- 869 tests (all passing)

## v0.9.50 — Async Hooks, CLAUDE_PLUGIN_DATA Storage

### Changed
- **5 hooks now async** — `lint_check.py`, `bash_post_tool.py`, `bash_failure.py`, `security_review_done.py`, and `session_end.py` run with `async: true`. These fire-and-forget hooks record data to the event log but don't inject context or block. Biggest win: agent no longer waits up to 5s for lint on every Write/Edit.
- **SMM storage uses `CLAUDE_PLUGIN_DATA`** — SMM now lives at `${CLAUDE_PLUGIN_DATA}/{project-id}/smm/` instead of `~/.claude/xp-agents/`. Respects plugin ecosystem conventions and sandbox customization. Falls back for `--plugin-dir` dev mode.
- **Both user and project scope supported** — project scope installs share the plugin with the team via `.claude/settings.json`.

### Stats
- 869 tests (all passing)

## v0.9.49 — Use CLAUDE_PLUGIN_DATA for SMM Storage

### Changed
- **SMM storage uses `CLAUDE_PLUGIN_DATA`** — SMM now lives at `${CLAUDE_PLUGIN_DATA}/{project-id}/smm/` instead of `~/.claude/xp-agents/{project-id}/smm/`. Falls back to the old path when `CLAUDE_PLUGIN_DATA` is not set (e.g., `--plugin-dir` development mode). Respects custom paths for sandbox and enterprise environments. Cleaned up automatically on `plugin uninstall`.
- **Both user and project scope supported** — project scope installs (`--scope project`) now work correctly for teams. SMM is shared across worktrees via the git-common-dir hash regardless of install scope.
- Install docs updated to show both scope options.

### Stats
- 869 tests (all passing)

## v0.9.48 — Kickoff Rename, Tiered Injection, Behavioral Guide Rewrite

### Changed
- **`/xp-session-review` → `/xp-kickoff`** — renamed skill, gate script (`kickoff_gate.py`), done script (`kickoff_done.py`), marker file (`.needs-kickoff`), all references.
- **Tiered SubagentStart injection** — Explore agents get Intent + Constraints only (~200 tokens). Plan, general-purpose, and background agents get full SMM + behavioral guide (~1000 tokens). xp-* agents skipped (use own preloads). Prevention over inspection.
- **BEHAVIORAL_GUIDE.md rewritten** — declarative, ~260 tokens. XP values underscored by Honesty. Five honesty rules for judgment calls. Each value is a focused paragraph. Added `append.sh` reference so agents know how to record events.

### Removed
- **xp-subagent-reviewer** agent and skill — dead since v0.9.29 (SubagentStop silently drops nudges). Replaced by upfront behavioral guide injection at SubagentStart.
- **Reviewer nudge from subagent_stop.py** — no longer returns anything for non-Plan subagents.

### Stats
- 869 tests (all passing)

## v0.9.47 — Tiered Subagent Context, Remove Dead Reviewer

### Changed
- **Tiered SubagentStart injection** — Explore agents get only Intent + Constraints pillars (~200 tokens). Plan, general-purpose, and background agents get full SMM + behavioral guide (~1000 tokens). xp-* agents skipped (use own preloads). Prevention over inspection — subagents get quality expectations upfront.

### Removed
- **xp-subagent-reviewer** agent and skill — dead since v0.9.29. SubagentStop silently drops `decision:"approve"` with `reason`, so the nudge never reached the agent. The tiered context injection replaces its purpose.
- **Reviewer nudge from subagent_stop.py** — `subagent_stop.py` no longer returns anything for non-Plan subagents.

### Stats
- 869 tests (all passing)

## v0.9.46 — Rename /xp-session-review to /xp-kickoff

### Changed
- **`/xp-session-review` → `/xp-kickoff`** — the skill orchestrates session start (retro → goals → housekeeping), not just review. All references updated: skill directory, gate script (`kickoff_gate.py`), done script (`kickoff_done.py`), marker file (`.needs-kickoff`), docs, tests.

### Stats
- 865 tests (all passing)

## v0.9.45 — Remove Advisory Mode, Doc Refresh

### Removed
- **Advisory enforcement mode** — `load_enforcement_mode()`, `ENFORCEMENT_STRICT`, `ENFORCEMENT_ADVISORY` constants, and all advisory/strict branching removed from `pre_tool_write.py`, `pre_tool_bash.py`, `session_review_gate.py`, `session_start.py`. The `enforcement` key removed from `settings.json`. If a gate is annoying, fix the gate — don't make it optional.
- **`_override_settings()` test helper** — no longer needed without enforcement mode.

### Docs
- **README.md rewritten** — session startup sequence, quality review as skill, PreToolUse split, simplify threshold, configuration section updated.
- **ARCHITECTURE.md updated** — hook map, injection model, plugin structure, session flows, enforcement section all updated for current implementation.
- **SMM_DESIGN.md updated** — injection model, mid-session context, watermarks, conflict detection sections corrected.

### Stats
- 865 tests (all passing)

## v0.9.44 — Token Optimization: File Splits, Hook Targeting, Review Trimming

### Changed
- **PreToolUse split from `*` to targeted matchers** — `pre_tool_write.py` (Write|Edit|MultiEdit) handles conflict detection, TDD order, and plan review gate. `pre_tool_bash.py` (Bash) handles push security gate and file-modification heuristic. Read/Grep/Glob/Agent/Skill no longer trigger PreToolUse at all.
- **Plan review gate uses marker file** — `.plan-awaiting-review` file instead of backward event log scan. Cleared in plan reviewer preload. O(1) check, zero event reads.
- **Simplify gate threshold** — skips `/simplify` when fewer than 3 distinct code files changed. Consolidated duplicate `is_code_file` from simplify_gate into `security.py`.
- **Quality review trimmed** — dropped redundant Clean Code checklist (already covered by /simplify's 3 agents). Focused on courage accountability, drift management, and debt awareness.
- **Quality review preload** — no longer re-injects SMM (inline skill, already in context). Now injects only diff + debt for changed files.
- **session_review_done hook** — no longer re-injects SMM (housekeeping already has agent Read it). Now injects only behavioral guide.
- **Test files split to match code** — `test_pre_tool.py` split into `test_pre_tool_write.py` and `test_pre_tool_bash.py`.

### Added
- **`pre_tool_write.py`** — PreToolUse for Write|Edit|MultiEdit: conflict detection via `.coordination.json`, TDD order tracking, marker-file plan review gate. Zero event log reads.
- **`pre_tool_bash.py`** — PreToolUse for Bash: push security gate, file-modification heuristic (detects `>`, `tee`, `sed -i`, `mv`, `cp` targets and checks against coordination). Advisory only for heuristic, blocks for push gate.
- **`debt_for_files.py`** — quality review preload script that surfaces existing debt events for changed files.
- **Simplify early-exit** — `count_distinct_code_files()` stops scanning at threshold.

### Removed
- **`pre_tool_use.py`** — replaced by `pre_tool_write.py` and `pre_tool_bash.py`.
- **Debt injection from PreToolUse** — moved to quality reviewer preload.
- **Dead `hook_output` code** in `post_tool_use.py`.
- **Redundant SMM injection** from quality review preload and session_review_done hook.

### Stats
- 881 tests (all passing)

## v0.9.43 — Assumption Resolution, Session UX, Quality Courage

### Fixed
- **Assumption accumulation bug** — `compute_resolutions()` lacked a `case "assumption"` branch, so assumptions from plan reviews were never resolvable via `metadata.resolves`. Compaction unconditionally retained them, and `prepare_curation_data()` only filtered via contradictions. This caused 39 stale assumptions to accumulate across 4 sessions. Added resolution mechanism to all three files.

### Added
- **`is_task_notification()` helper** in `_common.py` — shared check for background agent task-notifications, used by both `session_review_gate.py` and `user_prompt_log.py`.
- **Session review gate nudge on `/clear`** — marker content distinguishes "startup" (block) from "clear" (nudge). Mid-session resets no longer hard-block work in progress.
- **Task-notification skip in session review gate** — background agent completions no longer trigger the session review block.
- 8 new tests (887 total)

### Changed
- **Goal collection always runs** — `/xp-goal-collection` now shows existing goals and asks "Any goals for this session?" at every session start, not just when zero goals exist. Supports short-term session goals alongside long-term north star.
- **Quality review emphasizes courage** — Step 1 now defaults to applying simplify recommendations; "low severity" and "it's fine as-is" are explicitly invalid skip reasons.
- **`check_session_needs.sh`** — outputs `GOALS_REVIEW` (always) instead of binary `GOALS_NEEDED`/`Goals: PRESENT`. Added legacy `## Project Goals` fallback for goal display.

### Stats
- 887 tests (all passing)

## v0.9.42 — Tech Debt Cleanup (5 fixes + simplify)

### Fixed
- **Compaction race condition** — `compact_after_curation()` now uses `read_with_lock()` instead of unlocked `read_text()`, preventing data loss when events are appended during compaction.
- **Stale team watermarks** — All `.curation-watermark-*` files are now adjusted by `archived_count` after compaction, not just the primary one. Uses `write_json_atomic()` for crash safety.
- **Conflict nugget missing** — `pre_tool_use.py` now appends a high-severity concern event when a file conflict is detected, for team awareness alongside blocking.
- **Lint false positives** — `run_linter()` now skips files modified less than 1 second ago (mtime debounce), preventing false-positive concern events during rapid edits.
- **repair.py double-parse** — Replaced `parse_jsonl()` + second `json.loads()` loop with single-pass local loop that tracks malformed vs invalid directly. Removed unused `parse_jsonl` import.

### Changed
- **Conflict concern content** — Uses `check_working_on_overlap()` return value directly instead of wrapping with redundant "File conflict:" prefix (found by /simplify).

### Tech Debt Resolved
- Compaction race condition [5887e4db] — closed
- Stale team watermarks [0d8c4376] — closed
- Conflict nugget missing [dbdf1ea0] — closed
- Lint debounce [f7be28f8] — closed
- Repair double-parse [1bb8be5c] — closed

### Remaining
- Quality review stop gate fires too early with background agents [e72d72cd] — needs investigation

### Stats
- 879 tests (all passing)

## v0.9.41 — Event Log Compaction (M6), Prompt Nugget Rewrite, Doc Alignment

### Added
- **M6: Event log compaction** — New `compact_after_curation()` uses curation watermark as the compaction boundary instead of session count. Retains post-watermark events, last 3 session_ends, and SMM-referenced events. Resolved permanent events before the watermark are now archivable (the curated SMM is the durable record). Team safety via min(watermark) across agents.
- **`compact_log.py`** — Housekeeping script (step 9 in SKILL.md) that runs compaction after curation.
- **`_collect_smm_referenced_ids()`** — Collects IDs of active SMM items (unresolved goals, decisions, concerns, etc.) for retention during compaction.
- **`_read_all_curation_watermarks()`** — Supports team mode by reading all `.curation-watermark-*` files and using the oldest as the safe boundary.
- 12 new compaction tests in `TestCompactAfterCuration` (969 total)

### Changed
- **Prompt nugget rewrite** — `prompt_nugget.py` now uses `read_delta` with a dedicated watermark to show only new signal events (concerns, decisions, goals, debt, questions) since last prompt, instead of parsing `SHARED_MENTAL_MODEL.md` directly.
- **Quality review gate** — No longer blocks while simplify subagents are pending. Lets stops through until all subagents complete, then blocks for quality review on the next stop.
- **`compact()` delegates** — Legacy `compact()` function now delegates to `compact_after_curation()`. `PERMANENT_TYPES` constant and `--keep-sessions` CLI arg removed (dead code after policy change).
- **Watermark management** — Compaction resets `.watermark-prompt-nugget` to post-compaction count, updates `.curation-watermark`, and removes orphaned `.watermark-*` files.

### Docs
- **SMM_DESIGN.md** — Updated nugget model: "stop nuggets" replaced with "prompt nuggets (UserPromptSubmit)" throughout. Injection model table, mid-session nuggets section, and layer 3 description all updated.
- **SMM_REFACTOR_MILESTONES.md** — M5 title and body updated for prompt nuggets. Migration safety table updated.
- **README.md** — Token cost model updated: PreToolUse delta rows replaced with single prompt nugget row.
- **xp-subagent-reviewer.md** — Updated delivery mechanism reference from PreToolUse delta to prompt nugget.

### Tech Debt Recorded
- TOCTOU race in `compact_after_curation()` — unlocked read before locked replace
- Stale team watermarks not updated after compaction (solo mode only for now)
- JSONL parsing duplicated in 5 places (M7 cleanup scope)
- Conflict nugget missing from PreToolUse (design spec calls for informational nugget alongside blocking)

## v0.9.40 — Fix Retrospective Preload Overflow, Move Prompt Nugget to UserPromptSubmit

### Fixed
- **Retrospective preload overflow** — `preload.sh` was dumping the entire `.retro-input.json` (100KB+) via `cat`, exceeding Claude Code's output limits. Now strips `events_since_last_retro` array before output, keeping only the structured `digest` (~5KB). The agent prompt already says "Use `digest` for analysis."

### Changed
- **Stop nugget → prompt nugget** — Renamed `stop_nugget.py` to `prompt_nugget.py` and moved from Stop hook to UserPromptSubmit hook. Stop hooks don't support `additionalContext` (caused JSON validation errors); UserPromptSubmit does. Context injection on prompt submission is a better fit — reminds Claude about open intents/risks when starting new work.
- **Prompt nugget reads SMM file directly** — Instead of calling `prepare_curation_data()` (full event log parse, O(n)), now reads `SHARED_MENTAL_MODEL.md` directly (single file read, O(1)). Critical for UserPromptSubmit which fires on every prompt (~5-20x/session vs ~1x for Stop).
- **Stop hooks** — Now 3 hooks (was 4): simplify gate, quality review gate, TDD gate.
- 956 tests (was 957 — removed 2 event-based tests, added 1 SMM-based test + 2 integration tests)

## v0.9.39 — Four-Pillar SMM, Coordination File, Stop Nuggets (M3-M5)

### Added
- **M3: Skill Alignment** — All skills, subagent definitions, and behavioral guide updated to reference four-pillar SMM format (Intent, Constraints, Risks, Wisdom). Preload scripts use anchored dual-format grep (`^## X$`) to work before and after first curation.
- **M4: Coordination file** — `.coordination.json` for O(1) real-time agent conflict detection, replacing O(all_events) event log scanning. PostToolUse updates on every write, PreToolUse reads for overlap checks, SessionEnd clears entries. Stale entries (>30min) filtered automatically. Flock-protected.
- **M5: Stop nugget** — `stop_nugget.py` injects lightweight session checkpoint (~50-80 tokens) at Stop time via `additionalContext`. Uses `prepare_curation_data()` to extract current open intents and unresolved risks.
- **M5: SubagentStart reads from disk** — Prefers curated four-pillar `SHARED_MENTAL_MODEL.md` (written by housekeeping), falls back to `materialize()` for first session.
- `update_coordination()`, `read_coordination()`, `clear_coordination_agent()` helpers in `_common.py`
- 20 new coordination + stop nugget tests (955 total)

### Removed
- **PreToolUse delta injection** — No longer reads event log or injects `<smm-context>`/`<smm-delta>` on every tool call. Context delivered via session start (housekeeping), subagent start (disk read), and stop nuggets.
- **Tier classification system** — `classify_tier()`, `TIER_FULL`, `TIER_BLOCKING`, `TIER_RED_ONLY` removed from `pre_tool_use.py`. No longer needed without delta injection.
- **`materialize` and `read_delta` imports** from `pre_tool_use.py`

### Changed
- **Conflict detection** — `check_working_on_overlap()` now reads `.coordination.json` instead of scanning events. Signature changed from `(events, agent_id, ...)` to `(smm_dir, agent_id, ...)`.
- **Debt injection** — Still in PreToolUse for write tools, but no longer tied to tier system.
- **Stop hooks** — Now 4 hooks (was 3): simplify gate, quality review gate, TDD gate, stop nugget.
- **Simplify gate message** — Removed specific "30 seconds" wait time, encourages patience instead.

### Fixed
- **`save_retrospective.py` missing `sys.path` setup** — Script failed with `ModuleNotFoundError` for `_append_impl`. Added standard `sys.path.insert` calls matching all sibling scripts.
- **`check_questions.sh` substring collision** — `grep "## Intent"` matched `## Customer Intent` as substring. Fixed with anchored patterns (`^## Intent$`).
- **TOCTOU in `clear_coordination_agent`** — Removed premature `exists()` check before locking.

## v0.9.38 — Retrospective Helper & Navigator Cleanup

### Added
- **`save_retrospective.py` helper script** — encapsulates retrospective write-side plumbing (event append, file write, materialize) into a single script that accepts K/F/T JSON on stdin. Reduces retrospective agent tool calls from ~17 to ~3.
- 5 new tests for `save_retrospective.py` (907 total)

### Removed
- **`pair_guidance` event type** — removed from schema, validation, formatting, and stats. The navigator was deleted in v0.9.37 (SubagentStop limitation); this completes the cleanup.
- **`pair-programming` skill** — dead code since navigator removal. Quality review functionality already covered by `/xp-quality-review`.
- **Navigator health check in retrospective** — stopped false "CRITICAL: 0 navigator guidance" alarm that fired in 4 consecutive retrospectives.

### Changed
- **Retrospective agent prompt** — Actions section simplified from 3 manual steps (append.sh + Write + materialize) to a single `save_retrospective.py` pipe command.
- **Session start SKILLS_TEXT** — removed `/pair-programming` reference (2 skills remain: `/smm-protocol`, `/xp-values`).

### Fixed
- **Stale lint concerns** — recorded as technical debt. Lint hook fires on intermediate file states during rapid edits, producing false positives that auto-resolve but clutter the SMM.

## v0.9.37 — Hook UX & Materializer Bug Fix

### Added
- **statusMessage for all hooks** — every hook in `hooks.json` now shows descriptive spinner text while running (e.g., "Checking shared mental model...", "Running lint check...")
- **systemMessage support** — hooks can now show user-facing notifications separate from agent-only `additionalContext`. New `block_output()` helper in `_common.py` encapsulates the block+systemMessage pattern.
- **PLUGIN_TOOLS.md documentation** — documents `statusMessage` (config), `systemMessage` (output), and `additionalContext` fields with examples and audience table.
- 2 new tests for resolved decision filtering (910 total)

### Fixed
- **Resolved decisions still rendered in materializer** — `render_markdown()` listed all decisions including resolved ones in the Architecture Decisions section. Now filters through `decision_resolutions` index, consistent with how concerns, goals, and debt are already filtered.
- **Unused `json` import in tdd_stop_gate.py** — removed (flagged by lint last session).

### Changed
- **Stop gates use `block_output()`** — `quality_review_gate.py`, `simplify_gate.py`, and `tdd_stop_gate.py` now use the shared helper instead of inline JSON construction, adding user-facing messages.
- **`BlockedError` supports `system_message`** — optional parameter for user-facing notifications on blocked tool calls.

## v0.9.36 — Direct SMM Loading & Simplify Gate Timing

### Added
- **Direct SMM + Behavioral Guide loading in housekeeping skill** — new `load_context.sh` script materializes the SMM after triage and outputs file paths. Step 5 in SKILL.md instructs the skill to Read both files, ensuring they are first-class conversation content rather than relying on `additionalContext` injection.
- 3 new integration tests for `load_context.sh` (908 total)

### Changed
- **Simplify gate message includes wait instruction** — tells the agent to wait 30 seconds for background review agents to complete before checking results, reducing premature TaskOutput failures.

## v0.9.35 — Session Review Gate Fix for /clear

### Fixed
- **Session review gate not firing after `/clear`** — `session_start.py` previously returned `None` immediately for `source="clear"`, skipping marker creation and context injection. After `/clear`, the session review gate never blocked, allowing retrospectives to be silently skipped. Now treats "clear" as a fresh start like "startup": sets `.needs-session-review` marker and injects GUPP + skills context.

### Changed
- **Module docstring updated** — reflects all handled SessionStart sources (startup, resume, compact, clear)
- 4 new tests (903 total)

## v0.9.34 — Decision Resolution & Stop Message Cleanup

### Fixed
- **Resolved decisions still flagged as stale drift** — `compute_resolutions()` now tracks `decision_resolutions` alongside concern/goal/debt resolutions. `detect_drift_signals()` skips topics where all decisions are resolved. Eliminates false "stale decision" drift signals for completed work.

### Changed
- **Quality gate stop messages simplified** — pending-agents message now just says count and to wait. Quality review message shortened to "Run the /xp-quality-review skill before stopping."
- 2 new tests (900 total)

## v0.9.33 — Auto-Resolve Lint Concerns

### Added
- **Auto-resolve lint concerns** — `lint_check.py` now resolves unresolved lint concerns when lint passes for a file. Matches by file path so only concerns for the specific file are resolved. Mirrors the existing test concern auto-resolve pattern.
- **`LINT_CONCERN_PREFIX`** constant in `_common.py` — shared prefix for lint concern content matching.
- **`resolve_concerns()` shared helper** in `_common.py` — parameterized concern resolution accepting a matcher function, agent ID, and label. Eliminates duplication between test and lint resolution.
- 4 new tests (898 total)

### Changed
- **`_resolve_test_concerns`** in `bash_post_tool.py` — now delegates to `_common.resolve_concerns()` instead of duplicating the resolution logic.
- **Resolved Concerns section** in materializer — shows summary count instead of per-item listing to reduce SMM bloat.

### Removed (via /simplify)
- **`_make_event()` / `_append_safe()` wrappers** in `bash_post_tool.py` — redundant pass-through wrappers replaced with direct `_common.*` calls.

## v0.9.32 — Async Agent Timing Fix

### Fixed
- **Quality review gate fires too early** — when `/simplify` spawns background agents, the Stop hook no longer triggers quality review before those agents complete. The gate now detects pending subagents (started but not completed) and blocks with agent IDs and actionable guidance until they finish.
- **`stop_hook_active` bypass removed from quality gate** — the early-return on `stop_hook_active=True` prevented the gate from re-checking after pending subagents completed. Removed since the tracker-based idempotency check already prevents infinite loops.

### Added
- **SubagentStart event recording** — `subagent_start.py` now appends a `STATUS` event (`"Subagent {id} started"`) after writing the watermark. Pairs with existing `"Subagent {id} completed"` from SubagentStop for lifecycle tracking.
- **`_pending_subagent_ids()` helper** in `quality_review_gate.py` — scans events since loop boundary for started-but-not-completed subagents.
- **`subagent_started_content()` / `subagent_completed_content()`** in `_common.py` — canonical format helpers eliminating magic string coupling across `subagent_start.py`, `subagent_stop.py`, and `quality_review_gate.py`.
- 8 new unit tests, 1 integration test (895 total)

### Assumption
- SubagentStart hooks fire for background Agent tool calls (`run_in_background=true`). Load-bearing for the entire approach. Needs empirical verification after deploy.

### Stats
- 895 tests (894 + 1 new integration)

## v0.9.31 — Speed Up Session Review

### Added
- **`bulk_append()`** — multi-event atomic writes with single lock acquisition. Validates all events before acquiring lock (fail-fast, no partial writes). `bulk_append_safe()` wrapper filters invalid events and swallows lock errors for hook safety.
- **`resolve_prefix()`** — short-ID prefix resolution in `compute_resolutions()`. Supports 8-char prefixes from materialized output.
- **Auto-resolve test concerns** — `bash_post_tool.py` now resolves unresolved test-failure concerns when tests pass (`failed == 0`). Fixes stale concern accumulation at the source rather than in housekeeping.
- **Retro digest** — structured summary in `.retro-input.json` replaces raw event dump: `signal_events` (full dicts for decisions/concerns/etc.), `status_summary` (counts + samples), `concern_groups` (deduplicated by normalized content). ~2-5KB vs 88KB.
- **`TEST_CONCERN_RE`** shared constant in `_common.py` — used by both `tdd_stop_gate.py` and `bash_post_tool.py`.
- 21 new tests (887 total)

### Changed
- **Retrospective agent prompt** — updated to consume digest format, preferring `digest` over raw `events_since_last_retro`.
- **`tdd_stop_gate.py`** — imports `TEST_CONCERN_RE` from `_common` instead of defining locally.

### Fixed (via /simplify)
- **Input mutation** — `bulk_append` no longer mutates caller's event dicts (shallow copy when ANSI stripping needed).
- **Hot-path cost** — `_resolve_test_concerns` does early-exit scan for test concerns before expensive `compute_resolutions`.
- **Redundant import** — `_normalize_concern_content` uses module-level `re` instead of re-importing.

## v0.9.30 — Plan Review Gate via PreToolUse + Documentation Update

### Changed
- **Plan review mechanism** — SubagentStop writes `plan_awaiting_review` marker event instead of blocking. PreToolUse detects unreviewed plans and injects `additionalContext` nudge before writes. Two-step mechanism replaces the exit-2 block that caused planning loops.
- **Documentation updated** — ARCHITECTURE.md and README.md updated to reflect v0.9.29 changes: navigator removal, TaskCompleted removal, plan review gate, concern deduplication, quality review drift management, SMM injection trigger change, platform findings.

## v0.9.29 — Remove Navigator & TaskCompleted, Fix Planning Loop

### Fixed
- **Planning loop** — SubagentStop was blocking Plan agent output (`decision:"block"`), preventing the plan from reaching the main agent and causing infinite re-planning loops (ran 8 hours, 6.1MB events.jsonl, ~60,000 duplicate concerns). Changed to nudge (`decision:"approve"` with reason). Note: platform silently drops nudge reasons on SubagentStop, but the plan output now reaches the agent.
- **Duplicate concerns** — `detect_conflicts()` now deduplicates against existing unresolved concerns before generating new ones. Resolved concerns excluded from dedup so recurring conflicts are re-detected.
- **TaskCompleted hook blocking** — Removed entirely. Was blocking the first task in every group because no `pair_guidance` event existed yet.
- **Quality review preload permission** — Added missing `Bash(*/skills/*/scripts/*)` to xp-quality-review skill allowed-tools.
- **SMM injection trigger** — Changed from `/xp-session-review` to `/xp-housekeeping` because the orchestrator skill returns immediately while sub-skills do the work.

### Removed
- **Navigator subagent** — `agents/xp-navigator.md` and `skills/xp-navigator/` deleted. SubagentStop only supports `decision:"block"` (caused loop) or silence; nudges via `decision:"approve"` are silently dropped by the platform. Concerns already visible via SMM delta for writes.
- **TaskCompleted hook** — `scripts/task_completed.py` deleted, hook entry removed from `hooks.json`. Too granular (per-task not per-conversation-turn) for useful enforcement.
- **Navigator Guidance materializer section** — A7 section removed from `materialize.py`. pair_guidance events still valid in logs but no longer rendered.
- **Navigator nudge in PreToolUse** — "Run /xp-navigator" no longer injected before writes.

### Added
- **Drift management in quality review** — New Step 3 in `/xp-quality-review` skill checks code changes against recorded decisions and conventions. Records concerns for drift. Replaces the strategic alignment review the navigator was doing.
- **Concern deduplication with resolution awareness** — `detect_conflicts()` uses `compute_resolutions()` to exclude resolved concerns from dedup set, allowing recurring conflicts to be re-detected after resolution.

### Changed
- **BEHAVIORAL_GUIDE.md** — Navigator references replaced with reviewer references.
- **`subagent_stop.py`** — Dead `BlockedError` handler removed from `__main__`.
- **Stale question concern content** — Changed from dynamic event count to stable string for reliable deduplication.

### Platform Findings
- **SubagentStop only supports block or silence** — `decision:"approve"` with `reason` is silently dropped. No `additionalContext` support. This limits enforcement options for plan review.
- **TaskCompleted fires per-task** — Not per-conversation-turn. Too granular for hooks that need conversation-level state (like "has navigator run?").

### Stats
- 858 tests (down from 872 — removed navigator and TaskCompleted tests, added dedup and concern injection tests)

## v0.9.26 — Deterministic SMM + Behavioral Guide Injection

### Added
- **`session_review_done.py`** — PostToolUse:Skill hook that fires after `/xp-session-review` completes. Materializes SMM and injects both the fresh SMM and BEHAVIORAL_GUIDE.md as `additionalContext` in a single deterministic step.
- 6 new tests for session_review_done (867 total)

### Changed
- **Behavioral guide moved out of SessionStart** — `session_start.py` no longer injects BEHAVIORAL_GUIDE.md. It's now injected by `session_review_done.py` after session review, together with the fresh SMM. This ensures the two are loaded together, in order: SMM first, then behavioral guide.
- **`xp-session-review` skill simplified** — removed manual materialize step (step 4). The PostToolUse:Skill hook handles it deterministically.

### Fixed
- **Test marker leak** — `test_graceful_no_smm_dir` passed a nonexistent `smm_dir` with `source="startup"`, causing `session_start.run()` to fall through to `init.sh` which resolved to the real project's SMM dir and created `.needs-session-review` there. This happened on every test suite run (including lefthook pre-commit), causing the session review gate to block mid-session. Fixed by mocking `resolve_plugin_root` in the test.

### Tech Debt Recorded
- `bash_failure.py` records false "Test command failed" concerns for compound Bash commands where a non-test command (e.g. `ls`) exits non-zero but the test itself passed. The TDD stop gate then sees the stale failure concern and blocks.

## v0.9.24 — Event Lifecycle System

### Added
- **Event lifecycle resolution** — `metadata.resolves` mechanism for explicitly closing goals, concerns, and debt. The materializer is a pure view: renders open vs. resolved, no heuristic aging or pruning.
- **`/xp-session-review`** — orchestrator skill that sequences retro → goals → housekeeping at session start. Enforced by dual gates.
- **`/xp-housekeeping`** — lifecycle triage skill. Reviews open goals, unresolved concerns, draft decisions, and technical debt. Asks user for status, records resolutions.
- **Session review gate (UserPromptSubmit)** — `session_review_gate.py` blocks prompts until `/xp-session-review` runs. Allows the command itself through.
- **Session review gate (PreToolUse)** — defense-in-depth, blocks ALL tools when `.needs-session-review` marker exists. xp-agents skip via recursion prevention.
- **Completed Goals** reference section in materialized SMM
- **ANSI escape code stripping** at write time in `_append_impl.py`
- **Concern content truncation** to 500 chars in materialized output
- 28 new tests (858 total)

### Changed
- **`session_start.py` slimmed** — no longer injects SMM or nudges. Writes `.needs-session-review` marker, injects behavioral guide + GUPP + skills only. Fresh SMM is injected after session review completes via PreToolUse delta.
- **`compute_resolutions()` rewritten** — uses `metadata.resolves` as sole resolution mechanism for goals, concerns, and debt. Old `references`-based concern resolution removed.
- **Agent status scoped to current session** — prior session agents no longer appear in materialized SMM
- **Open debt only** in Technical Debt section — resolved debt filtered out

### Fixed
- **`session_review_gate.py` SMM dir resolution** — was passing None to `try_validate_smm_dir`, making gate dead code in production
- **Marker deletion timing** — marker now cleared only when session review completes (step 4), not when it starts. Prevents gate bypass if review aborted.

## v0.9.20 — Security Review Hook, TDD unittest Detection, Preload Permission Fix

### Fixed
- **Push gate proper fix** — replaced second-push bypass with PostToolUse:Skill hook (`security_review_done.py`) that writes the `.security-reviewed-{hash}` tracker only when `/security-review` actually completes
- **TDD stop gate blind to unittest** — `bash_post_tool.py` only detected pytest/jest/go test. Added `python3 -m unittest` detection and result parsing so the TDD stop gate has data to work with
- **Skill preload permissions** — `!` command preloads go through the same Bash permission check as user commands. Fixed by adding `allowed-tools` patterns (e.g., `Bash(*/skills/*/scripts/*)`) to skill frontmatter to pre-approve preload scripts
- **Navigator allowed-tools cleanup** — removed redundant `Bash(*/preload.sh)` from navigator skill; `Bash(*/skills/*/scripts/*)` already covers it

### Added
- `scripts/security_review_done.py` — PostToolUse:Skill hook that writes security tracker after `/security-review` completes
- PostToolUse:Skill hook entry in `hooks.json`
- unittest result parser in `bash_post_tool.py` (handles `Ran N tests`/`FAILED (failures=X, errors=Y)`)
- Integration test for unittest detection pipeline

### Discovered
- **bash_failure.py false positive** — lefthook ruff formatting failures get misclassified as "Test run failed (pytest)" because the full lefthook output contains test-like patterns. The TDD stop gate then blocks on a non-test failure. Needs investigation.
- **Plugin cache requires version bump** — `/reload-plugins` alone isn't sufficient if the version in `plugin.json` hasn't changed. Bump version to force cache invalidation.

## v0.9.19 — Preload Fix, Navigator Gate, Push Gate Fix

### Fixed
- **Skill preload permissions** — removed `!`command`` preloads from all 7 skills that failed with Bash permission errors. Forked skills now load data via `Read` + `Bash(*/init.sh)` in `allowed-tools`. Inline skills reference SMM context already in conversation.
- **Push gate stuck** — second push attempt after security review now auto-clears the gate by detecting the existing `security_review_requested` event for the current HEAD.

### Added
- **Navigator gate on TaskCompleted** — blocks task completion unless navigator guidance (`pair_guidance` event) has been provided. Second attempt allows through to prevent infinite loops. Addresses the retro finding that navigator produced 0 guidance events.
- **Inline retrospective data** — SessionStart now includes session health signals, key event summaries, and K/F/T analysis instructions directly in `additionalContext`, so the main agent can perform retrospective analysis without needing to invoke the `/xp-retrospective` skill separately.

### Changed
- `retrospective.py` — enriched `_build_context_summary` with health signals (navigator silence, concern resolution ratio, draft decisions) and condensed key event list
- `task_completed.py` — converted from quality-reviewer nudge to navigator gate + quality-reviewer nudge

### Discovered
- **Agent hooks broken** — `type: "agent"` hooks fail on all events with "Messages are required for agent hooks. This is a bug." Platform issue in Claude Code, not fixable from plugin side. Use command/prompt hooks or forked skills instead.
- **`!`command`` preloads not auto-approved** — plugin skill preload scripts go through the same Bash permission check as user commands. No plugin-level permission override exists.
- **Dead code** — `prompts/tdd_check.md` (unused prompt hook file), 8 preload shell scripts (no longer referenced from SKILL.md)

## v0.9.17 — Skill-Based Agent Execution

### Added
- `docs/PLUGIN_TOOLS.md` — comprehensive reference for all plugin tool types (hooks, skills, subagents) and their data flows
- `skills/xp-goal-collection/` — inline skill for first-session goal collection (split from customer-proxy)
- `skills/xp-question-triage/` — inline skill for question triage and intent reconciliation (split from customer-proxy)
- `skills/xp-navigator/` — forked skill wrapping the navigator subagent with `!`command`` preload
- `skills/xp-quality-reviewer/` — forked skill wrapping the quality reviewer subagent
- `skills/xp-plan-reviewer/` — forked skill wrapping the plan reviewer subagent
- `skills/xp-retrospective/` — forked skill wrapping the retrospective subagent
- `skills/xp-subagent-reviewer/` — forked skill wrapping the subagent reviewer subagent
- `skills/_preload_base.sh` — shared preload base for deterministic SMM state injection via `!`command``
- Security review carryforward — when diff between last reviewed commit and HEAD contains only non-code files, carry forward the review instead of blocking
- `_common.is_code_file()` and `_common.diff_has_code_changes()` — shared code/non-code classification for security review carryforward

### Changed
- All hook nudge messages now say "Run /skill-name" instead of "Invoke the subagent"
- Customer-proxy functionality split into two focused skills for better auto-matching
- `lefthook.yml` — shellcheck now uses `-x -e SC1091` for source following

### Removed
- `agents/xp-customer-proxy.md` — replaced by inline skills `/xp-goal-collection` and `/xp-question-triage`
- `skills/xp-customer-proxy/` — replaced by the two focused skills above

### Design decisions
- **Inline skills for user interaction** — customer-facing skills run inline in the main agent for full tool access (AskUserQuestion, Bash)
- **Forked skills for analysis** — reviewer/navigator skills use `context: fork` + `agent:` to delegate to existing subagents with preloaded SMM state
- **`!`command`` for deterministic setup** — preload scripts run before skill content loads, agent cannot skip them
- **Security review carryforward** — fail-closed design: assumes code changes on error, only skips review when diff is provably non-code
- **Split customer-proxy** — single-responsibility: goal collection is first-run, question triage is ongoing. Better description matching for auto-invocation

## v0.9.0 — Milestone 8: Hardening & Optimization

### Added
- `smm/compact.py` — Log compaction: archives old events, keeps permanent types (decision, convention, goal, debt, assumption, retrospective) + unresolved questions/concerns + last N sessions. Configurable `keep_sessions` (default 3). Archives to `backups/archive-{ts}.jsonl`. Removes all watermarks after compaction. Registered as PostCompact hook
- `smm/repair.py` — Log recovery: skips malformed JSON, validates required fields, deduplicates by event ID, sorts by timestamp. Backs up original to `backups/pre-repair-{ts}.jsonl`. Writes `.repair-report.json`. Supports `--dry-run`
- `smm/migrate.py` — Schema versioning framework: additive-only migrations with `CURRENT_VERSION = 2`. v1→v2: normalize timestamps to include timezone. Events with `schema_version > CURRENT` pass through unchanged (forward-compatible)
- **Drift Signals** (A8) — New Active Context section in materializer. Detects: stale decisions (topic with no activity in 5+ sessions), ignored conventions (3+ unresolved concerns referencing convention). Event-log-only analysis, no codebase I/O
- **Velocity** (A9) — New Active Context section in materializer. Metrics: events this session, total sessions, decisions made/revisited, churn topics (3+ decisions on same topic), concern resolution ratio
- Performance benchmarks — `materialize()` <100ms/100 events, <500ms/1000, <2000ms/5000. `read_delta()` <50ms/1000@500. `compact()` <1000ms/5000. `repair()` <1000ms/5000
- Watermark isolation tests — 3 agents concurrent delta read, each gets independent watermark
- Integration tests for compact/repair/migrate — subprocess-level: compact then session_start, repair corrupted then materialize, migrate idempotent re-run
- 66 new tests (802 total: 98 SMM + 188 engine + 415 hooks + 101 integration)

### Changed
- `smm/schema.json` — `schema_version` now allows values `[1, 2]`
- `hooks/hooks.json` — Added PostCompact hook for `compact.py` (5s timeout)
- `smm/materialize.py` — Two new Active Context sections: Drift Signals (A8) and Velocity (A9). Now has `detect_drift_signals()` and `compute_velocity()` functions

### Design decisions
- **Compact retention: 3 sessions + permanent types** — configurable via `keep_sessions`. Unresolved questions/concerns always retained regardless of age
- **Repair strategy: skip, don't fix** — malformed lines dropped, not corrected. Dedup + sort. Dry-run for inspection
- **Schema v2 is minimal** — proves the migration framework works. Real schema evolution (e.g., `backlog_item`) happens in M9+
- **Drift thresholds hardcoded** — stale=5 sessions, ignored=3 concerns. Can add settings later
- **Velocity always in Active Context** — actionable signal, not archival. Informs current session behavior
- **No new event types** — all M8 analysis uses existing event types
- **compact.py as PostCompact hook** — runs after Claude Code's built-in compaction

## v0.8.0 — Milestone 7: Integration Testing & Packaging

### Added
- `.claude-plugin/marketplace.json` — marketplace publishing manifest with owner, plugin name, and description
- `TestPluginIntegrity` (9 tests) — validates marketplace.json, plugin.json, hooks.json script references, agent files, skill files, settings.json, behavioral guide, and no external dependencies
- `TestFullSessionLifecycle` (1 test) — chains session_start → pre_tool_use(Write) → post_tool_use → session_end, verifying event accumulation, working_on propagation, and subagent nudges at each step
- `TestPlanReviewFlow` (2 tests) — Plan subagent blocks with plan-reviewer instruction, regular subagent nudges subagent-reviewer
- `TestThreeSessionAccumulation` (1 test) — 3-session retro data accumulation, verifying cross-session trend visibility in `.retro-input.json` previous_retros
- `TestCompactionReinjection` (1 test) — seed → pre_compact → truncate → session_start verifies SMM re-injection after compaction
- `TestLargeEventLog` (3 tests) — 1000 events through pre_tool_use, materialize, and retrospective without error
- `TestConcurrentAgentWrites` (1 test) — 5 workers run full subagent lifecycle concurrently, no event corruption, no duplicate IDs
- `TestWorktreeSharing` (1 test) — git worktree derives same SMM path as main repo, events visible from both locations
- `TestEmptyProject` (2 tests) — fresh git repo with no events, session_start nudges for goals, pre_tool_use produces navigator nudge
- 21 new tests (736 total: 228 SMM + 131 engine + 415 hooks + 92 integration)

### Design decisions
- **marketplace.json follows Claude Code marketplace format** — name, owner, plugins array with source and description
- **Edge cases tested via subprocess** — all tests run scripts as subprocesses matching production execution
- **Worktree test auto-skips** when git worktree add fails (CI environments without worktree support)
- **Concurrent test uses ThreadPoolExecutor** with 5 workers, verifies flock-based serialization holds under contention

## v0.7.0 — Milestone 6.5: Agent Hook to Plugin Subagent Migration

### Changed
- **Agent hooks replaced with plugin subagents** — Agent hooks (type: "agent" in hooks.json) can only use Read/Grep/Glob tools (confirmed empirically: Bash test failed). They cannot write events via `append.sh` or return advisory guidance. All 6 agent hook prompts have been converted to plugin subagents in `agents/` directory with full tool access (Bash, Read, Write, Edit, AskUserQuestion)
- **Command hooks now trigger subagents** via `additionalContext` injection (nudge) or exit 2 blocking (deterministic):
  - `pre_tool_use.py` — nudges xp-navigator for Write/Edit/MultiEdit
  - `post_tool_use.py` — nudges xp-quality-reviewer (background), returns additionalContext
  - `retrospective.py` — nudges xp-retrospective when retro data available
  - `session_start.py` — nudges xp-customer-proxy when goals missing or open questions
  - `subagent_stop.py` — blocks for Plan subagents (xp-plan-reviewer), nudges xp-subagent-reviewer for others
- **hooks.json** — all type: "agent" entries removed. Only type: "command" and one type: "prompt" (tdd_check.md) remain
- `plan_review.py` command hook removed (redundant with plan reviewer subagent)

### Added
- `agents/xp-navigator.md` — pair programming guidance (haiku, preloads smm-protocol + pair-programming skills)
- `agents/xp-quality-reviewer.md` — courage + simplicity code review (haiku, background: true)
- `agents/xp-retrospective.md` — Keep/Fix/Try analysis (inherit, preloads smm-protocol + xp-values skills)
- `agents/xp-customer-proxy.md` — goal collection + question triage (inherit, foreground for AskUserQuestion)
- `agents/xp-plan-reviewer.md` — plan size/TDD/decision review (inherit, preloads smm-protocol + xp-values)
- `agents/xp-subagent-reviewer.md` — holistic output review (haiku, background: true)

### Removed
- `prompts/navigator.md`, `prompts/quality_reviewer.md`, `prompts/retrospective_analyst.md`, `prompts/customer_proxy.md`, `prompts/plan_reviewer.md`, `prompts/subagent_reviewer.md` — replaced by plugin subagents
- `scripts/plan_review.py` — deterministic checks redundant with plan reviewer subagent

### Design decisions
- **Agent hooks are read-only gates** — confirmed empirically. Only use for ok/not-ok gating (tdd_check.md)
- **Plugin subagents have full tool access** — Bash, Write, Edit, AskUserQuestion all work
- **Nudge for frequent triggers, block for critical ones** — navigator nudges every write, plan reviewer blocks once per plan
- **background: true for async reviewers** — quality reviewer and subagent reviewer always run in background
- **skills preloaded into subagents** — subagents don't inherit parent skills, must list explicitly

## v0.6.0 — Milestone 6: CLAUDE.md & Skills

### Added
- `BEHAVIORAL_GUIDE.md` at plugin root — XP behavioral rules for the main agent, covering the Honesty Principle (7 rules), XP values as concrete behaviors, skills reference library with invocation guidance, session lifecycle protocol, code quality rules, and courage commitments. Loaded at runtime by `session_start.py` via `_load_behavioral_guide()` with `lru_cache` and graceful degradation
- `skills/smm-protocol/SKILL.md` — Event recording reference. All 16 event types with when-to-use, required fields, priority guide, `working_on`/`references` usage, common recording patterns, good vs. bad event examples
- `skills/xp-values/SKILL.md` — XP values as behavioral guide. Communication, Simplicity, Feedback, Courage, Respect as concrete behaviors with practical examples. Value priority when they conflict. Values in practice (design decision and code review examples)
- `skills/pair-programming/SKILL.md` — Pair programming protocol. Driver/navigator dynamic, responding to guidance, quality reviewer severity levels, conflict resolution, debt in pair programming, session flow walkthrough
- 14 new tests (730 total: 228 SMM + 131 engine + 422 hooks + 79 integration)

### Changed
- `scripts/session_start.py` — Behavioral guide injected between enforcement indicator and GUPP in `additionalContext`. Updated `SKILLS_TEXT` descriptions to match actual skill frontmatter and emphasize "invoke these regularly"
- Injection order: SMM → enforcement → behavioral guide → GUPP → skills

### Design decisions
- **Inject via `additionalContext`, not plugin CLAUDE.md** — CLAUDE.md is not an official plugin component per the plugin reference docs. Only `additionalContext` from hooks is reliable for installed plugins
- **BEHAVIORAL_GUIDE.md as data file** — keeps content editable without touching Python. Loaded at runtime by `session_start.py`
- **Skills prominently referenced in guide** — skills are voluntary (not enforced by hooks), so the guide drives regular usage with explicit "invoke when" instructions
- **Complementary, not duplicative** — guide covers main agent behavior gaps; hook prompts cover their specific agents

## v0.5.5 — Milestone 5.5: Security Review Gate

### Added
- Push gate in `pre_tool_use.py` — detects `git push` in Bash commands, blocks until `.security-reviewed-{HEAD-hash}` tracker exists. Writes `security_review_requested` event on block. Strict mode blocks (exit 2), advisory mode warns
- Path 1 detection in `user_prompt_log.py` — scans user prompt for `/security-review`, `security review`, `security audit` patterns. On match, writes HEAD-keyed tracker file
- Path 2 detection in `subagent_stop.py` — scores `last_assistant_message` against 6 security review output signals (security review heading, severity markers, vulnerability mentions). Threshold of 2+ prevents false positives. On match, writes tracker
- Security helpers in `_common.py` — `get_head_hash()`, `security_tracker_path()`, `security_tracker_exists()`, `write_security_tracker()`, `_cleanup_old_security_trackers()`. Hash validation (`^[0-9a-f]{7,40}$`) prevents path traversal
- `security_review_requested` event type in `_append_impl.py` and `schema.json`
- Security lens in `retrospective_analyst.md` — analyzes `security_review_requested` events through Courage value, surfaces gaps as Fix items
- 42 new tests (711 total: 228 SMM + 406 hooks + 77 integration)

### Design decisions
- **Three detection paths** — security reviews detected via user prompt (Path 1), subagent output (Path 2), or push gate request (Path 3). No reliance on agent cooperation
- **Gate on invocation, not outcome** — checks if a review was run, not what it found
- **Commit hash keying** — new commits invalidate tracker, same HEAD passes without re-review
- **No new hook registrations** — all logic fits into existing PreToolUse, UserPromptSubmit, SubagentStop hooks

## v0.5.4 — Milestone 5.4: Auto-Simplify at Loop End

### Added
- `scripts/simplify_gate.py` — Stop command hook. Detects file changes in the current loop (events since last `customer_input` with non-empty `working_on`). Blocks stop (exit 2) with instruction to run `/simplify`. Tracker file (`.simplify-{agent_id}.json`) prevents re-triggering after simplify runs. New loop (new `customer_input`) resets tracker
- `scripts/bash_failure.py` — PostToolUseFailure command hook (Bash). Captures failed test runs that `bash_post_tool.py` never sees (PostToolUse only fires on success). Writes status + concern events for failed test commands
- `hooks/hooks.json` — Added `simplify_gate.py` command hook to Stop section, added `PostToolUseFailure` section with `bash_failure.py` for Bash matcher
- SessionStart matcher updated from `startup|resume|compact` to `startup|resume|compact|clear` — SMM now re-injected when user runs `/clear`
- 31 new tests (653 total)

### Fixed
- `prompts/tdd_check.md` — Changed output format from `{"decision": "block"/"allow"}` to `{"ok": true/false, "reason": "..."}`. Prompt hooks must use the `ok`/`reason` format per the Claude Code hooks API

### Design decisions
- **No prompt hook for simplify** — hooks within the same Stop entry run in parallel, so command hook's `additionalContext` is not visible to a prompt hook. Command hook blocks directly via exit 2
- **Tracker keyed on loop_id** — last `customer_input` event ID. New loop = new ID = fresh trigger. No explicit clearing needed
- **`stop_hook_active` guard** — prevents infinite loops when agent retries after being blocked

## v0.5.3 — Milestone 5.3: Debt & Goal Integration

### Added
- `load_enforcement_mode()` in `_common.py` — reads `enforcement` from `settings.json`, defaults to `"strict"`. Supports `"strict"` and `"advisory"` modes
- `find_debt_for_file()` in `_common.py` — filters debt events by target file with path normalization
- `extract_active_context()` in `materialize.py` — splits materialized view at REFERENCE boundary, returns Active Context section only
- Active Context injection for TIER_BLOCKING (non-commit Bash) in `pre_tool_use.py` — replaces delta with materialized Active Context view
- Debt injection for write tools in `pre_tool_use.py` — looks up debt events for the target file and injects them into `additionalContext`
- Advisory enforcement mode — `pre_tool_use.py` converts `BlockedError` to warning, appends `[enforcement: advisory]` indicator
- `session_start.py` — injects `[enforcement: advisory]` indicator when in advisory mode so agent/prompt hooks see it
- `settings.json` — added `"enforcement": "strict"` default
- 26 new tests (609 total)

### Changed
- `pre_tool_use.py` — TIER_BLOCKING now uses `materialize()` + `extract_active_context()` instead of `read_delta()` for non-commit Bash
- `prompts/customer_proxy.md` — added goal collection (first-run) and intent reconciliation behaviors before question triage
- `prompts/navigator.md` — added Debt Awareness section: nudges driver to address debt when modifying files with known debt
- `prompts/quality_reviewer.md` — can now write `debt` events for acknowledged tradeoffs; checks if file debt was addressed
- `prompts/retrospective_analyst.md` — debt escalation in Fix items (aging markers), plugin health analysis from session stats, can write `debt` events for deferred fixes

## v0.5.2 — Milestone 5.2: SMM Enhancements — Schema & Materializer

### Added
- 3 new event types: `goal` (🎯 prefix), `debt` (requires `files`, with session-based aging), `customer_intent` (requires `intent_status`: open/delivered/superseded)
- Two-tier materialized view: Active Context (goals, conflicts, blocking questions, unacknowledged concerns, customer intent, agent status, navigator guidance) and Reference (decisions, conventions, resolved questions, discoveries, assumptions, technical debt, resolved concerns)
- Debt aging in materializer — counts `session_end` events after debt timestamp using `bisect`. 0–3 normal, 4–6 ⚠️, 7+ 🔴
- Session stats in `.retro-input.json` — pair_guidance_count, status_count, concerns raised/resolved, questions open/answered, decisions total/draft
- `compute_resolutions()` in `_append_impl.py` — shared resolution tracking used by materializer, retrospective, session_end, and detect_conflicts
- `read_with_lock()`, `write_watermark()` centralized in `_append_impl.py`
- `PRIORITY_BLOCKING`, `PRIORITY_ASSUMED`, `PRIORITY_INFO` constants in `_append_impl.py` (replace `PRIORITY_RED`)
- 34 new tests (585 total: 228 SMM + 309 hooks + 50 integration)

### Changed
- `materialize.py` — complete render rewrite to two-tier structure. Navigator guidance scoped to current session. Customer Input section removed
- `read_delta.py` — `format_delta()` handles goal, debt, customer_intent types
- `_append_impl.py` centralized as foundational module — `materialize.py`, `read_delta.py`, `_common.py` import shared functions instead of duplicating (6 functions deduplicated)
- `prompts/customer_proxy.md` — updated section references for two-tier SMM

### Security
- Watermark read uses `O_NOFOLLOW` to reject symlinks
- Watermark write rejects symlink targets before rename
- `normalize_path` resolves symlinks via `realpath` for overlap detection
- `references` and `files` array items validated as strings at write time

## v0.5.0 — Milestone 5: Agent Hooks — Session Lifecycle

### Added
- `scripts/retrospective.py` — SessionStart command hook for retrospective data preparation. Checks for unanalyzed events (≥5), gathers retro history, writes `.retro-input.json` atomically
- `prompts/retrospective_analyst.md` — SessionStart agent hook. Keep/Fix/Try analysis with XP values as lenses. Cross-session trend detection from previous retrospectives
- `prompts/customer_proxy.md` — SessionStart agent hook. Triages open questions via AskUserQuestion, records answers as events
- `prompts/subagent_reviewer.md` — SubagentStop async agent hook. Holistic review of subagent output for conventions, complexity, decision alignment
- `prompts/tdd_check.md` — Stop prompt hook. Single-turn evaluation blocking stop if tests failing, with `stop_hook_active` guard
- `hooks/hooks.json` — Added SessionStart agents (retrospective_analyst, customer_proxy), SubagentStop reviewer (async), Stop section (tdd_check prompt)
- 49 new tests (551 total: 190 SMM + 361 hooks)

### Changed
- `scripts/session_start.py` — Removed retro check logic (moved to `retrospective.py`). Now handles only SMM init + materialization + GUPP + skills

## v0.4.0 — Milestone 4: Agent Hooks — Quality & Navigation

### Added
- `prompts/navigator.md` — PreToolUse agent hook (Write/Edit/MultiEdit). Strategic guidance before code changes. Self-filters trivial changes. Can block on decision contradictions. Writes `pair_guidance` events
- `prompts/quality_reviewer.md` — PostToolUse async agent hook (Write/Edit/MultiEdit). Courage + simplicity review. Flags empty catch blocks, missing error handling, unnecessary complexity, premature abstraction, growing files. Writes `concern` events
- `scripts/plan_review.py` — SubagentStop command hook (Plan matcher). Deterministic plan analysis: step counting, TDD strategy detection, size flags, decision/convention lookup
- `prompts/plan_reviewer.md` — SubagentStop agent hook (Plan matcher). Checks milestone boundaries, TDD ordering, plan size, assumptions, decision conflicts. Extracts `decision` and `assumption` events
- `find_related_decisions()` extracted to `_common.py` for reuse across hooks
- 39 new tests (502 total: 190 SMM + 312 hooks)

## v0.3.4 — Milestone 3.4: Core Hooks — Customer & Subagent Tracking

### Added
- `scripts/user_prompt_log.py` — UserPromptSubmit hook. Logs every user prompt as `customer_input` event with `agent_id="customer"`. Truncates to 10,000 chars
- `scripts/subagent_stop.py` — SubagentStop hook. Records minimal completion status, runs conflict detection (patterns 2-5)
- Desktop notifications for 🔴 blocking questions — inline in `smm/_append_impl.py` at the `append_event()` choke point. macOS `osascript` / Linux `notify-send`
- `detect_conflicts()` and `make_concern()` extracted to `_common.py` with optional `file_path`/`cwd`
- Integration tests for both new scripts (subprocess-based)
- 50 new tests (439 total: 190 SMM + 249 hooks)

## v0.3.3 — Milestone 3.3: Core Hooks — PostToolUse

### Added
- `scripts/post_tool_use.py` — PostToolUse hook (Write/Edit/MultiEdit). Auto-generates `status` events with `working_on` from file paths. Structural conflict detection (all 5 patterns). Semantic context enrichment via references
- `scripts/lint_check.py` — PostToolUse hook (Write/Edit/MultiEdit). Detects project linter config (ruff, eslint, prettier, flake8). Runs linter, appends concern for errors. Warns once if no config
- `scripts/bash_post_tool.py` — PostToolUse hook (Bash). Git commit size check, auto-drafts decisions. Test result parsing (pytest/jest/go test) with status + concern events
- `scripts/_common.py` — Shared helpers extracted: `normalize_path`, `extract_file_path`, conflict detection, event factories
- `settings.json` — `commit_size_threshold: 10`
- 72 new tests (389 total: 190 SMM + 199 hooks)

## v0.3.2 — Milestone 3.2: Core Hooks — PreToolUse

### Added
- `scripts/pre_tool_use.py` — PreToolUse hook (matcher: `*`). Tiered delta injection via `additionalContext`: full delta for Write/Edit/MultiEdit/Bash(git commit), 🔴+pair_guidance for other Bash, 🔴-only for Read/Grep/Glob. `working_on` overlap blocking (exit 2). TDD order tracking

### Security
- Agent ID allowlist regex validation (replaced denylist)
- JSON arg size limits and init script path validation

## v0.3.1 — Milestone 3.1: Core Hooks — Session Lifecycle

### Added
- `.claude-plugin/plugin.json` — Plugin manifest
- `hooks/hooks.json` — Hook registrations with matchers, timeouts, `${CLAUDE_PLUGIN_ROOT}` paths
- `scripts/session_start.py` — SessionStart hook. Inits SMM via `init.sh`, materializes view, injects SMM + GUPP + skills via `additionalContext`
- `scripts/session_end.py` — SessionEnd hook. Computes duration, event count, unresolved items, active working_on, final status flag. Appends `session_end` event
- `scripts/pre_compact.py` — PreCompact hook. Timestamped backup of events.jsonl and SHARED_MENTAL_MODEL.md
- `scripts/subagent_start.py` — SubagentStart hook. Full SMM injection + watermark creation
- `scripts/_common.py` — Initial shared helpers: `resolve_smm_dir`, `read_hook_input`, `hook_output`, `is_xp_agent`

### Security
- SMM directory ownership and permissions validation
- Symlink-safe file opens with `O_NOFOLLOW`
- File permissions hardening: chmod 600 after touch and rename
- Init script path validation before execution

## v0.2.0 — Milestone 2: SMM Engine

### Added
- `smm/materialize.py` — Materializes events.jsonl into SHARED_MENTAL_MODEL.md with 5 structural conflict detection patterns, section-by-section rendering, atomic write via tempfile + rename
- `smm/read_delta.py` — Per-agent watermark-based delta reader with tiered filtering (full, blocking, red-only). Watermark only advances on full reads
- `smm/test_engine.py` — 96 tests covering parsing, index building, all 5 conflict patterns, all 11 rendered sections, watermark management, tier filtering, delta formatting

### Security
- Lock timeout graceful degradation (append without lock after 2s)
- Agent ID path traversal prevention

## v0.1.0 — Milestone 1: SMM Foundation

### Added
- `smm/schema.json` — JSON Schema (draft-07) defining all 12 event types with type-specific validation
- `smm/init.sh` — SMM directory initialization with Python 3.10+ validation and git-based project-id derivation
- `smm/append.sh` — Thin bash wrapper delegating to Python implementation
- `smm/_append_impl.py` — Event construction, validation, and atomic flock-based appending
- `smm/test_smm.py` — Foundation tests for init, append, schema validation, concurrency
- `LICENSE` — MIT license
- `CHANGELOG.md`

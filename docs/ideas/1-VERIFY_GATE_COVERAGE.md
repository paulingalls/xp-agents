# Test gates that misreport

**Status:** proposed. **Triaged:** 2026-08-05 against `main` @ `e3f293e3`, plugin v5.5.0.
**Sources:** `2026-08-02-bun-test-named-specs-never-gated.md`, `2026-07-17-plugin-gates-that-cry-wolf.md`, `2026-07-21-legacy-triage-plugin-scoped-items.md` (triaged and deleted; this doc is the surviving record), plus a live 2026-08-05 field report (debt `97dc46e66fd3`).

Four items. Items 1–2 are checks that exist, run, and are structurally incapable of catching what they were written to catch. Items 3–4 are the other direction: the test-failure concern fires on a phantom, and says too little to diagnose when it fires honestly. All four ride the same recorder.

---

## 1. `bun test <spec>` is never gated — **small, fully specified, prototype-verified**

`"bun"` is in `_WHOLE_TREE_FRAMEWORKS` (`scripts/verify_paths.py:78-92`) and `classify_path_strategy` (`:103-133`) has a `jest` branch but no `bun` branch, so every `bun` command collapses to the whole-tree sentinel `"."` — satisfied by any change on the branch, by design. `git log --since=2026-08-01 -- scripts/verify_paths.py` is empty; the file has not moved since the handoff.

Reproduced at HEAD, byte-for-byte with the handoff's table:

```
'bun test'                                 strat=whole_tree  paths={'.'}   ok
'bun test a.test.ts'                       strat=whole_tree  paths={'.'}   WRONG
'bun test pkg/x.test.ts pkg/y.test.ts'     strat=whole_tree  paths={'.'}   WRONG
'bun run test'                             strat=whole_tree  paths={'.'}   ok
'bun test:unit'                            strat=whole_tree  paths={'.'}   ok
'bun --filter @legacy/db test'             strat=whole_tree  paths={'.'}   ok
'cd packages/db && bun test src/x.test.ts' strat=whole_tree  paths={'.'}   WRONG
```

**Why it matters.** `bun` is a hybrid: a package-script launcher (`bun run test:e2e`) *and* a test runner naming spec files as positionals (`bun test a.test.ts`). The plugin models only the first half. In a TypeScript repo a typical story declares the authored proof (`bun test packages/db/src/__tests__/x.test.ts` → ungated) plus a reused whole-tree shell guard (gated) — so the gate enforces only the borrowed guard and never the file the story was written to prove. Downstream evidence in the reporting project: debt `a9763fa3beb5` and three `[verify-deferred]` commits (`65461593557b`, `3db4fd1d6508`, `da22fb20a235`) each recording the symptom before the common cause was found.

**Two parts, and they must ship together.**

*Part 1 — disambiguate direct-runner from script-alias.* Remove `"bun"` from `_WHOLE_TREE_FRAMEWORKS`; add a jest-style branch beside `:129-130`. `bun run <script>` → whole_tree; `bun <colon-suffixed-script>` → whole_tree; everything else → positional. Mirror `_FLAG_GAP`'s `{0,5}` from `test_parsing.py` so `bun --filter <pkg> run test` still resolves as an alias.

*Part 2 — fix the extractor's anchor.* **Part 1 alone is a regression.** `_extract_positional_paths` (`:263-298`) skips wrapper tokens (`bun` is in `_WRAPPER_TOKENS`, `:40-52`) then unconditionally consumes one more as "the runner binary" (`:283-284`). That holds for `npx jest …` but not for bun, where `bun` *is* the binary and `test` is a subcommand — so `bun --filter @legacy/db test` yields `paths={'@legacy/db'}`, reading a package name as a path. **A false positive is strictly worse than the sentinel: it makes the gate demand a file that can never be touched.** Anchor after the literal `test` token instead. (`_RUN_SUBCOMMANDS = {"test","run","--test"}` at `:56` is why `bun test a.test.ts` happens to anchor correctly today.) A prototype produced the correct table for all nine shapes including the `cd packages/db && …` rebase.

**Do not change** `test_parsing.py::is_test_run` — a single `"bun"` return is right, exactly as for jest.

**Two limitations to leave alone** (so they aren't mistaken for regressions): `bun test --coverage a.test.ts` extracts `.` under the deliberate space-form flag rule at `:290-292` (`npx jest --coverage a.test.js` behaves identically — pre-existing, fails open by design); and bun positionals are *filter patterns*, not strict paths, so a bare-word filter correctly falls to the sentinel via the path-shaped check at `:296-297`.

**Spec updates required alongside** (`verify_paths.py:4-6` names §10b authoritative): `agents/xp-plan-reviewer.md:147` — add `bun test <spec>` to the positional-runner list; `:148` — today lists bun only as a script alias, which is true but not the whole of it. The jest alias-vs-direct wording is the pattern to copy. Worth one sentence on filter-patterns-vs-paths.

**Tests.** `tests/hooks/test_verify_paths_command_parsing.py` — one bun assertion today (`test_bun_run_test_whole_tree:180`, still holds under the fix); copy the jest cluster shape at `:138-200`/`:243`. Assert `bun run test` and `bun test:unit` stay whole_tree.

**Guardrail check:** this is framework *policy* in a module that already routes per-framework (pytest/jest/vitest/cargo/go), and it *widens* coverage to a non-Python ecosystem. The regex is on a shell command string, not on source code. Not the leak the guardrail targets.

## 2. Milestone-level manual acceptance still shells its prose — **medium; the code flags this about itself**

Story level is fixed: `smm/_acceptance_execution.py:135-143` forbids `command`/`commands` on a `type: manual` block when `enforce_manual_shape` is on, so prose gets exactly one home (`steps`) and can never land in a shelled field (`b7385dd7`, `105b90be`, `c59e6469`, `63c9b0f6`).

**Milestone level is not.** `smm/execution_plan_schema.py` calls the validator with `enforce_manual_shape` at its `False` default (grep returns nothing), and `xp-sprint-reviewer`'s milestone acceptance gate shells a milestone block's `setup`/`command` via Bash — so prose declared there reaches a shell exactly as the story-level defect did, producing the same exit-127 fabricated red an operator cannot make green, at coarser granularity. The module docstring says so itself at `:30-35` and `:103-107`: *"an open gap rather than a proven-safe scope."*

**Direction.** Turn the flag on for the milestone caller. The work is not the flag — it's the per-item grandfather, because `validate_plan` walks every milestone on the read path too, so an ungrandfathered rule would reject existing plans. `smm/_manual_shape_exemption.py:32-45` and `sprint_schema.py:103-179` are the working template: exempt only when the on-disk block is manual+command *and* the incoming block is unchanged, failing closed (missing/symlinked/unreadable/corrupt → empty set → rule applies everywhere). This is a port, not a design.

**Files.** `smm/execution_plan_schema.py` (call site), `smm/_manual_shape_exemption.py` (pattern), `agents/xp-sprint-reviewer.md` (the gate that shells it).

**Known and deliberate, not a defect:** a story-level manual+command block already on disk is grandfathered and still runs (`_acceptance_execution.py:37-41`). A stored block must not refuse every unrelated later write to that sprint.

## 3. A test-failure concern can't be attributed to a suite, scope, or worktree — **small**

`scripts/bash_post_tool.py:265` and `scripts/bash_failure.py:111` both append `f"{concerns.TEST_FAILURES_PREFIX}: {failed} failed ({framework})"` with metadata `{"action": CONCERN_ACTION_TRANSIENT_TEST}` only. `grep cwd smm/event_metadata.py` returns nothing — there is no working-directory key at all.

So a 1-test scoped run, a `docker compose exec … pytest`, a teammate's worktree run, and a 508-test full suite all surface identically at kickoff. Partial mitigation exists: the sibling STATUS event now carries `test_count`/`test_passed` (`bash_post_tool.py:243-244`), so the *status* stream is distinguishable — but the **concern**, which is what carries forward and prints at kickoff, carries none of it.

The producers of the original false positives are fixed (`is_tdd_red_step` now ORs a working-tree signal, `commit_handling.py:337-359`; the concern is gated on `not tree_test_only`, `bash_post_tool.py:260` — `08ddcfa4`, `c2e79719`). This is the remaining half: even a *genuine* red can't be attributed by anyone reading the banner. Diagnosing one such streak cost the reporting project a whole scheduled story — max suite size in the flagged streak was 23 while the real suite was 508, and every full-suite run in the same window logged `495 passed, 0 failed`.

**Two constraints.** (a) Concern content has a hard byte budget and `append_safe` **silently drops** an event that busts it (`bash_failure.py:113-121`) — extra context goes in `metadata`, not the content string. (b) Any prefix change must keep `TEST_FAILURES_PREFIX` matching for `scripts/prompt_nugget.py:37`, `scripts/concerns.py:51`, and `_resolve_test_concerns`' un-gating path.

Note `bash_failure.py:104-125` is the parallel non-zero-exit path and has *less* information — it may have no parsed count at all.

## 4. Count regexes match test *output text*, so a green suite records a phantom failure — **small, field-confirmed, do first**

**Reported live 2026-08-05** (debt `97dc46e66fd3`, five phantom concerns resolved): a Bun suite running fully green recorded `4373 passed, 1 failed` and filed a high-severity concern that **blocked the Stop gate**. Observed identically at 4342, 4363 and 4373 passing, with zero real failures each time. Root cause: `reminder-job.test.ts` contains the comment `the batch must report 1 failed / 1 smsed`, bun echoes failing-test source in its error context, and the recorder's regex matched the comment.

**Reproduced against the shipped regexes:**

```python
out = '''  // the batch must report 1 failed / 1 smsed
 4373 pass
 2 skip
 0 fail
'''
re.search(r'(\d+)\s+fail', out).group(1)          # -> '1'   (the comment)
re.findall(r'^\s*(\d+)\s+fail\b', out, re.M)      # -> ['0'] (the summary)
```

**This is not a bun bug — it's the shape of every branch.** `_parse_two_counts` (`scripts/test_parsing.py:178-193`) does a bare `re.search` over the *whole* tool response and takes the **first** match. Three compounding weaknesses:

- **No line anchor.** Any framework that echoes source, code frames, or assertion context (bun, jest, vitest, pytest with source lines) can supply a digit-plus-keyword pair from a *comment or string literal*.
- **First match, not the summary.** The summary block comes *after* the error context, so on a failing-looking-but-green run the parser reads the earliest, least authoritative number.
- **`fail` is a prefix match.** The bun branch's `r"(\d+)\s+fail"` (`:421`) matches `1 failed` inside prose. Same for `pass`.

**Direction — two independent fixes, both worth taking.**

*A. Anchor the counts to the framework's summary line.* Add `^\s*` + `re.MULTILINE` and a trailing `\b` in `_parse_two_counts`, and prefer the **last** match over the first. Line-anchoring alone kills the reported case (the echoed comment is preceded by `//`), and last-match handles a framework that prints a per-file tally before its total. This is per-framework policy in a module that already routes per-framework — not a guardrail leak — but it must be re-validated against every existing branch's fixture, since some summaries are mid-line (`ok | 5 passed | 2 failed`, `test result: ok. 15 passed; 0 failed`).

*B. Cross-check against the exit status the recorder already computes.* `bash_post_tool.py:226` already derives `exit_proves_pass` via `test_attribution.exit_status_proves_runner_passed(command)`, but consults it **only on the `failed == 0` legs** (`:227`, `:270`, `:287`). The `failed > 0` concern branch at `:261` never looks at it. `bash_post_tool.py` is registered on `PostToolUse` (the success path; `bash_failure.py` handles `PostToolUseFailure`), so exit 0 **plus** shell structure proving the runner's status reached the shell means the runner exited 0 — and a runner that exited 0 cannot have real failures. `failed > 0 and exit_proves_pass` is therefore a *provable* parse artifact.

Fix B is framework-agnostic, catches the whole class rather than one regex shape, and is a natural guard to keep even after A lands. Suggested behavior: suppress the concern, record the STATUS with a `parser_status` marking the contradiction (do not silently rewrite `failed` to 0 — the honest record is "the parse and the exit status disagree"), and surface it so the mis-parse gets fixed rather than hidden.

**Why the impact is out of proportion to the bug.** The concern is `severity: high` with `CONCERN_ACTION_TRANSIENT_TEST`, and the Stop gate refuses to let the agent stop while it is open. Every green full-suite run re-filed it, so the gate could not be cleared by doing the correct thing (running the suite) — the operator had to diagnose a regex. This is also why item 3 matters: the concern content gave no way to tell a phantom from a real red.

**Files.** `scripts/test_parsing.py:178-193` (`_parse_two_counts`) and every `case` arm's regexes (`:239-448`), `scripts/bash_post_tool.py:226`/`:261` (the cross-check), `scripts/test_attribution.py::exit_status_proves_runner_passed`. Tests: the parser fixtures alongside `tests/hooks/` — add a case per framework where the echoed-source text contains a plausible count, since that fixture shape does not exist today.

---

## Sequencing

1. **4** (phantom counts) — field-confirmed, actively blocking a Stop gate. Fix B first (framework-agnostic, catches the class), then A (kills it at the source).
2. **1** (bun paths) — smallest, fully specified, closes a gate that currently cannot fail for every Bun project. Parts 1 and 2 in one commit.
3. **3** (concern attribution) — small, metadata-only, and what would have made item 4 diagnosable in minutes rather than a session.
4. **2** (milestone manual shape) — medium; the grandfather is the work, and the template already exists.

Note 1 and 4 are both bun-triggered but touch different modules (`verify_paths.py` vs `test_parsing.py`) and are independent.

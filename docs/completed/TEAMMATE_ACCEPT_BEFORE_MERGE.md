# Design: Teammate-Mode `/xp-accept` Before Merge

## Problem

The current teammate-mode flow merges teammate branches **before** `/xp-accept` runs. Three concrete bugs result:

| ID | Symptom |
|---|---|
| `4860d3666cef` | `/xp-accept` Step 0 (cross-teammate review) sees an empty `git diff HEAD` because branches are already merged. The review doesn't fire. |
| `9d53a1ca7a9d` | `/xp-story-close` per-story preflight refuses (CURRENT_BRANCH IS TARGET_BRANCH after merge). Per-story close pipeline is unreachable in teammate mode. |
| `159346c1763e` | `cleanup_teammate.py` is invoked manually with the wrong branch name (the worktree directory name vs the actual checked-out branch), because the flow that should call it (`/xp-story-close` per story) doesn't fire. |

The combined-state quality check that Step 0 was meant to provide is already done — better — by `/xp-sprint-close`. Empirical evidence from sprint-049 iter 3: the close-reviewer caught a real BLOCK (`5dbeffb39c9f`) on `test_sprint_store.py` oversize-after-shim that nothing else caught. Step 0 had nothing to look at.

## Root cause

`/xp-assign` post-spawn step 4 (`/xp-assign/SKILL.md:192`) eagerly merges teammate branches into the sprint base. This was modeled on the solo flow's mental model ("after work, integrate") but defeats both the per-story `/xp-story-close` pipeline (designed for unmerged source branches) and `/xp-accept` Step 0 (designed for "merged teammate changes" diff scope).

Solo mode doesn't have this problem because `/xp-story-close` owns the merge — `/xp-accept` only marks the story done.

## Proposed flow

Mirror the solo-mode timing for teammate mode:

```
                Solo                          Teammate (proposed)
  -----------------------------    -------------------------------------
  /xp-assign creates 1 branch      /xp-assign creates N branches + spawns N teammates
                                   teammates work in parallel + push
                                   /xp-assign post-spawn: report only (NO merge)
  work happens
  /xp-accept (1 in-progress)       /xp-accept (N in-progress)
   - run pytest in repo             - for each story: run pytest in story's worktree
   - mark done                      - mark done
   - dispatch /xp-story-close       - dispatch /xp-story-close per done story
                                       (loop, same as solo)
  /xp-story-close                  /xp-story-close (per story)
   - close-reviewer (story diff)    - close-reviewer (story diff — alive)
   - merge → push → delete          - merge → push → delete
   - JIT-promote next               - cleanup teammate worktree (per-story symmetry)
                                       — works because branch_name in sprint.json
                                       points at the actual branch
  /xp-sprint-close                 /xp-sprint-close
   - cross-cutting review           - cross-cutting review (unchanged — this is
   - merge sprint → plan              where combined-state issues surface)
```

**The teammate flow becomes the solo flow with N branches alive simultaneously.** No new pipeline, just removed eagerness.

## File-by-file changes

### `plugins/xp-agents/skills/xp-assign/SKILL.md`

**Post-Spawn section (current step 4 deleted):**

```diff
 ## Post-Spawn

 1. Wait for Bash task notifications
 2. Read task output for branch name, report path, cost
 3. Read report file for summary
-4. Merge each teammate's story branch: `git merge <story-branch> --no-ff`
-5. Run full test suite on merged result
-6. Run `/xp-accept` to verify acceptance criteria
+4. Run `/xp-accept` to verify acceptance criteria for each story
```

The orchestrator does NOT merge. Each story branch stays alive on its teammate worktree until its `/xp-story-close` invocation merges it.

### `plugins/xp-agents/skills/xp-accept/SKILL.md`

**Two changes:**

1. **Step 0 (cross-teammate review) — deleted or repurposed.** The combined-state review is `/xp-sprint-close`'s responsibility. Per-story file_domain enforcement is `/xp-close-reviewer`'s responsibility (already runs at story-close time in story mode). Step 0's middle layer is dead-weight.

   *Honesty note*: deleting Step 0 loses one specific signal — "did the merge introduce a problem the per-story reviews missed?" Coverage of that signal in the proposed flow:
   - **Per-story merge correctness**: each `/xp-story-close` merge fires the project's pre-commit hook (tests run on the merge commit). Per-story breakage caught immediately.
   - **Cross-teammate combination breakage**: caught at `/xp-sprint-close` review (cumulative diff vs plan branch) AND by the sprint→plan merge commit firing the hook again.
   - **Merge conflicts specifically**: cannot be caught by pre-merge tests in any flow — only post-merge tests detect them. The post-merge tests in `/xp-story-close` and `/xp-sprint-close` cover this.
   - Today's Step 0 catches none of these (empty diff). Net loss: zero. Net gain: one fewer redundant test run + tighter attribution (failure surfaces at the merge that introduced it, not "one of these two").

2. **Per-story acceptance command — run in the story's worktree.** Update Step 1 (Automated acceptance):

   ```diff
   - Run `acceptance_execution.command` via Bash.
   + Run `acceptance_execution.command` via Bash, **with `cwd` set to the
   + story's worktree** when one exists (story has a teammate worktree
   + listed in TEAMMATE_WORKTREES). For solo stories without a worktree,
   + run from the main repo as today. The `cwd` change is the universal
   + pattern — it works regardless of test runner (pytest, jest, go test,
   + cargo test, etc.).
   ```

   Concrete pattern in skill prose: `Bash` invocation with `cd <worktree-path> && <command>` (the orchestrator can compute `<worktree-path>` from the worktree name in the preload + the project's `.claude/worktrees/` location).

### `plugins/xp-agents/skills/xp-story-close/SKILL.md`

**No changes needed.** The skill already handles unmerged-source-branch (preflight passes), forks close-reviewer with the unmerged story diff, runs the merge, deletes the source branch. The teammate-worktree cleanup at Step 7b already exists — it just hasn't fired in teammate mode because `/xp-story-close` itself didn't fire.

The cleanup_teammate.py branch-name bug (Q4 / `159346c1763e`) is a separate fix needed regardless: the script should derive the actual checked-out branch via `git -C <worktree> rev-parse --abbrev-ref HEAD` rather than treating `args.name` as a branch name.

### `plugins/xp-agents/scripts/cleanup_teammate.py`

The script today takes only `--name` (the worktree directory name) and `--smm-dir`. It passes `args.name` to `git merge-base --is-ancestor`, which fails when the worktree dir name (`worktree-story-007`) differs from the actual branch (`paulingalls/story-007-perf-consolidation`).

Use the existing `worktree.worktree_path(name, cwd)` helper (`scripts/worktree.py:41`) to locate the worktree, then derive the branch via `git -C <wt-path> rev-parse --abbrev-ref HEAD`. No new CLI arg required.

```diff
- def verify_merged(name: str, cwd: str) -> bool:
+ def verify_merged(branch: str, cwd: str) -> bool:
      ...
  def main(argv=None) -> int:
      args = parser.parse_args(argv)
      cwd = worktree.resolve_git_root(os.getcwd())
+     wt_path = worktree.worktree_path(args.name, cwd)
+     branch = subprocess.run(
+         ["git", "-C", str(wt_path), "rev-parse", "--abbrev-ref", "HEAD"],
+         capture_output=True, text=True, check=True,
+     ).stdout.strip()
-     if not verify_merged(args.name, cwd):
+     if not verify_merged(branch, cwd):
```

`args.name` stays the worktree dir name (callers don't change). The cleanup of markers/reports continues to key off `name` (those paths are name-keyed, not branch-keyed — verified in `cleanup()`).

### Hooks (separate fix, not strictly part of this design)

`bash_post_tool.py:107` emits the same "Session-end checklist" as the Stop hook on every `git push`. Either:
- Drop the message from the PostToolUse path, OR
- Scope it to a specific session-completion signal (sprint-end event recorded, all in-progress stories done, etc.).

## Migration path

This is an additive design — old solo flow doesn't change. The teammate path becomes correct rather than special.

**Recommended sequence** (avoids landing a knowingly-broken intermediate state, satisfies "one logical change per commit"):

1. Land `cleanup_teammate.py` branch-derivation fix as its own micro-story. Stands alone — bug exists today regardless of merge timing.
2. Land `/xp-assign` post-spawn change + `/xp-accept` worktree-cwd change + `/xp-accept` Step 0 deletion as a **single coherent commit**. These three are co-dependent; landing any one in isolation leaves the teammate flow worse off than before.
3. Test end-to-end with a 2-teammate sprint.

Splitting step 2 into three commits would land a deliberately-broken intermediate (teammate acceptance fails between commits), which violates the small-commits constraint by trading commit size for commit correctness — wrong direction.

## Open questions

1. ~~**What about the orchestrator's "full test suite on merged result" check?**~~ **RESOLVED**: tests already run via the **project's** pre-commit/pre-push hook on every merge commit (universal, runner-agnostic). Today's orchestrator-level test run after `/xp-assign` post-spawn is redundant with the hook that fires on the merge commit. The proposed flow has ONE FEWER redundant run, not a delayed signal.

   **Hook-absent fallback** (because hooks are encouraged but not required):
   - Add `close_common.py: pre_commit_hook_present(repo_root) -> bool` — deterministic detection (no LLM judgment). Checks `git config core.hooksPath` (respect overrides), then `<hooks-dir>/pre-commit` and `<hooks-dir>/pre-push` for executable files, then framework markers (`.pre-commit-config.yaml`, `lefthook.yml`/`yaml`, `.husky/` dir).
   - **Reuse existing helpers**: `plugins/xp-agents/smm/seed_smm.py:267` already defines `has_git_hooks(root)` covering most framework markers; `plugins/xp-agents/scripts/identity.py:103` (`_git_config(key, cwd)`) already reads git config keys. Extract / extend these rather than rewriting from scratch. The new piece is the `core.hooksPath` override check + executable-bit check (`os.access(path, os.X_OK)`).
   - Trusts the dominant convention: hook present → tests will run. Doesn't parse hook content — knowing WHAT the hook does is project policy.
   - `/xp-story-close` and `/xp-sprint-close` preload surfaces `PRE_COMMIT_HOOK=present|absent`.
   - When `absent`, skill prose instructs: "Run the project's test command (find it in CLAUDE.md / system_context.json) before confirming the merge." The LLM uses existing project knowledge — no new schema field, no per-sprint declaration. The plugin doesn't lecture about hooks (that's a Risks pillar concern, not a workflow gate).
   - Detection robustness is the load-bearing piece. We've already seen `core.hooksPath` override in this repo (lefthook warning during this session). Tests for the detector should cover: default hooks dir, overridden hooks dir, executable check, framework markers, missing hook + missing markers (returns False).

2. ~~**What if two teammates need to acceptance-test against each other's code?**~~ **RESOLVED**: this can't happen for genuine teammates. If story-A and story-B need each other's code to test, they must share a file → `scheduled-overlap` exits 0 → `/xp-assign` auto-picks solo (sequential). If no shared file exists, neither story's tests actually depend on the other's branch — they depend on the existing sprint-base infra. Edge case "story-A's acceptance test imports from story-B's domain without overlap" = poorly scoped file_domain, caught at `/xp-review-plan`, not a runtime concern. The overlap predicate is doing the load-bearing work.

3. ~~**Worktree path discovery in `/xp-accept`**~~ **RESOLVED**: preload emits `<story-id>: <abs-path>` rows in the TEAMMATE_WORKTREES section. Skill prose iterates in-progress stories, looks up path by story-id, prepends `cd <path> && ` to the acceptance command (universal, runner-agnostic). Single source of truth: the Python that creates the worktree (`spawn_teammate.py` / `branching.py`) owns the path convention; the preload calls into the same helper that constructs `wt_path` rather than re-implementing it. Decoupled — if the path convention ever moves (e.g., out of `.claude/worktrees/`), only the worktree-creation module changes; the preload and every consuming skill keep working.

   Apply the same preload change to `/xp-story-close` (it also operates on a teammate worktree for Step 7b cleanup).

   ```
   ### TEAMMATE_WORKTREES
   story-007: /Users/.../xp-agents/.claude/worktrees/worktree-story-007
   story-008: /Users/.../xp-agents/.claude/worktrees/worktree-story-008
   ```

## Honest tradeoffs

- **Deleting Step 0** is the right call empirically (it never fired correctly in teammate mode), but it's a visible behavior change. Document it in the migration commit message.
- **Running tests in worktrees** is the universal pattern, but introduces the assumption that the worktree's `cwd` is the project root. For monorepos this might require thought. For now, document that `acceptance_execution.command` is expected to be runnable from the project root (which is true today as well).
- **Lazy merge changes the failure-detection timing.** Cross-teammate test breakage now surfaces at `/xp-story-close` of the second story (when the merge actually happens), not before `/xp-accept`. **Accepted as-is — no preview-merge step.** Adding "optional" preview-merge is debt: optional features rot. The detection timing shifts but the signal is preserved (each `/xp-story-close` merge fires the project's pre-commit hook). The first failure points directly at the merging story instead of "one of these two teammates broke it." Worth confirming with customer that this trade is acceptable.

## Independence from in-flight execution plan

The security-review tiered migration (M-3..M-6 remaining) does not touch `/xp-assign`, `/xp-accept`, `/xp-story-close`, `cleanup_teammate.py`, or hook plumbing. Specifically:
- M-3 changes `agents/xp-close-reviewer.md` (Tier 3 dispatch). No overlap.
- M-4 changes `pre_tool_bash.py`, `markers.py`, `PROCESS_GUIDE.md`, `xp-retrospective.md`, `xp-plan-reviewer.md` (commit-gate cutover). No overlap.
- M-5 deletes `xp-security-triage` skill + `xp-security-reviewer` agent. No overlap.
- M-6 version bump + CHANGELOG. No overlap.

This work can land on `main` as a standalone free-session series without conflicting with the security migration. Sprint-049 is already merged to plan branch; recommend doing this on `main` (or a free branch off `main`) rather than waiting for the security migration to land.

## Concerns this design resolves

- `4860d3666cef` (Step 0 empty diff) — Step 0 deleted
- `9d53a1ca7a9d` (story-close preflight refuses) — branches stay unmerged at close time
- `159346c1763e` (cleanup branch-name bug) — direct fix in cleanup_teammate.py

## Adjacent fixes (bundle into the same free session)

These two concerns surfaced in the same session and are tiny single-file fixes. Independent of the teammate-merge design but cheap to land alongside it.

### Concern `1d18655aa396` — Duplicate session-end-checklist hook

**Symptom**: the same "Session-end checklist: Summarize what was accomplished..." prose fires from two hooks:

- `scripts/session_end_warning.py:40` — Stop hook (correct: fires once at actual session end)
- `scripts/bash_post_tool.py:107` — PostToolUse:Bash hook on every `git push` (false-positive: fires multiple times per session)

This session hit it 4-5 times mid-iteration, treating each push as a session-end signal.

**Fix options**:

1. **Drop the message from `bash_post_tool.py`.** Cleanest. The Stop hook already covers the legitimate case. The PostToolUse path was likely added when push was rare; today's flow pushes constantly.
2. **Scope `bash_post_tool.py:107` to a real session-completion signal** (e.g., only fire after `/xp-sprint-close` push, detected via the most-recent sprint event). More work, more surface area for bugs.

Recommendation: **option 1.** Delete the duplicate.

**Files**: `plugins/xp-agents/scripts/bash_post_tool.py:107` (and surrounding lines for the "session-end-checklist" emission) + tests in `plugins/xp-agents/tests/hooks/test_bash_post_tool.py` (if any pin the current behavior).

### Concern `426365da2551` — `[sprint-direct]` constraint unwired

**Symptom**: SMM Constraints pillar item `b2467c56ddbf` claims:

> PreToolUse blocks direct commits to sprint branch at stage 2+; [sprint-direct] in commit message bypasses for /xp-accept window

But the actual code only accepts `[release]` or `[chore]`:

- `plugins/xp-agents/scripts/pre_tool_bash.py:172` calls `is_escape_hatch_commit(command)`
- `plugins/xp-agents/scripts/commits.py:297` defines `_ESCAPE_HATCH_RE = re.compile(r"^\[(release|chore)\]", re.IGNORECASE)` (used by `is_escape_hatch_commit` at `commits.py:300`)
- `[sprint-direct]` appears nowhere in the codebase

The hook reminder prose (look near the gate at `pre_tool_bash.py:172` for the surrounding warn-message construction) tells the user to use `[release]/[chore]`, contradicting the SMM constraint.

This session: I committed sprint-direct close-reviewer fixes with `[sprint-direct]` prefix; the hook fired the warning prose but didn't actually block (verify exact behavior — either the gate is advisory in this path, or my commit succeeded for an unrelated reason). Need to nail down the actual behavior in the fix.

**Fix options**:

1. **Update the SMM constraint** to match the code: `b2467c56ddbf` should say `[release]` and `[chore]` are the bypass tokens. Constraint becomes truthful; behavior unchanged.
2. **Wire `[sprint-direct]` into the regex.** Add `sprint-direct` to `_ESCAPE_HATCH_RE` alternation, document it in the hook prose. Constraint becomes true; gives a more semantic name for the close-window case (vs `[chore]` which is generic).

Recommendation: **option 2** — `[sprint-direct]` is a more honest token for what the close-window flow needs (the commit IS direct to sprint; the work IS post-merge cleanup; calling it `[chore]` masks intent). Adds one alternation to one regex, plus the constraint becomes self-documenting.

**Files**: `plugins/xp-agents/scripts/commits.py:297` (regex), `plugins/xp-agents/scripts/pre_tool_bash.py:172` and surrounding warn-message prose (mentions `[release]/[chore]` — add `[sprint-direct]`), `plugins/xp-agents/tests/hooks/test_pre_tool_bash*.py` (pin the new alternation), SMM Constraints (update `b2467c56ddbf` content if it ever gets re-curated — auto-curated, so usually leave alone).

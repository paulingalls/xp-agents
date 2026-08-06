# The commit-path hooks: one misclassification, one silent kill, one linear cost

**Status:** proposed. **Triaged:** 2026-08-05 against `main` @ `e3f293e3`, plugin v5.5.0.
**Sources:** `2026-07-29-git-merge-abort-blocked-by-commit-gate.md`, `2026-04-28-m5-polish-bundle-resume.md`, `2026-07-21-commit-events-lost-to-heredoc-redirect.md` (triaged and deleted; this doc is the surviving record).

Every item here rides the synchronous Bash commit path — the hook stack charged directly to the user on every `git commit`.

---

## 1. `git merge --abort` is classified as a commit and blocked — **small, real operator harm**

`scripts/git_commits.py:80`:

```python
return bool(re.search(GIT_PREFIX + r"(?:commit|merge)\b(?!-)", scan_target))
```

The `(?!-)` lookahead is evaluated at the character *after* `merge`, which for `git merge --abort` is a space — so the plumbing guard never fires. Measured at HEAD against the real function:

| command | `is_git_commit` | correct? |
|---|---|---|
| `git commit -m x` | True | yes |
| `git merge origin/main` | True | yes |
| `git merge --abort` | **True** | **no** |
| `git merge --continue` | **True** | arguable |
| `git merge --quit` | **True** | **no** |
| `git merge-tree a b` | False | yes |
| `git push --dry-run` | False | yes |

`commit_gate_parts` (`scripts/pre_tool_bash_commit_gates.py:93`) then runs the whole stack. For a conflicted back-merge the realistic blocker is the review-cycle gate at `:171-190` — *"Run /xp-quality-review before committing — N code files changed since last review."* The tier-1 security scan (`:138`) and staged-lint gate (`:161`) also run against a conflicted index.

**Why it matters more than it looks.** The escape hatch is more destructive than the gated operation: an operator who cannot `git merge --abort` reaches for `git reset --hard HEAD`, which discards uncommitted work the abort would have preserved. Reported live from a real sprint-019 close (concern `92adc8ac748a`, debt `3bb853069cad`).

**Repro.** Start a conflicted merge with 2+ changed code files since the last review, then run `git merge --abort`.

**Direction.** Reject the non-commit-producing argument forms alongside the existing plumbing check:

```python
if re.search(GIT_PREFIX + r"merge\s+--(?:abort|quit)\b", scan_target):
    return False
```

Three refinements for the plan:
- `is_git_commit` is also the PostToolUse entry condition (`bash_post_tool`/`commit_handling`), so the exemption also suppresses a pointless post-commit confirmation pass — a benefit.
- `--continue` genuinely produces a merge commit. Lean toward keeping it gated but **deciding it explicitly** — today's pass-through is an accident of the lookahead, not a decision. Either way the code comment should say which.
- `git rebase --abort` / `git cherry-pick --continue` aren't matched at all (the regex only covers `commit|merge`), so there is no equivalent hole.

**Files.** `scripts/git_commits.py::is_git_commit` (fix site), `scripts/pre_tool_bash_commit_gates.py::commit_gate_parts` (consumer). Tests: `tests/hooks/test_bash_commit_detection.py` or `test_command_classification_git_commit.py`.

## 2. `coordination.py` kills its own hook process on lock contention — **small, correctness bug**

`scripts/coordination.py:36-44` (`update_coordination`) and `:115-123` set `signal.signal(signal.SIGALRM, signal.SIG_DFL)` then `signal.alarm(2)` around a blocking `fcntl.flock(lock_fd, fcntl.LOCK_EX)`. **`SIG_DFL` for `SIGALRM` is terminate the process.** If the lock is held longer than 2s the hook is killed outright: the `except (OSError, SystemExit)` at `:40` never runs, the `finally` never runs, nothing lands in `hook_errors.jsonl`.

`.coordination.json` is exactly what gets contended when parallel teammates run — the condition under which the timeout is most likely to fire. This contradicts CLAUDE.md's "Fail loud, never corrupt, always recoverable."

**Direction.** The canonical helper exists and this module can already reach it: `smm/_append_impl.py:130` `flock_with_timeout()` arms `SIGALRM` with a real `_on_alarm` handler (`:155`) raising `LockTimeoutError`; `smm/adoption_store.py:107` already reuses it, and `coordination.py:14` already `sys.path.insert`s `smm/` and imports `write_json_atomic` from it. Swap both call sites onto `flock_with_timeout` and log-and-swallow via the `_common.append_safe` pattern.

**Open sub-question the plan must settle.** `flock_with_timeout` uses `LOCK_TIMEOUT_SECONDS` (10s); coordination uses 2s. Decide whether coordination keeps a shorter budget — it is a best-effort advisory file, and blocking a hook 10s on it is its own problem — or adopts the standard. `scripts/in_place_locks.py:40` documents a "10s SIGALRM budget" for a comparable lock; weigh against it.

## 3. No runtime budget on the synchronous `bash_post_tool` — **small, do before item 4**

`bash_post_tool.py` was converted async → synchronous and nothing bounds its wall-clock. No timing assertion exists anywhere in `tests/hooks/test_bash*.py` or `tests/integration/` (the only `perf_counter`/`monotonic` hit is an unrelated timestamp comparison at `tests/integration/test_hook_liveness_e2e.py:205`); all ten budget-suite files measure **bytes**, not runtime. This hook is on the critical path of every `git commit` in every project the plugin ships to, and a regression would degrade all of them silently.

**Respect the local convention.** `tests/test_lefthook_perf_gate.py:199-218` gates wall-clock timers behind an `XP_PERF` `skipUnless` and *asserts the skip stays in place*, because unguarded timers running 16-wide under `pytest -n auto` measure the machine rather than the code ("Perf benchmarks assert structural invariants, not wall-clock").

**So prefer the structural invariant:** assert *"the commit path spawns at most K linter subprocesses for N files."* Deterministic, runs on every commit, and it directly pins item 4's fix red before the fix exists. Alternatively gate a real timer behind `XP_PERF` and register it with the perf gate.

**Files.** New test alongside `tests/hooks/test_bash_commit.py` (372 lines, room under the 500 cap).

## 4. One linter process per committed file — **medium**

`scripts/lint_resolution.py:73` `resolve_lint_on_commit()` loops over committed files calling `check_and_resolve_lint()` (`:23`) per file; each call runs `detect_linter_config(...)` *and* a full `run_linter(...)` subprocess. An N-file commit spawns N linter processes plus N config detections — inside a synchronous hook, so the latency is charged to the user's commit. It is the largest per-commit cost in that hook, worst on the large release/refactor commits this repo produces routinely.

**Three things the plan must get right:**

1. **This is not "ruff batching."** The debt was filed in ruff's vocabulary; implementing it that way ships a language-specific leak into shipped plugin code — precisely the guardrail trap sprint-103 fell into three times. Batch by resolved **(linter, config, cwd) triple**, working for eslint/rubocop/clang-format alike.
2. **The pre-commit gate already solved this.** `scripts/staged_lint.py` "lints the real paths, still batched as one linter process for N files," covering ruff, eslint, prettier, flake8, rubocop, clang-format with each argv verified against the real binary. Reuse that machinery; do not invent a second scheme.
3. **Preserve per-file config fidelity.** The per-file call threads `config_path` and `root` deliberately — the comment at `lint_resolution.py:44-48` explains that a concern raised with one config could *never* clear if the re-run used a different one. That is why grouping by triple, not by flat file list, is the right shape.

**Files.** `scripts/lint_resolution.py:23`, `:73`; `scripts/lint_check.py` (`detect_linter_config`, `lint_invocation_target`, `run_linter`); reuse `scripts/staged_lint.py`.

---

## 5. A heredoc body containing `-m` becomes the commit message — **small, root-caused**

Promoted from concern `3a59b2018e99`, which an auto-producer filed at `low`. Not a regression of the heredoc family fixed in v4.16.0 — a different function.

`commit_message.recover_commit_message` (`:123-135`) searches `_SIMPLE_MSG_RE` over the **whole command** before it ever reaches the `-F -` stdin branch at `:136`. Commit `9d403643`'s heredoc body contained the line `pytest -m "user's" & ruff check 'src'`, so the recovered message was `"user's"` instead of the subject. Confirmed by minimal repro: the identical heredoc without a `-m` token in the body parses correctly.

**The blast radius is the reason this isn't cosmetic.** `_head_matches_command` failed → **no commit event was recorded at all**; the commit's `Resolves-Event: a162e74896be` never linked, leaving a fixed high-severity concern open through the merge gate; and `is_escape_hatch_commit` could not see the `[sprint-direct]` prefix, so the branch guard and review-cycle gate both misjudged the commit.

**Direction.** Prefer the `-F -` / `-F <path>` branch whenever its flag is present, or bound the `-m` search to the text before the heredoc opener. **Files.** `scripts/commit_message.py`.

## Also worth a look (unverified — do not plan as a defect yet)

`dash_c_unreachable` only judges `git -C` tokens. A `cd "$WT" && git commit` shape hides the target repo the same way; `pre_tool_bash_commit_gates.py:106` resolves it via `parse_effective_cwd`, which **silently falls back to the hook's `cwd` on an unresolvable path** — the exact silent-wrong-repo failure the `-C` block (`:119-127`, shipped v5.1.0) was written to close. Nobody has confirmed this path is reachable in practice. Investigate before filing.

Related and **recommended closed as superseded**: the PostToolUse recovery branch for an unreachable `git -C` (`commit_handling.py:156-164`) never probes candidate HEADs, and `commit_command.commit_repo_candidates` (`:329-390`) still exists to serve it. Since v5.1.0 that branch is only reachable if the PreToolUse block was bypassed, so the honest question is whether the worktree scan still earns its keep — not whether to add HEAD probing to it.

---

## Sequencing

One small free-mode branch covers 2–4: **2** first (independent correctness fix, smallest, highest value), then **3** as the red structural pin, then **4** to turn it green. **1** is independent of all three and can go first or in parallel.

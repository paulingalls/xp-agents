# Spike-009: Does the lint subsystem need its current size?

**Story:** sprint-121 / story-009 — answers open question `1657e4005741`, carried 2 sessions under
a "keep-for-now" assumption. Code-free.

Every claim below names the command that produced it and the output observed.

## 1. Question

> "Does the lint subsystem need its current size? 1526 lines + a 66-linter registry, largely
> duplicating a project's own commit hook. Unique value: (a) `--no-verify` immunity — but that is
> ~10 lines, not 1526; (b) projects with NO hook; (c) index-vs-worktree strictness."

## 2. The question's premises are stale — corrected by counting

| Question says | Counted today |
|---|---|
| 1526 lines | **2048** — `lint_check` 600, `linters` 493, `staged_lint` 441, `linter_invocation` 365, `lint_resolution` 149 |
| 66-linter registry | **17 linters** (`linters.py:73` `LINTER_COMMANDS`; the union of every linter-keyed table is also 17). 11 tables / 102 rows. `LINTER_CONFIGS` has 29 rows mapping onto those 17. |
| (a) "~10 lines" | the comparator is **126 lines** — see §3 |

No subset of the files sums to 1526; `lint_check.py` was 514 at HEAD~30. The numbers were stale
when the question was written, and **triage acted on them for two sessions.** That is the finding
behind the finding: a question carrying uncounted numbers reads as measured and isn't.

## 3. Claim (a) — `--no-verify` immunity: **REFUTED** on both axes

**Size.** The claim compares against the `branch -d/-D` refusal, calling it ~10 lines. Measured:
`pre_tool_bash.py:237-362` = **126 lines** (`_DELETE_FLAG_RE`, `_SHELL_SEPARATORS`,
`_simple_commands`, `_story_branch_deletes`, `_unmerged_story_branch_delete_block`) — 12.6× the
claim. Its own docstring records why: *"A tokenizer rather than a regex, and the distinction is the
whole fix: a regex mistake."* A `--no-verify` refusal needs the same shlex tokenizer, or it refuses
`git commit -m "don't use --no-verify"`.

**Value — the decisive axis.** Refusing `--no-verify` only preserves *whatever the project's own
hook does*. On a project with **no hook**, it delivers **nothing**. That population is precisely
claim (b). So **(a) and (b) mutually undercut**: the cheap alternative works only where the
subsystem is least needed, and is worthless exactly where (b) says the subsystem earns its keep.
The two claims cannot both support shrinking.

Confirmed: nothing refuses `--no-verify` today. Every occurrence is our own code passing it
deliberately (`close_common.py:372`, `branch_lifecycle.py:145`).

## 4. Claim (b) — projects with no hook: **UNRESOLVED** (and in-sample it *strengthens* duplication)

**The gate is unconditional** — confirmed. `staged_lint.staged_lint_gate` (`staged_lint.py:275`)
and `pre_tool_bash.py:430` never consult hook presence. We lint every project, including those
whose own hook will also run. The detection primitive already exists (`smm/git_hooks.py`,
`will_fire_hook:64`) but **no lint path calls it** — only `close_common` and `seed_smm` do.

**Population census** (`git_hooks.will_fire_hook`, which honors `core.hooksPath`):

| repo | pre-commit hook |
|---|---|
| xp-agents | lefthook |
| legacy | lefthook |
| legacy2 | lefthook |
| divineruin | **yes** — no framework marker, but `core.hooksPath=.githooks` with an executable `pre-commit` |

**4 of 4 have one.** In this sample the subsystem *always* duplicates an existing pre-commit hook —
which supports the question's duplication premise, not the defence.

But **n=4, all one author's repos.** That is not evidence about the plugin's user population, which
is what claim (b) is about. Recorded **UNRESOLVED** rather than guessed (the phpcs precedent). This
matters: (b) is one of the two values that buy the registry (§7).

## 5. The question missed a fourth value

`hooks.json:164-178` registers `lint_check.py` on **PostToolUse `Write|Edit|MultiEdit`** — an
edit-time feedback loop that runs after every agent edit, with no relation to commit hooks and no
duplication of them. The question enumerated three unique values and omitted this one, then
concluded the subsystem "largely duplicates a project's own commit hook."

## 6. Claim (c) — index vs worktree: **CONFIRMED**, bidirectionally, measured

Fixture: this repo. `lefthook.yml:4-9` runs `ruff check {staged_files}` — staged *paths*, read off
**disk**; no `stage_fixed`, no index checkout. Our gate reads index bytes (`git show :<path>`,
`staged_lint.py:55-66`).

Measured independently — our `PreToolUse` gate intercepts `git commit` before lefthook runs, so
each tool was invoked directly rather than via a commit attempt:

**Direction 1 — edit-after-add.** Stage a file with `import os` unused (ruff F401), then fix the
worktree copy. Index = bad, worktree = clean.

| tool | reads | verdict |
|---|---|---|
| `ruff check <path>` (lefthook's literal command) | disk | `All checks passed!` — **exit 0, MISSES it** |
| `staged_lint_gate` (ours) | index | **BLOCKS** — `F401 'os' imported but unused` *(staged bytes)* |

**Direction 2 — the inverse.** Stage the file clean, then break the worktree copy. Index = clean,
worktree = bad.

| tool | reads | verdict |
|---|---|---|
| `ruff check <path>` | disk | **exit 1, BLOCKS** — on content that is not being committed |
| `staged_lint_gate` (ours) | index | **PASS** — the index is clean |

So the delta is not "we are stricter." It is **we judge exactly what is being committed**: lefthook
fails *open* on direction 1 (the `cfaacb88` edit-after-add hole) and fails *closed* on direction 2.
(c) is confirmed and structural.

## 7. What each value actually buys — the decomposition

(c) reproducing justifies the **index read**, not the footprint. A single-linter gate reading the
index delivers (c) just as well. So the verdict must be per-component:

| Component | Lines | Bought by | Verdict |
|---|---|---|---|
| `staged_lint.py` | 441 | **(c)** — measured, both directions | **Keep.** This is why the subsystem exists. |
| registry + runners (`linters.py`, `linter_invocation.py`) | 858 | (b) + (d) | **Keep — but not on (b)'s evidence.** See below. |
| `lint_check.py` | 600 | (d), the unlisted edit-time loop | **Keep the function; SPLIT the file** — 600 > the 500 cap. |
| `lint_resolution.py` | 149 | shared | — |

**The registry is not an optimization question.** `system_context.json` carries
`plugin-project-agnostic` as a **principle**: *"Shipped plugin code is project-agnostic in
vocabulary AND language. No single-language impl… The plugin ships to projects in any language."*
Shrinking 17 linters toward ruff-only is not a size win — it is **superseding a pillar**, and would
need to be argued as such. So the registry rests on a standing architectural decision, not on
(b)'s unresolved population claim. Recording that honestly matters: (b) being UNRESOLVED does *not*
weaken the registry, because the registry was never load-bearing on (b).

## 8. Debt disposition — the debts do NOT evaporate

4 of 5 open lint debts are **registry-table** debts, so they evaporate only if the registry
shrinks — which §7 says would supersede a pillar:

| id | lives in | fate |
|---|---|---|
| `9804e4fd387a` | `linters.py:225` — phpcs absent from `LINTER_STDIN_SHAPES` | survives |
| `e74ad685b1ee` | `linters.py:282` vs the 5 `.eslintrc*` rows `:36-40` | survives |
| `3dd079960446` | `linters.py:151` — `LINTER_ARGV_SHAPES`, 2 rows | survives |
| `87387a9ac121` | `linters.py:282` ↔ `:33-35`, no enforcing test | survives |
| `10c21161278c` | `lint_check.py` at 600 lines | **real and actionable — split the file** |

They are the **maintenance cost of the project-agnostic pillar**, not evidence of bloat. Test
surface is 2907 lines / 151 tests across 5 files — a 1.42:1 test-to-source ratio.

## 9. Verdict

**KEEP.** The question rested on stale numbers (1526→2048, 66→17), a refuted claim (a), and an
omitted fourth value. Its one sound instinct — that we duplicate a project's own hook — is true in
4/4 sampled repos, but §6 shows the duplication is not redundancy: on the edit-after-add case the
project's hook is *wrong* and ours is right.

The single actionable item is **`lint_check.py` at 600 lines** (debt `10c21161278c`) — a cap
violation and a split, not a shrink. That is independent of this question and was already tracked.

## 10. What this spike does NOT settle

- **Whether a cheaper design delivers (c)+(d) in fewer than 2048 lines was never costed out.** A
  blanket "the size is right" would be an assumption; the honest claim is only that no evidence
  presented here supports shrinking, and that the registry is pillar-bound.
- **Claim (b) is UNRESOLVED** — n=4, all one author. If the plugin's real population mostly ships
  hooks, the gate-on-hook-presence option (6 lines away, `will_fire_hook`) becomes worth costing.
  That is a different question and needs different evidence.
- The (d) edit-time loop's **value** was confirmed to exist as a registration, not measured for
  usefulness.

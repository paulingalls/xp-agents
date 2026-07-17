# Spike-005: Worktree bootstrap — can it be automated?

**Story:** sprint-121 / story-005 — gates a proposed bootstrap-automation milestone. Code-free.

Every claim below names the command that produced it and the exit code observed. Where a claim
could not be measured, it says so.

## 1. Question

`stack.worktree_bootstrap` (shipped sprint-003) runs a project-declared setup command in a fresh
teammate worktree. It is recorded **only when the project already documents a setup entry point** —
and most projects never wrote one, because most projects don't use worktrees. Can the plugin
*derive* the command instead?

Two sub-questions: is a differential detector **affordable**, and is it **robust**?

## 2. Why this needed measuring at all

The record contradicted itself three ways, and none of the three cited a measurement:

| Source | Claim |
|---|---|
| `worktree_bootstrap.py:77-83`, `CHANGELOG.md:80-87` | bare worktree **false-GREENs**; absence is "not reliably loud" |
| SMM risk `f9afab74c152` | lint gate **fails** on missing generated files |
| Customer (2026-07-16) | it **false-REDs**; a weak agent gets stuck and never finishes |

The real source is `legacy/scripts/init-worktree.sh:10-22` — a measured rationale dated
2026-07-16, in a *different repo*, never carried back here. It is also the origin of the
otherwise-undefined "6.4s" in `worktree_bootstrap.py:29-30`.

**All three were partly right. Both failure modes are real, from two different files.**

## 3. Method

- **Subject:** `legacy2` — bun/Expo monorepo, no setup script, gitignores `node_modules/`,
  `.expo/`, `expo-env.d.ts`. The typical unprovisioned user project.
- **Second data point:** `divineruin` — same family (bun monorepo), different enough (eslint flat
  config, pyright), also no setup script.
- **Control:** `xp-agents` — stdlib-only Python, nothing gitignored that matters.
- Bare worktree via `git worktree add --detach`. Each command run in **primary** and **worktree**,
  capturing the **true** exit code (never through a pipe — see §7).

## 4. Findings

### 4.1 False-RED — confirmed (this is the stuck agent)

After the strongest inferable candidate (`bash scripts/init-env.sh && bun install`, exit 0, 2208
packages), `bun run typecheck` in the worktree:

```
exit=2
apps/mobile/src/app/_layout.tsx(3,8): error TS2882: Cannot find module or type
declarations for side-effect import of '@/global.css'.
```

Exactly one error, in a file the story never touched. Primary: **exit 0**. Cause: missing
`apps/mobile/expo-env.d.ts`. Predicted verbatim by `init-worktree.sh:16-18`.

### 4.2 False-GREEN — confirmed (isolated)

The two modes **mask each other**: while TS2882 fails the run, tsc never resolves a route, so
TS2322's absence is *unobservable, not absent*. Reading that as "false-green refuted" would record
a wrong verdict. Isolate by supplying `expo-env.d.ts` **only**, leaving `.expo/types/router.d.ts`
absent:

| checkout | `router.d.ts` | bogus `Href` route |
|---|---|---|
| primary | present | **exit 2 — TS2322** ("not assignable… 187 more") |
| worktree | absent | **exit 0 — compiles clean** |

Same code, same command, opposite verdicts.

### 4.3 Tests false-RED too — the rejected decision rested on an untested claim

`docs/completed/teammate-acceptance-in-provisioned-env.md:35-46` (2026-06-20) rejected
provisioning on: *"Confirmed with the user: teammates run their own unit tests fine in the bare
worktree."*

Measured on legacy2: bare `bun test` → **exit 1**, 12–13 unresolvable modules (`@legacy/tokens`,
`drizzle-orm/pg-core`, `react/jsx-dev-runtime`) in **both** placements. Primary → **exit 0, 2897
pass**. The claim is refuted. story-005's reversal of that decision was correct — for reasons
nobody had checked.

### 4.4 The invariant/variant split is PER-ARTIFACT, not per-project

The decisive result. `worktree_bootstrap.py:84-90` predicts gitignored state splits into
checkout-invariant (installable) and checkout-variant (generated per checkout). Measured — and a
single project has **both**:

| repo | command | candidate | gap closes? |
|---|---|---|---|
| `divineruin` | `bun run typecheck` | `bun install` | **YES** (1 → 0) |
| `legacy2` | `bun test` | `bun install` | **YES** (1 → 0, 2897 pass) |
| `legacy2` | `bun run typecheck` | `init-env.sh && bun install` | **NO** (TS2882 remains) |

legacy2's *tests* are invariant; its *typecheck* is variant. So a project cannot be classified
once — **every declared command must be differentialed and verified separately.**

Why legacy2's typecheck resists inference: expo-router emits both type files at dev-server
**startup**; there is no standalone `expo typegen` in SDK 56 (`init-worktree.sh:20-22`). No
inferable install command can produce them.

### 4.5 A candidate's own exit code proves nothing

**Both** candidates exited **0**. legacy2's installed 2208 packages, looked perfect, and fixed
neither bug. Only re-running the differential separates them. This is the single most important
constraint on any design here.

## 5. Affordability

| repo | command | primary | worktree |
|---|---|---|---|
| legacy2 | `bun run typecheck` | 9s | 10s (1s when failing fast) |
| xp-agents | `pytest -n auto` | 55s | 57s |

The differential costs ~2× the project's own command. `bun install` measured at 2–3s — **warm
cache, not a cold install**; do not generalize that number.

## 6. Robustness — the detector has a false-positive mode

The control was expected to show no gap. It **failed**, for a reason unrelated to provisioning:

```
xp-assign:   447 chars (budget 400)
xp-schedule: 336 chars (budget 300)
```

`PLUGIN_ROOT` is emitted as an absolute path, so preload stdout length includes the checkout path.
Primary root = 41 chars → passes. Worktree at a 124-char path → fails. **Proof:** the same worktree
at a short path (`/private/tmp/wt1`) passes.

Worktrees *always* live at a different path than the primary, so any path-sensitive check diverges.
An exit-code differential therefore has an **intrinsic false-positive mode**. (This is also a real
portability bug in xp-agents — concern `b2e542c120b9` — a deep clone fails the suite for no code
reason.)

## 7. Method failure worth recording

The control was nearly reported as "no gap": `pytest … | tail -3` makes `$?` **tail's** exit code,
so a red run read as green. The same shape then fired the hook's *"All prior test failures resolved
— tests are green"* over a **failing** run — live evidence that debt `859cdd229b1c`'s hole is real
even though its proposed fix is inert (`PostToolUse` only fires on exit 0). Filed as
`5331a47bf19f`.

Never read a runner's exit code through a pipe.

## 8. Conclusion

**Detect → propose → verify → refuse.**

1. **Detect** per declared command via the differential (primary vs bare worktree).
2. **Propose** a candidate — LLM judgment reading the repo (allowed: language-aware judgment, not
   language-specific implementation).
3. **Verify** by re-running the differential. Never trust the candidate's exit code (§4.5).
4. **Refuse** and ask the user to declare/author a command when verification fails. An unverified
   guess is worse than an empty field: it restores the false-green the feature exists to kill.

Corollary: the current "record only what the project documents" design is **vindicated, not
wrong** — inference cannot author what `init-worktree.sh` knows (Metro port-band scan,
process-group reap, marker-based regen, `uv sync`). A ≤100-char command expresses none of it. The
product opportunity is helping the user *create* the script (the `/xp-scaffold-acceptance`
pattern), not inferring it.

**Debt `7abaece7d6d8`:** `worktree_create.py` (the `WorktreeCreate` hook) calls no bootstrap, reads
no system_context. Every user-driven `/worktree` is bare, and §4 shows bare is not a degraded
convenience. Provisioning belongs at the primitive.

## 9. Caveats

- **n=2.** Both subjects are bun monorepos. Neither speaks to the middle ground (plain `npm ci`, no
  codegen). Verdicts are scoped to the measured stacks.
- `bun install` timings are warm-cache.
- The false-GREEN measurement required mutating legacy2's primary (scratch probe, removed;
  `git status --porcelain` verified 0 after).
- Module resolution **walks up** the directory tree: a worktree inside the repo resolved
  `@legacy/shared` from the *primary's* `node_modules` while an outside one did not — identical
  otherwise. Partial, invisible cross-checkout resolution. Filed `6c689f7e9f96`; needs its own
  spike.

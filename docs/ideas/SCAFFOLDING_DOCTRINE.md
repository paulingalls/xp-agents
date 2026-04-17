# Scaffolding Doctrine

## Purpose

Define how the plugin writes new tooling into a project — acceptance
harnesses, CI workflows, development ergonomics — and the guardrails
that keep scaffolding from being intrusive, destructive, or
over-opinionated.

This doctrine is cross-cutting. It is invoked by other doctrines
(acceptance, branching) that identify *what* is missing but
deliberately refuse to *add* it themselves. Those doctrines define the
gap; this one defines how the gap gets filled when the customer asks
for help.

---

## Principle

Analysis is read-only. Scaffolding is write. The plugin keeps these
fully separate so customers trust analysis skills not to surprise them
with file changes, and trust scaffolding skills to only run when
explicitly invoked.

Scaffolding is **agent-driven, not template-driven**. The plugin does
not vendor frozen templates. Instead, the scaffolding skill uses the
agent's knowledge — augmented by web search for current tool
versions and best practices — to install and configure tooling.
`AskUserQuestion` drives every customer-owned decision (which tool,
which config choice, which directory in a monorepo). Correctness is
gated by a mandatory verification step: by the end of a successful
scaffold, at least one test actually runs and passes.

This approach trades the determinism of vendored templates for the
freshness and flexibility of agent-driven configuration — and relies
on verification as the safety net that catches bad generations.

---

## Core Flow

Every scaffolding invocation follows the same shape:

1. **Detect** — call the same detection logic the corresponding
   analysis skill uses. If the tooling is already present, stop and
   confirm intent with the customer before proceeding (see
   Re-Invocation below).
2. **Refresh knowledge** — before writing, confirm the latest
   installable version and current best practices for the selected
   tool via web search. Scaffolded output should reflect the tool as
   it exists today, not as the agent learned it at training time.
3. **Ask** — use `AskUserQuestion` for every customer-owned decision:
   which tool, which config style, which directory for a monorepo,
   which language features to enable. No silent guesses.
4. **Plan** — assemble the list of files to create, files to modify,
   commands to run. Show it to the customer for approval.
5. **Confirm** — customer explicitly approves the plan. No silent
   writes.
6. **Write** — apply the plan atomically. Leave no partial state on
   failure.
7. **Install and verify** — run dependency installation (npm, uv,
   bun, cargo, whatever the project uses) and a smoke check. By the
   end, at least one test must run and pass. If anything fails,
   revert cleanly.
8. **Commit** — follow the project's branching stage (see below).
9. **Record** — status event describing what got scaffolded, what
   versions were installed, and where the first passing test lives.

Skip a step and scaffolding becomes either intrusive (writing without
permission) or unreliable (committing broken scaffolding that fails
at the next step).

---

## Guardrails

### Never overwrite existing tooling without explicit intent

If detection finds an existing config, harness, or workflow, the
scaffolding skill **stops and asks** via `AskUserQuestion` what the
customer meant. Options: add a different/complementary tool on top,
redo (which routes the customer to git revert first), or cancel.
There is no silent overwrite path.

### Idempotent

Re-running scaffolding on an already-scaffolded setup detects the
existing tooling first. Without explicit "add complementary tool"
intent, nothing is written. No duplicate files, no duplicated
`package.json`/`pyproject.toml` entries.

### Preview before write

Customer sees a plan before anything lands:

```
/xp-scaffold-acceptance

Selected surface: browser
Selected tool: Playwright (latest: @playwright/test 1.xx.y, confirmed via npm registry)

Planning scaffold:

  Create: tests/acceptance/example.spec.ts (happy-path test, 12 lines)
  Create: playwright.config.ts (single-project browser config, 18 lines)
  Modify: .gitignore (+1 line for playwright artifacts)
  Modify: package.json (+@playwright/test devDependency, +scripts.test:acceptance)

Install + verify:
  npm install
  npx playwright install chromium
  npx playwright test tests/acceptance/example.spec.ts    # must pass green

Commit plan:
  Branch: paul/scaffold-browser-acceptance (new, off main)
  Message: "[chore] Scaffold browser acceptance with Playwright"

Proceed? [yes / show files / no]
```

The customer can expand any file before approving. No silent writes,
no "trust me."

### Fail loud, leave no partial state

If anything fails mid-scaffold — a file write, dependency install,
the verification test, or the commit — the operation reverts
cleanly. Files get removed, manifest edits get reset, new branches
get deleted, env additions get cleaned up. The project returns to
its pre-scaffold state.

If the revert itself fails: emit a loud error with
manual-recovery instructions, not a silent inconsistency.

### Blast-radius scaling

Different scaffolding categories have different blast radiuses.
Higher blast radius requires stronger confirmation:

| Category | Blast radius | Confirmation |
|----------|--------------|--------------|
| Acceptance harness | Adds test infra; doesn't affect existing workflows | Preview + yes/no |
| Dev ergonomics (lint/format configs, commit hooks) | Changes every subsequent commit | Preview + diff of affected files + yes/no |
| CI workflows | Runs on every push; may block merges | Preview + PR-target confirmation + yes/no |
| Branch protection documentation | Advisory only (plugin never calls GitHub API) | Preview + yes/no |

Actual repository-settings changes (enabling branch protection,
granting permissions) are out of scope — the plugin never makes API
calls to external services on the customer's behalf.

### Single-purpose invocation

One scaffold command does one thing.
`/xp-scaffold-acceptance` handles acceptance, not CI.
`/xp-scaffold-ci` handles CI, not acceptance. No "scaffold
everything" mega-command — too much at once is impossible to review.

### Verification is non-negotiable

Scaffolding without a green-test verification step is not scaffolding
— it is noise. Every scaffolding category defines what "it works"
means:

- **Acceptance harness** — the generated first test runs and passes
  against the current system. A test that can't pass on first run
  masks configuration bugs.
- **CI workflows** — the YAML parses and passes the platform's
  linter (`act --list` for GitHub Actions, `gitlab-ci lint`, etc.).
- **Lint/format configs** — the linter/formatter loads and runs
  against at least one real file.

Verification failure reverts the write. No "commit and hope."

---

## Agent-Driven Configuration (Not Templates)

Historically scaffolding tools ship with frozen templates:
`create-react-app`, `cargo generate`, `cookiecutter`. This plugin does
not. Three reasons:

1. **Templates go stale.** A vendored Playwright template frozen in
   plugin v2.14 is wrong by v2.16 when Playwright 1.50 ships. Shipping
   template updates requires plugin releases. Agent-driven scaffolding
   asks the web for the current tool at invocation time.
2. **Projects differ more than templates assume.** A Next.js app in a
   monorepo with bun, a Rails app served from a subdirectory, a Django
   + Vite hybrid — template trees rarely fit cleanly. Agents handle
   irregularity via `AskUserQuestion`.
3. **Templates duplicate the plugin's native pattern.** Skills define
   *process* (ask the user, verify the result, record the event);
   LLMs provide *content* (what config to write, which package to
   install). Templates blur that boundary.

Agent-driven scaffolding requires the agent to:

- Confirm the selected tool's **latest installable version** via web
  search before writing `package.json` / `pyproject.toml` / `Cargo.toml`
  entries.
- Check the **tool's current best practices** (e.g., has Playwright's
  config format changed? Is `playwright install` still the right
  install command?).
- Handle project-specific irregularities by asking the customer rather
  than assuming.

The trade-off: less determinism than templates. The verification gate
(mandatory passing test) absorbs the risk. If the agent generates a
broken config, the test fails, and the change reverts.

---

## Tool Selection

Initial tool suggestions come from `/xp-system-context`'s surface
analysis — that's where the customer sees which surfaces need coverage
and which canonical tools exist for each. `/xp-scaffold-acceptance`
builds its tool list from that analysis output, presents it to the
customer via `AskUserQuestion`, and accepts a customer-named
alternative too.

**For tools on the canonical list** (Playwright, Cypress, pytest,
Bats, jest, cargo test, etc.): the agent proceeds with web-refreshed
knowledge of the tool.

**For tools the customer names that are not on the canonical list**:
the agent does extra web research before writing — enough to install
correctly, configure a minimal setup, and pass the verification test.
If the agent cannot find reliable installation/configuration guidance
for the named tool, it says so and declines to proceed, rather than
guessing.

This supports custom stacks (bun for monorepos, newer test runners
like vitest or bun:test, niche tools like hurl for HTTP acceptance)
without maintaining a template per tool.

---

## Monorepo Handling

Best-practice monorepo setup is non-trivial. Scaffolding does it right
or it doesn't do it.

**Detection signals** for monorepos: `packages/`, `apps/`,
`workspaces` field in `package.json`, `bun.lockb` + workspaces entry,
`pnpm-workspace.yaml`, Turborepo / Nx / Lerna config, Cargo
`workspace` section, Python monorepos with per-package
`pyproject.toml`.

**Behavior:**

1. If a monorepo is detected, `/xp-scaffold-acceptance` asks the
   customer where to scaffold: at the workspace root (shared config
   across packages), or in a specific package (`packages/<name>/`).
2. If the customer's answer is ambiguous, ask for structure details:
   is there a shared test config? Does each package run tests
   independently? Does CI run per-package or per-workspace? Use the
   answers to place files appropriately.
3. Bun is a first-class monorepo runtime — specifically support
   `bun` for workspace-root scripts (`bun test`, bun-installed
   devDependencies, bun-compatible Playwright wiring).

For single-package repos, scaffolding defaults to the repo root. No
`--cwd` needed.

---

## Interaction With Other Doctrines

### Acceptance doctrine

Acceptance scaffolding produces a **minimal working harness**: the
runner, the config, and one test that exercises the current system's
happy path and passes. The first test is proof-of-life, not coverage.

After scaffolding:

- `system_context.md`'s "Acceptance Testing" section reflects the
  newly-present layer.
- The original `/xp-system-context` concern about the missing layer
  is resolved.
- A template command is recorded that sprint-start can use when
  populating future stories' `acceptance_execution.command` field.

**Coverage builds forward, not backward.** Going forward, milestone
**capstone stories** (see acceptance doctrine) naturally own the
cross-cutting acceptance tests the new harness enables. If the
customer wants to **backfill** acceptance coverage over already-shipped
features, that is a separate sprint — not something scaffolding
injects.

### Branching doctrine

Scaffolding is work. Work follows the branching doctrine:

- **Stage 0** (below floor): committed directly to `main` with
  `[chore]` prefix.
- **Stage 1**: scaffolding gets its own `<user>/scaffold-<what>`
  branch, merged directly to `main` on verification green.
- **Stage 2+**: scaffolding branch + PR to `main` (or integration
  branch at Stage 3), same as any milestone delivery.

Scaffolding does not bypass the commit gate. `[chore]` prefix exists
for exactly this case at Stage 0–1; at Stage 2+, CI gates the PR.

---

## Teammate Interaction

Scaffolding **refuses to run while any teammate worktree is live**.
The blast radius — manifest changes, dependency installs, shared
config files — makes post-scaffold merge conflicts a near-certainty.

Refusal message:

> *"N teammate worktrees are currently live: story-042 (paul),
> story-043 (alice). Scaffolding modifies shared manifests and adds
> dependencies; running it now would create merge conflicts when
> teammate work lands. Finish or pause teammate worktrees, then
> re-invoke."*

No `--force` escape hatch. A customer who needs to scaffold while
teammates are live can create a clean branch off an unrelated base
and scaffold there — but doing so knowingly, in git, rather than via
a plugin flag that hides the trade-off.

---

## Re-Invocation

When a customer invokes a scaffold command and detection finds the
tooling already in place, the skill does **not** silently refuse and
does **not** offer destructive overwrite. Instead it asks via
`AskUserQuestion`:

> *"Detected existing Playwright configuration
> (`playwright.config.ts`, `@playwright/test` in package.json). What
> would you like?*
>
> - *Add a complementary tool on top (e.g., Cypress alongside
>   Playwright)*
> - *Redo from scratch (you'll need to `git revert` the original
>   scaffold commit first; I can point you to the commit)*
> - *Cancel — I invoked this by mistake*"

"Add complementary" is a supported path (there are legitimate reasons
to have two harnesses — e.g., Playwright for e2e, a separate runner
for component tests). "Redo from scratch" is not supported via any
plugin flag — git revert is the correct mechanism, keeps the
"never overwrite" guarantee clean, and produces a history where the
redo is visible and reversible. "Cancel" exits with no changes.

---

## Commit Strategy

**Prefer a single commit** for a scaffolding invocation. Reviewability
matters — one commit showing "all the new Playwright bits" is easier
to read than six commits adding pieces one at a time.

Exceptions where multiple commits are allowed:

- Scaffolding that spans logically-distinct layers (acceptance harness
  + a separate CI workflow wiring it in) — split by layer.
- Large dependency installs with `package.json` changes best kept
  separate from code changes.

Commit message convention:

```
[chore] Scaffold <category> <target> via <tool>

Tool version: <pinned version>
Files created: <list>
Files modified: <list>
Verification: <what passed>
```

Machine-readable enough that a later `/xp-sprint-review` can
attribute scaffolding work without special handling. The pinned tool
version in the message lets future agents know what state the project
is in without re-reading lockfiles.

---

## Scope of Scaffolding Categories

Initial scope (v1):

- **Acceptance harness.** Per surface (browser, HTTP, CLI, SDK,
  automation, message/event). Customer picks the specific tool
  (`/xp-scaffold-acceptance` asks which).

Later (v2+, each its own execution plan):

- **CI workflows.** Tied to branching Stage 2+. Minimum workflow
  runs tests + lint on PR; scaffold picks the right platform
  (GitHub Actions, GitLab CI, CircleCI) from existing repo signals
  or asks.
- **Commit discipline tooling.** lefthook/pre-commit, ruff config,
  prettier config, biome, etc. Blast radius makes these opt-in per
  item.
- **Branch protection documentation.** A README section or a
  repository-settings snippet — the plugin never modifies remote
  repo settings, but it can write down what the customer should
  set.

Explicitly **out of scope** — these are not scaffolding concerns:

- Application-level code (business logic, models, UI components).
  Those are stories, not scaffolding.
- Dependency upgrades. Scaffolding adds; it does not upgrade what's
  already there.
- Infrastructure-as-code setup (Terraform modules, Kubernetes
  manifests). Too project-specific for a generic scaffolder.

---

## How Skills Use This Doctrine

- **`/xp-scaffold-acceptance`** — inline skill (not forked). Reads
  surface analysis from `system_context.md`, asks customer for tool
  choice via `AskUserQuestion`, refreshes tool knowledge via web
  search, asks project-specific questions (monorepo layout, existing
  conventions), plans + previews + writes + installs + verifies +
  commits per the Core Flow above.
- **`/xp-system-context`** — identifies missing acceptance layers as
  concerns. Points at `/xp-scaffold-acceptance` in the concern
  content. Never invokes it automatically.
- **`/xp-sprint-start`** and **`/xp-sprint-review`** — refer customers
  to `/xp-scaffold-*` skills when the conversation surfaces a
  scaffold-shaped gap, but do not invoke automatically.

Future scaffolding skills (`/xp-scaffold-ci`, `/xp-scaffold-lint`,
etc.) follow the same shape: inline, `AskUserQuestion`-driven, web-
refresh before writing, mandatory verification, branching-stage-aware
commit.

---

## Status

Draft. Not yet in any execution plan. Design source for a forthcoming
execution plan after both the acceptance-testing plan and the
branching-strategy plan ship. Deliberately parallel to the other two
doctrines (acceptance, branching) in structure and philosophy — the
three together describe the plugin's position on build-time
(branching), done-time (acceptance), and bootstrap-time (scaffolding)
concerns.

The debt event `d2d162c60200` (scaffolding-skill deferral) now has a
doctrine to point at, not just a "TBD" note. Both the acceptance and
branching doctrines reference this doc's principles rather than
repeating the scaffolding-specific rules.

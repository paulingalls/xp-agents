# Acceptance Testing Doctrine

## Purpose

Define what "done" means in this plugin, and give every XP skill a shared
reference for how acceptance testing fits the XP loop.

The bar: **when the customer comes back and sees "done," they can be
confident the agent built what they actually wanted.** Passing unit and
integration tests is necessary but not sufficient — they prove code
correctness, not product correctness.

---

## Principle

Definition of done for a story = **acceptance criteria verified against the
running system**, not "tests are green."

- Commit-level correctness (unit + integration green, review cycle complete)
  is what the TDD loop already enforces. That loop does not change.
- Story-level correctness (the system does what the customer asked) is what
  acceptance testing adds. This is what `/xp-accept` enforces.

These are two loops on two clocks. They do not block each other.

---

## Two Loops

### Commit loop (TDD)

```
red → green → /simplify → /xp-quality-review → /xp-security-triage → commit
```

Runs constantly during implementation. Fast. Enforces correctness of the
code we just wrote. Unchanged by this doctrine.

### Story loop (acceptance)

```
story in-progress → code complete → /xp-accept → run acceptance harness → done
```

Runs at story boundary. Slower. Enforces that the shipped code produces the
customer-observable behavior the story promised.

Commits continue flowing even while acceptance lags. There is no new sprint
status for "acceptance pending" — the window should be short; if it drags,
the harness is the problem.

---

## Acceptance Surfaces

Acceptance is about observing the system at its external boundary. Most
projects fit one of six surfaces. `/xp-system-context` uses this table to
detect acceptance gaps: if the project presents a given surface and the
canonical layer is missing, raise a concern (→ risk). The agent applies
judgment — a clearly-scoped proof-of-concept or throwaway script is not
a concern.

| Surface          | What "acceptance" looks like                                                            | Example tooling                                            |
| ---------------- | --------------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| HTTP / WebSocket | Real server up, drive it over the wire, assert on responses                             | curl, supertest, Postman/Newman, k6, wscat                 |
| Browser          | Real browser loads the real page, drive the UI, assert on DOM (includes extensions)     | Playwright, Cypress, Puppeteer, `playwright --load-extension` |
| CLI              | Spawn the binary with args/stdin, assert on stdout / stderr / exit code                 | Bats, pytest + subprocess, expect                          |
| SDK              | **Both** integration tests exercising the public API **and** an example consumer app that uses the SDK in its target environment | pytest `tests/integration/` + `examples/`; `cargo run --example`; `example/` consumer for JS/TS |
| Automation       | Drive a real or emulated device, assert on what the user sees                           | Detox, Maestro, Appium, XCUITest                           |
| Message / event  | Publish input (queue message, file drop, cron tick), assert on side effect (DB row, outbound call, emitted file) | LocalStack, Testcontainers, harness that publishes + polls downstream |

**SDK is intentionally AND, not OR.** Integration tests prove the public
API does what the docstrings promise. An example consumer proves the API
is actually usable from its target environment (does it import cleanly,
does the happy path work from a real caller). Both matter; they are not
redundant.

**Projects often present more than one surface.** A fullstack web app has
both Browser and HTTP surfaces; a library that also ships a CLI has both
SDK and CLI surfaces. Each surface gets its own acceptance layer.

The plugin should nudge projects toward having *some* acceptance layer at
each surface they present. A Next.js site without browser e2e is a
concern. A Rust library without an `examples/` consumer is a concern. A
Kafka consumer without a publish-and-observe harness is a concern. These
are not style preferences — they are the minimum surface area for
confident "done."

---

## BDD Prose as the Universal Acceptance Format

Every story's `acceptance_criteria` is a list of Given/When/Then
statements.

```
Given a registered user with a valid session
When they click "Export"
Then a CSV download starts within 2 seconds
And the CSV contains every row visible on screen
```

Why Given/When/Then:

- **Forces observability** — you cannot write "Then the user is happy."
  You can write "Then the user sees a toast with text 'Saved'." The shape
  prevents vague criteria.
- **Tool-agnostic** — the prose maps 1:1 onto whatever runner the project
  uses: Playwright, pytest, curl, Cucumber, manual walkthrough.
- **Readable without tooling** — prose is a forcing function even for
  stories that never get an executable test.

The executable Gherkin form (Cucumber, behave, SpecFlow) is **optional**,
adopted only when the project already uses a BDD runner. Default is prose
criteria + project-native test file.

---

## `acceptance_execution` Schema (per story in `sprint.json`)

Every story declares how acceptance gets run so `/xp-accept` knows what to
invoke:

```json
"acceptance_execution": {
  "type": "playwright" | "pytest" | "bash" | "bats" | "cargo" | "manual" | ...,
  "command": "npx playwright test tests/acceptance/story-042.spec.ts",
  "setup": "docker compose up -d && scripts/seed-test.sh",
  "notes": "Requires backend on :3000 with Postgres seeded."
}
```

- `type` — which runner the story's acceptance test uses.
- `command` — the exact invocation `/xp-accept` runs. Exit code 0 = pass.
- `setup` — optional prerequisite commands (compose up, seed DB, etc.).
- `notes` — anything the agent or human needs to know before running.

`type: "manual"` is the explicit fallback for acceptance that genuinely
cannot be automated (visual/UX judgment). In that case `/xp-accept`
presents criteria and walks the human through them.

### External Services and Hermeticity

If the developer can manually verify the feature, the acceptance test
can automate the same workflow. This applies even when the system
depends on external services (payment providers, OAuth, third-party
APIs).

- **Credentials live in the developer's environment**, not the repo.
  `system_context.md` documents the required env vars and secret
  sources. `/xp-accept` fails fast if any are missing rather than
  running in a broken state.
- **Hermetic is a direction, not a gate.** Acceptance can hit real
  sandbox services on day one. As cost, rate limits, or flake pressure
  grows, migrate toward mocks/containers (stripe-mock, LocalStack,
  Testcontainers, recorded cassettes). Doctrine encourages this shift
  but does not require it upfront.
- **A few flows resist automation** (3DS popups, SMS OTP, CAPTCHA,
  bot-blocked OAuth). Use `type: "manual"` for those, or mock at the
  boundary. Don't pretend a test covers what it can't.

---

## Automation-First Policy for `/xp-accept`

`/xp-accept` spawns the runner itself. Reads exit code. Marks story done
only on green.

Rationale:

- "Pass" under human-reported acceptance is often undeserved confidence
  after unit/integration green — the customer is essentially rubber-stamping.
- Automated e2e is "almost as good as the demo" — it closes the gap
  between what tests prove and what the user actually sees.
- Flaky e2e is a problem to fix in the harness, not a reason to stay
  human-in-loop.

Manual remains a first-class option for truly unautomatable acceptance
(e.g., "does the chart look readable"). The decision is per-story via
`acceptance_execution.type`, not a global policy.

---

## Acceptance Criteria at Two Granularities

Milestones and stories carry acceptance criteria at different
granularities on purpose.

- **Milestone-level acceptance — free-form prose.** A milestone is a
  coherent slice of customer value spanning multiple behaviors.
  Gherkin at this layer produces either uselessly-abstract statements
  ("Given a user exists, When they use the product, Then it works") or
  a list of thirty G/W/T statements that will just be rewritten more
  precisely at story level. Free-form prose lets a milestone say:
  *"Users can log in with Google or GitHub, sessions persist for 30
  days with secure refresh, and the admin console shows the auth
  source per user."* That is readable, reviewable, and rich enough
  for `/xp-sprint-start` to decompose into multiple observable
  stories. **The rule: milestone acceptance must be observable in
  principle** — a reasonable reader can imagine what passes and what
  fails — even though it is not yet executable.
- **Story-level acceptance — Given/When/Then.** A story carves out a
  single observable behavior from the milestone. Its
  `acceptance_criteria` is a list of G/W/T statements (see above).
  These are the executable done-state for the story and map to the
  acceptance test(s) `/xp-accept` runs.

Narrative done-state at milestone; executable done-state at story.

---

## Milestone-Level Acceptance (Cross-Cutting)

Story-level acceptance verifies each slice in isolation. It does not
verify that slices compose into a working feature. Two stories can
both pass their G/W/T criteria while the seam between them — interface
mismatch, UX incoherence, flow breakage at hand-off — remains broken.

Milestones therefore get an optional cross-cutting acceptance test that
exercises the composed feature as a customer would.

### The Capstone Story

When a milestone's feature has enough composition surface to warrant a
cross-cutting test, the sprint includes a **capstone story** as its
final story. The capstone story's deliverable is the cross-cutting
acceptance test itself.

- The capstone story's `acceptance_criteria` are the milestone's prose
  acceptance rendered into Given/When/Then — making the milestone's
  done-state executable.
- The capstone's `file_domain` owns the cross-cutting test file
  (e.g., `tests/acceptance/milestone-03-user-onboarding.spec.ts`).
- The capstone's `acceptance_execution` points at that test.

Writing the cross-cutting test is first-class sprint work — estimated,
visible, planned — not a ceremony tacked onto review time. The
capstone is proposed during `/xp-sprint-start` decomposition; the
customer can decline for small milestones, refactors, or surfaces
where feature-level testing is genuinely impractical.

### Milestone `acceptance_execution`

When a milestone carries cross-cutting acceptance, it grows its own
`acceptance_execution` block, with the same shape as the story-level
field:

```json
"acceptance_execution": {
  "type": "playwright",
  "command": "npx playwright test tests/acceptance/milestone-03-user-onboarding.spec.ts",
  "setup": "docker compose up -d && scripts/seed-test.sh",
  "notes": "Exercises the full signup → verify → first-login → dashboard flow"
}
```

### Sprint-Review Gate

`/xp-sprint-review` reads the milestone's `acceptance_execution`
before flipping milestone status to `delivered`:

- **All stories done AND milestone acceptance green** → milestone
  `delivered`.
- **All stories done AND milestone acceptance red** → milestone stays
  open; review reports the failure; customer decides next steps (fix,
  defer to a follow-up sprint, or override-with-concern).
- **No milestone `acceptance_execution` declared** → current behavior
  preserved (all stories done → delivered).

This gates milestone delivery on observable feature correctness, not
on "every story was individually done."

---

## How Skills Use This Doctrine

- **`/xp-system-context`** — cites the surface table when deciding
  whether to raise concerns about missing acceptance layers. Documents
  present layers in a new "Acceptance Testing" section of
  `system_context.md`.
- **`/xp-plan`** — reads the acceptance section of `system_context.md`
  when decomposing change requests into milestones. Milestones carry
  free-form, observable prose acceptance criteria shaped by what's
  achievable with the project's surfaces.
- **`/xp-sprint-start`** — writes each story's `acceptance_criteria` as
  Given/When/Then, fills in `acceptance_execution`, and proposes a
  capstone story when the milestone warrants a cross-cutting
  acceptance test.
- **`/xp-accept`** — reads story-level `acceptance_execution`, spawns
  the runner, evaluates, marks done.
- **`/xp-sprint-review`** — reads milestone-level `acceptance_execution`
  if declared; runs it before flipping the milestone to `delivered`;
  falls back to the all-stories-done check when no milestone-level
  acceptance is declared.
- **`/xp-review-plan`** — checks that plan-mode plans advance the
  current milestone's acceptance criteria; flags any vagueness.
  Requires access to `execution_plan.json` in addition to the sprint
  and the plan-mode output.

---

## Reviewer Coverage

Acceptance-thinking needs auditing at each layer where it's written:

- **Execution-plan review** — when `/xp-plan` produces
  `execution_plan.json`, an internal review step validates that each
  milestone has observable acceptance criteria rich enough to
  decompose into multiple stories, that ordering respects
  dependencies, and that the project's surfaces are referenced
  appropriately.
- **Sprint review (pre-execution)** — when `/xp-sprint-start`
  decomposes a milestone into stories, an internal review step
  validates that each story has G/W/T acceptance criteria and a
  filled-in `acceptance_execution` block.
- **Plan-mode review** — `/xp-review-plan` cross-checks the plan-mode
  output against the current milestone (from `execution_plan.json`)
  and current stories (from `sprint.json`).

---

## Analysis vs Scaffolding

`/xp-system-context` is a read-only analysis skill. **It never
scaffolds a missing acceptance harness.** Installing Playwright,
writing a first test, adding a CI workflow — these are intrusive,
opinionated changes to a project's shape. That is not what an
analysis skill does.

Instead, concerns raised by `/xp-system-context` must be **actionable**.
A concern is not "no acceptance harness found"; it is:

> *"Browser surface present (Next.js detected in `package.json`), no
> Playwright or Cypress config found. Acceptance tests cannot run until
> a harness is installed. Options: install Playwright (`npm init
> playwright`), install Cypress, or if UI coverage is not required for
> this project, explicitly dismiss this concern."*

The concern tells the customer what surface was detected, what is
missing, what to do next, and what the consequence is if left
unresolved. Vague concerns get ignored; actionable ones drive change.

A dedicated scaffolding skill (e.g., `/xp-scaffold-acceptance`) is
deferred — it needs holistic design alongside how acceptance testing
integrates across the plugin, not a bolt-on.

---

## Flaky Acceptance

`/xp-accept` runs the acceptance command **once**. Exit 0 → story done.
Non-zero → fail, show the output, **do not retry**.

Flake is information. A test that passes only on the second try is
telling you something is wrong — the harness, a race, a timing
assumption, third-party weather. Auto-retry removes the signal and
erodes "done" into "done-ish." The TDD loop does not auto-retry, and
acceptance inherits the same discipline.

When acceptance fails, the customer is given three options:

1. **Debug and re-run** — fix the cause, run again.
2. **Override this run as passing** — requires a reason string;
   records a `concern` event describing suspected flake. This preserves
   customer agency (ship when upstream is down) while forcing the
   symptom to surface at the next retrospective.
3. **Defer the story** — move it to `deferred` with a reason; comes
   back in a later sprint.

There is no "try again" option that silently masks flake. The fix for
a racy harness is to stabilize it (explicit waits, assertion-level
retry, fixed fixtures) — not to retry the whole test.

---

## Status

All design decisions resolved. This document is the source for:

- `/xp-plan` when decomposing acceptance-related change requests into
  milestones.
- `/xp-system-context` when evaluating acceptance coverage against a
  project's surfaces.
- `/xp-sprint-start` when writing story-level acceptance criteria.
- `/xp-accept` when executing and evaluating acceptance tests.

Deferred: dedicated scaffolding skill (recorded as debt).

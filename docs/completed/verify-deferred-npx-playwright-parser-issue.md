# verify-deferred parser: `npx playwright` runner not recognized

> **RETIRED 2026-05-26** (free-2026-05-26-npx-playwright-parser). Disposition:
> the report's stated premise was imprecise — `is_test_run` already classifies
> `npx playwright test` (test_parsing.py), and no plugin code auto-generates the
> `[verify-deferred]` commits described (those were the consuming agent's own
> bypass rationale). The real gap was the *path-extraction* parser
> (`verify_paths._extract_paths_from_command`), which handled only four Python
> shapes and silently failed open for every other runner — so verify-touch gave
> JS/other-platform projects no enforcement at all. Fixed across the
> author→check→verify loop: extraction now covers all classified runners
> (positional → extract the spec path; whole-tree/script-alias → fail-open
> sentinel), §10b flags non-verifiable commands, and sprint-start/xp-plan/
> doctrine steer authoring toward path-naming commands (commits 86b61fbc,
> 1fd0ce36; decision 4b2454f96b41). Suggested fix direction #1 adopted; #2/#3
> (spec-shape / config detection) unneeded once authoring names the spec.

**SMM debt id:** `2e335b58b9ba` (Orbit OS project, xp-agents plugin)
**First observed:** sprint-005 story-001 (Firebase emulator + login E2E)
**Reproduced:** sprint-005 story-002 (planning kanban E2E)

## Symptom

When a commit modifies a Playwright spec file whose test runner is invoked via
`npx playwright`, the post-commit `[verify-deferred]` parser does **not**
recognize the spec as touched by the corresponding test commit. The parser
emits a follow-up commit of the form:

```
[verify-deferred] parser doesn't recognize `npx playwright` runner;
<spec-path> IS touched by <commit-sha>
```

Concrete commits in the Orbit repo demonstrating this:

- `269ecb8 [verify-deferred] parser doesn't recognize npx playwright runner;
  login.spec.mjs IS touched by 9b6b81b`
- `edf4252 [verify-deferred] parser doesn't recognize npx playwright runner;
  planning-kanban.spec.mjs IS touched by e9d2a7a`

In both cases the underlying commit (`9b6b81b`, `e9d2a7a`) **does** touch the
spec file directly, but the parser misclassifies the runner and produces a
spurious follow-up commit instead of treating the original as verified.

## Project setup that triggers it

- Playwright is installed as a devDependency of `frontend/` (not at repo root).
- `frontend/package.json` declares the test scripts as:
  ```json
  {
    "scripts": {
      "test:e2e": "playwright test",
      "test:e2e:ui": "playwright test --ui"
    }
  }
  ```
- During iteration / from worktrees, the runner is invoked from the repo root
  as `npx playwright test ...` rather than via `npm run -w frontend test:e2e`.
  Both invocations execute the same `frontend/playwright.config.mjs` and
  `frontend/tests/e2e/*.spec.mjs`.

The parser appears to recognize the `npm run` form but not the `npx playwright`
form. We suspect the test-runner detection is matching on the literal `npm`
binary in the command string rather than the resolved Playwright config.

## Why this matters

Every story that ships a Playwright spec produces an extra
`[verify-deferred]` commit on the branch. Cosmetic noise so far (no story has
been blocked), but it pollutes the commit log and makes the close-reviewer
look twice at every PR diff to confirm the spec was genuinely covered. After
two sprints of this we're externalizing the issue rather than continuing to
record it as in-repo debt.

## Suggested fix directions

Pick whichever is cheapest for the parser:

1. **Recognize `npx playwright` as a Playwright runner invocation** — match
   the `playwright` binary regardless of whether it's wrapped in `npm run`,
   `npx`, `pnpm exec`, `yarn`, or invoked directly.
2. **Detect Playwright by spec file shape** — files matching
   `**/*.spec.{mjs,ts,js}` whose imports include `@playwright/test` are
   Playwright specs regardless of how the test command is spelled.
3. **Detect Playwright by config presence** — if `playwright.config.{mjs,ts,js}`
   exists in the project (or any parent dir up to the repo root) and the
   touched file is under the configured `testDir`, treat it as a Playwright
   spec.

Option 2 or 3 would also cover other invocation paths we haven't hit yet
(VS Code Test Explorer, CI matrix runners, `pnpm test`, etc.).

## Reproduction

```bash
# In a repo with frontend/playwright.config.mjs and a spec under frontend/tests/e2e/
cd <repo-root>
echo "// touch" >> frontend/tests/e2e/some.spec.mjs
git add frontend/tests/e2e/some.spec.mjs
git commit -m "test(e2e): touch some.spec.mjs"
npx playwright test frontend/tests/e2e/some.spec.mjs --project=chromium
# Observe: a follow-up [verify-deferred] commit is created stating the parser
# did not recognize the npx playwright runner, even though the spec was
# committed in the immediately prior commit.
```

## Affected repos

- `aljazeera/orbit-os` (private) — `ingallsp/sprint-005-frontend-char` and
  ancestor branches.

Happy to provide further parser logs or test on a patched plugin build if
useful.

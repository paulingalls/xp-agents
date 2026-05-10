# `/xp-scaffold-acceptance` — three bugs from first real-world use

**Resolution:** All three bugs shipped in sprint-081 v3.1.29 (2026-05-10). Bug 1 → known_installs.json + run_verify_identity apply phase. Bug 2 → create_scaffold_branch derives base from current non-protected branch. Bug 3 → dropped HEAD subject prefix gate from apply-record. Sprint-081 also picked up a SPIKE for related probe-quality work (decision 4d181aef4c31, sprint-082 follow-up).

---

**Plugin:** `xp-agents`
**Origin:** First real-world invocation against an Expo mobile app, 2026-05-04. User ran the skill from a free-branch with 3 prior commits already on it and chose Maestro for the automation surface.
**Status:** Draft — feed into next `/xp-sprint-start` planning.

## Why

The skill worked end-to-end but only after 3 manual recoveries: a wrong `brew install` package, a branch-base bug in `apply-commit` that pushed an empty branch to origin, and a commit-subject parse failure in `apply-record`. Capturing each with concrete fix sketches.

---

## Bug 1 — `brew install --cask maestro` pulled the wrong tool

**Symptom.** The skill's install step ran `brew install --cask maestro` and silently installed `Maestro.app` v0.15.4 (an unrelated GUI productivity app), not the mobile-dev-inc Maestro CLI for mobile e2e testing. The verify step then raised a Python exception (binary-not-found) because the CLI wasn't on PATH.

**Root cause.** Two compounding issues:
- The web-search step that suggested the install command found the popular but wrong package (Maestro.app).
- The skill's install probe doesn't validate that the installed binary matches the expected tool — it only checks `brew install` exit code.

**Recovery (manual).** User uninstalled the wrong cask, then discovered that even after `brew tap mobile-dev-inc/tap`, plain `brew install maestro` still resolved to the wrong package. The fully-qualified `brew install mobile-dev-inc/tap/maestro` finally pulled the correct CLI (Maestro 2.5.1 + openjdk + glib + little-cms2).

**Fix directions:**

1. **Tool-identity verification probe.** After install, before declaring success, run the tool's `--version` and assert the output matches an expected pattern (e.g., for Maestro mobile CLI: `Maestro 2.x.x` with no GUI references). If it doesn't match, treat install as failed.

2. **Known-good install map for popular acceptance tools.** Override the web-search install command with a curated map for tools where the popular name collides:
   ```
   maestro (mobile e2e):  brew install mobile-dev-inc/tap/maestro
   playwright:            npm install -D @playwright/test && npx playwright install
   cypress:               npm install -D cypress
   ...
   ```
   The web-search output becomes a fallback for tools not in the map.

3. **Fully-qualified install commands by default.** When a brew tap is involved, always use `tap/formula` form — `brew install user/tap/name` works whether the tap is added or not. Plain `brew install name` is ambiguous when multiple taps offer the same name.

### File domain (when this lands as a sprint story)

- `plugins/xp-agents/skills/xp-scaffold-acceptance/SKILL.md` — Step 4 (build plan) gains the known-good install map; Step 6 (apply) adds the version-output probe to verify
- `plugins/xp-agents/skills/xp-scaffold-acceptance/scripts/known_installs.json` (NEW) — the curated map
- `plugins/xp-agents/tests/integration/test_scaffold_acceptance.py` — test that the verify step rejects a wrong-binary install (mock a `brew install` that lands the wrong tool)

---

## Bug 2 — `apply-commit` branched off `main`, ignored active free-branch, pushed empty branch to origin on timeout

**Symptom.** User ran the skill while on a free-branch (`paulingalls/free-2026-05-05-check-prod-readiness`) with 3 prior commits. The skill's `apply-commit` step:

1. Created a new branch `paulingalls/scaffold-automation-acceptanc` (note truncation — separate cosmetic bug) off `main`'s HEAD `fde1713`, NOT off the active free-branch
2. Pushed the new branch to origin BEFORE the commit step ran
3. Hit a 30-second timeout on the commit step
4. Left an EMPTY branch on origin + a divergent local branch + the user's free-branch with the staged scaffold files still in working tree

**Root cause.** Two compounding bugs:

- `apply-commit` derives its branch base from a hardcoded `main` instead of consulting the project's branching context. `branching.py get-base --cwd .` already knows about free-branch / sprint-branch / plan-branch contexts and would have returned the right answer.
- The push-then-commit ordering means a timeout in the commit step leaves a polluted remote. Push should be the LAST step, after commit succeeds.

**Recovery (manual).** User switched back to the free-branch (which still had the staged scaffold), deleted the rogue local + remote `paulingalls/scaffold-automation` branch (with explicit confirmation), committed the scaffold manually with the correct trailer, and proceeded.

**Fix directions:**

1. **Use `branching.py get-base` (or stay on the current branch entirely).** The skill should ask: "scaffold work belongs on this branch?" — yes (commit on the current branch) or "create a new branch" — and if the latter, derive the base from `branching.py get-base --cwd .` so the new branch forks from the right place.

2. **Reorder: stage → commit → push.** Push is irreversible from the orchestrator's standpoint (rewriting remote history requires force-push, which the plugin avoids). Commit-first, push-last means a commit-step failure leaves no remote pollution.

3. **Truncated branch name.** Cosmetic — the slug seems to be cut at some byte limit and lost the `e` from `acceptance`. Worth a quick test pinning the slug-generation logic to a length cap that respects word boundaries.

### File domain

- `plugins/xp-agents/skills/xp-scaffold-acceptance/scripts/apply_commit.py` (or wherever apply-commit lives) — replace `main` with `branching.py get-base` lookup; reorder push to AFTER commit
- `plugins/xp-agents/skills/xp-scaffold-acceptance/SKILL.md` — Step 8 prose reflects the new ordering + branch derivation
- `plugins/xp-agents/tests/integration/test_scaffold_acceptance.py` — pin: scaffold launched from a free-branch commits to that free-branch (or a child), never to a fresh-from-main branch; pin: commit-step failure leaves origin clean

---

## Bug 3 — `apply-record` refuses commits whose subject doesn't match its hardcoded format

**Symptom.** After manually committing the scaffold (because of bug 2's recovery), `apply-record` refused to flip the surface from `gap` → `covered` because the user's commit subject (`feat(scaffold): ...` style, conventional-commits) didn't match the skill's hardcoded `[chore] Scaffold ...` prefix.

**Root cause.** `apply-record` parses the commit subject to identify "the scaffold commit" rather than looking it up by SHA or by SMM event id. Subject parsing is brittle by design — every project has its own commit-message convention (conventional-commits, semantic-release, plain prose, project-specific prefixes), and the plugin can't enforce one without breaking adoption in projects that use a different style.

**Recovery (manual).** User manually applied what `apply-record` would have done: edited `system_context.json` to flip the surface to `covered`, appended a decision event with `metadata.resolves` pointing at the surface-gap risk event.

**Fix direction:**

Pass the SHA of the just-completed commit (or the SMM event id of the snapshot/plan event) directly into `apply-record` instead of parsing for it. The skill already has the SHA in scope from the `git commit` invocation that just ran — wire it through. `apply-record` becomes:

```bash
apply-record --commit-sha <sha> --surface <name> --resolves <event-id>
```

No subject parsing, no convention assumption, works regardless of how the user formats commits.

### File domain

- `plugins/xp-agents/skills/xp-scaffold-acceptance/scripts/apply_record.py` (or wherever apply-record lives) — accept `--commit-sha` argument, drop subject parsing
- `plugins/xp-agents/skills/xp-scaffold-acceptance/SKILL.md` — Step 9 passes the SHA captured from Step 8
- `plugins/xp-agents/tests/integration/test_scaffold_acceptance.py` — pin: apply-record works with arbitrary commit subjects (conventional-commits, plain prose, [chore] prefix)

---

## Sequencing

- Bugs 1 / 2 / 3 are independent and dep-free with each other
- Bug 2 is the highest-leverage fix (it left polluted state on origin and could have lost work)
- Each is roughly one M-sized story; could ship together as a "scaffold-acceptance hardening" mini-sprint, or as three stories within a larger sprint

## Provenance

- All three bugs reproduced in a single real-world session (2026-05-04, SimplyHuman mobile project) on the first run of `/xp-scaffold-acceptance` against an actual Expo app
- Transcript captured by user, summarized in the section bodies above
- The user did the recovery manually — no data loss, but the recovery cost was substantial (~5 user prompts to triage and clean up)

## Shared close-pipeline reference

Apply Steps 4 → 4b → 6 below in order after the close skill's Step 3 (PR
creation), then continue with the close skill's mode-specific tail
(Step 7+). Story-close skips Steps 4 and 4b.

### Step 4: Security Review

Applies to **free, sprint, plan**. Story-close is dispatched inside
an active sprint; the enclosing sprint-close covers it.

```
Skill(skill: "security-review",
      args: "the cumulative diff on branch <CURRENT_BRANCH> since merge-base with <TARGET_BRANCH>")
```

Fold each finding into Block / Concern / Keep; file one event per
non-Keep bullet:

| Verdict | `<SEVERITY>` | `<DISPOSITION>` | Effect at Step 6 |
|---|---|---|---|
| Block   | `high`       | `Block`   | Counts toward abort-default |
| Concern | `medium`     | `Concern` | Recorded only |
| Keep    | (no event)   | —         | — |

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "concern" --agent "<close-skill-name>" --severity "<SEVERITY>" \
  --content "Security <DISPOSITION>: <one-line summary>" \
  --files '["<paths /security-review pointed at>"]' \
  --metadata '{"kind":"security","close_cycle_id":"<CLOSE_CYCLE_ID>","close_mode":"<close-mode>"}'
```

Substitute `<close-skill-name>`, `<close-mode>` (`free`/`sprint`/`plan`),
and `<CLOSE_CYCLE_ID>` / `<SMM_DIR>` from the preload values above.

**Surface the prose to the user before Step 6** — the Skill tool
result is invisible to them. Step 4 findings bypass Step 5c (the
classifier scopes to close-reviewer findings only) and flow directly
to the Step 6 count. Do NOT pass them to xp-close-reviewer in Step
4.5 — clean separation. Quality and security are independent streams.

### Step 4b: Full code review (conditional)

Run only when the preload emitted `RUN_FULL_CODE_REVIEW=true` (cumulative close
diff ≥ `REVIEW_CYCLE_THRESHOLD` code files); skip otherwise — story-close and
below-threshold closes never set it. This is the one broad multi-agent
correctness pass over the whole close diff (per-increment used self-find). Run:

```
Skill(skill: "code-review", args: "high <TARGET_BRANCH>...HEAD")
Skill(skill: "xp-quality-review")
```

`/code-review` identifies (fixes nothing); the `/xp-quality-review` that follows
sees `MODE=consume-findings` and spawns xp-code-reviewer to validate & fix, plus
quality/drift/debt. Fix inline or record as debt. Like Step 4, handled here —
not Step 5c.

### Step 5: Present findings

Output the reviewer's Keep / Concern / Block summary verbatim — the
tool result is invisible to the user.

### Step 5b: Resolve Addressed Concerns

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/xp-work-selection/scripts/triage_preload.py \
  --smm-dir <SMM_DIR>
```

For each concern annotated **MAYBE ADDRESSED** in the "Open Concerns"
section: judge from session context + listed commits. When confident:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/xp-work-selection/scripts/work_selection_decide.py \
  triage-drop --smm-dir <SMM_DIR> --event-id <event-id>
```

When in doubt, leave open. Report auto-resolved count alongside
reviewer findings before Step 6.

### Step 5c: Classify and act on reviewer findings

For each NEW concern/block from xp-close-reviewer in Step 4.5
(severity high "Block" or medium "Concern"), decide if code-fixable.
**Default to ASK if unsure.**

**Code-fixable — fix now, then resolve via `Resolves-Event: <event-id>`
in the fix commit body:**

> When the fix lands in a teammate worktree, run from the orchestrator
> with `git -C <worktree-path> commit ...` — never `cd <wt> && git
> commit && cd -`. The cd-back fires before the trailer-extract hook,
> so the hook reads the wrong HEAD and the auto-link silently breaks.

- `lint` → `ruff format && ruff check --fix`, re-test
- `test_failure` → read the test runner output, edit at named file:line, re-run
- `ac_coverage` (missing assertion / weak / partial AC / brittle /
  ambiguous) → add the assertion or doc named in the concern
- `file_domain_drift` → move file into declared dir OR amend
  `sprint.json` `file_domain`
- `honesty_gap` → fix the named code path
- `file_split` (>500 lines) → extract a cohesive group, update imports
- `spec_drift` (plan vs SKILL.md vs sprint.json mismatch) → update the
  doc that disagrees with the plan

**Ask user — defer to Step 6's AskUserQuestion:**

- `design_decision` (superseded decision, architectural call) → user
  picks; record a decision event with the chosen option
- `ac_amendment` (AC interpretation choice) → user re-reads the AC,
  updates inline in the plan/doc
- `plan_discipline` (cadence, post-hoc unactionable, informational) →
  acknowledge and move on; cannot be retroactively fixed

When in doubt, ASK — silent mis-fixes are hard to recover.

**Audit trail — required.** Retro tooling samples these to measure
classifier precision; the Step 6 auto-merge gate counts ask-routed
events to verify whether it can fire.

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "status" --agent "main" \
  --content "concern-classify <event-id>: <fix|ask> (<category>) — <one-line reason>" \
  --metadata '{"action":"concern_classify","route":"<fix|ask>","category":"<category>","concern_id":"<event-id>","close_cycle_id":"<CLOSE_CYCLE_ID>"}' \
  --working-on '[]'
```

`metadata.action="concern_classify"` is the canonical signal; `route`
is the fix/ask discriminator. `close_cycle_id` (from the preload)
scopes the count — SMM is shared across worktrees and concurrent
close-cycles would otherwise leak in.

After acting, continue to the next finding, then Step 6.

### Step 6: Confirm the merge

Use `AskUserQuestion`: "Merge into ${TARGET_BRANCH}" or
"Abort — fix concerns first".

**Compute abort-default deterministically.** Every Block from Step 4.5
(quality) AND Step 4 (security) was recorded as a `severity=high`
concern in this close cycle:

```bash
HIGH_CONCERN_COUNT=$(python3 ${CLAUDE_PLUGIN_ROOT}/smm/smm_cli.py \
  --smm-dir <SMM_DIR> count-concerns \
  --severity high --cycle-id <CLOSE_CYCLE_ID> --since-ts <CLOSE_START_TS>)
```

If `> 0`, list "Abort — fix concerns first" FIRST with "(Recommended)"
appended. The user can still pick Merge to override. When 0, keep
default ordering (Merge first). `<SMM_DIR>`, `<CLOSE_CYCLE_ID>`,
`<CLOSE_START_TS>` come from the preload above.

If the user picks abort, stop here. Branch and PR stay intact.

If the preload included a `### HOOK_GUIDANCE` section, follow it
before confirming the merge.

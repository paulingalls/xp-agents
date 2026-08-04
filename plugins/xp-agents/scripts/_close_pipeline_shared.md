## Shared close-pipeline reference

Apply Steps 5-6b below after Step 4.5, then the skill's tail (Step 7+).

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

> A fix in a teammate worktree commits with `git -C <worktree-path>
> commit ...`, path substituted literally — never `cd <wt> && git
> commit && cd -`, whose cd-back beats the trailer-extract hook and
> silently breaks the auto-link.

- `lint` → run the project's formatter and linter in fix mode, re-test
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

`close_cycle_id` (from the preload) scopes the count — SMM is shared
across worktrees and concurrent close-cycles would otherwise leak in.

Loop to the next finding, then Step 6.

### Step 6: Confirm the merge

Use `AskUserQuestion`: "Merge into ${TARGET_BRANCH}" or
"Abort — fix concerns first".

**Compute abort-default deterministically.** Every Block from Step 4.5
(quality) AND Step 4 (security) was recorded as a `severity=high`
concern in this close cycle:

```bash
HIGH_CONCERN_COUNT=$(git diff --no-renames --name-only -z <TARGET_BRANCH>...<CURRENT_BRANCH> \
  | python3 ${CLAUDE_PLUGIN_ROOT}/smm/smm_cli.py \
  --smm-dir <SMM_DIR> count-concerns --diff-paths - \
  --severity high --cycle-id <CLOSE_CYCLE_ID> --since-ts <CLOSE_START_TS>)
```

If `> 0`, list "Abort — fix concerns first" FIRST with "(Recommended)"
appended. The user can still pick Merge to override. When 0, keep
default ordering (Merge first). `<SMM_DIR>`, `<CLOSE_CYCLE_ID>`,
`<CLOSE_START_TS>` come from the preload above.

Pipe the diff verbatim: `--no-renames` keeps a renamed file's OLD
path, `-z` survives a newline in one. `--diff-paths -` drops ONLY an
untagged concern whose files all lie outside the diff (the log is
shared across worktrees); an empty or unreadable diff counts
everything — fail closed. Name both branches, not `HEAD`: the range
must not depend on your cwd.

If the user picks abort, stop here — after Step 6b. Branch and PR stay
intact.

If the preload included a `### HOOK_GUIDANCE` section, follow it
before confirming the merge.

### Step 6b: Release the cycle markers

On **every** exit — merge, auto-merge, abort — right after Step 6,
including when the mode's gate skipped the Step 6 prompt:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/markers.py \
  --smm-dir <SMM_DIR> consume CLOSE_CYCLE_ID
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/markers.py \
  --smm-dir <SMM_DIR> consume CLOSE_CYCLE_ACTIVE
```

Left behind, the id tags concerns raised after this close ended and the
next close's `--cycle-id` count then EXCLUDES those; the active marker
keeps gating Stop. Both are safe to re-run or run absent.


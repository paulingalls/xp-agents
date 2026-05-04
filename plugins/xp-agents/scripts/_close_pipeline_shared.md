## Shared close-pipeline reference

The following steps are shared across the close skills; each step lists
its applicable skills inline (most apply to all four — story, sprint,
plan, free — but a few are scoped). Apply them in order after the close
skill's Step 4 (Fork the close-reviewer), then continue with the close
skill's mode-specific tail (Step 7+).

### Step 4.5: Security Review

Skills that apply this step: **free, sprint, plan** close unconditionally, plus **story (when no sprint envelope wraps)**.
Story-close defers to sprint-close's cumulative diff when an active
sprint wraps the story; otherwise (no sprint, or orphan story branch)
Step 4.5 fires from story-close itself. See xp-story-close/SKILL.md
Step 4.5 for the gating clause.

Invoke `/security-review` against the cumulative close diff. The close
skill is main-agent context, so the PostToolUse:Skill hook fires and
emits the SECURITY_COMPLETE event automatically.

```
Skill(skill: "security-review",
      args: "the cumulative diff on branch <CURRENT_BRANCH> since merge-base with <TARGET_BRANCH>")
```

Read the prose findings; fold each bullet into Block / Concern / Keep
and file one event per non-Keep bullet. Reviewer verdict → values:

| Reviewer verdict | `<SEVERITY>` | `<DISPOSITION>` | Effect at Step 6 |
|---|---|---|---|
| Block            | `high`       | `Block`         | Counts toward abort-default |
| Concern          | `medium`     | `Concern`       | Recorded only |
| Keep             | (no event)   | —               | — |

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "concern" --agent "<close-skill-name>" --severity "<SEVERITY>" \
  --content "Security <DISPOSITION>: <one-line summary>" \
  --files '["<paths /security-review pointed at>"]' \
  --metadata '{"kind":"security","close_cycle_id":"<CLOSE_CYCLE_ID>","close_mode":"<close-mode>"}'
```

Substitute `<close-skill-name>` (e.g. `xp-free-close`), `<close-mode>`
(`free`/`sprint`/`plan`/`story`), `<CLOSE_CYCLE_ID>`, and `<SMM_DIR>`
from the preload values at the top of this context.

The shared Step 6 abort-default reads severity=high concerns filtered
by `close_cycle_id` + `since-ts` (deterministic event count) — Block
findings here automatically Recommend-Abort. **Do not pass these
findings to xp-close-reviewer in Step 4 — clean separation.** The
reviewer is quality-only; security and quality are independent
review streams that converge only at the Step 6 abort-default count.

**Surface the security review prose to the user before Step 6.** The
Skill tool result is not visible to them — output the Block / Concern
/ Keep bullets as text so they can see what the abort-default count
is reacting to. (Step 5 will surface the close-reviewer prose
separately; both streams arrive at Step 6 independently.)

Step 4.5 concerns bypass Step 5c (the fix-or-ask classifier scopes
to close-reviewer findings only — security findings flow directly to
the Step 6 count).

### Step 5: Present findings

Output the reviewer's Keep / Concern / Block summary verbatim to the
user. The tool result is not visible to them — surface it as text.

### Step 5b: Resolve Addressed Concerns

Scan for open concerns that this work likely addressed. Run the triage
preload to find them:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/xp-work-selection/scripts/triage_preload.py \
  --smm-dir <SMM_DIR>
```

Focus on the "Open Concerns" section of the output. For each concern
annotated with **LIKELY ADDRESSED**: use your session context and the
listed commits to judge whether the concern was genuinely fixed. When
confident, auto-resolve:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/xp-work-selection/scripts/work_selection_decide.py \
  triage-drop --smm-dir <SMM_DIR> --event-id <event-id>
```

When in doubt, leave the concern open — it surfaces at the next kickoff
for manual triage. Report how many were auto-resolved alongside the
reviewer findings before asking the user to confirm the merge.

### Step 5c: Classify and act on reviewer findings

For each NEW concern or block xp-close-reviewer just filed in Step 4
(severity high "Block" or severity medium "Concern" — both apply),
decide whether it's code-fixable. **Default to ASK if unsure** —
better to surface a fixable item to the user than to mis-classify a
non-code item as "fix" and silently get it wrong.

**Code-fixable — fix it now, then mark resolved by including
`Resolves-Event: <event-id>` in the fix commit body** (the auto-link
hook closes the concern when the trailer matches):

- `lint` (ruff/format errors) → `ruff format && ruff check --fix`, re-test
- `test_failure` (failing tests) → read the test runner output, edit
  code at the named file:line, re-run the failing test
- `ac_coverage` (missing assertion / weak test / partial AC / brittle
  test design / ambiguity) → add the assertion or doc named in the
  concern
- `file_domain_drift` (modified files outside declared `file_domain`) →
  move file into declared dir OR amend `sprint.json` `file_domain`
- `honesty_gap` (reviewer found a miss at file:line) → fix the named
  code path
- `file_split` (file >500 lines) → pick a cohesive extraction target
  (group of related functions/classes), move group, update imports
- `spec_drift` (plan vs SKILL.md vs sprint.json mismatch) → update the
  doc that disagrees with the plan

**Ask user — defer to Step 6's AskUserQuestion:**

- `design_decision` (superseded decision, architectural call) → user
  picks; record a decision event with the chosen option
- `ac_amendment` (AC interpretation choice) → user re-reads the AC,
  updates the AC reading inline in the plan/doc
- `plan_discipline` (cadence, post-hoc unactionable, informational
  heads-up) → acknowledge and move on; cannot be retroactively fixed

When in doubt, ASK — the user can always redirect a fixable item, but
a silent mis-fix is hard to recover.

**Audit trail:** for each classified item, append a status event
recording the decision. Retrospective tooling samples these events to
measure classifier rule precision over time, AND the Step 6
auto-merge gate (story-close + free-close) counts the ask-routed
events to verify whether it can fire — so this step is required for
every classification:

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "status" --agent "main" \
  --content "concern-classify <event-id>: <fix|ask> (<category>) — <one-line reason>" \
  --metadata '{"action":"concern_classify","route":"<fix|ask>","category":"<category>","concern_id":"<event-id>","close_cycle_id":"<CLOSE_CYCLE_ID>"}' \
  --working-on '[]'
```

The `--metadata` block is the canonical signal: `action="concern_classify"`
is what `smm_cli.py count-classifications` filters on, and `route` is
the fix/ask discriminator the auto-merge gate counts. `close_cycle_id`
is the strict scoper — substitute the `CLOSE_CYCLE_ID` value emitted
by the preload at the top of this context. It prevents concurrent
close-cycles in other teammate worktrees from leaking
classifications into this cycle's count (SMM is shared across
worktrees). The `concern-classify` content prefix stays for human
readability (retros + grep-by-eye); structured consumers read
`metadata.action`, never the content string.

After acting on the classification (fix-and-mark or queue-for-Step-6),
continue to the next finding. When all findings are processed,
proceed to Step 6.

### Step 6: Confirm the merge

Use `AskUserQuestion` to ask whether to proceed with the merge. Two
options: "Merge into ${TARGET_BRANCH}" or "Abort — fix concerns first".

**Compute the abort-default flag deterministically.** Every Block from
the close-reviewer (Step 4 quality review) AND every Block from the
Step 4.5 security review is recorded as a `severity=high` concern
within this close cycle. Count them via the structured filter:

```bash
HIGH_CONCERN_COUNT=$(python3 ${CLAUDE_PLUGIN_ROOT}/smm/smm_cli.py \
  --smm-dir <SMM_DIR> count-concerns \
  --severity high --cycle-id <CLOSE_CYCLE_ID> --since-ts <CLOSE_START_TS>)
```

If `HIGH_CONCERN_COUNT > 0`, list "Abort — fix concerns first" as the
FIRST option and append "(Recommended)" to its label. The user can
still pick Merge to override. When the count is 0, keep the default
ordering (Merge first).

`<SMM_DIR>`, `<CLOSE_CYCLE_ID>`, and `<CLOSE_START_TS>` come from the
preload values at the top of this context.

If the user picks abort, stop here. The branch and PR (if any) stay
intact for follow-up work.

If the preload included a `### HOOK_GUIDANCE` section, follow it
before confirming the merge.

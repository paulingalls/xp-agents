## Shared close-pipeline reference

The following steps are shared across all four close skills (story,
sprint, plan, free). Apply them in order after the close skill's Step 4
(Fork the close-reviewer), then continue with the close skill's mode-
specific tail (Step 7+).

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

### Step 6: Confirm the merge

Use `AskUserQuestion` to ask whether to proceed with the merge. Two
options: "Merge into ${TARGET_BRANCH}" or "Abort — fix concerns first".

**If the close-reviewer's prose summary above contains any Block
finding (recorded by xp-close-reviewer at severity high per Step 3.5),
list "Abort — fix concerns first" as the FIRST option and append
"(Recommended)" to its label.** This honors the xp-close-reviewer
Step 3.5 contract: Block findings flip the merge default to Abort.
The user can still pick Merge to override. When no Block was filed,
keep the default ordering (Merge first).

If the user picks abort, stop here. The branch and PR (if any) stay
intact for follow-up work.

If the preload included a `### HOOK_GUIDANCE` section, follow it
before confirming the merge.

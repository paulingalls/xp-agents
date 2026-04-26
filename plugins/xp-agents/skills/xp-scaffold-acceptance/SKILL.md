---
name: xp-scaffold-acceptance
description: >-
  Scaffold acceptance test harness for a project surface. Triggers on
  /xp-scaffold-acceptance. Inline skill: detects active teammates and existing
  tooling, then asks the customer to pick a surface and tool. Refuses to run
  while teammate worktrees are live; full install/verify/commit flow lands in
  M-2 through M-5.
allowed-tools:
  - Read
  - AskUserQuestion
  - Bash(python3 -c *)
---

# Scaffold Acceptance

This skill is the entry point for `/xp-scaffold-acceptance`. **Inline — do not fork a subagent.** M-1 covers Step 1 (detect) and Step 3 (ask). Steps 2 and 4–9 are reserved for later milestones; never write, install, or commit during M-1.

## Step 1: Detect

**Resolve `SMM_DIR` and your `agent_id` from the session.** Then perform two checks before doing anything else.

### 1a. Refuse if teammates are live

Call `coordination.has_active_teammates(smm_dir, agent_id)` from `plugins/xp-agents/scripts/coordination.py`:

```bash
python3 -c "
import sys
from pathlib import Path
sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT}/scripts')
from coordination import has_active_teammates
print(has_active_teammates(Path('<SMM_DIR>'), '<your-agent-id>'))
"
```

If the result is `True`, **stop immediately** and emit the doctrine refusal text verbatim. Replace `N` with the actual count and list the live worktrees:

> *"N teammate worktrees are currently live: story-042 (paul), story-043 (alice). Scaffolding modifies shared manifests and adds dependencies; running it now would create merge conflicts when teammate work lands. Finish or pause teammate worktrees, then re-invoke."*

No `--force` flag, no escape hatch. Exit cleanly.

### 1b. Read surfaces and detect existing tooling

If no teammates are live, call `scaffold_detect.read_acceptance_surfaces(smm_dir)` to load the `acceptance_surfaces` array from `system_context.json`. For each surface, call `scaffold_detect.detect_existing_tooling(surface_name, repo_root)`:

```bash
python3 -c "
import sys
from pathlib import Path
sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT}/scripts')
from scaffold_detect import read_acceptance_surfaces, detect_existing_tooling
smm = Path('<SMM_DIR>')
repo = Path('<REPO_ROOT>')
for surface in read_acceptance_surfaces(smm):
    name = surface['name']
    print(name, detect_existing_tooling(name, repo))
"
```

If `read_acceptance_surfaces` returns an empty list, `system_context.json` either is missing or has no `acceptance_surfaces` field — exit cleanly with: _"No acceptance surfaces are recorded in system_context.json. Run /xp-system-context first to detect surfaces, then re-invoke."_

If any surface reports `has_tooling=True`, route to the **re-invocation stub** (below). Otherwise proceed to Step 3.

### 1c. Re-invocation stub

When existing tooling is detected, use `AskUserQuestion` to ask the customer how to proceed. M-1 only stubs the question — every option exits with the M-5 deferral message:

```
AskUserQuestion(
  question: "Detected existing <tool> for <surface>. What would you like?",
  options: [
    "Add a complementary tool on top",
    "Redo from scratch (git revert path)",
    "Cancel — invoked by mistake",
  ]
)
```

Whatever the customer picks, respond:

> Full re-invocation flow lands in M-5 — for now, no changes were made. Re-invoke after M-5 ships, or perform the action manually.

Exit cleanly.

## Step 2: Refresh knowledge

_Reserved for M-2 onward — web-search confirmation of tool versions and best practices before any write._

## Step 3: Ask

If detection finds no existing tooling and surfaces are present, use `AskUserQuestion` to gather the customer's choices.

**Surface question** — list the surfaces from `read_acceptance_surfaces` whose `status` is `"gap"` (or all surfaces if none are tagged gap). Each option is the surface name. Skip if there is exactly one gap surface.

```
AskUserQuestion(
  question: "Which acceptance surface should I scaffold?",
  options: [<surface name per gap surface>]
)
```

**Tool question** — call `scaffold_detect.canonical_tools_for(<chosen surface>)` and present each canonical tool plus a final option for a customer-named alternative:

```
AskUserQuestion(
  question: "Which tool for the <surface> surface?",
  options: [
    <canonical tool 1>,
    <canonical tool 2>,
    ...,
    "Other (I'll name it)",
  ]
)
```

If the customer picks "Other," ask a follow-up free-text question for the tool name. Record both selections in working memory and exit cleanly. **No writes, no installs.** The plan-and-confirm flow lands in M-2 onward.

## Step 4: Plan
## Step 5: Confirm
## Step 6: Write
## Step 7: Install and verify
## Step 8: Commit
## Step 9: Record

_Reserved for M-2 onward — see docs/ideas/SCAFFOLDING_DOCTRINE.md §Core Flow for the full nine-step pipeline._

---
name: xp-scaffold-acceptance
description: >-
  Scaffold acceptance test harness for a project surface. Triggers on
  /xp-scaffold-acceptance. Inline skill: detects active teammates and existing
  tooling, asks the customer to pick a surface and tool, web-refreshes the
  tool's latest version, then plans + previews the scaffold for explicit
  yes/show-files/no confirmation. Refuses to run while teammate worktrees are
  live; the actual write/install/commit flow lands in M-3 through M-5.
allowed-tools:
  - Read
  - AskUserQuestion
  - WebSearch
  - Bash(python3 -c *)
---

# Scaffold Acceptance

This skill is the entry point for `/xp-scaffold-acceptance`. **Inline — do not fork a subagent.** M-1 covers Step 1 (detect) and Step 3 (ask). M-2 adds Step 2 (web-refresh) and Steps 4–5 (plan + confirm). Steps 6–9 are reserved for M-3 onward; never write, install, or commit during M-1 or M-2.

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

#### Detection caveat: NO_CONFIG_FILE_SIGNAL

The `sdk` and `message_event` surfaces are listed in
`scaffold_detect.NO_CONFIG_FILE_SIGNAL`. For those surfaces,
`detect_existing_tooling` returning `has_tooling=False` means **"no
config-file signal,"** not **"no tooling exists"** — sdk libraries use
inline doctest/hypothesis patterns, message/event harnesses wire in via
test-runner code without dedicated config files. If the chosen surface
is `sdk` or `message_event`, treat the absence of a config file as
inconclusive and ask the customer whether tooling already exists before
proceeding to Step 4. Do not silently scaffold over hidden coverage.

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

After Step 3 collects surface + tool selections (and before Step 4 builds the plan), use the `WebSearch` tool to confirm the **tool's latest stable version** and current best practices. Search for `<tool> latest stable release` and, separately, `<tool> recommended config <year>`. Pin the version into a local Python variable (`tool_version`) — Step 4 records it in the plan and Step 8 (M-4) writes it into the commit message and dependency manifest.

**Canonical tools** (`scaffold_detect.canonical_tools_for(surface)`): proceed with the web-refreshed knowledge.

**Customer-named non-canonical tools**: do extra research — install command, config-file format, minimal verification command. Then call `scaffold_plan.decline_if_unreliable(tool, guidance)`:

```bash
python3 -c "
import sys
from pathlib import Path
sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT}/scripts')
from scaffold_plan import decline_if_unreliable
result = decline_if_unreliable('<tool>', '''<guidance text or empty>''')
print(result.decline, result.reason)
"
```

If `result.decline` is `True`, emit `result.reason` verbatim and exit cleanly — declining rather than guessing.

**Still no writes in M-2.** Web-refresh produces in-memory variables only.

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

If the customer picks "Other," ask a follow-up free-text question for the tool name. Record both selections in working memory and proceed to Step 2 (web-refresh) followed by Step 4 (plan).

## Step 4: Plan

Assemble the structured `ScaffoldPlan` via `scaffold_plan.build_plan(...)`. Build the `files_to_create` and `files_to_modify` lists from your web-refreshed knowledge of the tool — typical entries: a config file, a happy-path test, a `.gitignore` modification, a `package.json` / `pyproject.toml` / `Cargo.toml` modification. Set `verify_cmd` to the runner's invocation against the generated test (e.g., `npx playwright test tests/acceptance/example.spec.ts`). Set `branch_name` to `<user>/scaffold-<surface>-acceptance`.

**Draft each file body in working memory before assembling the plan.** The plan dict carries only path/description/line_count metadata — the actual file content lives in your working memory so Step 5's `show files` branch can print it on demand. If you cannot author a file body confidently from web-refreshed knowledge, do not include it in `files_to_create`; loop back to Step 2 for more research, or call `decline_if_unreliable` and exit.

```bash
python3 -c "
import sys, json
from dataclasses import asdict
from pathlib import Path
sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT}/scripts')
from scaffold_plan import build_plan
plan = build_plan(
    surface='<surface>',
    tool='<tool>',
    tool_version='<version>',
    files_to_create=[<...>],
    files_to_modify=[<...>],
    install_cmds=[<...>],
    verify_cmd='<verify>',
    branch_name='<user>/scaffold-<surface>-acceptance',
)
print(json.dumps(asdict(plan), indent=2))
"
```

**M-2 stops here for write-side concerns.** The plan is in-memory only. Step 5 previews it; Steps 6–9 (M-3 onward) actually write.

## Step 5: Confirm

Render the plan with `scaffold_plan.render_preview(plan)` and show the output to the customer verbatim. Then ask via `AskUserQuestion`:

```
AskUserQuestion(
  question: "<rendered preview ending with: Proceed? [yes / show files / no]>",
  options: [
    "yes",
    "show files",
    "no",
  ]
)
```

**`yes`** — in M-2, stop here with: _"Plan approved. Write/install/verify/commit lands in M-3 onward — no changes were made."_ M-3 will pick up from this point.

**`show files`** — Print every drafted file body (authored in working memory during Step 4) in fenced code blocks, with the target path as the heading for each block. Then re-ask the same `AskUserQuestion` with the three options. Looping `show files` is allowed; the customer must eventually pick `yes` or `no`.

**`no`** — exit cleanly with: _"Cancelled — no changes were made."_ No partial state.

## Step 6: Write
## Step 7: Install and verify
## Step 8: Commit
## Step 9: Record

_Reserved for M-3 onward — see docs/ideas/SCAFFOLDING_DOCTRINE.md §Core Flow for the full nine-step pipeline._

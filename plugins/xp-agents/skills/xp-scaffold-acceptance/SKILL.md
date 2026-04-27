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
  - Bash(python3 */scripts/scaffold_cli.py *)
---

# Scaffold Acceptance

This skill is the entry point for `/xp-scaffold-acceptance`. **Inline — do not fork a subagent.** M-1 covers Step 1 (detect) and Step 3 (ask). M-2 adds Step 2 (web-refresh) and Steps 4–5 (plan + confirm). Steps 6–9 are reserved for M-3 onward; never write, install, or commit during M-1 or M-2.

## Step 1: Detect

**Resolve `SMM_DIR` and your `agent_id` from the session.** Then perform two checks before doing anything else.

### 1a. Refuse if teammates are live

Run the `teammates-active` subcommand. **Exit code is the signal**:
exit 0 means no teammates active (proceed); exit 1 means teammates
active — stdout has a `{count, worktrees: [...]}` JSON payload the
agent reads to populate the doctrine refusal. Exit 2 means the
coordination data could not be read (stop and surface the stderr
message; do NOT emit the doctrine refusal — we don't know if
teammates are live).

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_cli.py \
    --smm-dir <SMM_DIR> teammates-active --agent-id <your-agent-id>
```

If the command exits 1, **stop immediately** and emit the doctrine refusal text verbatim. Replace `N` with the actual count and list the live worktrees from the JSON payload:

> *"N teammate worktrees are currently live: story-042 (paul), story-043 (alice). Scaffolding modifies shared manifests and adds dependencies; running it now would create merge conflicts when teammate work lands. Finish or pause teammate worktrees, then re-invoke."*

No `--force` flag, no escape hatch. Exit cleanly.

### 1b. Read surfaces and detect existing tooling

If no teammates are live, run `detect-surfaces`. The CLI loads
`acceptance_surfaces` from `system_context.json` and runs the existing-
tooling probe per surface, returning a single JSON array on stdout:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_cli.py \
    --smm-dir <SMM_DIR> detect-surfaces --repo-root <REPO_ROOT>
```

Each array element has `{name, status, harness, has_tooling, tool_name, config_files}`. Read the JSON directly.

If the array is empty, `system_context.json` is missing or has no `acceptance_surfaces` field — exit cleanly with: _"No acceptance surfaces are recorded in system_context.json. Run /xp-system-context first to detect surfaces, then re-invoke."_

If any surface reports `has_tooling=true`, route to the **re-invocation stub** (below). Otherwise proceed to Step 3.

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

**Customer-named non-canonical tools**: do extra research — install command, config-file format, minimal verification command. Pass the gathered guidance to `assess-tool` via heredoc on stdin (empty heredoc means "no guidance found"). The CLI prints `{"decline": bool, "reason": str|null}`:

```bash
cat <<'GUIDANCE_EOF' | python3 ${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_cli.py \
    assess-tool --tool '<tool>'
<guidance text — apostrophes, quotes, backslashes, newlines all safe>
GUIDANCE_EOF
```

If `decline=true` in the JSON output, emit the `reason` string verbatim and exit cleanly — declining rather than guessing.

The heredoc carries the guidance — the `'GUIDANCE_EOF'` quoting form disables shell expansion inside, so any character (including `$`, `` ` ``, `'`, `"`, `\`, newline) is delivered verbatim to the CLI's stdin. The `--tool` value still goes through one layer of shell quoting; if the tool name itself contains an apostrophe (rare — e.g. `o'reilly-runner`), put the name in a shell variable and pass it through:

```bash
tool="o'reilly-runner"
cat <<'GUIDANCE_EOF' | python3 ${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_cli.py \
    assess-tool --tool="$tool"
<guidance text>
GUIDANCE_EOF
```

Double-quoted `"$tool"` preserves the apostrophe.

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

Pass a plan-input JSON to `build-plan` on stdin. Required keys:
`surface`, `tool`, `tool_version`, `files_to_create`,
`files_to_modify`, `install_cmds`, `verify_cmd`, `branch_name`.
File-list entries need `path` and `description`; `line_count` is
optional on creates.

Capture the JSON output into `$PLAN_JSON` so Step 5 can pipe it into
`render-preview`:

```bash
PLAN_JSON=$(cat <<'PLANEOF' | python3 ${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_cli.py \
    build-plan
{
  "surface": "browser",
  "tool": "playwright",
  "tool_version": "1.51.0",
  "files_to_create": [
    {"path": "tests/acceptance/example.spec.ts",
     "description": "happy-path test", "line_count": 12},
    {"path": "playwright.config.ts",
     "description": "single-project browser config", "line_count": 18}
  ],
  "files_to_modify": [
    {"path": ".gitignore",
     "description": "+1 line for playwright artifacts"},
    {"path": "package.json",
     "description": "+@playwright/test devDep, +scripts.test:acceptance"}
  ],
  "install_cmds": ["npm install", "npx playwright install chromium"],
  "verify_cmd": "npx playwright test tests/acceptance/example.spec.ts",
  "branch_name": "paul/scaffold-browser-acceptance"
}
PLANEOF
)
```

`$PLAN_JSON` now holds the structured plan; Step 5 pipes it into `render-preview`.

**M-2 stops here for write-side concerns.** The plan is in-memory only. Step 5 previews it; Steps 6–9 (M-3 onward) actually write.

## Step 5: Confirm

Pipe the `build-plan` JSON output into `render-preview`. The CLI emits
the formatted preview text (matching scaffolding doctrine
§Preview-before-write) ending with `Proceed? [yes / show files / no]`:

```bash
printf '%s' "$PLAN_JSON" | python3 ${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_cli.py \
    render-preview
```

Show the preview text to the customer verbatim. Then ask via `AskUserQuestion`:

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

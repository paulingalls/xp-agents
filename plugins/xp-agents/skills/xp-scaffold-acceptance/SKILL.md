---
name: xp-scaffold-acceptance
description: >-
  Scaffold an acceptance test harness for a project surface. Triggers on
  /xp-scaffold-acceptance. Inline skill that detects active teammates and
  existing tooling, asks the customer to pick a surface and tool (with
  monorepo path placement when relevant), web-refreshes the tool's latest
  version, plans + previews the scaffold for explicit yes/show-files/no
  confirmation, then atomically writes + installs + verifies + commits and
  flips the system_context surface to covered. Re-running on a scaffolded
  repo offers add-complementary / redo-via-revert / cancel. Refuses to run
  while teammate worktrees are live.
allowed-tools:
  - Read
  - AskUserQuestion
  - WebSearch
  - Bash(python3 */scripts/scaffold_cli.py *)
---

# Scaffold Acceptance

This skill is the entry point for `/xp-scaffold-acceptance`. **Inline — do not fork a subagent.** Step 1 detects teammates, monorepo layout, and existing tooling; Step 2 web-refreshes the tool's latest version; Step 3 asks for surface + tool; Steps 4–5 plan + preview + confirm; Steps 6–7 write + install + verify with atomic revert; Steps 8–9 commit + flip system_context to covered.

**Runtime order is 1 → 3 → 2 → 4 → 5 → 6 → 7 → 8 → 9** — Step 3 picks tool before Step 2 web-refreshes its version. Sections below follow doctrine numbering, not execution order; don't be misled by reading 1→2→3→4→5 top-to-bottom.

`$REPO_ROOT` in Steps 6–7 is the customer's repository root (the cwd at skill invocation, unless the customer named a different one in Step 1). Resolve it once and reuse:

```bash
REPO_ROOT="${REPO_ROOT:-$(pwd)}"
```

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

### 1b. Resolve scaffold scope (monorepo path placement)

Before detection runs, resolve `$REPO_ROOT` against any monorepo layout —
running detection at the wrong scope makes Step 1c (detect-surfaces) and
Step 1d (re-invocation) blind to package-scoped configs. Call
`detect-monorepo` against the original repository root:

```bash
TOP_REPO_ROOT="${REPO_ROOT:-$(pwd)}"
MONO_JSON=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_cli.py \
    detect-monorepo --repo-root "$TOP_REPO_ROOT")
```

Parse `$MONO_JSON`. When `is_monorepo` is `false`, `$REPO_ROOT` stays at
`$TOP_REPO_ROOT`. When `is_monorepo` is `true`, ask the customer where
the scaffold should land via `AskUserQuestion` — options are
`["<repo root>", *<packages>]` from the JSON's `packages` array
(repo-relative posix labels such as `packages/web`, `apps/api`):

```
AskUserQuestion(
  question: "Detected <kind> monorepo with N packages. Where should the scaffold land?",
  options: ["<repo root>", "packages/web", "packages/api", ...]
)
```

Resolve the chosen option to an absolute `$REPO_ROOT`:

- `<repo root>` → keep `$REPO_ROOT="$TOP_REPO_ROOT"`.
- A package path (e.g., `packages/web`) → set `$REPO_ROOT="$TOP_REPO_ROOT/<package>"`.

**No silent path assumptions.** If the chosen path does not exist on disk
(stale `detect-monorepo` output, or the package directory was moved/
deleted between detection and the customer's answer), emit a stderr note
naming the missing path and **re-prompt** the same `AskUserQuestion`.
Do not fall back to `$TOP_REPO_ROOT` silently. If the customer keeps
picking missing paths, exit cleanly with a layout-fix message.

`$REPO_ROOT` resolved here flows through every later step (Step 1c
detect-surfaces, Step 1d re-invocation, Steps 4-9 apply pipeline).

### 1c. Read surfaces and detect existing tooling

With `$REPO_ROOT` resolved (from Step 1b), run `detect-surfaces`. The
CLI loads `acceptance_surfaces` from `system_context.json` and runs the
existing-tooling probe per surface, returning a single JSON array on
stdout:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_cli.py \
    --smm-dir <SMM_DIR> detect-surfaces --repo-root <REPO_ROOT>
```

Each array element has `{name, status, harness, has_tooling, tool_name, config_files}`. Read the JSON directly.

If the array is empty, `system_context.json` is missing or has no `acceptance_surfaces` field — exit cleanly with: _"No acceptance surfaces are recorded in system_context.json. Run /xp-system-context first to detect surfaces, then re-invoke."_

If any surface reports `has_tooling=true`, route to the **re-invocation flow** (Step 1d). Otherwise proceed to Step 3.

### 1d. Re-invocation flow

When Step 1c detected existing tooling for the chosen surface, use `AskUserQuestion`:

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

Branch on the answer:

**Add complementary tool.** Loop back to Step 3 with one adjustment: when listing the canonical tool options, **exclude the existing `tool_name`** from the list. Concretely, build the Step 3 tool-question options as `[t for t in canonical_tools_for(<surface>) if t != <existing tool_name>] + ["Other (I'll name it)"]`. The downstream flow (Step 2 web-refresh, Step 4 plan, Step 5 confirm, Steps 6-9 apply) runs unchanged — `apply-write` stages new files alongside the existing tool, and the customer's preview in Step 5 shows them what gets added.

**Redo from scratch.** Resolve the introducing commit via `find-introducing-commit` against the detected `config_files`. Read the chosen surface's `config_files` array from the Step 1c `detect-surfaces` JSON and substitute them as literal `--config-files <path>` flags in the invocation (one flag per file). Example for a `browser` surface with two playwright configs:

```bash
INTRO_JSON=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_cli.py \
    find-introducing-commit --repo-root "$REPO_ROOT" \
    --config-files "$REPO_ROOT/playwright.config.ts" \
    --config-files "$REPO_ROOT/playwright.config.js")
```

The agent reads the `config_files` list out of the Step 1c JSON and writes one `--config-files` flag per entry — same agent-substitution model used throughout this SKILL (no bash array extraction; no inline `python3 -c`). At least one `--config-files` flag is required by argparse.

Parse `$INTRO_JSON`. If the JSON is a non-null dict, surface the revert pointer to the customer verbatim:

> Detected existing scaffold introduced by commit `<sha>` ("<subject>", <date>). To redo from scratch, run: `git revert <sha>` then re-invoke `/xp-scaffold-acceptance`.

If `$INTRO_JSON` is `null` (config files untracked, or not in a git repo), emit the manual-cleanup fallback:

> Detected existing config files (<config_files>) but could not pin an introducing commit (untracked, or not a git repo). Remove or revert these files manually, then re-invoke `/xp-scaffold-acceptance`.

In both cases, exit cleanly. **No writes.**

**Cancel.** Exit cleanly with the doctrine cancel message: _"Cancelled — no changes were made."_

### Add-complementary loopback note

The **add complementary tool** branch keeps the `$REPO_ROOT` resolved by
Step 1b (the package the customer just chose, or the repo root if not a
monorepo). The complementary tool lands at the same scope as the
existing tool — that is the intended semantic, since the customer is
adding to the existing scaffold within that package, not picking a
different package. No re-entry to Step 1b is needed.

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

#### NO_CONFIG_FILE_SIGNAL caveat (sdk, message_event)

The `sdk` and `message_event` surfaces are listed in
`scaffold_detect.NO_CONFIG_FILE_SIGNAL`. For those surfaces,
`detect_existing_tooling` returning `has_tooling=False` in Step 1c
means **"no config-file signal,"** not **"no tooling exists"** — sdk
libraries use inline doctest/hypothesis patterns, message/event harnesses
wire in via test-runner code without dedicated config files. If the
customer just picked `sdk` or `message_event` here in Step 3, treat
Step 1c's `has_tooling=False` as inconclusive and ask the customer
whether tooling already exists before proceeding to Step 4. Do not
silently scaffold over hidden coverage.

## Step 4: Plan

Assemble the structured `ScaffoldPlan` via `scaffold_plan.build_plan(...)`. Build the `files_to_create` and `files_to_modify` lists from your web-refreshed knowledge of the tool — typical entries: a config file, a happy-path test, a `.gitignore` modification, a `package.json` / `pyproject.toml` / `Cargo.toml` modification. Set `verify_cmd` to the runner's invocation against the generated test (e.g., `npx playwright test tests/acceptance/example.spec.ts`). Set `branch_name` to `<user>/scaffold-<surface>-acceptance`.

**Draft each file body before assembling the plan and embed it in the plan dict.** Each `files_to_create` and `files_to_modify` entry carries a `body` field with the full desired contents — Step 5's `show files` branch and Step 6's `apply-write` both read from `$PLAN_JSON.*.body`. (`path`/`description`/`line_count` are metadata for the preview; `body` is the contract.) If you cannot author a file body confidently from web-refreshed knowledge, do not include it in `files_to_create`; loop back to Step 2 for more research, or call `decline_if_unreliable` and exit.

**`install_cmds` entries and `verify_cmd` are argv-shaped, not shell strings.** Step 7 runs them with `subprocess.run(shlex.split(cmd), shell=False)` — pipes (`|`), conjunctions (`&&`/`||`), redirects (`>`, `>>`), background (`&`), and `$VAR` expansion don't work as bare commands. Wrap them in `sh -c "..."` when shell features are needed:

- ✅ `"npm install"`, `"npx playwright install chromium"`, `"pytest tests/"`
- ❌ `"npm install && npm test"` — shlex.split treats `&&` as an arg to npm
- ✅ `"sh -c 'npm install && npm test'"` — shell-feature escape hatch
- ❌ `"echo $HOME > /tmp/log"` — both `>` and `$VAR` need `sh -c`

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
     "description": "happy-path test", "line_count": 12,
     "body": "import { test, expect } from '@playwright/test';\n..."},
    {"path": "playwright.config.ts",
     "description": "single-project browser config", "line_count": 18,
     "body": "import { defineConfig } from '@playwright/test';\n..."}
  ],
  "files_to_modify": [
    {"path": ".gitignore",
     "description": "+1 line for playwright artifacts",
     "body": "<existing .gitignore content>\n/test-results/\n"},
    {"path": "package.json",
     "description": "+@playwright/test devDep, +scripts.test:acceptance",
     "body": "<existing package.json with devDeps + scripts deep-merged>"}
  ],
  "install_cmds": ["npm install", "npx playwright install chromium"],
  "verify_cmd": "npx playwright test tests/acceptance/example.spec.ts",
  "branch_name": "paul/scaffold-browser-acceptance"
}
PLANEOF
)
```

`$PLAN_JSON` now holds the structured plan; Step 5 pipes it into `render-preview`.

The plan is in-memory only at this point — Step 5 previews it; Step 6 (M-3) writes.

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

**`yes`** — proceed to Step 6 (Write). The plan in `$PLAN_JSON` carries everything Step 6 needs.

**`show files`** — Render the same plan with bodies under a `Files:` section by re-invoking `render-preview` with `--show-files`:

```bash
printf '%s' "$PLAN_JSON" | python3 ${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_cli.py \
    render-preview --show-files
```

Bodies are read directly from `$PLAN_JSON.files_to_create[].body` and `$PLAN_JSON.files_to_modify[].body` — no working-memory drafting. Then re-ask the same `AskUserQuestion` with the three options. Looping `show files` is allowed; the customer must eventually pick `yes` or `no`.

**`no`** — exit cleanly with: _"Cancelled — no changes were made."_ No partial state.

## Step 6: Write

**`files_to_modify` carries the FULL desired body, not a diff.** apply.py is format-agnostic — it writes whatever body the plan provides. For a real `package.json` / `pyproject.toml` / `Cargo.toml` modification, you must read the existing file (Step 4 working memory), deep-merge the new entries (preserving customer devDeps, scripts, dependencies), and embed the **complete merged contents** into `files_to_modify[].body`. Mismanaging this clobbers customer manifest state — the preview that Step 5 shows the customer is the contract.

**BDD-runner conditional:** if `system_context.acceptance_surfaces[<surface>].harness` names a BDD runner (`cucumber`, `behave`, `specflow`, etc.), Step 4's `files_to_create` bodies should be Gherkin `.feature` content and `verify_cmd` should invoke that BDD runner — Given/When/Then prose alone is not executable acceptance for those projects.

Pipe the approved `$PLAN_JSON` into `apply-write`:

```bash
APPLY_JSON=$(printf '%s' "$PLAN_JSON" | python3 ${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_cli.py \
    apply-write --repo-root "$REPO_ROOT")
```

The CLI prints a JSON object on stdout. Parse it: on `ok=true` capture `snapshot_id` into `$SNAPSHOT_ID` for Step 7 and proceed. On `ok=false` (write failure), the snapshot has already auto-reverted — surface `reason` verbatim to the customer and exit cleanly. If `recovery` is set (revert itself failed), surface that string verbatim too — it names the snapshot directory and unrestored paths for manual recovery.

## Step 7: Install and verify

**Once apply-write returns `ok=true` you MUST follow it with both `apply-install` AND either `apply-verify` (to complete the pipeline) or `apply-revert` (to cancel). Never abandon a snapshot mid-pipeline** — the snapshot dir under TMPDIR stays on disk between phases (apply-install does not clean it up; cleanup happens at apply-verify success or apply-revert success). Walking away after apply-install leaks the snapshot forever.

With `$SNAPSHOT_ID` from Step 6, run `apply-install` first; only run `apply-verify` if install came back `ok=true`:

```bash
INSTALL_JSON=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_cli.py \
    apply-install --snapshot-id "$SNAPSHOT_ID" --repo-root "$REPO_ROOT")
# Parse INSTALL_JSON: if .ok is false, surface .reason verbatim and exit.
VERIFY_JSON=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_cli.py \
    apply-verify --snapshot-id "$SNAPSHOT_ID" --repo-root "$REPO_ROOT")
# Same parse for VERIFY_JSON.
```

On any `ok=false`, the failing phase's `stderr` is captured into `reason` and the snapshot has already auto-reverted. Surface `reason` verbatim, plus `recovery` if set, then exit cleanly.

**`apply-revert` is for explicit customer cancellation only** — phase failures already self-heal, so do not call it after an `ok=false`. Use it when the customer says "stop, undo this" between Step 6 and Step 7 while everything is still green.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_cli.py \
    apply-revert --snapshot-id "$SNAPSHOT_ID" --repo-root "$REPO_ROOT"
```

After a green verify, the snapshot directory is **retained** for Steps 8–9 (commit + record); both consume the snapshot's plan to know what to commit and which surface to flip. The terminal phase (`apply-record`) cleans the snapshot up. If the customer cancels between Step 7 and Step 8, call `apply-revert` instead — it cleans up too.

## Step 8: Commit

Resolve the **missing-acceptance concern_id** for the chosen surface — that is the open `concern` event that `xp-system-analyzer` raised when the gap was first detected. Use `grep` against `${SMM_DIR}/events.jsonl` to extract its 12-hex id without reading the full log:

```bash
CONCERN_ID=$(grep "\"topic\": \"missing-acceptance-${SURFACE}\"" \
    "${SMM_DIR}/events.jsonl" \
    | tail -1 | grep -oE '"id": "[a-f0-9]{12}"' | cut -d'"' -f4)
CONCERN_ID="${CONCERN_ID:-none}"
```

`tail -1` picks the **most recent** matching concern — re-runs of `xp-system-analyzer` against an already-resolved gap leave the latest emit as the live one.

If no matching open concern exists (e.g., manual scaffold not preceded by analyzer), `$CONCERN_ID` falls back to `none` — `apply-commit` writes `Resolves-Event: none` per doctrine.

```bash
COMMIT_JSON=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_cli.py \
    --smm-dir <SMM_DIR> apply-commit \
    --snapshot-id "$SNAPSHOT_ID" --repo-root "$REPO_ROOT" \
    --surface "$SURFACE" --tool "$TOOL" --concern-id "$CONCERN_ID")
# Parse COMMIT_JSON: on ok=false, surface .reason verbatim and exit.
# COMMIT_JSON.sha and .branch carry the new commit's coordinates.
```

`apply-commit` is stage-aware: at Stage 0 it commits on the current HEAD; at Stage 1+ it creates `<user>/scaffold-<surface>` and commits there, refusing outright if HEAD is on a protected branch (`main`/`master`).

## Step 9: Record

Flip the surface to covered and resolve the concern via the decision-event STRONG link:

Pull the scaffold commit SHA out of `$COMMIT_JSON` (Step 8) and pass it to `apply-record` as `--commit-sha` so the surface flip is gated on the commit having actually landed:

```bash
COMMIT_SHA=$(printf '%s' "$COMMIT_JSON" | grep -oE '"sha": "[a-f0-9]+"' | cut -d'"' -f4)

RECORD_JSON=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_cli.py \
    --smm-dir <SMM_DIR> apply-record \
    --snapshot-id "$SNAPSHOT_ID" --repo-root "$REPO_ROOT" \
    --surface "$SURFACE" --concern-id "$CONCERN_ID" \
    --agent-id "$AGENT_ID" --commit-sha "$COMMIT_SHA")
# Parse RECORD_JSON: on ok=false, surface .reason verbatim and exit.
# On ok=true, .decision_event_id carries the resolution event's id.
```

`apply-record` updates `system_context.acceptance_surfaces[<surface>]` to `status=covered` with `acceptance_template_command=verify_cmd`, and (when `concern_id` is a 12-hex event ID, not the `none` sentinel) appends a `decision` event with `metadata.resolves=[concern_id]` so the gap-surface concern cascades closed. The snapshot is auto-cleaned up after success.

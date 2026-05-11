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

Entry point for `/xp-scaffold-acceptance`. **Inline — do not fork a subagent.**

**Runtime order is 1 → 3 → 2 → 4 → 5 → 6 → 7 → 8 → 9** — Step 3 picks
tool before Step 2 web-refreshes its version.

`$REPO_ROOT` is the customer's repository root, resolved once:

```bash
REPO_ROOT="${REPO_ROOT:-$(pwd)}"
```

## Step 1: Detect

Resolve `SMM_DIR` and your `agent_id` from the session. Then run two
checks.

### 1a. Refuse if teammates are live

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_cli.py \
    --smm-dir <SMM_DIR> teammates-active --agent-id <your-agent-id>
```

Exit 0: no teammates, proceed. Exit 1: teammates active — stdout has
a `{count, worktrees: [...]}` JSON payload; emit the doctrine refusal
verbatim, replacing `N` and listing the live worktrees:

> *"N teammate worktrees are currently live: story-042 (paul), story-043 (alice). Scaffolding modifies shared manifests and adds dependencies; running it now would create merge conflicts when teammate work lands. Finish or pause teammate worktrees, then re-invoke."*

Exit 2: coordination data unreadable — surface stderr, do NOT emit the
refusal (we don't know if teammates are live). No `--force` escape
hatch in any case.

### 1b. Resolve scaffold scope (monorepo path placement)

Resolve `$REPO_ROOT` against any monorepo layout before detection —
wrong scope misses package-scoped configs.

```bash
TOP_REPO_ROOT="${REPO_ROOT:-$(pwd)}"
MONO_JSON=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_cli.py \
    detect-monorepo --repo-root "$TOP_REPO_ROOT")
```

When `is_monorepo=false`, `$REPO_ROOT=$TOP_REPO_ROOT`. When `true`,
ask via `AskUserQuestion` with options `["<repo root>", *<packages>]`
from the JSON's `packages` array (repo-relative posix labels):

```
AskUserQuestion(
  question: "Detected <kind> monorepo with N packages. Where should the scaffold land?",
  options: ["<repo root>", "packages/web", "packages/api", ...]
)
```

Resolve the choice: `<repo root>` keeps `$TOP_REPO_ROOT`; a package
path sets `$REPO_ROOT="$TOP_REPO_ROOT/<package>"`. If the chosen path
doesn't exist (stale detection), emit a stderr note and **re-prompt**
— never silently fall back. Exit cleanly with a layout-fix message
if the customer keeps picking missing paths.

### 1c. Read surfaces and detect existing tooling

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_cli.py \
    --smm-dir <SMM_DIR> detect-surfaces --repo-root <REPO_ROOT>
```

Returns a JSON array; each element has `{name, status, harness,
has_tooling, tool_name, config_files}`.

If the array is empty, exit cleanly: _"No acceptance surfaces are
recorded in system_context.json. Run /xp-system-context first to detect
surfaces, then re-invoke."_

If any surface reports `has_tooling=true`, route to Step 1d. Otherwise
proceed to Step 3.

### 1d. Re-invocation flow

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

**Add complementary tool.** Loop back to Step 3 but exclude the
existing `tool_name` from the canonical tool options:
`[t for t in canonical_tools_for(<surface>) if t != <existing tool_name>] + ["Other (I'll name it)"]`.
Steps 2, 4–9 run unchanged; `$REPO_ROOT` from Step 1b persists.

**Redo from scratch.** Resolve the introducing commit via
`find-introducing-commit` (one `--config-files <path>` flag per entry
from the Step 1c JSON; argparse requires at least one):

```bash
INTRO_JSON=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_cli.py \
    find-introducing-commit --repo-root "$REPO_ROOT" \
    --config-files "$REPO_ROOT/playwright.config.ts" \
    --config-files "$REPO_ROOT/playwright.config.js")
```

If `$INTRO_JSON` is a non-null dict, surface verbatim:

> Detected existing scaffold introduced by commit `<sha>` ("<subject>", <date>). To redo from scratch, run: `git revert <sha>` then re-invoke `/xp-scaffold-acceptance`.

If `null` (untracked or not a git repo), emit the manual-cleanup fallback:

> Detected existing config files (<config_files>) but could not pin an introducing commit (untracked, or not a git repo). Remove or revert these files manually, then re-invoke `/xp-scaffold-acceptance`.

Exit cleanly in both cases. **No writes.**

**Cancel.** Exit: _"Cancelled — no changes were made."_

## Step 2: Refresh knowledge

After Step 3 collects surface + tool, consult the curated map BEFORE
WebSearch — some tool names collide with unrelated packages (`brew
install --cask maestro` lands the GUI app Maestro.app, not the mobile
e2e CLI):

```bash
KNOWN=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/known_installs.py "<tool>")
KNOWN_RC=$?
```

Exit 0 → `KNOWN` is JSON `{install_cmds, verify_identity_cmd,
expected_version_pattern}`; bind those fields verbatim and pass them
into Step 4's `build-plan` input JSON. Exit 2 → no curated entry; fall
through to WebSearch. Initial map covers `maestro`, `playwright`,
`cypress`, `detox`. Add new entries via PR when a real collision shows
up — do not pre-populate speculatively.

Regardless of map hit, **WebSearch always runs** to refresh `tool_version`
(map entries intentionally omit it — versions move on each release).
Search `<tool> latest stable release` and `<tool> recommended config
<year>`. Pin the version as `tool_version` — Step 4 records it in the
plan, Step 8 writes it to the commit message and manifest.

**Canonical tools** (`scaffold_detect.canonical_tools_for(surface)`):
proceed with web-refreshed knowledge.

**Customer-named non-canonical tools:** research install command,
config format, minimal verification command. Pass the guidance to
`assess-tool` via heredoc (empty heredoc means "no guidance found"):

```bash
cat <<'GUIDANCE_EOF' | python3 ${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_cli.py \
    assess-tool --tool="<tool>"
<guidance text — apostrophes, quotes, backslashes, newlines all safe>
GUIDANCE_EOF
```

If the CLI prints `{"decline": true, "reason": "..."}`, emit the reason
verbatim and exit. `'GUIDANCE_EOF'` quoting disables shell expansion;
`--tool="<tool>"` (double-quoted) is apostrophe-safe in tool names.

## Step 3: Ask

If detection finds no existing tooling and surfaces are present, use
`AskUserQuestion` to gather selections.

**Surface question** — list surfaces with `status="gap"` (or all if
none are tagged gap). Skip if there is exactly one gap surface.

```
AskUserQuestion(
  question: "Which acceptance surface should I scaffold?",
  options: [<surface name per gap surface>]
)
```

**Tool question** — call `scaffold_detect.canonical_tools_for(<chosen surface>)`:

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

If the customer picks "Other," ask a free-text follow-up. Record both
selections and proceed to Step 2 (web-refresh) then Step 4 (plan).

#### NO_CONFIG_FILE_SIGNAL caveat (sdk, message_event)

The `sdk` and `message_event` surfaces (in
`scaffold_detect.NO_CONFIG_FILE_SIGNAL`) wire in via inline doctest/
hypothesis patterns or test-runner code, with no config-file signal.
For these, Step 1c's `detect_existing_tooling` returning
`has_tooling=False` means "no config-file signal," not "no tooling
exists" — ask the customer whether tooling already exists before
scaffolding.

## Step 4: Plan

Assemble the `ScaffoldPlan` via `scaffold_cli.py build-plan`. Build
`files_to_create` / `files_to_modify` from web-refreshed tool
knowledge — typical: config file, happy-path test, `.gitignore`
update, manifest (`package.json` / `pyproject.toml` / `Cargo.toml`)
update. Set `verify_cmd` to the runner's invocation against the test
file. Set `branch_name` to `<user>/scaffold-<surface>-acceptance`.

**Draft each file body and embed it in the plan dict.** Each entry
carries a `body` field with full desired contents — Step 5's
`show files` and Step 6's `apply-write` both read `$PLAN_JSON.*.body`.
If you cannot author a body confidently, omit the file and loop back
to Step 2 for more research (or call `decline_if_unreliable` and exit).

**`install_cmds` and `verify_cmd` are argv-shaped, not shell strings.**
Step 7 runs them with `subprocess.run(shlex.split(cmd), shell=False)`
— pipes, `&&`/`||`, redirects, `&`, `$VAR` expansion don't work bare.
Wrap with `sh -c` when shell features are needed
(e.g., `"sh -c 'npm install && npm test'"`).

Required keys: `surface`, `tool`, `tool_version`, `files_to_create`,
`files_to_modify`, `install_cmds`, `verify_cmd`, `branch_name`.
Optional keys (identity probe — bind from Step 2's known-installs
JSON when available): `verify_identity_cmd`, `expected_version_pattern`.
File-list entries need `path` + `description` (+ optional `line_count`
on creates). Capture JSON output into `$PLAN_JSON` for Step 5:

```bash
PLAN_JSON=$(cat <<'PLANEOF' | python3 ${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_cli.py \
    build-plan
{
  "surface": "browser", "tool": "playwright", "tool_version": "1.51.0",
  "files_to_create": [
    {"path": "tests/acceptance/example.spec.ts",
     "description": "happy-path test", "line_count": 12,
     "body": "import { test, expect } from '@playwright/test';\n..."},
    {"path": "playwright.config.ts",
     "description": "browser config",
     "body": "import { defineConfig } from '@playwright/test';\n..."}
  ],
  "files_to_modify": [
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

## Step 5: Confirm

Pipe `$PLAN_JSON` into `render-preview`, show the preview verbatim,
then ask:

```bash
printf '%s' "$PLAN_JSON" | python3 ${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_cli.py \
    render-preview
```

```
AskUserQuestion(
  question: "<rendered preview ending with: Proceed? [yes / show files / no]>",
  options: ["yes", "show files", "no"]
)
```

**`yes`** — proceed to Step 6.

**`show files`** — re-invoke `render-preview --show-files` (reads
bodies from `$PLAN_JSON.files_to_create[].body` and
`files_to_modify[].body`), then re-ask the same question. Looping
`show files` is allowed.

**`no`** — exit: _"Cancelled — no changes were made."_

## Step 6: Write

**`files_to_modify` carries the FULL desired body, not a diff.** For
manifest modifications (`package.json` / `pyproject.toml` /
`Cargo.toml`), read the existing file in Step 4, deep-merge the new
entries, and embed the complete merged contents — mismanaging this
clobbers customer manifest state.

**BDD-runner conditional:** if
`system_context.acceptance_surfaces[<surface>].harness` names a BDD
runner (`cucumber`, `behave`, `specflow`, etc.), `files_to_create`
bodies must be Gherkin `.feature` content and `verify_cmd` invokes
that runner — Given/When/Then prose alone is not executable.

Pipe the approved `$PLAN_JSON` into `apply-write`:

```bash
APPLY_JSON=$(printf '%s' "$PLAN_JSON" | python3 ${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_cli.py \
    apply-write --repo-root "$REPO_ROOT")
```

On `ok=true`, capture `snapshot_id` into `$SNAPSHOT_ID` and proceed to
Step 7. On `ok=false`, the snapshot already auto-reverted — surface
`reason` (and `recovery` if set, naming the snapshot dir and
unrestored paths) verbatim, then exit.

## Step 7: Install and verify

**After apply-write `ok=true` you MUST always follow with `apply-install`
AND either `apply-verify` (complete) or `apply-revert` (cancel) — never
abandon a snapshot mid-pipeline.** Cleanup only happens at verify or
revert success; the snapshot leaks otherwise.

```bash
INSTALL_JSON=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_cli.py \
    apply-install --snapshot-id "$SNAPSHOT_ID" --repo-root "$REPO_ROOT")
# Parse: if .ok is false, surface .reason verbatim and exit.

# Identity-verify (name-collision guard): no-op when verify_identity_cmd is empty;
# else asserts tool's --version output matches expected_version_pattern.
# Mismatch triggers the same auto-revert as install/verify failure.
IDENTITY_JSON=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_cli.py \
    apply-verify-identity --snapshot-id "$SNAPSHOT_ID" --repo-root "$REPO_ROOT")
# Parse: if .ok is false (phase=verify-identity), surface .reason verbatim and exit.

VERIFY_JSON=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_cli.py \
    apply-verify --snapshot-id "$SNAPSHOT_ID" --repo-root "$REPO_ROOT")
```

On any `ok=false`, the failing phase's stderr lands in `reason` and the
snapshot has already auto-reverted — surface `reason` (and `recovery`
if set) verbatim, then exit.

**`apply-revert` is for explicit customer cancellation only** (phase
failures self-heal):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_cli.py \
    apply-revert --snapshot-id "$SNAPSHOT_ID" --repo-root "$REPO_ROOT"
```

## Step 8: Commit

Resolve the missing-acceptance `concern_id` (the open concern
`xp-system-analyzer` raised at gap detection) by grepping
`${SMM_DIR}/events.jsonl`:

```bash
CONCERN_ID=$(grep "\"topic\": \"missing-acceptance-${SURFACE}\"" \
    "${SMM_DIR}/events.jsonl" \
    | tail -1 | grep -oE '"id": "[a-f0-9]{12}"' | cut -d'"' -f4)
CONCERN_ID="${CONCERN_ID:-none}"
```

`tail -1` picks the most recent match. Falls back to `none` when no
matching concern exists (manual scaffold not preceded by analyzer);
`apply-commit` then writes `Resolves-Event: none`.

```bash
COMMIT_JSON=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_cli.py \
    --smm-dir <SMM_DIR> apply-commit \
    --snapshot-id "$SNAPSHOT_ID" --repo-root "$REPO_ROOT" \
    --surface "$SURFACE" --tool "$TOOL" --concern-id "$CONCERN_ID")
# Parse: on ok=false, surface .reason verbatim and exit.
# COMMIT_JSON.sha and .branch carry the new commit's coordinates.
```

Stage-aware: Stage 0 commits on current HEAD; Stage 1+ creates
`<user>/scaffold-<surface>` and commits there, refusing if HEAD is on a
protected branch (`main`/`master`). The scaffold branch forks off the
current branch when non-protected (free / sprint / plan / generic
feature branch) so any user work already on that branch stays
reachable; on a protected branch the refusal fires before forking.

## Step 9: Record

Pass the commit SHA from `$COMMIT_JSON` as `--commit-sha` so the
surface flip is gated on the commit actually landing:

```bash
COMMIT_SHA=$(printf '%s' "$COMMIT_JSON" | grep -oE '"sha": "[a-f0-9]+"' | cut -d'"' -f4)

RECORD_JSON=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_cli.py \
    --smm-dir <SMM_DIR> apply-record \
    --snapshot-id "$SNAPSHOT_ID" --repo-root "$REPO_ROOT" \
    --surface "$SURFACE" --concern-id "$CONCERN_ID" \
    --agent-id "$AGENT_ID" --commit-sha "$COMMIT_SHA")
# Parse: on ok=false, surface .reason verbatim and exit.
# On ok=true, .decision_event_id carries the resolution event's id.
```

`apply-record` flips
`system_context.acceptance_surfaces[<surface>].status=covered` with
`acceptance_template_command=verify_cmd`, and (when `concern_id` is a
real event ID, not `none`) appends a `decision` event with
`metadata.resolves=[concern_id]` so the gap concern cascades closed.
Snapshot is auto-cleaned on success.

The HEAD-advancement gate checks that (1) the commit exists and (2) HEAD
matches `--commit-sha`. Subject convention is **not** gated, so manual
recovery flows where the user committed the scaffold themselves with a
non-canonical subject (conventional-commits, plain prose, custom prefix)
still work — the SHA-match alone binds record to the exact commit.

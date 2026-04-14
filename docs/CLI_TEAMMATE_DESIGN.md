# CLI Teammate Design

> **Implementation Status:** All 4 milestones delivered (Sprints 014–017).
> - **M1** (Sprint 014): Teammate detection via `is_worktree_teammate()`, SessionStart injection, kickoff gate bypass
> - **M2** (Sprint 015): `spawn_teammate.py` launcher, `teammate_output_filter.py`, `/xp-assign` spawning via Bash `run_in_background`
> - **M3** (Sprint 016): TeammateIdle/TaskCompleted TDD gates, commit-gated review cycle enforcement for teammates
> - **M4** (Sprint 017): `/xp-accept` with worktree cleanup (`cleanup_teammate.py`), teammate branch merge workflow
>
> **Divergences from design:**
> - `resolve_agent_id()` was extracted into `identity.py` (not inline in `_common.py` as described)
> - Worktree helpers were extracted into `worktree.py` (not inline in `_common.py`)
> - The `xp-teammate.md` agent definition was removed as planned — teammate context is purely SessionStart-injected

## Problem

Worktree subagents spawned via the Agent tool have platform limitations that prevent reliable hook enforcement:

- **Stop hooks don't receive `agent_type` or `agent_id`** — the stop gate can't identify or enforce the review cycle for teammates ([#33049](https://github.com/anthropics/claude-code/issues/33049), 42% failure rate for SubagentStart/SubagentStop hooks)
- **Subagents can't spawn sub-agents** — `/simplify` (3 Explore agents), `/xp-security-triage` (forked skill), and other forked skills fail inside teammates
- **Stop hooks don't reliably fire** for worktree-isolated subagents — confirmed empirically across multiple test runs

## Solution: Replace Agent Tool with `claude -p`

Spawn teammates as independent `claude -p` CLI processes in manually-created git worktrees. Each process is a full session with complete hook lifecycle support.

### Advantages

- **Full hook lifecycle** — Stop, SessionStart, SessionEnd all fire. Review cycle enforceable at stop time.
- **Sub-agent spawning works** — teammates can use `/simplify` (3 parallel Explore agents), `/xp-security-triage` (forked), and any forked skill.
- **`--name`** — human-readable session names (e.g., `teammate-story-001`) for `/resume`, debugging, and marker scoping.
- **`--model` / `--effort`** — inherited from user settings by default. Honors the customer's model choice for code-writing agents. Teammate's sub-agents (Explore, security reviewer) use platform defaults.
- **Session persistence** — teammates can be resumed with `--resume` if they crash.
- **Monitor integration** — `--output-format stream-json` enables real-time event streaming.

## Spawning Mechanism

### Launcher Script: `spawn_teammate.py`

A Python script that manages the worktree lifecycle and launches `claude -p`. Called by `/xp-assign` via Bash with `run_in_background`.

Responsibilities:
1. Create git worktree from the current branch (not default branch)
2. Generate a teammate name (e.g., `teammate-story-001`)
3. Detect plugin loading mode (`--plugin-dir` for dev, omit for marketplace install)
4. Set environment variables (`SMM_DIR`, `TEAMMATE_ID`, `WORKTREE_PATH`)
5. Build and exec the `claude -p` command

```bash
# Example invocation from xp-assign:
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/spawn_teammate.py \
  --name "teammate-story-001" \
  --story-context "$(cat story_context.txt)" \
  --smm-dir "$SMM_DIR"
```

The script constructs:
```bash
git worktree add .claude/worktrees/teammate-story-001 -b teammate-story-001 HEAD
cd .claude/worktrees/teammate-story-001

claude -p \
  --name "teammate-story-001" \
  --dangerously-skip-permissions \
  --allowedTools "Read,Write,Edit,Bash,Grep,Glob,Skill,Agent" \
  --plugin-dir "$PLUGIN_DIR"  # only in dev mode \
  < prompt.txt
```

### Prompt Construction

The prompt is self-contained — the teammate has no prior context. It combines the **plan steps** (primary implementation instructions) with the **sprint story** (acceptance criteria and design context). The plan was generated and reviewed before xp-assign runs — its content is the validated implementation strategy.

```
You are a worktree-isolated teammate.

## Plan Steps
<plan steps assigned to this teammate — the reviewed implementation instructions>
<includes: file paths, what to change in each, TDD ordering, dependencies>

## Sprint Story: <story title>

### Design Context
<inlined context from sprint story>

### File Domain
<files this story exclusively owns>

### Interface Contracts
<shared boundaries with other teammates — advisory>

### Acceptance Criteria
<testable conditions from sprint story, including E2E criteria>

## SMM Directory
SMM_DIR=<path>

## Workflow
Follow strict TDD: write failing test, make it pass, refactor, commit.
Run the full review cycle before each commit: /simplify, /xp-quality-review, /xp-security-triage.
Record decisions, assumptions, and concerns via append.sh.

When done, report: what was implemented, which acceptance criteria are met,
commits made, and any concerns.
```

The plan steps are the primary input — "what to do and how." The story provides "how to verify it's done." xp-assign maps plan steps to teammates based on file domain overlap and dependency analysis.

## Identity: Worktree Name as Agent ID

**Confirmed:** `--name` is a display label only — hooks never receive it. Neither `session_id` (a UUID) nor any other hook input field reflects the `--name` value.

The **worktree directory name** extracted from `cwd` is the reliable identity. The launcher script names worktrees intentionally (e.g., `teammate-story-001`), and this becomes the agent_id for marker scoping.

`--name` is still passed for `/resume` UI and debugging, set to match the worktree name.

### `resolve_agent_id()`

A shared helper in `_common.py` that all hooks use instead of `input_data.get("agent_id", "main")`:

```python
def resolve_agent_id(input_data: dict) -> str:
    """Resolve agent_id from hook input, worktree path, or default."""
    # 1. Platform-provided agent_id (subagent hooks)
    agent_id = input_data.get("agent_id", "")
    if agent_id:
        return agent_id
    # 2. Worktree name from cwd (CLI teammate sessions)
    cwd = input_data.get("cwd", "")
    idx = cwd.find("/.claude/worktrees/")
    if idx >= 0:
        return cwd[idx + len("/.claude/worktrees/"):].split("/")[0]
    # 3. Default for lead agent
    return "main"
```

This gives each teammate a stable, unique identity derived from its worktree name. Marker files become `.review-cycle-teammate-story-001.json`, `.tdd-teammate-story-001.json`, etc. No collisions between parallel teammates.

### Hooks That Need `resolve_agent_id()`

Every hook that currently does `input_data.get("agent_id", "main")`:
- `review_cycle_done.py` — writes review cycle markers
- `pre_tool_bash.py` — reads markers for commit gate
- `teammate_stop_gate.py` — reads markers for stop gate
- `bash_post_tool.py` — commit handling, marker reset
- `pre_tool_write.py` — TDD tracking, coordination
- `post_tool_use.py` — coordination updates
- `lint_check.py` — lint concern recording
- `bash_failure.py` — failure recording
- `post_tool_exit_plan.py` — plan marker

## Hook Modifications

### SessionStart (`session_start.py`)

When `cwd` is a worktree path, enter teammate mode:
- **Skip**: `.needs-kickoff` marker, `.needs-execution-plan`, `.needs-sprint`, `.needs-system-context` markers, execution plan archival
- **Inject**: XP Values + Enhanced Teammate Guide + Curated SMM (rendered from `shared_mental_model.json`)
- **Skip**: GUPP startup prompt (teammate doesn't need session orchestration instructions)

### Kickoff Gate (`kickoff_gate.py`)

Already bypassed for worktree cwds (implemented).

### Teammate Stop Gate (`teammate_stop_gate.py`)

Detect worktree teammates via cwd path (partially implemented). With `resolve_agent_id()`, marker lookup works correctly.

### SessionEnd (`session_end.py`)

When `cwd` is a worktree path:
- Record a "teammate completed" status event with branch name (so the lead knows which branch to merge)
- Clean up agent-scoped markers (already handled by `cleanup_agent_markers`)
- Concerns and assumptions are already in `events.jsonl` from the teammate's work — no duplication needed

## Enhanced Teammate Guide

Replace `TEAMMATE_GUIDE.md` injection for CLI teammates with an enhanced version that includes elements from `PROCESS_GUIDE.md` relevant to teammates:

### Include:
- **Review cycle** — `/simplify` → `/xp-quality-review` → `/xp-security-triage` → commit (full versions, not inline alternatives)
- **Event recording protocol** — how to write decisions, assumptions, concerns via `append.sh`
- **TDD discipline** — red/green/refactor/commit
- **Commit conventions** — small commits, one logical change, format before staging

### Exclude:
- Kickoff flow
- Sprint planning / story selection
- Housekeeping / SMM curation
- Plan mode / plan review
- Acceptance testing
- Sprint review

## Lifecycle

```
/xp-assign
  ├── Analyzes plan steps for parallelization
  ├── For each parallel step:
  │   ├── spawn_teammate.py creates worktree + launches claude -p
  │   └── Bash run_in_background → lead gets task notification on completion
  ├── Lead continues (or waits)
  │
  ├── Teammate completes → task notification
  │   ├── SessionEnd hook records completion event to SMM
  │   ├── Filter script writes report file + cost event
  │   └── Lead reads branch name + report from task output
  │
  ├── Lead merges each branch:
  │   ├── git merge teammate-story-001 --no-ff
  │   ├── Resolve conflicts (file domains should prevent these)
  │   └── Run full test suite on merged result
  │
/xp-accept
  ├── Full review cycle on merged result:
  │   ├── /simplify — cross-story duplication, reuse, quality, efficiency
  │   ├── /xp-quality-review — drift check against SMM constraints
  │   └── /xp-security-triage — security review of combined changeset
  ├── Fix any findings
  ├── Verify acceptance criteria per story (E2E tests)
  ├── Mark stories done
  └── cleanup_teammate.py removes worktrees
```

## Worktree Cleanup: `cleanup_teammate.py`

Called by `/xp-accept` after stories are verified:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/cleanup_teammate.py \
  --worktree teammate-story-001
```

Responsibilities:
1. Verify worktree branch is merged (all commits reachable from current branch)
2. Remove worktree (`git worktree remove`)
3. Delete the local branch (`git branch -d`)
4. Clean up agent-scoped markers from SMM dir

Keeps worktrees alive until acceptance passes — allows re-entry if fixes are needed.

## Plugin Data Path (`CLAUDE_PLUGIN_DATA`)

When using `--plugin-dir` (dev mode), `CLAUDE_PLUGIN_DATA` resolves to `xp-agents-inline`. Marketplace installs use `xp-agents-xp-agents`. Both use the same project hash from `git rev-parse --git-common-dir`, so the SMM directory is shared.

The launcher script should detect which mode is active:
- If the lead session uses `xp-agents-inline`, pass `--plugin-dir`
- If marketplace install, omit `--plugin-dir` (plugin auto-discovered)

Detection: check if `CLAUDE_PLUGIN_DATA` contains `inline` or inspect the installed plugins manifest.

## Output Streaming (`--output-format stream-json`)

Adding `--output-format stream-json --verbose` to the `claude -p` command produces a rich JSON event stream on stdout. Each line is a JSON object with a `type` field:

| Type | Subtype | Contents |
|------|---------|----------|
| `system` | `hook_started` | Hook name, event, hook_id |
| `system` | `hook_response` | Hook stdout/stderr, exit_code, additionalContext |
| `system` | `init` | Full session metadata: model, tools, plugins, skills, cwd, session_id |
| `assistant` | — | Model responses: thinking, tool_use calls, text output |
| `user` | — | Tool results (stdout, stderr, is_error) |
| `result` | `success` | Final summary: total_cost_usd, duration_ms, num_turns, usage breakdown, model |

### Key Data Available

- **Cost per teammate**: `result.total_cost_usd` gives exact cost for the session
- **Model confirmation**: `init.model` confirms which model is running
- **Hook visibility**: Every hook fire and response is visible in the stream
- **Tool use tracking**: Every tool call and result is streamed

### What Hooks Already Capture

Hooks record to `events.jsonl` automatically — no duplication needed:
- Simplify/quality/security review results
- Commit events, test results, lint concerns
- Decisions, assumptions, concerns via `append.sh`
- Session start/end

### New Data Only Available from Stream

- **Cost** (`total_cost_usd`) — not visible to any hook
- **Duration** (`duration_ms`) — not visible to any hook
- **Turn count** (`num_turns`) — not visible to any hook

These are useful for sprint velocity, sizing calibration, and cost tracking per story.

### Output Handling

The launcher script pipes stream-json through a filter that captures the completion report and session metrics:

```bash
claude -p ... --output-format stream-json --verbose \
  | python3 ${CLAUDE_PLUGIN_ROOT}/scripts/teammate_output_filter.py \
    --smm-dir "$SMM_DIR" --teammate-id "teammate-story-001"
```

The filter script:
1. Reads JSON lines, watches for `"type":"result"`
2. Writes the teammate's final output (`result.result`) to `{smm_dir}/.teammate-report-{name}.txt`
3. Appends one SMM event with cost/duration metadata:
   `"Teammate completed: $0.32, 45 turns, 3m 12s"` with `metadata: {cost_usd, turns, duration_ms}`
4. Echoes a summary line to stdout: report file path, branch name, cost — this appears in the Bash task output

The lead's workflow after task notification:
1. Read the Bash task output for the branch name and report file path
2. Read the report for the teammate's summary (what was implemented, criteria met, concerns)
3. Merge the branch: `git merge teammate-story-001 --no-ff`
4. The cost/duration event is already in `events.jsonl` for retro analysis

This keeps the lead free — no Monitor needed.

## Documentation Updates Required

These docs need updating as part of the implementation:

- **CLAUDE.md** — update "Worktree subagents over Agent Teams" key decision to reflect CLI teammate approach. Update file structure for new scripts. Update test layout for new test files.
- **ARCHITECTURE.md** — update teammate spawning mechanism, hook map changes, lifecycle diagram.
- **PROCESS_GUIDE.md** — update teammate references if any (mostly lead-facing, may be minimal).
- **TEAMMATE_GUIDE.md** — replace with enhanced version that includes review cycle (full `/simplify`, not inline) and event recording protocol. Remove Agent Teams framing.
- **xp-teammate.md** agent definition — removed (CLI teammates don't use agent definitions; teammate context is injected via SessionStart).
- **xp-assign/SKILL.md** — rewrite spawning section: Agent tool → `spawn_teammate.py` via Bash.
- **xp-accept/SKILL.md** — add merged-code review cycle as first step, add worktree cleanup step.
- **CHANGELOG.md** — new version entry documenting the CLI teammate approach.
- **docs/AGENT_TEAMS_DESIGN.md** — major update or rewrite to reflect CLI teammate approach replacing Agent Teams + subagent worktree approaches.
- **docs/SMM_DESIGN.md** — update injection model table (teammates use SessionStart, not SubagentStart), rename "Progressive Curation (Agent Teams)" to cover CLI teammates, update SubagentStart section to note CLI teammate path, note `resolve_agent_id()` in coordination section.
- **docs/spawn-team-refactor.md** — already moved to `docs/completed/`. Superseded by this design doc.

## Resolved Design Questions

1. **Long prompts** — `claude -p` accepts stdin. Launcher script writes prompt to temp file and pipes it.
2. **Error recovery** — Worktree and branch persist after crashes. Spawn a fresh `claude -p` in the same worktree — it sees partial work via `git status` and `git log`.
3. **Concurrent merge conflicts** — File domain non-overlap prevents these. If they occur, the lead resolves manually.
4. **xp-assign behavior** — Spawn all teammates via `run_in_background`, lead gets task notification as each completes.
5. **`--name` vs identity** — `--name` is display-only (confirmed empirically). Worktree directory name is the hook-visible identity. `--name` set to match for `/resume` UI consistency.

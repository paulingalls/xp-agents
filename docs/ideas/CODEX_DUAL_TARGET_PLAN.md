<!--
PROVENANCE — drafted 2026-07-15 from a research session (Codex docs + repo map).
Doc-version assumptions: latest Codex CLI as of July 2026 (hooks system live,
`--dangerously-bypass-hook-trust` honored through `codex exec` thread start/resume
per openai/codex#26434, plan mode default-on since v0.96, `codex plugin
marketplace add` available). Latest Claude Code. Re-verify the "Codex platform
facts" section before executing any phase — the Codex hooks layer is
experimental and churns between releases.
-->

# Codex dual-target plan — one repo, two marketplaces, cross-provider teammates

## Goal

From this single GitHub repo:

1. **Install** xp-agents into Claude Code (`/plugin marketplace add paulingalls/xp-agents`)
   and into Codex: first register the marketplace (`codex plugin marketplace add
   paulingalls/xp-agents`), then install the plugin (`codex plugin add
   xp-agents@xp-agents`).
2. **Cross-launch teammates**: a lead running in either harness can spawn
   worktree teammates in either harness (`claude -p` or `codex exec`), with the
   same XP enforcement (commit-gated review cycle, TDD gates, stop gates, SMM
   injection) applied to both.

## Why this is feasible (research summary)

Codex shipped a hooks system that is a near-clone of Claude Code's:

- Same `hooks/hooks.json` file format, three-level structure, regex matchers.
- Events: SessionStart, SubagentStart, PreToolUse, PermissionRequest,
  PostToolUse, PreCompact, PostCompact, UserPromptSubmit, SubagentStop, Stop.
- Same protocols we already use: exit 2 + stderr to block, `{"decision":
  "block", "reason": ...}` on Stop/SubagentStop to force continuation,
  `hookSpecificOutput.additionalContext` to inject context.
- Plugin-bundled hooks, with `CLAUDE_PLUGIN_ROOT` / `CLAUDE_PLUGIN_DATA`
  provided as documented compatibility aliases alongside `PLUGIN_ROOT` /
  `PLUGIN_DATA`. Our `hooks.json` interpolations and `smm/init.sh` may work
  verbatim.
- Plugins: manifest at `.codex-plugin/plugin.json`, same `skills/<name>/SKILL.md`
  frontmatter format, marketplace catalogs at `.agents/plugins/marketplace.json`,
  GitHub-shorthand install with `@ref` pinning.
- Headless: `codex exec -` (stdin prompt), `--json` JSONL event stream,
  `-o/--output-last-message`, sandbox modes, `--ask-for-approval never`,
  `--dangerously-bypass-hook-trust` for unattended hook execution.
- Custom subagents: TOML files in `.codex/agents/` (project) or
  `~/.codex/agents/` (personal); SubagentStart/SubagentStop hooks fire for them.

Key refs: learn.chatgpt.com/docs/hooks, /docs/non-interactive-mode,
/docs/build-plugins, developers.openai.com/codex/subagents.

Our own architecture cooperates: hooks-first means the enforcement layer is
exactly the thing Codex cloned; the SMM is plain files; teammate identity is
cwd/env-based (never platform identity); the spawn pipeline is a plain
subprocess. An audit of `hooks/hooks.json` found **all hooks are
`type: "command"`** (Codex parses-but-skips `prompt`/`agent` hook types — we
don't use them) and 10 of our 14 registered events exist in Codex.

## The load-bearing insight: 4-way matrix → 2 spawn targets

The lead's harness is irrelevant to spawning. `spawn_teammate.py` is invoked
from a shell by both harnesses identically. So "Claude→Codex, Codex→Claude,
Claude→Claude, Codex→Codex" collapses to:

- **Spawn target A (exists)**: `claude -p` command build + stream-json parse.
- **Spawn target B (new)**: `codex exec` command build + JSONL parse.

behind a `--provider {claude,codex}` seam in `spawn_teammate.build_command()`
and `teammate_output_filter.py`. Everything else in the pipeline — worktree
lifecycle, `SMM_DIR`/`XP_TEAMMATE_NAME` env, `is_worktree_teammate()` cwd
detection, `teammate_runner.py` tee + watchdog, story promotion — is already
provider-neutral and does not change.

Packaging synergy: the installed plugin directory ships **both** manifests, so
a Codex lead points a Claude teammate's `--plugin-dir` at Codex's plugin cache
copy, and a Claude lead relies on the user's one-time marketplace registration
**and plugin installation** for Codex teammates. No second checkout.

## Gap inventory (what does NOT port as-is)

| # | Gap | Severity | Resolution (phase) |
|---|-----|----------|--------------------|
| 1 | `PostToolUse:Skill\|Agent` → `review_cycle_done.py` sets `quality_review_done`; Codex skills are $-mention instruction loads, not tool calls — no hook fires. Commit gate + teammate stop gate hang off this marker. | **Blocker** | Make marker-setting explicit: review flow's final step runs a marker script that validates preconditions itself, and/or run reviews as Codex subagents caught by SubagentStop. (P1) |
| 2 | `Write\|Edit\|MultiEdit` matchers — Codex edits via `apply_patch` (patch-blob `tool_input`, not `{file_path, ...}`). | High | `tool_input` normalization layer in `_common` consumed by `pre_tool_write.py` / `post_tool_use.py`; codex hooks variant matches `apply_patch`. (P1 prep, P2 wiring) |
| 3 | `PostToolUseFailure:Bash` (test-failure signal) — event absent in Codex; its PostToolUse fires for failed commands too. | High | Fold failure detection into the PostToolUse handler, keyed on exit status in the payload. (P1) |
| 4 | `SessionEnd` absent in Codex — teammate completion event written there today. | Medium | Move to `teammate_output_filter.py` (which already records completion externally). (P1) |
| 5 | `PreToolUse:EnterPlanMode` / `PostToolUse:ExitPlanMode` — Codex plan mode is a collaboration mode, not a tool call. | Medium | Run planning as a subagent; keep plan review on SubagentStop (already our design). Schedule-gate-on-plan-entry either moves to UserPromptSubmit heuristics or is Claude-only. (P1/P4) |
| 6 | `AskUserQuestion` hooks (`question_answered.py`) — Codex `request_user_input` exists only inside plan mode and is not hook-visible. | Low | Skill prose instructs the model to append clarification events directly; hook remains Claude-only. (P4) |
| 7 | `TeammateIdle` / `TaskCompleted` / `WorktreeCreate` — Claude platform events. Already near-no-ops for CLI teammates (gate on `teammate_name`, an Agent-Teams-only field). | Low | Claude-only; omit from codex hooks variant. (P2) |
| 8 | stream-json parse in `teammate_output_filter.py` (`total_cost_usd`, `num_turns`, `result`). | High | Codex JSONL parser behind same interface; cost computed from token counts. (P3) |
| 9 | SMM lives outside the worktree (`CLAUDE_PLUGIN_DATA`, user-level) — Codex `workspace-write` sandbox blocks the teammate's own `append.sh` shell calls. | High | First test `--sandbox workspace-write --add-dir "$SMM_DIR" --add-dir /tmp/xp-agents-teammates/`; use `danger-full-access` only if that fails. Decide in P0. (P3) |
| 10 | Hook trust: non-managed Codex hooks need one interactive trust review per content hash; re-review after every plugin update. | Medium | Headless teammates: `--dangerously-bypass-hook-trust`. Interactive leads: documented `/hooks` trust step in install docs. (P2/P5) |
| 11 | Codex docs note PreToolUse "doesn't yet intercept all shell calls" — a commit gate with a bypass hole is not a gate. | **Blocker if real** | Empirical test matrix in P0: every way Codex can shell out must hit the gate, or Codex teammates wait. (P0) |
| 12 | Model/effort tiers (`--model sonnet/opus`, `--effort`) are Claude names. | Medium | Provider-aware tier map (sprint tier → `-m gpt-5.x-…` + `-c model_reasoning_effort=…`). (P3) |
| 13 | Lead orchestration: Claude's `run_in_background` Bash + task-notification tells the lead a teammate finished; Codex has no re-invoking notification. | Medium | Codex lead polls: completion sentinel + SMM event already written by the filter; `/xp-assign` prose gains a poll/check loop for Codex leads. (P4) |
| 14 | `agents/*.md` (xp-code-reviewer etc.) are Claude subagent definitions; Codex custom agents are TOML and `plugin.json` has no `agents` field. | Medium | Translate to TOML; deliver via setup script/skill into `.codex/agents/` (project) since plugins can't bundle them. (P4) |

## Phases

Each phase leaves `main` shippable for Claude-only users. Phase order is
dependency order: decoupling before packaging, packaging before Codex
teammates (a Codex teammate without loaded hooks is an unenforced teammate),
teammates before Codex leads.

### Phase 0 — Spike (de-risk before committing)

Throwaway branch; nothing merges except the findings doc.

Setup: hand-write a minimal `.codex-plugin/plugin.json` that declares both
`"skills": "./skills/"` and `"hooks": "./hooks/hooks.codex.json"`, plus a
Codex hooks file containing only `SessionStart` (session_start.py),
`PreToolUse:Bash` (pre_tool_bash.py), and `Stop` (teammate_stop_gate.py +
tdd_stop_gate.py). Register the repository marketplace, install the plugin
from it, and start a fresh `codex exec` session — do not validate only a
hand-copied plugin directory. Run one worktree teammate via `codex exec
--dangerously-bypass-hook-trust` with `SMM_DIR` + `XP_TEAMMATE_NAME` exported.

Pass/fail checklist — ALL must pass to proceed:

- [ ] The repo marketplace catalog is accepted, `codex plugin add
      xp-agents@xp-agents` succeeds, and a new Codex session discovers an
      xp-agents skill. This proves the distributable package, rather than an
      ad-hoc local layout, loads correctly.
- [ ] Hooks fire at all under `codex exec` with the bypass flag (plugin-bundled,
      headless, non-interactive).
- [ ] `CLAUDE_PLUGIN_ROOT`/`CLAUDE_PLUGIN_DATA` compat aliases reach hook
      processes; `smm/init.sh` resolves and `events.jsonl` receives appends.
- [ ] SessionStart `additionalContext` (guide + rendered SMM) actually lands in
      the model's context (probe: instruct model to echo a marker from the guide).
- [ ] Commit gate blocks: `git commit` with ≥3 changed code files and no
      `quality_review_done` marker is denied with our stderr reason, **via every
      shell path Codex has** (gap #11). Enumerate and test each.
- [ ] Stop gate blocks: `{"decision": "block"}` forces the turn to continue.
- [ ] Sandbox decision (gap #9): first confirm whether hook processes and
      teammate shell calls can write `$SMM_DIR` under `workspace-write` plus
      `--add-dir` for the SMM/log roots; use `danger-full-access` only if that
      scoped configuration fails.
- [ ] Record hook stdin payload shapes (`tool_name`, `tool_input`, exit status
      fields) for Bash and apply_patch — feeds the P1 normalization layer.

Deliverable: `docs/completed/CODEX_SPIKE_FINDINGS.md` with observed payloads,
version numbers, and a go/no-go. **No-go criterion**: gap #11 confirmed with no
workaround → park the plan, file upstream issue, revisit on Codex release.

### Phase 1 — Decouple (Claude-only shippable; value even if Codex never lands)

Refactors that remove Claude-specific coupling. Full test suite green after
each story; behavior on Claude Code unchanged.

1. **Explicit review marker** (gap #1). The quality-review flow sets
   `quality_review_done` by running a marker script as its final step (script
   validates preconditions: review actually ran, findings recorded), instead of
   relying on `PostToolUse:Skill|Agent` inference. Keep the hook as
   belt-and-suspenders on Claude; the script becomes the source of truth.
2. **Failure folding** (gap #3). PostToolUse:Bash handler detects failures from
   the payload; `PostToolUseFailure` registration becomes Claude-only redundancy.
3. **SessionEnd → runner** (gap #4). Teammate-completion event written by
   `teammate_output_filter.py`; `session_end.py` teammate branch becomes
   Claude-only redundancy.
4. **tool_input normalization** (gap #2). `_common` gains
   `normalize_write_input(tool_name, tool_input) -> {files, kind}` consumed by
   write/edit hooks; Claude shapes today, apply_patch shape added in P3.
5. **Plugin-root self-resolution.** Scripts resolve plugin root relative to
   `__file__` first, then `PLUGIN_ROOT`, then `CLAUDE_PLUGIN_ROOT` — removes the
   assumption that the invoking harness exports a Claude compatibility variable
   into shell contexts.
6. **Plan review via subagent** (gap #5) if not already fully true post-pull —
   verify `pre_tool_plan_mode.py` / `post_tool_exit_plan.py` degrade gracefully
   when the plan-mode tools never fire.

### Phase 2 — Dual packaging

1. `.codex-plugin/plugin.json` alongside `.claude-plugin/plugin.json`, with the
   same name/version/description and explicit `"skills": "./skills/"` plus
   `"hooks": "./hooks/hooks.codex.json"`. A manifest pin test verifies the
   two manifests retain identical shared metadata.
2. **Generated hooks variants.** One source spec (e.g.
   `hooks/hooks.spec.json` or generate from the existing file) → emit
   `hooks.json` (Claude: full event set) and `hooks.codex.json` (Codex: mapped
   matchers, Claude-only events omitted, and no `async: true` handlers because
   Codex skips them). Checked in; a pin test asserts both are regeneration-clean
   so they cannot drift (fits the repo's pin-test culture).
3. Marketplace catalogs: `.claude-plugin/marketplace.json` (exists or add) and
   `.agents/plugins/marketplace.json` at repo root. The Codex catalog has
   `interface.displayName` and an xp-agents entry with structured local source
   (`{ "source": "local", "path": "./plugins/xp-agents" }`),
   `policy.installation`, `policy.authentication`, and `category`; validate it
   through marketplace registration plus a real `codex plugin add`.
4. Install docs (README + PROCESS_GUIDE where user-facing): Codex requires both
   `codex plugin marketplace add paulingalls/xp-agents` and `codex plugin add
   xp-agents@xp-agents`, plus the Codex `/hooks` trust step (gap #10) and
   minimum version pins.
5. Guardrail note: per CLAUDE.md, shipped prose stays harness-vocabulary-clean
   too — PROCESS_GUIDE/SKILL text must not assume "Claude" where it means "the
   harness". Audit shipped prose for harness-name leaks the same way we audit
   for language leaks.

### Phase 3 — Codex teammates (from either lead)

1. `spawn_teammate.py --provider codex`: build
   `codex exec - --json --dangerously-bypass-hook-trust -o <last-msg-path>` +
   `--sandbox` and `--add-dir` flags per the P0 decision (gap #9), `-m` /
   `-c model_reasoning_effort` from the provider-aware tier map (gap #12),
   cwd = worktree, prompt via stdin (preamble unchanged).
2. Preflight checks: Codex binary on PATH, authenticated, marketplace
   registered, and plugin installed (else fail with the exact two commands:
   `codex plugin marketplace add paulingalls/xp-agents`; `codex plugin add
   xp-agents@xp-agents`).
   Same-style preflight added for claude when spawned from a Codex lead
   (`--plugin-dir` resolved from the installed plugin copy, wherever the lead's
   harness cached it).
3. `teammate_output_filter.py`: Codex JSONL parser behind the existing
   interface (gap #8) — completion detection, final message, token usage,
   cost derived from tokens; same one-line summary and SMM completion event.
4. apply_patch wiring into the P1 normalization layer (gap #2), using P0's
   recorded payload shapes.
5. Execution-plan/sprint schema: executor field grows a provider dimension
   (tier wire already exists; extend, don't fork).
6. Integration test: spawn a real Codex teammate against a fixture repo (CI:
   skip-if-no-codex, same pattern as lint binary tests); assert commit gate
   blocked once, review marker unblocked it, SMM events landed, story promoted.

### Phase 4 — Codex leads

1. Lead-side skills as `$`-mentions: verify each interactive skill's SKILL.md
   loads and behaves under Codex; adjust prose where it assumes Claude tool
   names (AskUserQuestion → ask in chat; gap #6).
2. Lead gates (kickoff, sprint stop, close-cycle, schedule) verified under a
   Codex interactive session; matcher/payload fixes as found.
3. Orchestration without task notifications (gap #13): `/xp-assign` under a
   Codex lead uses background spawn + poll (sentinel file / SMM event check);
   prose branch keyed on harness detection.
4. Reviewer agents for Codex (gap #14): TOML translations of
   `agents/*.md`, installed into `.codex/agents/` by a setup skill/script.
5. AGENTS.md: ship/generate a thin AGENTS.md pointer (Codex reads it natively)
   that defers to the SessionStart-injected guides — one source of truth,
   mirroring the CLAUDE.md/PROCESS_GUIDE dedup rule.

### Phase 5 — Hardening

1. CI matrix: smoke teammate on both harnesses (claude -p and codex exec)
   against a fixture project; version-pinned Codex, canary job on latest.
2. Version gates at spawn time: refuse a provider whose CLI is older than the
   pinned minimum, with upgrade instructions.
3. Docs: README quad-matrix (lead × teammate), troubleshooting (trust, auth,
   sandbox), CHANGELOG discipline for hook-variant changes (every hooks change
   re-triggers Codex trust review — batch them).
4. Retro the experiment: which redundant Claude-only hooks (P1 items 1–3) can
   be deleted outright now that script-set markers are the source of truth.

## Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Codex hooks churn/regress between releases (experimental) | High | Version pin + canary CI; hooks variants generated so retargeting is one emitter change |
| PreToolUse shell-coverage hole (gap #11) unfixable | Medium | P0 no-go gate; upstream issue; Codex-teammate feature flag stays off |
| Trust-review UX tax alienates Codex users | Medium | Batch hook changes per release; document; watch for managed/requirements.toml options |
| GPT-5.x-codex responds differently to gate pressure (stop-gate loops, block-reason compliance) | Medium | P3 integration test includes a deliberately-blocked flow; tune TEAMMATE_GUIDE prose per harness if needed |
| Maintenance: every new hook now has two targets | Certain | Generation + pin test makes drift a test failure, not a code-review hope |

## Non-goals

- Agent Teams parity on Codex (we already chose CLI teammates over Agent Teams).
- Providers beyond Claude Code and Codex — but the `--provider` seam and
  normalization layer are the extension points if that ever changes.
- Porting Claude-only redundancies (TeammateIdle/TaskCompleted/WorktreeCreate).

## Open questions (resolve in P0/P1)

1. Does `codex exec` load a marketplace-installed plugin in every intended
   mode (interactive, headless, and a worktree cwd)? Resolve with the Phase 0
   clean-install smoke test; do not pre-seed trust configuration from the spawn
   script unless the result proves it is required.
2. Exact Codex hook stdin field names for tool payloads (docs say common fields
   match; `tool_input` shape for apply_patch unverified) — P0 checklist item.
3. Does the Codex JSONL stream expose enough for the watchdog's
   activity-detection (any event flow = alive)? Expected yes (`--json` streams
   all events).
4. Cost reporting: token→dollar mapping source for Codex models (config? static
   table? omit and report tokens only?).

<!--
PROVENANCE — drafted 2026-07-15 from a research session (Codex docs + repo map).
Revised 2026-07-24 in a design session in two passes.

Pass 1 audited the claims against OUR code: split gap #9 into sandbox reach vs
silent path divergence, re-scoped gaps #4/#12/#14, added gaps #15-17, settled the
SMM-root and tier-abstraction designs.

Pass 2 checked the Codex-side claims against the live docs, which moved several
findings in BOTH directions:
  - Event overlap is 10 of 14 (the original figure). Pass 1 briefly "corrected"
    this to 9 by trusting this doc's own incomplete Codex event list instead of
    the hooks reference. SessionEnd exists; gap #4 largely dissolved.
  - ~~Gap #11, the headline blocker, is probably not real~~ — **P0 measured it as
    REAL**, by an undocumented mechanism (exec_command + write_stdin). Fixable with
    a mandatory `--disable unified_exec`.
  - Gap #18 is new and Blocker-class: untrusted plugin hooks are skipped
    SILENTLY, so an untrusted Codex session looks enforced but is not.
    **P0 CONFIRMED this, and found the prescribed mitigation broken on Codex.**
  - `--add-dir` and `sandbox_workspace_write.writable_roots` both exist, so the
    gap #9a mitigation is real and the SMM-root decision's premise holds.
    **P0 confirmed least privilege suffices.**
  - ~~Effort values are minimal|low|medium|high|xhigh — Codex has a `minimal` we
    lack and lacks our `max`~~ — **P0 measured `low|medium|high|xhigh|max|ultra`:
    no `minimal`, and `max` and `ultra` are both real.** Support does vary per
    model, but the table must be keyed per **tier**.

Pass 3 completed the audit — the Skill hook surface, plan-mode/question hooks,
skill+subagent packaging, and the Claude-side plugin reference:
  - Gap #9c is the most consequential find of the whole session and has nothing
    to do with Codex: CLAUDE_PLUGIN_DATA is DELETED on plugin uninstall, and the
    entire SMM lives there today.
  - Gap #6 is a deadlock, not a Low: QUESTION_GATE clears only via
    AskUserQuestion, so a Codex lead raising a blocking question bricks its writes.
  - Gaps #23/#24 are new Blocker/High: the Skill hook surface also carries the
    teammate privilege gate and the ACCEPT_IN_FLIGHT drain.
  - Gap #5 degrades BETTER than written — second doors already exist in code.
  - Gap #26 was mis-attributed to Codex; Claude auto-invokes skills too.
  - Gaps #31/#32 + the payload table: our 33 handlers read ~~14~~ **15** distinct
    payload fields (`session_id` was omitted) and only 4 were documented for Codex.
    ~~All four Stop gates release via stop_hook_active, a Claude-specific latch —
    absent it, a gate can block the agent from ever ending its turn.~~ — **P0
    measured `stop_hook_active` PRESENT and functional on Codex**, so gap #31's
    Blocker dissolves; `agent_type` is present but always `'default'`, so gap #32
    stands for a different reason.

**Recurring theme worth carrying into implementation:** most findings are
latent Claude-side weaknesses that porting merely exposed — enforcement that can
vanish silently, a gate with exactly one escape hatch, a marker that leaks, an SMM
in a deletable directory. Phase 1 is therefore worth shipping on its own merits
even if Codex never lands.

Codex model identifiers remain unverified by design — they are P0 deliverables,
not assumptions. Claims sourced from third-party knowledge bases rather than
official docs are marked unverified inline (notably the .git/.codex/.agents
sandbox protection).
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
- Events: SessionStart, **SessionEnd**, SubagentStart, PreToolUse,
  PermissionRequest, PostToolUse, PreCompact, PostCompact, UserPromptSubmit,
  SubagentStop, Stop. (`SessionEnd` was missing from this list in the original
  draft and that omission propagated into a wrong gap #4 and a wrong event count
  — corrected 2026-07-24 against the hooks reference.)
- Same protocols we already use: exit 2 + stderr to block, `{"decision":
  "block", "reason": ...}` on Stop/SubagentStop to force continuation,
  `hookSpecificOutput.additionalContext` to inject context.
- Plugin-bundled hooks, with `CLAUDE_PLUGIN_ROOT` / `CLAUDE_PLUGIN_DATA`
  provided as documented compatibility aliases alongside `PLUGIN_ROOT` /
  `PLUGIN_DATA`. Our `hooks.json` interpolations and `smm/init.sh` may work
  verbatim.
- Plugins: manifest at `.codex-plugin/plugin.json`, `skills/<name>/SKILL.md`,
  marketplace catalogs at `.agents/plugins/marketplace.json`, GitHub-shorthand
  install with `@ref` pinning. ⚠️ "**same** frontmatter format" was too strong —
  ~~Codex supports only `name`/`description` there and puts the rest in a separate
  `agents/openai.yaml`; all 18 of our skills carry more~~ — **P0 measured: Codex's own
  guidance documents `argument-hint`, `disable-model-invocation`, `user-invocable`,
  `allowed-tools` and `context`/`agent`/`model` too, and nothing is rejected. All 19
  of our skills carry extra keys; only `effort` is undocumented** (gap #25).
- Headless: `codex exec -` (stdin prompt), `--json` JSONL event stream,
  `-o/--output-last-message`, sandbox modes, `--ask-for-approval never`,
  `--dangerously-bypass-hook-trust` for unattended hook execution.
- Custom subagents: TOML files in `.codex/agents/` (project) or
  `~/.codex/agents/` (personal). ⚠️ "SubagentStart/SubagentStop **fire for them**"
  is an **unverified assertion** — the subagents documentation does not state it.
  Gap #1's fallback marker path depends on it, so P0 must confirm it and record the
  payload field that identifies which agent ran.

Key refs (all re-fetched 2026-07-24): learn.chatgpt.com/docs/hooks,
/docs/non-interactive-mode, /docs/build-plugins, /docs/build-skills,
/docs/config-file/config-reference,
learn.chatgpt.com/docs/agent-configuration/subagents.

**Reading note.** Claims in this section were written from a research pass and
several proved wrong on re-verification. Treat anything here without a "verified
<date>" marker as a hypothesis, and prefer the gap inventory below — it carries the
verification status per item.

Our own architecture cooperates: hooks-first means the enforcement layer is
exactly the thing Codex cloned; the SMM is plain files; teammate identity is
primarily cwd/env-based rather than platform identity (with one Claude-branded
legacy fallback — gap #16); the spawn pipeline is a plain subprocess. An audit
of `hooks/hooks.json` found **all hooks are `type: "command"`** (Codex
parses-but-skips `prompt`/`agent` hook types — we don't use them) and **10 of
our 14 registered events exist in Codex** — verified against the hooks reference
2026-07-24. The four that do not: `PostToolUseFailure`, `TaskCompleted`,
`TeammateIdle`, `WorktreeCreate`. Codex's eleventh event, `PermissionRequest`,
we do not register.

Codex's full event set is `SessionStart`, `SessionEnd`, `SubagentStart`,
`PreToolUse`, `PermissionRequest`, `PostToolUse`, `PreCompact`, `PostCompact`,
`UserPromptSubmit`, `SubagentStop`, `Stop`. **`SessionEnd` does exist** — an
earlier draft of the event list in this doc omitted it, which made gap #4 look
worse than it is. Only `PreToolUse` onward can block; `SessionStart`,
`SessionEnd`, and `SubagentStart` cannot.

A second audit found **two `async: true` handlers** in the whole file:
`compact.py` on `SessionEnd` and `bash_failure.py` on `PostToolUseFailure`. Codex
documents `async` as "parsed, but asynchronous command hooks aren't supported
yet." Since `SessionEnd` *is* a Codex event, this matters: whether `compact.py`
runs synchronously or is skipped outright decides if `events.jsonl` ever compacts
on Codex. **P0 must observe which.** `bash_failure.py` is moot — its event is
absent regardless.

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
copy. The reverse direction is **not** symmetric — `codex exec` has no
`--plugin-dir` (gap #21), so a Claude lead spawning Codex teammates depends on the
user's one-time marketplace registration **and** plugin installation, with no
ad-hoc fallback. Still no second checkout, but the Codex direction has a hard
prerequisite the Claude direction does not.

## Gap inventory (what does NOT port as-is)

| # | Gap | Severity | Resolution (phase) |
|---|-----|----------|--------------------|
| 1 | `PostToolUse:Skill\|Agent` → `review_cycle_done.py` sets `quality_review_done`; Codex skills activate by `$`-mention or implicit description match, not tool calls — no hook fires. Commit gate + teammate stop gate hang off this marker. **Audited 2026-07-24: the loss is wider than the review marker.** The `Skill`-matched hook surface carries *three* separate responsibilities — see gaps #23 and #24. **Also: a second marker path already exists** — `subagent_stop.py::_update_review_cycle_flags` sets `quality_review_done` (and `simplify_done`) from `SubagentStop`, keyed on `agent_type`/`agent_id`. Today that fires because forked review skills present as subagents on Claude. | **Blocker** | Make marker-setting explicit: add a `quality_review_done` leg to the **existing** `review_flag_cli.py`, which already has exactly this shape for `simplify_done` — its docstring says no leg is needed because a Claude hook fires for the review either way — at the time of writing "/xp-quality-review still launches via the Skill tool," since v5.16.0 the `xp-code-reviewer` Agent completion. Codex falsifies both forms. That makes P1 item 1 a small, well-precedented change rather than new machinery. Keep `SubagentStop` as the second path — **but note the plan's claim that SubagentStart/SubagentStop fire for Codex custom subagents is NOT stated in the subagents docs. It is load-bearing for this fix and is now a P0 check.** **Measured 2026-08-05 (P0 spike): BOTH marker paths are dead on Codex.** Skills are not tool calls, *and* `collaboration.spawn_agent` arrives as `collaborationspawn_agent` (the dot is stripped), which the case-sensitive `Agent` matcher never matches. `SubagentStart`/`SubagentStop` DO fire — but `agent_type` is always `'default'`, never our name, so the keyed routing cannot select anything. The explicit CLI leg is therefore mandatory, not a belt-and-braces addition. Observed separately: the model, blocked at the gate, synthesized a `PostToolUse:Skill` payload and piped it into the hook to write the marker — on this harness that is the only available route, and it means the marker is unauthenticated on BOTH harnesses. (P1) |
| 2 | `Write\|Edit\|MultiEdit` matchers — Codex edits via `apply_patch`. Verified 2026-07-24: tool events carry `tool_name` (canonical, e.g. `Bash`, `apply_patch`, MCP ids), `tool_input`, `tool_use_id`, and `tool_response` on PostToolUse — and **both Bash and apply_patch put their payload in `tool_input.command`**, so file paths must be parsed out of patch text rather than read from a `file_path` field. | High | `tool_input` normalization layer in `_common` consumed by `pre_tool_write.py` / `post_tool_use.py`; codex hooks variant matches `apply_patch`. The normalizer needs a patch-text path extractor, which is the one piece with no Claude-side analogue — and per the project-agnostic guardrail it must work on patch structure, not on any language's syntax. **Measured 2026-08-05 (P0 spike): CONFIRMED against a real captured payload, with three additions.** `tool_name` for an edit is verbatim **`apply_patch`**, so the matcher's `Edit`, `Write` and `MultiEdit` alternatives are **dead names** on this harness. Both Bash and `apply_patch` do carry `tool_input.command`, but they differ **in kind** — a shell command vs patch TEXT — so the extractor parses `*** Update File:` / `*** Add File:` / `*** Delete File:` lines. `tool_response` arrives as a plain string, which `bash_post_tool.py` already handles. And the shell `tool_name` is `Bash` only by **normalisation**: `functions.exec`, `exec_command` and `shell_command` all normalise to it, and no tool named `Bash` exists. (P1 prep, P2 wiring) |
| 3 | `PostToolUseFailure:Bash` (test-failure signal) — event absent in Codex; its PostToolUse fires for failed commands too. | High | Fold failure detection into the PostToolUse handler, keyed on exit status in the payload. Codex's PostToolUse carries `tool_response`, but the docs do not spell out where a non-zero exit status appears — P0 must record the exact field before the handler is written, since "no failure detected" would fail silently. **Measured 2026-08-05 (P0 spike): FALSIFIED — this resolution cannot be implemented as written.** A failed tool call fires `PreToolUse` and then **nothing**: no `PostToolUse` at all (4 of 5 `tool_use_id`s paired; the failed `apply_patch` did not), and `PostToolUseFailure` is not a recognised Codex event. There is no PostToolUse to key an exit status on. Any handler pairing Pre/Post sees a hanging `PreToolUse`. The failure text IS on stderr, so a Codex failure signal must come from somewhere other than a post-hook — this needs a new design, not a folded-in branch. (P1) |
| 4 | ~~`SessionEnd` absent in Codex~~ — **mostly dissolved.** `SessionEnd` *is* a Codex event (verified 2026-07-24), so `session_end.py`'s teammate-completion event needs no relocation. What remains: `SessionEnd` also carries `compact.py` with `async: true`, and Codex parses-but-does-not-yet-support async handlers. | Low (was Medium) | Observe in P0 whether an `async` handler on a supported event runs synchronously or is skipped. If skipped, compaction on Codex falls back to its `PostCompact` trigger alone — a session that never compacts context never compacts `events.jsonl` — and P1 either drops the `async` flag (it buys little) or adds a size check at `SessionStart`. Note Codex cannot block on `SessionEnd`, so nothing gate-like may ever depend on it. **Measured 2026-08-05 (P0 spike): RUNS SYNCHRONOUSLY, not skipped.** Codex says so itself — `warning: running async SessionEnd hook synchronously` — measured on the real `session_end.py`(async false) + `compact.py`(async true) pairing, corroborated by side effect. So compaction needs no third trigger and open question 7 is answered. **New, and open: `SessionEnd` hook timeouts are clamped to 3s** — both a 2500 ms and a 1500 ms entry drew `warning: clamping SessionEnd hook timeout to 3s`. Both are already under 3s on Claude semantics, so either Codex caps every `SessionEnd` timeout regardless, **or it reads the number as SECONDS** — in which case every `timeout` in a Codex hooks file is off by 1000×. Do not write a shipped Codex timeout until one run distinguishes them. |
| 5 | `PreToolUse:EnterPlanMode` / `PostToolUse:ExitPlanMode` — Codex plan mode is a collaboration mode, not a tool call. **Audited 2026-07-24: both hooks already have second doors, so this degrades better than written.** (a) The schedule plan-mode gate's second door is `pre_tool_write.py`, which runs the same gate against writes — `pre_tool_plan_mode.py` calls itself "the gate's second door" explicitly. (b) `PLAN_AWAITING_REVIEW` is written not only by `post_tool_exit_plan.py:39` but also by `subagent_stop.py:337` — and `SubagentStop` exists on Codex. | Low-Medium (was Medium) | The planned resolution is **already implemented**, not aspirational: plan-as-subagent + `SubagentStop` genuinely sets the marker today. ⚠️ **Cross-dependency to respect:** the schedule gate's surviving door runs on write interception, so it only fires on Codex once gap #2's `apply_patch` normalization lands. Until then *both* doors are shut and the schedule gate is absent on Codex — sequence gap #2 before claiming gap #5 is handled. Also depends on the P0 check that SubagentStop fires for Codex subagents at all. (P1) |
| 6 | `AskUserQuestion` hooks (`question_answered.py`) — Codex `request_user_input` exists only inside plan mode and is not hook-visible. **Audited 2026-07-24: this is not Low, it is a deadlock.** `QUESTION_GATE` is armed when a blocking question is appended (`smm/_append_impl.py:226`) and consumed **only** by `question_answered.py:81` on `PostToolUse:AskUserQuestion`. It is a lead gate (`lead_gates.py:200`, `plan_files_exempt=False`), and its own message states AskUserQuestion "is the ONLY way to clear this." On Codex there is no such tool, so **a Codex lead that raises a blocking question permanently blocks its own writes with no recovery path.** Teammates are exempt, so only leads brick. | **Blocker** (was Low) | Add a CLI leg that clears `QUESTION_GATE` *while recording a real answer* — the skill asks in chat (Codex's native affordance), then passes the answer text to the CLI, which appends the `answer` event and consumes the marker. Same pattern as gaps #1/#24: replace tool-call inference with an explicit, precondition-validating script. **The honesty property must survive the port**: require the answer text so the leg cannot be used to fake-clear a gate, which is exactly what the current message warns against. **Measured 2026-08-05 (P0 spike): the deadlock is real, the prescribed remedy WORKS, and the framing needs one correction.** Correction: Codex **can** ask — in Default mode it asks directly in chat, and writes work there. What is unavailable outside plan mode is the **structured picker**: `request_user_input is unavailable in Default mode`, verbatim, and two candidate fixes both failed unchanged (`tools.experimental_request_user_input={mode="allow"}`, `collaboration_mode="full"`). Switching to plan mode is **not** a workaround — tested interactively, plan mode refused to create a file *and* refused to append via a shell command (*"You must not perform mutating actions."*), so a lead there cannot record the answer it just received. So the CLI leg above is exactly right, and the real cost is prose: **56 `AskUserQuestion` references across 13 shipped `SKILL.md` files, 15 further shipped files including `hooks/hooks.json` itself, and 31 test files pinning the same vocabulary.** Phase 4 is expensive, not blocked. Teammates are unaffected — this is a lead gate. (P1) |
| 6b | `ASKING_USER` (set by `question_answered.py` on the "Chat about this…" failure path) defers three stop gates — close-cycle, housekeeping, sprint — and is consumed by `user_prompt_log.py` on `UserPromptSubmit`. | Low (genuinely) | No action. The marker exists only because Claude's AskUserQuestion has a "chat instead" escape hatch that leaves a dialogue mid-flight. Codex asks in chat natively, so there is no such state to defer for, and the consumer (`UserPromptSubmit`) exists on Codex anyway. Self-consistent by omission. |
| 7 | `TeammateIdle` / `TaskCompleted` / `WorktreeCreate` — Claude platform events. Already near-no-ops for CLI teammates (gate on `teammate_name`, an Agent-Teams-only field). | Low | Claude-only; omit from codex hooks variant. (P2) |
| 8 | stream-json parse in `teammate_output_filter.py` (`total_cost_usd`, `num_turns`, `result`). Audited: only ~6 coupling points, so the interface is genuinely small. | High | Codex JSONL parser behind same interface. Verified `--json` event spec 2026-07-24: `thread.started`, `turn.started`, `turn.completed`, `item.started`, `item.completed`, `item.failed`, `error`. The final message is the last `item.completed` of type `agent_message` (or just use `-o <path>`). `turn.completed.usage` carries `input_tokens`, `cached_input_tokens`, `output_tokens`, `reasoning_output_tokens` — **no cost field**, so `total_cost_usd` has no direct analogue and cost must be derived or reported as tokens (see open question #4). `num_turns` maps to counting `turn.completed` events. (P3) |
| 9a | **Sandbox reach.** SMM lives outside the worktree (user-level) — Codex `workspace-write` sandbox may block the teammate's own `append.sh` shell calls. | ~~High~~ **Settled** | First test `--sandbox workspace-write --add-dir "$SMM_DIR" --add-dir "$WORKTREE_BASE"`; use `danger-full-access` only if that fails. **Measured 2026-08-05 (P0 spike): least privilege SUFFICES — `danger-full-access` was never needed and never tried.** Both a hook append and a teammate shell `append.sh` succeeded under `workspace-write` with `--add-dir` for the user-level root; `flock` and the atomic rename both work outside the workspace. **Two caveats for whoever writes the spawn flags.** `.git` is **read-only** under `workspace-write`, so a commit fails *after* the gate allows it — gate decisions stay observable, but a landed commit cannot be demonstrated without widening the sandbox. And `--add-dir` grants **write** access; **reads are broader** — the model read outside every `--add-dir` path freely, which invalidated one spike control's stated reasoning (not its conclusion). (P3) |
| 9b | **CLOSED for the Claude side in v5.0.0; the Codex half lands when the codex row is built.** **Path divergence (worse than 9a, and silent).** `smm/init.sh` USED TO derive `BASE_DIR` from `CLAUDE_PLUGIN_DATA` with a hardcoded `$HOME/.claude/...` fallback. `PROJECT_ID` (hash of the absolute git-common-dir) is harness-neutral, but the *root* is not. So a Claude lead and a Codex lead on the same repo resolve **two different SMMs with no error** — which defeats the broadcast-log premise. Codex's native `PLUGIN_DATA` is never consulted; and if Codex drops the `CLAUDE_PLUGIN_DATA` compat alias, a Codex-only user silently gets a `~/.claude` tree. | **High** | Resolution order is `XP_AGENTS_DATA` → neutral `$HOME/.xp-agents/data`, with host roots as discovery-only candidates and a copy-not-move relocation for existing SMMs. Shipped; see "SMM root" below. The originally planned `→ PLUGIN_DATA → CLAUDE_PLUGIN_DATA` preference chain was rejected — it re-creates this very gap. Spawned teammates are already safe (the lead exports `SMM_DIR` and `init.sh` honors it verbatim) — this bites *independent leads* and fresh Codex sessions. (P1) |
| 9c | **CLOSED — shipped in v5.0.0 (see P1 item 7).** **`CLAUDE_PLUGIN_DATA` IS DELETED ON UNINSTALL — the SMM lives there.** The Claude plugins reference: the data directory "is deleted automatically when you uninstall the plugin from the last scope where it is installed… The CLI deletes by default; pass `--keep-data` to preserve it." `${CLAUDE_PLUGIN_DATA}` resolves to `~/.claude/plugins/data/{id}/`, which is exactly where `init.sh` puts `events.jsonl`, `sprint.json`, `execution_plan.json`, `system_context.json`, `session_history.json`, and every retrospective. It survives *updates* ("outlives any single plugin version") but not uninstall. | **High — and live on Claude today, with no Codex involved** | This converts the gap #9b decision from "harness hygiene" into **data-loss prevention**: moving the SMM to `XP_AGENTS_DATA` / `~/.xp-agents` takes the project's entire memory out of a directory managed by plugin lifecycle operations. Ship the P1 SMM-root change with a migration that *copies* rather than moves, and document `--keep-data` for anyone on the old layout. Worth its own release note — a user who uninstalls to reinstall a newer version currently loses all XP history silently. (P1, urgent) |
| 10 | Hook trust: non-managed Codex hooks need one interactive trust review per content hash; re-review after every plugin update. | Medium — but see gap #18, which reframes the *consequence* of untrusted hooks from friction to silent non-enforcement. | Headless teammates: `--dangerously-bypass-hook-trust`. Interactive leads: documented `/hooks` trust step in install docs. **Better option the earlier draft missed:** hooks delivered via `requirements.toml` are "marked as managed, trusted by policy, and can't be disabled" — the right answer for org/CI deployments, and it removes the re-review-per-update tax entirely. Worth evaluating in P2 rather than treating bypass flags as the only path. (P2/P5) |
| 11 | PreToolUse shell coverage — a commit gate with a bypass hole is not a gate. | **Downgraded from "Blocker if real" to High-verify.** | The current hooks reference says PreToolUse intercepts `Bash`, `apply_patch`, MCP tools, and most local function tools, and names one documented exception: **hosted tools such as `WebSearch`**, which don't use the local hook path. Our commit gate rides `PreToolUse:Bash`, which is squarely in the intercepted set, and no hosted tool can run `git commit`. So the feared hole appears not to exist as described. **Measured 2026-08-05 (P0 spike): the hole IS real, by a mechanism the docs do not describe — and it is worse than a missing matcher.** `exec_command` opens a **persistent shell session**; `PreToolUse` fires once for the launch command (captured: `tool_input.command == "zsh"`) and **never again** for anything sent into it with `write_stdin`. The `write_stdin` commit produced no `PreToolUse` capture of any kind, so every gate riding `PreToolUse:Bash` — commit gate, tier-1 secret scan, staged-lint, branch protection — is blind to that channel. It does **not** trigger the no-go criterion because `--disable unified_exec` removes both `exec_command` and `write_stdin` and substitutes `shell_command`, which normalises to `Bash` and IS gated (verified by re-enumerating the tool set). **That flag is a hard spawn-time requirement, not a suggestion** — without it the gate is decorative. `--enable`/`--disable` take feature names; `unified_exec` is accepted, `exec_command` and `shell_session` are not. |
| 12 | **Tier vocabulary is Claude model names, and it is load-bearing.** `smm/tier_wire.py` single-sources `TEAMMATE_MODELS = {haiku, sonnet, opus, fable}`, which fans out to 4 shipped code importers (`markers.py`, `retrospective.py`, `spawn_command.py`, `smm/sprint_schema.py`), 4 prose files (`agents/xp-plan-reviewer.md`; `xp-assign` / `xp-kickoff` / `xp-schedule` SKILL.md), and 5 binding tests that pin the prose to the constants. Because `sprint_schema.py` is a consumer, **persisted** `sprint.json` / `execution_plan.json` carry these strings. `TEAMMATE_EFFORTS` (`low…max`) is likewise described in-file as a Claude knob; ~~Codex's `model_reasoning_effort` has no `xhigh`/`max`~~ — **Measured 2026-08-05 (P0 spike): both halves false.** `xhigh` and `max` are both advertised by live models, `ultra` exists and is real, and **`minimal` is advertised by nothing.** `effort_supported()` still needs harness awareness, but for the opposite reason — Codex's set is a superset at the top, not a subset. See the corrected Tier abstraction section. | **High** (was Medium — this is a vocabulary refactor across a prose-pin test surface, not a flag mapping) | Abstract tiers + per-harness lookup table. Decided; see "Tier abstraction" below. (P1 for the refactor, P3 to fill the codex row) |
| 13 | Lead orchestration: Claude's `run_in_background` Bash + task-notification tells the lead a teammate finished; Codex has no re-invoking notification. | Medium | Codex lead polls: completion sentinel + SMM event already written by the filter; `/xp-assign` prose gains a poll/check loop for Codex leads. (P4) |
| 14 | `agents/*.md` (xp-code-reviewer etc.) are Claude subagent definitions; Codex custom agents are TOML and `plugin.json` has no `agents` field. The frontmatter leaks Claude vocabulary **twice**, not once: all 7 agents pin `model: opus\|sonnet`, *and* `tools:` names Claude tools (`Read, Edit, Grep, Glob, Bash, Write`) where Codex edits via `apply_patch`. The same tool-name leak is hardcoded at `spawn_command.py:19` — `_ALLOWED_TOOLS = "Read,Write,Edit,Bash,Grep,Glob,Skill,Agent"`, passed to `--allowedTools`, which has no Codex equivalent. | Medium | Translate to TOML; deliver via setup script/skill into `.codex/agents/` (project) since plugins can't bundle them. `model:` resolves through the gap-#12 tier table rather than naming a model. `tools:` and `_ALLOWED_TOOLS` need a per-harness tool-vocabulary map. Verified 2026-07-24: `codex exec` has **no CLI tool-restriction flag**; the nearest analogues are config-level (`features.shell_tool`, `apps.<id>.enabled_tools`/`disabled_tools`, `mcp_servers.<id>.enabled_tools`), and they use Codex's tool namespace, not Claude's. So `_ALLOWED_TOOLS` is simply omitted for Codex and the restriction comes from `--sandbox` plus `--ask-for-approval` (`untrusted`/`on-request`/`never`, or a granular object). ~~Also unconfirmed-but-promising: marketplace-entry fallback manifests reportedly carry an `agents` field~~ — **Measured 2026-08-05 (P0 spike): NOT REAL as a manifest field.** `"agents": "./agents/"` was added and installed; `plugin/read` returned `appTemplates, apps, description, hooks, marketplaceName, marketplacePath, mcpServers, scheduledTasks, shareUrl, skills, summary` — **no `agents` key**, silently ignored, no error, while `skills` and `hooks` surfaced normally. The directory was copied into the cache but is never surfaced. The name is overloaded three ways and only one ships subagents: `<skill>/agents/openai.yaml` is per-skill UI+policy metadata (no), the manifest key is accepted-and-ignored (no), and `config.toml` (`default_subagent_model`, `default_subagent_reasoning_effort`, `max_depth`, `AgentRoleToml`) is the real one (**yes**). Secondary sources most plausibly saw the first sense. **The `.codex/agents/` setup-script path stands as the only route**, so this gap does not simplify. (P4; `_ALLOWED_TOOLS` in P3 with the spawn seam) |
| 15 | `session_start.py:245` reads `.claude-plugin/plugin.json` to report the plugin version. | ~~Low~~ **Medium — it misreports today** | ~~Works as long as Phase 2 ships both manifests~~, but nothing in Phase 2 names this consumer. Make the read try `.codex-plugin/plugin.json` as a fallback, or resolve the manifest name per harness. **Measured 2026-08-05 (P0 spike): CONFIRMED, and it bites now rather than at Phase 2.** `plugin_loader.plugin_version()` hardcodes `.claude-plugin/plugin.json`, so a Codex session reported `v5.5.0` while the installed Codex manifest — and the version-keyed cache path it actually executed from — was `5.3.13`. It hides the one number identifying which cached copy is running, which is exactly the confusion the version-keyed cache already causes. Concern `08bdfb8403cd`. (P2) |
| 16 | `identity.py:20` `WORKTREE_PATH_FRAGMENT = ".claude/worktrees/"` — the legacy in-repo worktree fallback (`worktree.py:95`, fires only when the out-of-repo base is unresolvable) is Claude-branded. | Low | Rename to a harness-neutral fragment with back-compat detection of the old one, so existing worktrees keep being recognized. Note this is why the feasibility claim above says teammate identity is *primarily* cwd-based: the primary `worktree-story-` fragment is neutral, the legacy parent is not. (P1) |
| 17 | **The SMM root also locates teammate worktrees.** `worktree.py:82` places them at `{base}/{project-id}/worktrees/{name}` — a deliberate sibling of the SMM dir, because out-of-repo placement stops a Node module walk-up from reaching the primary checkout's `node_modules` (the dependency-resolution leak story-024 fixed). | Medium | Any change to the SMM root moves teammate worktrees with it. This is the reason git-anchoring the SMM was rejected (see "SMM root" below) — it would drag worktrees back next to the repo and reintroduce the leak. Any future re-litigation of SMM placement must decouple the worktree base first. (constraint on P1) |
| 18 | **Untrusted plugin hooks are SILENTLY SKIPPED, not errored.** Codex "skips plugin-bundled hooks until you review and trust the current hook definition." An interactive Codex lead that has not granted trust therefore runs with **every XP gate silently absent** — TDD gate, commit gate, stop gates, schedule gate — and nothing says so. | **Blocker** (new; supersedes gap #10's framing of trust as a UX tax) | Enforcement must fail loud. Add a positive liveness check: `SessionStart` writes a heartbeat marker, and the interactive skills refuse to proceed when it is missing/stale, reporting the `/hooks` trust step. This is worth doing on Claude too — it converts "hooks silently not loaded" from an invisible failure into a visible one on both harnesses. **Measured 2026-08-05 (P0 spike): the premise is CONFIRMED and the mitigation is BROKEN.** Confirmed: untrusted plugin hooks are skipped silently — the hooks file is demonstrably read (six `additionalContextLimit` warnings name it by path) yet no handler runs and nothing says so. Broken: the heartbeat is **written** keyed on the payload `session_id` but **read** from the environment, and Codex exports none of `XP_SESSION_ID` / `CODEX_THREAD_ID` / `CLAUDE_CODE_SESSION_ID` to hook processes. The read misses and degrades to a time-only check, so **on a shared SMM root an unenforced session started within four hours of an enforced one reports LIVE.** The spike's untrusted control only reported honestly because each run had its own scratch root. Two shipped defects compound it: `SessionStart` emits a self-contradicting pair when SMM init fails (`SMM init failed — xp-agents disabled.` beside `XP agents (v5.5.0) active.`, concern `e32c04a46599`), and that context **surfaces only at the first turn, not at startup** (concern `7c688f1295d6`) — so a user cannot tell at the banner whether enforcement is live. **Fix the liveness read before any Codex teammate ships.** (P1 for the mechanism, P2 for the Codex trust docs) |
| 19 | **Plugin-bundled hooks are version-gated.** The capability was added late (openai/codex issue #16430 — "docs imply plugin-local hooks, but runtime only executes global hooks.json" — fixed by PR #19705) and is referenced behind a `plugin_hooks` enablement. | **High** | The minimum-version pin is load-bearing for *enforcement*, not hygiene: an older Codex runs our plugin's skills while ignoring its hooks, which is precisely the unenforced-teammate failure mode. Pin a minimum version, verify at spawn (P5 item 2 moves earlier), and pair with the gap #18 liveness check. **Do not treat the version pin as a substitute for #18** — see "Why the version pin is not enough" below. **Measured 2026-08-05 (P0 spike): PARTIALLY answered — the floor is NOT established.** Plugin-bundled hooks execute on `codex-cli` **0.146.0**, and **no `plugin_hooks` enablement was set in any run**, so none is required on that version. But only 0.146.0 was ever installed — no older build was obtained — and a floor cannot be inferred from one passing version. **So P3's spawn-time version check cannot be written from this spike**: pinning `>= 0.146.0` pins the only version tested, which is defensible as a conservative floor but must not be recorded as a measured one. This makes the #18 liveness check load-bearing rather than advisory, exactly as this row's last sentence warns. (P0 established one working version, not the floor; P3 to enforce at spawn) |
| 20 | **Codex auto-discovers `./hooks/hooks.json` when the manifest omits a `hooks` field.** Our `hooks/hooks.json` is the *Claude* variant. | **High** | The `.codex-plugin/plugin.json` manifest MUST set `hooks` explicitly to `./hooks/hooks.codex.json`; omitting it makes Codex load the Claude file with its Claude-only event registrations. Manifest hook paths resolve relative to the plugin root and must stay inside it. **Measured 2026-08-05 (P0 spike): both halves confirmed, and the second one relaxes a requirement.** An explicit manifest `hooks` entry **REPLACES** default `./hooks/hooks.json` discovery rather than merging — so setting it is mandatory, as this row says, and open question 8's first half is answered. Unknown event names are **silently ignored**: `PostToolUseFailure`, `TeammateIdle`, `TaskCompleted` and `WorktreeCreate` were all registered deliberately and nothing errored or warned. **So the generated per-harness hooks variant is tidy, not mandatory** — the failure mode this row feared (a rejected file) does not occur. (P2, tested in P0) |
| 21 | **`codex exec` has no `--plugin-dir` equivalent.** No CLI flag or config setting loads a plugin ad hoc; config exposes only `plugins.<plugin>.mcp_servers` overrides. | Medium | Asymmetry with Claude, where `--plugin-dir` is how a headless teammate gets the plugin at all. A Codex teammate therefore **requires** the plugin to be installed for the user — the Phase 3 preflight is a hard fail with no fallback, not a warning. This also removes the "no second checkout" convenience in the packaging-synergy note below for the Codex direction. (P3) |

Second audit pass (2026-07-24) — the `Skill` hook surface and the skill/subagent
packaging formats:

| # | Gap | Severity | Resolution (phase) |
|---|-----|----------|--------------------|
| 23 | **The teammate privilege gate disappears.** `pre_tool_skill.py` (`PreToolUse:Skill`) blocks CLI teammates from lead-owned lifecycle skills — plan, schedule, accept, close — because "teammates implement one story and report; the lead coordinates the project." On Codex, skill activation is not a tool call, so this **authority boundary cannot fire at all**: a Codex teammate could run `/xp-sprint-close`. Nothing in the earlier plan mentions this. | **Blocker** | `PermissionRequest` is the only Codex hook positioned to intercept skill activation (`approval_policy.granular.skill_approval` gates "skill-script approval prompts", and PermissionRequest runs "when Codex is about to ask for approval" and may deny). **But the catch is fatal for teammates:** headless teammates run `--ask-for-approval never`, so no approval is requested and the hook never fires. So the gate must move into the skills themselves — a teammate check at the top of each lead-owned skill's preload, which is harness-independent and works even with no hook. Do this in P1; it also hardens Claude against a teammate that bypasses the Skill tool. **Measured 2026-08-05 (P0 spike): the `PermissionRequest` route is doubly dead, so the in-skill check is the ONLY option.** `PermissionRequest` was registered and **never fired in any run**; and `approval_policy.granular.skill_approval` **gates nothing in either direction** (see #28), so there is no approval to intercept even before the headless `--ask-for-approval never` argument bites. Nothing here is salvageable as a hook. |
| 24 | **`ACCEPT_IN_FLIGHT` never drains.** `accept_terminal.py` (also `PostToolUse:Skill\|Agent`) consumes the marker when `/xp-accept` dispatches to `/xp-schedule` or `/xp-sprint-review`. `sprint_stop_gate.py:67` suppresses the sprint stop gate while it is armed, so on Codex the marker leaks and the stop gate stays suppressed for the rest of the session. | High | Same fix shape as #1 — drain from the skill itself (a CLI leg) rather than inferring completion from a tool call. The marker CLI allowlist already includes `ACCEPT_IN_FLIGHT` (`markers.py:397`), so the arm/consume plumbing exists; only the trigger point moves. (P1) |
| 25 | **SKILL.md frontmatter is Claude-shaped.** ~~All 18 shipped skills~~ **19 as of the P0 spike, read from disk** use `allowed-tools` (19), plus `effort` (6), `context` (3), `agent` (3). Codex's SKILL.md supports only `name` and `description`; optional metadata lives in a **separate `agents/openai.yaml`** (`interface`, `policy`, `dependencies.tools`). `allowed-tools` is a third site of the Claude tool-vocabulary leak, after `agents/*.md` `tools:` and `spawn_command._ALLOWED_TOOLS`. | ~~Medium~~ **Low** | ~~Codex's SKILL.md supports only `name` and `description`~~ — **Measured 2026-08-05 (P0 spike): the premise is mostly wrong and the blocker branch is FALSIFIED.** Codex's own embedded authoring guidance documents `name, description, argument-hint, disable-model-invocation, user-invocable, allowed-tools, context / agent / model`. **Three of our four extra keys — `allowed-tools`, `context`, `agent` — are documented Codex fields.** Only `effort` is genuinely undocumented, and Codex documents `model` in the slot we use `effort` for. Nothing is rejected: with a deliberately malformed control skill in the same scan producing `errors: 1` and being dropped from the listing, our 19 shipped skills and an invented-key control all loaded clean. **So no generated per-harness SKILL.md is needed.** Scoped honestly: the loader channel cannot separate *warned-about* from *silently ignored*, and a quiet `app-server` stderr is not silence on every channel — for this gap the distinction does not matter, but for any shipped decision resting on "silent", it does. **Also worth knowing:** Codex's own bundled `skill-creator/scripts/quick_validate.py` allows only `{name, description, license, allowed-tools, metadata}` and would reject `effort`, `context` and `agent` — three keys the same binary documents. It is an authoring lint, not the loader, so a user running it against our skills gets failures the runtime never raises. **Still open and NOT observed: whether `allowed-tools` is HONOURED** — Codex documenting the key means it may be *enforcing* a tool restriction on our skills rather than ignoring it, which would be a behaviour change. Needs a model-in-the-loop tool-list check. (P2) |
| 26 | **Implicit skill invocation on description match.** Codex activates skills either by `$`-mention or implicitly when a task matches the skill's `description`. Our skills are lifecycle-ordered and gate-protected, so implicit activation could fire `/xp-story-close` or `/xp-accept` out of sequence. **Correction (2026-07-24): this is NOT Codex-specific.** The Claude plugins reference says skills "are automatically discovered when the plugin is installed" and "Claude can invoke them automatically based on task context" — so we are already exposed on Claude, and Codex is the harness that actually offers a *control*. | **High** (existing latent risk, not a new one) | Set `policy.allow_implicit_invocation: false` in the generated `agents/openai.yaml` for every lifecycle skill, and investigate whether Claude has an equivalent (if not, tighten the `description` fields so they read as "invoke me explicitly" rather than as task-matching bait). Our carefully-written descriptions are an *attack surface* here, not an aid. **Measured 2026-08-05 (P0 spike): the risk is REAL and the control WORKS — but they now conflict with a decision made in the same sprint.** Real: a Codex session started running `/xp-kickoff` unprompted. Works, both legs: with `policy.allow_implicit_invocation: false` injected into one skill's `agents/openai.yaml`, a live session listing every `xp-agents:` skill returned **18 of 19 with that one absent**, and an explicit `$xp-agents:xp-plan` still delivered the body. **Two catches.** (a) The policy is **invisible to the loader channel** — a skill with it and one without return byte-identical `skills/list` records, so a per-skill opt-out cannot be audited from `app-server`, only by asking a live model what it can see. (b) **CONFLICT, unresolved:** sprint-004 also recorded `harness-config-sidecar-ban` — no shipped skill may carry an `agents/` sidecar — and pinned it in the collected suite. The ban and the only working mitigation cannot both hold; the packaging milestone must pick. Whether Codex honours SKILL.md `disable-model-invocation` instead is **not observed** (reported upstream as ignored, but Codex's own guidance documents the key). Concern `760cdeab8ddc`. (P2, plus a Claude-side investigation) |
| 27 | **Codex's effort vocabulary differs *between its own surfaces*.** CLI/config `model_reasoning_effort` accepts `minimal, low, medium, high, xhigh`; **subagent TOML** documents `ultra, max, xhigh, high, medium, low` — it has `ultra`/`max` and lacks `minimal`. | Medium | The `HARNESSES` table needs a per-**surface** effort map (CLI-spawn vs subagent-definition), not one per harness. ~~Keep the union axis (`minimal…max`, plus a decision on `ultra`)~~ — **Measured 2026-08-05 (P0 spike): the CATALOG is authoritative, and it disagrees with both documented sets.** `model/list` returns `supportedReasoningEfforts` as a **required per-model field**; the observed union is **`low, medium, high, xhigh, max, ultra`** and **`minimal` is advertised by nothing.** `ultra` is real rather than drift — catalog-advertised on two models, described *"Maximum reasoning with automatic task delegation"*, and accepted in a live run. So there is **no per-surface split to model**: the abstract axis is `low…ultra`, `minimal` should be dropped, `ultra` added. **But the catalog is not a support boundary in the permissive direction** — `gpt-5.6-luna` accepts and answers at `ultra`, which it does not advertise. |
| 28 | **`skill_approval: false` auto-rejects skills silently.** Reported behavior: "when false, Codex auto-rejects that category silently." | ~~Medium~~ **Dissolved** | ~~Another silent-failure mode in the gap #18 family~~ — **Measured 2026-08-05 (P0 spike): FALSIFIED in both directions, and the assumed shape is wrong too.** Shape: `skill_approval` is not a standalone top-level boolean but a field of `GranularAskForApproval` (alongside `sandbox_approval`, `rules`, `request_permissions`, `mcp_elicitations`), defaulting to `false`. Behaviour: at `false` (the default) skills invoke normally with **no auto-reject**; at `true`, measured in an interactive customer-driven session, **no approval prompt appeared and the skill was delivered anyway**. It gates nothing. **So install docs need NOT require it enabled.** The negative is trustworthy because the config shape was validated by control first: the granular policy is accepted by `--strict-config` while a nonsense field in the same object is rejected (`missing field sandbox_approval`). Scoped honestly: one version, and a field defaulting to false could be activated by a later release. Separately, `codex exec` cannot exercise it at all — `approval: never` was reported in every headless run including with the validated granular policy; `codex exec` pins it. |

Audited clean (2026-07-24), recorded so nobody re-audits them: the skill
`preload.sh` scripts already self-resolve `PLUGIN_ROOT` from `BASH_SOURCE` rather
than the env var — P1 item 5's concern is **already satisfied** for that whole
surface. `lefthook.yml` and the CI workflows contain no harness assumptions.
`teammate_output_filter.py`'s stream coupling is only ~6 points, confirming gap
#8's "behind the same interface" premise.

Two residual prose/path leaks found in that sweep, both small:

| # | Gap | Severity | Resolution (phase) |
|---|-----|----------|--------------------|
| 29a | `skills/_preload_base.sh:267` tells the user to "look in CLAUDE.md" for the test command — harness-specific advice in shipped prose (Codex reads AGENTS.md). | Low | Name both files, or say "the project's agent instructions". Folds into Phase 2 item 5's prose audit. (P2) |
| 29b | `skills/xp-review-plan/scripts/preload.sh:35` points the user at `~/.claude/plans/` on a bad plan marker. The *path resolution* is already clean (marker file → `.last-plan-path`), so this is only the error message — but it is the visible tip of gap #5: Codex plan mode is a collaboration mode and may not produce a plan file at all. | Low (message) / see #5 (mechanism) | Make the message harness-neutral and driven by the recorded marker path. (P1 with the gap #5 verification) |

Third audit pass (2026-07-24) — the Stop-gate release valve and subagent routing:

| # | Gap | Severity | Resolution (phase) |
|---|-----|----------|--------------------|
| 31 | **All four Stop gates release via `stop_hook_active`, a Claude-specific latch.** `tdd_stop_gate.py`, `sprint_stop_gate.py`, `housekeeping_stop_gate.py`, and `close_cycle_stop_gate.py` all branch on `input_data.get("stop_hook_active")`. Claude latches it `True` session-wide once any Stop hook returns a `reason`; our gates use that as the escape so an agent can eventually terminate (age-gated abandonment handling). If Codex omits the field it reads falsy **forever**, the bypass never fires, and a gate can block the agent from ever ending its turn. | ~~**Blocker**~~ **RESOLVED — premise falsified** | **Measured 2026-08-05 (P0 spike): `stop_hook_active` is PRESENT AND FUNCTIONAL on Codex.** It reads `False` on a turn's first Stop, flips `True` after a block and stays `True`; all four Stop gates bypass on `True`, so they release correctly and the loop is bounded. A Stop block does force the turn to continue, confirmed directly. **One caveat that IS load-bearing: the flip is not on a fixed firing number** — one run read `False, True, True, True`, another `False, False, True`. No gate may assume a block count. **So the decoupling work this row prescribes is no longer required for Codex** — though a timestamp-based release remains a legitimate Claude-side robustness win, since today's design leans on a subtle documented latching behaviour. Also confirmed: Stop cannot inject context (`ignoring additionalContextLimit for Stop hook … this event cannot emit additionalContext`), so blocks travel as `{"decision":"block"}` only. *Original analysis, kept for the record:* this is the mirror image of gap #18: that one is "gates silently absent," this is "gates that can never release" — and an unbounded stop loop burns tokens indefinitely, which is the worse failure. P0 must determine Codex's loop-protection mechanism and its field name (Codex documents Stop as blockable, so *some* protection must exist). If there is no equivalent, the gates need their own turn-counter or timestamp-based release that does not depend on a platform latch — which is also a Claude-side robustness win, since today the design leans on a subtle documented latching behavior. Note `close_cycle_stop_gate` is partly protected by the SessionStart sweep backstop; the other three are not. (P0 to identify, P1 to decouple) |
| 32 | **Subagent routing depends on two undocumented fields.** `agent_type` (10 uses) and `agent_id` (7) drive: review-cycle flags (`subagent_stop.py`), the `PLAN_AWAITING_REVIEW` write, housekeeping completion, and the `SubagentStart` `_TIERS` injection registry. That registry also keys on **Claude built-in agent type names** — `Explore`, `workflow-subagent`, `general-purpose`, `claude` — which do not exist on Codex. | **High** | Unknown types fall through to the full-SMM tier, so type-name misses degrade toward *more* injection rather than none — good design, and it caps the severity. The hard dependency is different: `xp-retrospective` receives `RETRO_INPUT` and `xp-housekeeper` receives `CURATION_INPUT` **only** through this injection (their own agent definitions say so). If `SubagentStart` does not fire on Codex, or names the agent differently, those two agents get no inputs. This raises the existing "does SubagentStart/Stop fire" P0 question from "gap #1's fallback" to "input delivery for four agents." ~~Name the Codex TOML agents identically to the Claude ones so the `xp-` matching keeps working.~~ **Measured 2026-08-05 (P0 spike): both fields are PRESENT and the value is USELESS, so identical naming will not save the routing.** `SubagentStart`/`SubagentStop` **do** fire, answering the load-bearing question. But `agent_type` is **always `'default'`** — never our agent name — and both fields are absent entirely on top-level tool events, present only on subagent-scoped ones. Two consequences: `_common.is_xp_agent` tests `agent_type.startswith("xp-")`, so it is permanently False and **recursion prevention has never fired on this harness**; and the `_TIERS` registry cannot select a tier, so it falls through to the full-SMM default for every Codex subagent. The fallback caps the severity exactly as this row predicts — but **`RETRO_INPUT`/`CURATION_INPUT` delivery is still unproven**: whether `SubagentStart` `additionalContext` reaches a Codex subagent at all was NOT observed (the hook fires, and `SubagentStart` is not among the six events that cannot emit context — but delivery was never measured). Routing needs a different key than `agent_type`, or an explicit hand-off. (P0 verified firing, not delivery; P4 to wire) |

### Hook payload compatibility surface

Enumerating every field our hooks actually read gives P0 an exact checklist
instead of "verify the payloads." ~~Our 33 handlers consume 14 distinct fields;
only 4 are documented for Codex.~~ **Measured 2026-08-05 (P0 spike): the surface is
15 fields, not 14** — `session_id` was omitted here and shipped code reads it in four
places (`hook_liveness.payload_session_id`, `housekeeping_flight` ×3,
`bash_post_tool`). The `Codex status` column below is now **observed**, not documented.

| Field | Uses | Codex status — **observed** | What breaks if absent |
|---|---|---|---|
| `cwd` | 18 | ✅ **present on every event** | Everything — teammate detection, agent-id resolution, SMM routing |
| `tool_input` | 12 | ✅ present on PreToolUse/PostToolUse | Write/commit gates (shape differs — gap #2) |
| `agent_type` | 10 | ⚠️ **present but always `'default'`** | All subagent routing (gap #32). Present ≠ usable: `is_xp_agent` is permanently False, so recursion prevention never fires |
| `agent_id` | 7 | ⚠️ **present, a UUID** — absent on top-level tool events | Per-agent review flags, marker scoping. Scoping works; naming does not |
| `stop_hook_active` | 4 | ✅ **present AND functional** — gap #31 falsified | Stop gates never release — **does not occur**; but the flip is not on a fixed firing number |
| `tool_name` | 3 | ✅ present — **normalised**, see gap #2 | Matcher-adjacent dispatch. `Bash` exists only as a normalised name; `collaboration.*` loses its dot |
| `source` | 3 | ✅ **present on SessionStart**, value `'startup'` | SessionStart branching. Only `'startup'` was ever observed — resume/compact values unverified |
| `tool_response` | 2 | ✅ present on PostToolUse, **as a plain string** | Failure detection (gap #3) — but see below, there is no PostToolUse on failure |
| `prompt` | 2 | ✅ **present on UserPromptSubmit** | UserPromptSubmit logging + nugget injection |
| `error` | 2 | ❌ **never observed** | Failure paths — event absent on Codex anyway |
| `reason` | 1 | ✅ present on SessionEnd | — |
| `name` | 1 | ❌ never observed | — |
| `is_interrupt` | 1 | ❌ never observed | — |
| `exit_code` | 1 | ❌ **never observed** | Bash failure — **and a failed call fires no PostToolUse at all**, so this cannot be recovered there (gap #3) |
| **`session_id`** | **4** | ✅ **present on every event** — *missing from the original table* | Liveness heartbeat scoping, housekeeping flight records, bash post-tool routing |

**Fields Codex sends that this table never listed**, recorded so a handler can use
them: `turn_id`, `transcript_path`, `model`, `permission_mode`, `tool_use_id`,
`last_assistant_message` (Stop, SubagentStop), `agent_transcript_path` (SubagentStop).

The three that matter are `agent_type`/`agent_id`, `stop_hook_active`, and `source`:
between them they carry all subagent routing, every Stop gate's release, and
SessionStart's fresh-vs-resume branch. **All three resolved, and two resolved against
what this doc assumed**: `stop_hook_active` works (so gap #31's Blocker dissolves) and
`agent_type` is present-but-useless (so gap #32 is not fixed by naming agents
identically). `source` is present but only ever seen as `'startup'`.

## Design decisions

Settled in the 2026-07-24 design session. Both are recorded as SMM decision
events; these are the rationale, not a re-litigation.

### SMM root (gap #9b)

**SHIPPED in v5.0.0.** Resolution order in `smm/init.sh` is now:

```bash
BASE_DIR="${XP_AGENTS_DATA:-$HOME/.xp-agents/data}"
SMM_DIR="${BASE_DIR}/${PROJECT_ID}/smm"
```

A dedicated `XP_AGENTS_DATA` wins, then a harness-neutral default, and **nothing
else is a preference**. Host-managed roots (`CLAUDE_PLUGIN_DATA`, and Codex's
`PLUGIN_DATA` when that row is built) are consulted only as a *discovery*
candidate list for an SMM that already exists, never to choose where a new one
goes — see P1 item 7 for why treating either as a preference defeats the purpose.
`PROJECT_ID` (hash of the absolute git-common-dir) is unchanged — it is already
harness-neutral and is what makes every worktree share one SMM.

**Rejected: anchoring the SMM to the git common dir** (`$GIT_COMMON_DIR/xp-agents/smm`).
Tempting — identical across harnesses by construction, no env var, and seemingly
inside the writable workspace so gap #9a evaporates. Rejected for three reasons,
in increasing order of severity:

1. It reverses the user-level SMM decision.
2. Per gap #17 it drags teammate worktrees back next to the repo, reintroducing
   story-024's `node_modules` walk-up leak.
3. **It probably does not even work on Codex.** Secondary sources report that
   Codex's sandbox keeps control directories — `.git`, `.codex`, `.agents` —
   read-only *even when their parent root is writable*. If true, an SMM inside
   `.git` could never be appended to by a sandboxed teammate, which is the exact
   opposite of the intended benefit. **Unverified** — the official config
   reference does not document protected-path behavior, so treat this as a strong
   caution rather than an established fact, and settle it in P0 if anyone ever
   wants to revisit.

Revisit only after decoupling the worktree base from the SMM base *and*
confirming point 3.

The chosen approach's sandbox story is sound: `codex exec` supports `--add-dir`
(repeatable) and `config.toml` supports `sandbox_workspace_write.writable_roots`,
so a user-level SMM can be granted write access under `workspace-write` without
resorting to `danger-full-access`. Two adjacent settings to watch:
`exclude_slash_tmp` and `exclude_tmpdir_env_var` can withdraw `/tmp`, which
matters if any teammate log or lock path lands there.

Existing SMMs are relocated automatically, by COPY — no symlink was built, and
the "or-symlink" half of the original sketch is not the shipped design. The
source tree is never deleted, so an interrupted relocation loses nothing and
every failure path falls back to reading it. A `.migrated-to` file is left in
the old tree and BOTH resolvers follow one hop along it
(`init.sh:follow_migration_pointer` and
`smm_dir_resolve.follow_migration_pointer`), so a process holding a handle
pinned before the move still lands on the live tree. Relocation declines while
any teammate is live, and `scripts/migrate_smm_root.py` is the manual
inspect/relocate escape hatch.

### Hook liveness, and why the version pin is not enough (gaps #18, #19)

The obvious objection to the liveness heartbeat is "if we require a new enough
Codex, doesn't that cover it?" It does not, for three reasons.

**1. Trust-skip is the newest version's designed behavior, not a bug.** Codex
"skips plugin-bundled hooks until you review and trust the current hook
definition," keyed on the definition's **content hash** — so it re-arms after every
plugin update. Upgrading makes gap #18 more reliably present, not less. A version
floor fixes gap #19's cause and nothing about #18's.

**2. A version check has nowhere to run for an interactive lead.** For a spawned
teammate a preflight is natural — the lead shells out, so it can check
`codex --version` and pass `--dangerously-bypass-hook-trust`. There, version pin
plus bypass really does cover both gaps. But an interactive lead has no spawner:
the user starts a session directly, and the only place a version check could live
is inside a hook. That is circular — if hooks are not running, neither is the check
that would say so. The heartbeat inverts the dependency: skills load as instruction
loads, independent of the hook runtime, and the marker can only have been written
*by* a hook. A skill observing "no fresh marker" is the one check that still
executes when the thing being tested is broken.

**3. The heartbeat is cause-agnostic; the version pin tests a proxy.** A floor
catches one cause. The heartbeat tests the property we actually care about — are
the gates live? — and therefore also catches: plugin not installed or not enabled,
a wrong manifest `hooks` path (gap #20), the `plugin_hooks` enablement off, a hooks
file rejected for unknown event names (open question #8), hooks disabled by the
user, and plain plugin-load failure **on Claude**. None of those are version
problems. In XP terms the pin asserts "this should work"; the heartbeat observes
"this does work."

**Keep both, but the heartbeat is the safety net** — the version pin is cheap
insurance at a seam where a preflight already exists. If one had to go, it is the
pin: the heartbeat catches an old Codex ignoring hooks as a side effect, while the
pin catches none of the other causes and cannot run interactively.

Implementation is small: `SessionStart` already writes markers via
`markers.marker_write`, and `_preload_base.sh` is sourced by 16 preload scripts, so
one check in one file covers every skill that has a preload.

Two wrinkles to settle rather than discover:

- **Staleness is the real design problem.** If hooks never run this session, a
  heartbeat from a previous *working* session is still on disk. Session-id keying
  does not help because a preload may not know the current session id. Refresh the
  heartbeat from `UserPromptSubmit` as well (it already has three handlers
  registered and fires every prompt), so a dead hook runtime goes stale within one
  turn. It is still time-based, so pick the threshold deliberately.
- **Teammate SessionStart writes no markers today** (`session_start.py:117` —
  "Teammate SessionStart: XP Values + Guide + cadence + SMM. No markers."). Decide
  whether teammates get their own heartbeat write or an explicit exemption that
  leans on the spawner's bypass flag.

### Tier abstraction (gaps #12, #14)

**Two independent axes**, model tier × effort tier, resolved through a
per-harness table. Fusing them into a single "intensity" tier was considered and
rejected: it would delete already-wired, already-tested `--model`/`--effort`
plumbing and lose a real point in the space (a cheap model thinking hard is not
the same trade as a strong model thinking briefly).

**Model tiers are `economy` / `standard` / `advanced` / `frontier`**, chosen to be
**deliberately disjoint** from effort's `low` / `medium` / `high` / `xhigh` / `max`.
This is not cosmetic: the same token appears in CLI args, the plan-reviewer's
recommendation metadata, `tier-recommendation-*` decision topics, the kickoff
menu, and persisted `executor_model` fields. A shared adjective like `medium`
meaning two different things across those surfaces is a bug factory.

Abstract effort tiers must be the **union** across harnesses, not Claude's set.
~~Verified 2026-07-24: … Codex's `model_reasoning_effort` accepts `minimal, low,
medium, high, xhigh` … So Codex has a `minimal` we lack and lacks our `max`. The
abstract axis is therefore `minimal, low, medium, high, xhigh, max`.~~

**Measured 2026-08-05 (P0 spike): wrong at BOTH ends.** Read from `model/list`, the
observed union is **`low, medium, high, xhigh, max, ultra`**. There is **no `minimal`**
— nothing advertises it — and `max` **is** advertised and accepted. `ultra` is real
rather than documentation drift: catalog-advertised on two models, described
*"Maximum reasoning with automatic task delegation"*, and accepted in a live run.
**So the abstract axis is `low, medium, high, xhigh, max, ultra`: drop `minimal`, add
`ultra`.** Claude offers `low, medium, high, xhigh, max`, so Codex is a superset at
the top rather than a differently-shaped set.

~~Effort support is **per model, not per harness**~~ — **Measured 2026-08-05 (P0
spike): it must be keyed by TIER, and this changes the CLAUDE row too.**
`smm/tier_wire.py:46` `EFFORT_SUPPORT` is *already* tier-keyed (its own comment says
"Per-tier effort support") and only **looks** model-keyed because Claude's tiers are
named after models. Codex breaks that coincidence: `advanced` and `frontier` are both
`gpt-5.6-sol`, so a model-keyed `effort_support` **collapses two tiers into one**. The
per-model catalog facts remain the *source* of the values; the *key* is the tier.
Codex does confirm the underlying premise — `supportedReasoningEfforts` is a required
**per-model** field, so support genuinely varies by model, exactly as `haiku` rejects
effort on Claude today.

**But the catalog is not a support boundary in the permissive direction.**
`gpt-5.6-luna` **accepts and answers at `ultra`**, which it does not advertise. Some
enforcement exists — `gpt-5.2@ultra` and an invalid value both failed — but neither was
rejected up front: both ran ~16 s and died with `stream disconnected before
completion`. **An unsupported pair surfaces as an opaque mid-stream disconnect, the
same shape a genuine transport failure takes.** See the corrected
"Unsupported pairs" note below.

```python
HARNESSES = {
  "claude": {
    "binary": "claude",
    "models": {"economy": "haiku", "standard": "sonnet",
               "advanced": "opus", "frontier": "fable"},
    # abstract effort tier -> harness spelling; None = no equivalent.
    # `minimal` dropped from the axis and `ultra` added, per the P0 correction above.
    "efforts": {"low": "low", "medium": "medium",
                "high": "high", "xhigh": "xhigh", "max": "max",
                "ultra": None},
    # abstract model tier -> abstract effort tiers that model accepts
    "effort_support": {"economy": frozenset(),          # haiku rejects effort
                       "standard": ..., "advanced": ..., "frontier": ...},
    "model_flag":  ["--model", "{model}"],
    "effort_flag": ["--effort", "{effort}"],
  },
  # FILLED 2026-08-05 by the P0 spike, read from `model/list`. Entitlement-scoped:
  # re-enumerate rather than trusting these ids. `effort_support` is TIER-keyed.
  "codex": {
    "binary": "codex",
    "models": {"economy": "gpt-5.6-luna", "standard": "gpt-5.6-terra",
               "advanced": "gpt-5.6-sol", "frontier": "gpt-5.6-sol"},
    "efforts": {                          # `minimal` gone: advertised by nothing
                "low": "low", "medium": "medium", "high": "high",
                "xhigh": "xhigh", "max": "max",   # was wrongly None
                "ultra": "ultra"},                # real; new to the abstract axis
    "effort_support": {"economy":  {"low","medium","high","xhigh","max"},
                       "standard": {"low","medium","high","xhigh","max","ultra"},
                       "advanced": {"low","medium","high","xhigh","max","ultra"},
                       "frontier": {"low","medium","high","xhigh","max","ultra"}},
    # NEW FIELD. UNVERIFIED: advanced and frontier share one model, so high-vs-ultra
    # is the entire separator between the top two tiers, and nothing confirms the
    # effort is honoured (the rollout echoes the REQUEST). Re-measure on a real
    # prompt before shipping frontier as distinct from advanced.
    "default_effort": {"economy": "medium", "standard": "medium",
                       "advanced": "high", "frontier": "ultra"},
    "model_flag":  ["-m", "{model}"],
    "effort_flag": ["-c", "model_reasoning_effort={effort}"],
  },
}
```

A `None` effort entry means "this harness has no equivalent". Adding harness #3
is then a data change, not a code change.

**Three things the tier milestone must decide rather than inherit** (P0 spike):

1. **`default_effort` is a NEW field** the drafted shape has no slot for. Either the
   **Claude row gains one too** or the two harnesses diverge in shape — the very thing
   this abstraction exists to prevent.
2. **It is a default, not a fusion of the two axes.** This doc rejected fusing model
   tier with effort tier; a default that stays overridable preserves both. Codex agrees
   by example — `gpt-5.6-sol`'s own `defaultReasoningEffort` is **`low`**, blurbed
   *"try starting lower, then turn it up"*.
3. **Codex offers three visible coding tiers, not four.** Nothing sits above `sol`, so
   `advanced` and `frontier` share a model and are separated only by default effort —
   and that separation is **unverified**, because the rollout records the *requested*
   effort, not the effective one. Hidden models (`gpt-5.4`, `gpt-5.4-mini`,
   `codex-auto-review`) are excluded deliberately: hidden from Codex's own picker means
   deprecated or restricted.

~~Codex also accepts a `-e <effort>` shorthand~~ — **Measured 2026-08-05 (P0 spike):
there is NO `-e`/`--effort` flag on `codex exec`. Only `-m, --model`.** Effort goes
through `-c model_reasoning_effort=` exactly as `effort_flag` above already says; it
was only the prose that would have misled an implementer.

Codex does read `model` / `model_reasoning_effort` from `~/.codex/config.toml`, and
passing explicit `-c` overrides beats it — **verified end to end**: requesting `low`
against a config saying `high` yields `low`. **Do not reach for
`--ignore-user-config` to isolate a measurement**: it also discards `model_provider`
and auth, so every request 401s under a non-default provider. Explicit overrides are
both sufficient and safe.

**Per-surface effort sets (gap #27).** ~~Codex's two surfaces disagree with each
other, so `HARNESSES` needs a surface dimension, not just a harness one.~~

| Surface | Documented effort values | **Observed 2026-08-05** |
|---|---|---|
| Claude CLI (`--effort`) | `low, medium, high, xhigh, max` | not re-measured |
| Codex CLI (`-c model_reasoning_effort`) | `minimal, low, medium, high, xhigh` | **the CLI is a vehicle, not a value set — it passes whatever the catalog accepts** |
| Codex subagent TOML | `ultra, max, xhigh, high, medium, low` | **substantially right; `ultra` and `max` are both real** |
| **`model/list` catalog (authoritative)** | — | **`low, medium, high, xhigh, max, ultra`; no `minimal`** |

**Measured 2026-08-05 (P0 spike): there is no surface dimension to model.** The
*catalog* is authoritative for what exists, per model, and `-c model_reasoning_effort=`
is simply the CLI vehicle for it. The apparent disagreement was documentation drift in
the CLI direction, not two genuinely different value sets — and it drifted the
opposite way from what this row assumed: the subagent list was the accurate one.
`ultra` **is** real and belongs in the abstract axis. `minimal` does not.

**Codex subagent TOML shape** (verified 2026-07-24). Required: `name`,
`description`, `developer_instructions`. Optional: `model`,
`model_reasoning_effort`, `sandbox_mode`, `mcp_servers`, `skills.config`;
these override parent-session settings, resolving explicit spawn value →
`[agents]` defaults → parent session value. **There is no `tools` field** — so
`agents/*.md`'s `tools:` list has no Codex analogue at all, and `sandbox_mode` is
the only restriction lever. That settles the gap #14 question: don't try to
translate `tools:`; map the *intent* (read-only reviewer vs read-write fixer) onto
`sandbox_mode`.

~~Documented subagent model options as of 2026-07-24 are `gpt-5.6`, `gpt-5.4`,
`gpt-5.6-terra`, `gpt-5.3-codex-spark`.~~ **Measured 2026-08-05 (P0 spike): the live
catalog does not match that list** — of the four, only `gpt-5.6-terra` and `gpt-5.4`
appear, and `gpt-5.4` is **hidden**. The observed visible set is `gpt-5.6-sol`,
`gpt-5.6-terra`, `gpt-5.6-luna`, `gpt-5.5`, `gpt-5.2`. This is the churn the row warns
about, arriving inside two weeks — and it is why the mapping is recorded in
`docs/completed/CODEX_SPIKE_FINDINGS.md` and this table rather than inferred in code,
and why the ids are entitlement-scoped and must be re-enumerated, not trusted.

**The load-bearing benefit is maintenance, not cosmetics.** Today the tokens *are*
Claude model names, so adding a harness forces churn in 4 prose files and 5
binding tests. Once prose names only abstract tiers, the prose-pin surface stops
growing when a harness is added — which is what makes "more CLI harnesses later"
cheap.

**Unsupported pairs are dropped, never clamped.** A requested effort tier the
harness cannot honor is omitted with a stderr note, falling back to the model
default. This is already `spawn_command.build_command`'s tested contract; clamping
(`max` → `high`) would silently substitute an intent the caller did not express
and would make the same tier mean different things on different harnesses.

> **Measured 2026-08-05 (P0 spike): this contract is right, and on Codex there is no
> signal to implement it from.** The rule assumes the harness tells you a pair is
> unsupported. Codex does not: an unsupported pair is **neither validated up front nor
> clamped**. The run starts, burns ~16 s, and dies with
> `task_complete.error = "stream disconnected before completion"` — the same shape a
> genuine transport failure takes. Worse in the other direction, the catalog cannot be
> used as the check either, because it **under-reports**: `gpt-5.6-luna` accepts and
> answers at `ultra`, which it does not advertise. So "drop, don't clamp" must be
> enforced from our own `effort_support` table *before* spawning, and a spawn wrapper
> **cannot** distinguish an unsupported pair from a flaky connection after the fact.
> Do not build a retry policy that assumes it can.

**Tier is a property of the work; provider is a property of the operator's
environment.** The plan-reviewer therefore recommends a *tier* and must never
recommend a provider; provider comes from session config or a per-story override.
Useful consequence: existing `metadata.recommended_model` events stay semantically
valid, so they can be aliased rather than migrated.

**Migration is read-side aliasing**, not a data rewrite: accept
`haiku→economy`, `sonnet→standard`, `opus→advanced`, `fable→frontier` on load.
That covers persisted `executor_model` values in `sprint.json` /
`execution_plan.json` and old `tier-recommendation-*` events alike. Eventually
`recommended_model` wants renaming to `recommended_tier`; that is an event-wire
change and can lag behind the constant rename.

~~**Not yet known: Codex's actual model identifiers and its exact effort value
set.**~~ **DELIVERED 2026-08-05 — the `codex` row above is filled from `model/list`.**
The warning it carried still stands and is now evidence-backed: these must not be
guessed into constants, the ids are **entitlement-scoped** (`model_provider` matters),
and the documented subagent list was already stale within two weeks. Re-enumerate
before executing any phase. Full evidence, including what was *not* observed, is in
`docs/completed/CODEX_SPIKE_FINDINGS.md`.

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

Pass/fail checklist — ALL must pass to proceed.

> **Completed 2026-08-05. Legend: `[x]` observed · `[~]` partly observed · `[ ]` NOT
> observed.** Result: **19 observed, 3 partial, 1 not observed.** Full evidence in
> `docs/completed/CODEX_SPIKE_FINDINGS.md`, including the not-observed register with a
> reason for each gap. The four items that are not a clean `[x]` are called out here
> because a reader scanning ticks would otherwise miss them:
>
> - **`[~]` version floor (gap #19)** — hooks execute on 0.146.0 with no `plugin_hooks`
>   enablement, but no older build was tested, so the *minimum* is unknown.
> - **`[~]` hook liveness (gap #18)** — the *silently skipped* half is confirmed. The
>   *discriminating* half is not: the untrusted control ran on its own scratch root, so
>   it read not-live whether or not the marker discriminates anything, and the read is
>   since measured broken (see R2 in the findings doc). No trusted run exercised the
>   in-session liveness read. Concern `31e942bc97b0`.
> - **`[~]` SubagentStart/Stop fire** — they DO fire, which was the load-bearing half;
>   but `agent_type` is always `'default'`, so the identifying payload the item asks
>   for does not identify anything.
> - **`[ ]` SubagentStart injection reaching a subagent's context** — never measured.
>   This is the one gap that matters most, because `RETRO_INPUT`/`CURATION_INPUT`
>   delivery to two agents depends on it and nothing else covers it.
>
> Several items **passed while falsifying their own premise** — the tick means
> "observed", not "as predicted". See the corrections marked throughout this document.

- [x] The repo marketplace catalog is accepted, `codex plugin add
      xp-agents@xp-agents` succeeds, and a new Codex session discovers an
      xp-agents skill. This proves the distributable package, rather than an
      ad-hoc local layout, loads correctly.
- [x] Hooks fire at all under `codex exec` with the bypass flag (plugin-bundled,
      headless, non-interactive).
- [x] `CLAUDE_PLUGIN_ROOT`/`CLAUDE_PLUGIN_DATA` compat aliases reach hook
      processes; `smm/init.sh` resolves and `events.jsonl` receives appends.
- [x] SessionStart `additionalContext` (guide + rendered SMM) actually lands in
      the model's context (probe: instruct model to echo a marker from the guide).
- [x] Commit gate blocks: `git commit` with ≥3 changed code files and no
      `quality_review_done` marker is denied with our stderr reason, **via every
      shell path Codex has** (gap #11). Enumerate and test each.
- [x] Stop gate blocks: `{"decision": "block"}` forces the turn to continue.
- [x] Sandbox decision (gap #9): first confirm whether hook processes and
      teammate shell calls can write `$SMM_DIR` under `workspace-write` plus
      `--add-dir` for the SMM/log roots; use `danger-full-access` only if that
      scoped configuration fails.
- [x] Record hook stdin payload shapes (`tool_name`, `tool_input`, exit status
      fields) for Bash and apply_patch — feeds the P1 normalization layer. Docs
      say both use `tool_input.command`; capture a real apply_patch payload so the
      patch-text path extractor is written against fact, not inference.
- [~] **Hook liveness is observable (gap #18).** Confirm that untrusted
      plugin hooks are skipped *silently*, then confirm the SessionStart heartbeat
      marker distinguishes "hooks live" from "hooks absent". This is the check that
      keeps an unenforced session from looking like an enforced one.
- [~] **Establish the minimum Codex version (gap #19)** at which plugin-bundled
      hooks actually execute, and whether any `plugin_hooks` enablement is needed.
      Record the version in the findings doc; it becomes the spawn-time floor.
- [x] **Manifest `hooks` field behavior (gap #20).** Confirm an explicit
      `"hooks": "./hooks/hooks.codex.json"` is honored, and record what Codex does
      when a hooks file registers events it does not know (`PostToolUseFailure`,
      `TeammateIdle`, `TaskCompleted`, `WorktreeCreate`) — ignore or error. If it
      errors, the generated Codex variant must omit them, not merely map them.
- [x] **`async` handler behavior on a supported event (gap #4).** Register
      `compact.py` with `async: true` on `SessionEnd` and observe: runs
      synchronously, or skipped?
- [x] **Codex model + effort table (gap #12).** Record the concrete model ids for
      each abstract tier and the per-model effort support, including which models
      accept `xhigh`. Fills `HARNESSES["codex"]`.
- [x] **Does any manifest/marketplace field ship subagents (gap #14)?** Secondary
      sources mention an `agents` field in marketplace fallback manifests. If real,
      Phase 4 gets simpler; if not, confirm the `.codex/agents/` setup-script path.
- [~] **Do SubagentStart/SubagentStop actually fire for Codex custom subagents,
      and with what identifying payload?** This doc asserted they do; the subagents
      documentation does not say so. Gap #1's second marker path depends on it, and
      `subagent_stop.py` keys on `agent_type`/`agent_id` — so record the exact field
      that names the agent, or the routing cannot work.
- [x] **Does Codex reject or ignore unknown SKILL.md frontmatter keys** (gap #25 —
      `allowed-tools`, `effort`, `context`, `agent`)? Rejection makes this a blocker
      and forces generated per-harness SKILL.md files.
- [x] **Confirm implicit skill invocation can be disabled** per skill via
      `policy.allow_implicit_invocation: false` in `agents/openai.yaml` (gap #26),
      and that a `$`-mention still works when it is off.
- [x] **Confirm `skill_approval: false` silently auto-rejects** (gap #28) and decide
      whether install docs must require it enabled.
- [x] **Reconcile the two Codex effort value sets** (gap #27): CLI
      `minimal…xhigh` vs subagent TOML `low…ultra`. Which is authoritative per
      surface, and is `ultra` real?
- [x] **Dump a raw payload for every event we register** — SessionStart,
      UserPromptSubmit, PreToolUse, PostToolUse, SubagentStart, SubagentStop, Stop —
      and check them against the compatibility table above (14 fields as written;
      **15 as measured** — `session_id` was missing). The three that
      decide feasibility are `agent_type`/`agent_id` (gap #32), `stop_hook_active`
      (gap #31), and `source`.
- [x] **What is Codex's Stop-loop protection (gap #31)?** Codex documents Stop as
      blockable, so something must prevent infinite blocking. Find the mechanism and
      its field name. If there is no per-payload signal, the Stop gates need a
      platform-independent release.
- [ ] **Does `SubagentStart` injection reach a Codex subagent's context at all?**
      Not just "does the hook fire" — confirm `additionalContext` lands, since
      `RETRO_INPUT`/`CURATION_INPUT` delivery for retro and housekeeper depends on
      it (gap #32).
- [x] **BEHAVIORAL: does the model respect the gates?** *(moved here from P3 — it
      is the highest-variance unknown in the plan and the cheapest thing to observe,
      because P0 is already running a real teammate.)* Our guides, block reasons, and
      stop-gate prose were tuned on Claude over many sprints; nothing establishes
      that a GPT-5.x model reads them the same way. With the teammate running,
      observe qualitatively:
      - Given a blocked `git commit` with our stderr reason, does it **run the
        review** — or retry, work around the gate, or argue with it?
      - On a Stop-gate block, does it continue productively, or loop? (Pairs with
        gap #31 — a model that loops plus a gate that cannot release is an unbounded
        token burn.)
      - Does it follow TDD ordering and the review cycle from `TEAMMATE_GUIDE`
        prose alone?
      - Does it honor the sequential-discipline note, or batch gated steps?
      Discovering in P3 that the model fights the gates would waste Phases 2 and 3.

Deliverable: `docs/completed/CODEX_SPIKE_FINDINGS.md` with observed payloads,
version numbers, and a go/no-go.

**No-go criteria** (revised — the original named gap #11, which the 2026-07-24
doc review downgraded to Low):

1. **Plugin-bundled hooks unreliable across Codex versions** (gap #19). If
   enforcement cannot be depended on to load, a Codex teammate is an unenforced
   teammate and the feature is worse than not shipping it.
2. **The model does not respect the gates** (the behavioral check above). Gates that
   are present but ignored are the same outcome as gates that are absent.
3. Gap #11 confirmed after all, with no workaround.

Any of these → park Codex, file upstream issues, ship Phase 1 anyway (it stands on
its own merits), revisit on a later Codex release.

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
3. ~~**SessionEnd → runner**~~ (gap #4) — **dropped.** `SessionEnd` exists on
   Codex, so the teammate-completion event needs no relocation. What is left is
   deciding `compact.py`'s `async` flag once P0 reports whether async handlers run
   there; if they do not, drop the flag (it buys little) or add a `SessionStart`
   size check. Keep this slot as a reminder that the original item was based on a
   wrong event list.
4. **tool_input normalization** (gap #2). `_common` gains
   `normalize_write_input(tool_name, tool_input) -> {files, kind}` consumed by
   write/edit hooks; Claude shapes today, apply_patch shape added in P3.
5. **Plugin-root self-resolution.** Scripts resolve plugin root relative to
   `__file__` first, then `PLUGIN_ROOT`, then `CLAUDE_PLUGIN_ROOT` — removes the
   assumption that the invoking harness exports a Claude compatibility variable
   into shell contexts.
6. **Plan review via subagent** (gap #5) — **verified already true**, so this
   reduces to a regression test: `subagent_stop.py:337` writes
   `PLAN_AWAITING_REVIEW` and `pre_tool_write.py` is the schedule gate's second
   door. Pin both so a future refactor cannot quietly remove the only doors that
   survive on Codex. Sequence **after** item 4 — the write door needs apply_patch
   normalization to fire on Codex at all.
7. ~~**Harness-neutral SMM root** (gaps #9b **and #9c**)~~ — **SHIPPED in v5.0.0**,
   ahead of the rest of the phase, because #9c was live on Claude with no Codex
   involved. What landed differs from what this item originally specified, and
   the difference is the point: the resolution order is **`XP_AGENTS_DATA` →
   `$HOME/.xp-agents/data`, and nothing else is a preference.** The originally
   planned `XP_AGENTS_DATA` → `PLUGIN_DATA` → `CLAUDE_PLUGIN_DATA` → `$HOME/…`
   chain does **not** achieve the goal and must not be revived: the host always
   sets `CLAUDE_PLUGIN_DATA`, so honoring it as a preference leaves every SMM in
   the deletable directory and makes the fix a no-op in exactly the case it
   exists for — and `PLUGIN_DATA` is Codex's native data root, so honoring it
   re-creates the per-harness split that IS gap #9b. Both host roots are still
   **read**, but only to discover an SMM that already exists, via a candidate
   list rather than one path (the variable is absent in some hook processes, and
   a dev-mode install resolves the plugin id differently).

   Relocation copies and never moves, and declines while any teammate is live —
   worktree directories **or** in-place markers. On the gap #17 worktree sibling
   base: it does not migrate. It derives from the SMM's parent, so live
   worktrees would be orphaned by a move; the liveness gate is what protects
   them, and a SessionStart advisory covers the case where a stale worktree
   directory holds the gate on indefinitely.
8. **Abstract tier vocabulary** (gap #12). Rename `tier_wire` constants to
   `economy`/`standard`/`advanced`/`frontier`, introduce the `HARNESSES` table with
   the claude row populated, make `effort_supported()` harness-aware, add read-side
   legacy aliasing, and update the 4 prose files plus their 5 binding tests. The
   codex row stays a placeholder until P0/P3. Claude behavior unchanged.
9. **Harness-neutral worktree fragment** (gap #16). Rename the legacy
   `.claude/worktrees/` fragment, keeping back-compat detection of the old spelling
   so existing worktrees stay recognized.
10. **`QUESTION_GATE` clear-with-answer CLI leg** (gap #6). Removes the deadlock
    and, on Claude, gives a recovery path for a gate that currently has exactly one
    escape. Must require the answer text so the honesty property holds.
11. **Move lead-only enforcement into the skills** (gaps #23, #24). The teammate
    privilege gate and the `ACCEPT_IN_FLIGHT` drain currently ride the `Skill` tool
    surface, which does not exist on Codex — and, on Claude, is bypassable by any
    path that does not go through the Skill tool. Put the teammate check in each
    lead-owned skill's preload and give `ACCEPT_IN_FLIGHT` an explicit drain leg.
    Both are hook-independent, so they harden Claude today and port for free.
12. **`quality_review_done` CLI leg** (gap #1) on the existing
    `review_flag_cli.py`, matching the `simplify_done` leg's shape, and correct that
    file's docstring assumption about the Skill tool.
13. **Hook liveness heartbeat** (gap #18) — the highest-value item in this phase
    and valuable on Claude alone. `SessionStart` writes a heartbeat (session id +
    plugin version + timestamp); the interactive skills check it and refuse to
    proceed when it is missing or stale, naming the likely cause (Codex: hooks not
    trusted, run `/hooks`; either harness: plugin not loaded). Today, if hooks fail
    to load for any reason, every XP gate quietly disappears and the session looks
    normal — that is an honesty failure independent of Codex. Converting silent
    non-enforcement into a loud refusal is the point.

### Phase 2 — Dual packaging

1. `.codex-plugin/plugin.json` alongside `.claude-plugin/plugin.json`, with the
   same name/version/description and explicit `"skills": "./skills/"` plus
   `"hooks": "./hooks/hooks.codex.json"`. A manifest pin test verifies the
   two manifests retain identical shared metadata.

   Verified 2026-07-24 on the Claude side: `plugin.json` supports `name`,
   `version`, `description`, `author`, `homepage`, `keywords`, `skills`,
   `commands`, `agents`, `hooks`, `mcpServers`, and `dependencies` — so **both**
   harnesses accept a `hooks` path and both auto-discover `hooks/hooks.json` when
   it is omitted, which is what makes gap #20's explicit-path fix symmetrical.
   Note manifest component keys **replace** the default directory rather than
   adding to it, so listing `hooks` means the default is no longer scanned.

   Two useful affordances the earlier draft missed:
   - **Claude ignores unrecognized top-level fields** (warnings, not errors) and
     the docs explicitly endorse "one manifest that doubles as" another
     ecosystem's. Wrong *types* still fail. So the two manifests can safely carry
     each other's keys if that ever simplifies generation.
   - **`claude plugin validate --strict` treats those warnings as errors** — a
     ready-made CI check for a misspelled or leftover field. Adopt it in Phase 5's
     CI matrix rather than writing our own field linter.
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
   `--sandbox` and `--add-dir` flags per the P0 decision (gap #9a), with `-m` and
   `-c model_reasoning_effort` emitted from the `HARNESSES["codex"]` row whose
   model/effort values P0 supplies (gap #12) — the abstract tier constants and the
   table itself already landed in P1. `_ALLOWED_TOOLS` becomes per-harness here
   (gap #14). cwd = worktree, prompt via stdin (preamble unchanged).
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
   alongside the abstract model/effort tiers (tier wire already exists; extend,
   don't fork). Per the tier/provider split above, the planner and plan-reviewer
   still emit only a tier — provider is set by session config or a per-story
   override, never recommended by a reviewer.
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
| PreToolUse shell-coverage hole (gap #11) unfixable | ~~**Low**~~ **Occurred — and the mitigation is now mandatory config, not a feature flag.** The hole is real by an undocumented mechanism (`exec_command` + `write_stdin`), so the "only hosted tools are exempt" reasoning was wrong. It is *fixable*, which is why the no-go did not trigger | **`--disable unified_exec` on every Codex spawn — a hard requirement.** Without it every `PreToolUse:Bash` gate is bypassable and the enforcement story is decorative. The P0 gate earned its keep here |
| **A retry policy mistakes an unsupported model/effort pair for a flaky connection** | **Medium — new, found in P0** | An unsupported pair is neither rejected up front nor clamped: it burns ~16 s and dies with `stream disconnected before completion`. Validate the pair against our own `effort_support` table **before** spawning; never infer support from a failed run |
| Trust-review UX tax alienates Codex users | Medium | Batch hook changes per release; document; prefer `requirements.toml` managed hooks (trusted by policy, cannot be disabled) for org deployments |
| **Silent non-enforcement**: hooks not trusted (gap #18) or a too-old Codex (gap #19) yields a session that looks enforced but is not — teammates commit unreviewed code and nothing reports it | **High — CONFIRMED in P0, and the mitigation is currently broken** | ~~The P1 liveness heartbeat is the mitigation~~ — **it does not work on Codex as shipped.** The heartbeat is written keyed on the payload `session_id` but read from the environment, and Codex exports no session id to hook processes, so the read degrades to time-only and **an unenforced session started within 4h of an enforced one reports LIVE** on a shared SMM root. Compounded: the SessionStart context surfaces only at the first turn, not at startup, so the banner cannot tell you either. **Fix the liveness read before any Codex teammate ships** — until then this risk has no mitigation, only a name. Treat any gate that can vanish quietly as a correctness bug, not a UX issue |
| Codex model ids and effort support churn (versions move fast) | High | The `HARNESSES` table is data; keep model ids in one place, pin a canary CI job, and never infer a tier mapping in code |
| ~~**SMM destroyed by a plugin uninstall** (gap #9c)~~ — happened today on Claude, no Codex needed, and silently | ~~**High / already live**~~ **CLOSED in v5.0.0** | P1 item 7 shipped ahead of the phase. Residual, tracked as concerns rather than re-opened here: relocation declines while a stale worktree directory exists (mitigated by a SessionStart advisory), and only `smm/` relocates, so a forced relocation cuts the sibling worktree directories loose. A handle pinned before the move is NOT residual — both resolvers follow the `.migrated-to` pointer one hop |
| Lifecycle skills fire out of order via implicit invocation (gap #26) — also already live on Claude | Medium | `policy.allow_implicit_invocation: false` on Codex; audit `description` fields on both harnesses so they do not read as task-matching bait |
| GPT-5.x-codex responds differently to gate pressure (stop-gate loops, block-reason compliance) | ~~**Medium likelihood, high impact — and entirely unmeasured**~~ → **Measured in P0 and it did NOT occur.** It obeyed a blocked commit, ran a real independent review, explicitly declined to bypass, followed test-first and the review cycle from prose alone, and continued productively through a Stop block without looping. Residual: **cost**, not compliance — 61k tokens to answer a one-word prompt through one gate cycle. And sequential-discipline was consistent but never stress-tested | **Observed in P0**, not deferred to P3: the spike already runs a real teammate, so watching gate compliance is nearly free there, and it is a no-go criterion. P3's deliberately-blocked integration test then becomes a regression test rather than the first look. Tune `TEAMMATE_GUIDE` prose per harness if needed. Compounds with gap #31 — a looping model plus a gate that cannot release is an unbounded token burn |
| Maintenance: every new hook now has two targets | Certain | Generation + pin test makes drift a test failure, not a code-review hope |
| Tier rename (gap #12) touches persisted sprint data and 5 prose-pin tests at once — a botched migration mislabels stories' executors | Medium | Read-side aliasing rather than data rewrite, so old values keep loading; land the rename as its own P1 story with the alias table tested against real `sprint.json` fixtures before any prose changes |
| SMM-root change (gap #9b) relocates a live SMM without its worktree siblings, orphaning in-flight teammate state | Medium — **partly live** | SHIPPED: relocation is a COPY (the old path stays readable and authoritative on any failure), refuses while any teammate worktree or in-place marker is live, and leaves a `.migrated-to` pointer both resolvers follow. STILL OPEN: only `smm/` moves, so a `--force` relocation cuts the sibling worktree directories loose — worktree placement derives from the SMM's parent, and putting them back needs `git worktree move` |

## Non-goals

- Agent Teams parity on Codex (we already chose CLI teammates over Agent Teams).
- *Implementing* harnesses beyond Claude Code and Codex. Additional CLI harnesses
  are an explicit future goal, so the `--provider` seam, the `HARNESSES` table, and
  the tool-input normalization layer are designed as the extension points — adding
  harness #3 should be a data change plus a stream parser, with no prose churn. But
  no third harness is built in these phases.
- Porting Claude-only redundancies (`PostToolUseFailure`, `TeammateIdle`,
  `TaskCompleted`, `WorktreeCreate`). Note `SessionEnd` is **not** in this set — it
  exists on Codex.

## Open questions (resolve in P0/P1)

1. ~~Does `codex exec` load a marketplace-installed plugin in every intended mode?~~
   **ANSWERED (P0): yes, in all three.** Headless `codex exec`, an interactive
   session, and a real git worktree all loaded a marketplace-installed plugin and ran
   its bundled hooks. `${CLAUDE_PLUGIN_ROOT}` expands and a script in a non-standard
   subdirectory is copied into the cache and executed from there.
   **Trust configuration IS required and the result proves it**: untrusted plugin
   hooks are skipped **silently**, so headless spawns need
   `--dangerously-bypass-hook-trust` and interactive leads need the `/hooks` step.
   **New operational trap:** the plugin cache is **version-keyed** and
   `marketplace upgrade` is Git-only, so without a manifest version bump a run
   silently executes the previously cached copy — which reads exactly like "the hook
   did not fire".
2. Exact Codex hook stdin field names for tool payloads — **partly answered**
   (2026-07-24): common fields are `session_id`, `cwd`, `hook_event_name`, plus
   `turn_id` on turn-scoped hooks; tool events add `tool_name`, `tool_input`,
   `tool_use_id`, and `tool_response` on PostToolUse. Both Bash and `apply_patch`
   carry their payload in `tool_input.command`. ~~Still capture a real apply_patch
   payload in P0 before writing the path extractor.~~ **ANSWERED (P0): captured.** The
   payload is recorded with field names verbatim in
   `docs/completed/CODEX_SPIKE_FINDINGS.md`. `tool_input.command` for `apply_patch`
   carries **patch TEXT**, so the extractor parses `*** Update File:` / `*** Add File:`
   / `*** Delete File:` lines. Also observed: `tool_response` is a plain **string**;
   the payload carries `session_id`, `turn_id`, `transcript_path`, `model`,
   `permission_mode` and `tool_use_id`, none of which this doc listed.
3. ~~Does the Codex JSONL stream expose enough for the watchdog's
   activity-detection?~~ **Answered: yes.** `--json` streams `thread.started`,
   `turn.started`/`turn.completed`, `item.started`/`item.completed`/`item.failed`,
   and `error`, so any line is a liveness signal. Note `item.failed` and `error`
   give the watchdog a real failure signal too, which the Claude path infers less
   directly.
4. Cost reporting — **narrowed**: `turn.completed.usage` gives `input_tokens`,
   `cached_input_tokens`, `output_tokens`, `reasoning_output_tokens` and **no cost
   field**, so there is no analogue to Claude's `total_cost_usd`. Remaining choice:
   ship a static per-model price table (drifts, needs maintenance) or report tokens
   only and drop dollar figures for Codex teammates. Leaning tokens-only —
   an honest token count beats a silently stale dollar amount.
5. ~~**Codex model identifiers per abstract tier** — still open and P0-gated.~~
   **ANSWERED (P0):** `economy = gpt-5.6-luna`, `standard = gpt-5.6-terra`,
   `advanced = gpt-5.6-sol @ high`, `frontier = gpt-5.6-sol @ ultra` — see the filled
   `HARNESSES["codex"]` row above. The effort value set stated in this question was
   **wrong** (no `minimal`; `max` and `ultra` are both real). Two things the answer
   carries that the question did not anticipate: **Codex has only three visible coding
   tiers**, so the top two share a model and differ only by default effort; and
   **advertised support is not enforced support** — `gpt-5.6-luna` accepts an `ultra`
   it does not advertise. "They churn" is now evidence: the previously documented
   subagent ids were already stale.
6. **Codex tool vocabulary for TOML agent definitions** — the `--allowedTools`
   half is answered (no CLI equivalent; config-level `features.shell_tool` /
   `apps.*.enabled_tools` only, in Codex's namespace), so `_ALLOWED_TOOLS` is
   omitted for Codex. Still needed: the concrete tool names to write into TOML
   agent definitions, and ~~whether a manifest/marketplace `agents` field can ship
   them at all (gap #14)~~ — **that half is ANSWERED (P0): NO.** `plugin/read` returns
   no `agents` key; the field is accepted and silently ignored, so the
   `.codex/agents/` setup path is the only route. **Still open:** the concrete tool
   names for TOML agent definitions.
7. ~~**Does compaction need a third trigger?** (gap #4).~~ **ANSWERED (P0): no.** An
   `async: true` handler on `SessionEnd` **runs synchronously** — Codex says so itself
   (`warning: running async SessionEnd hook synchronously`) — so compaction fires and
   neither remedy is needed. **But a new question replaces it:** `SessionEnd` hook
   timeouts are **clamped to 3s**, and it is unresolved whether Codex caps every
   `SessionEnd` timeout or **reads the number as seconds** — the latter would mean
   every `timeout` in a Codex hooks file is off by 1000×. Do not write a shipped Codex
   timeout until one run distinguishes them.
8. ~~**Does an explicit manifest `hooks` path suppress `./hooks/hooks.json`
   auto-discovery** (gap #20), and what does Codex do with unrecognised event names?~~
   **ANSWERED (P0), both halves.** An explicit `hooks` entry **REPLACES** discovery
   rather than merging, so setting it is mandatory. Unrecognised event names are
   **silently ignored** — four were registered deliberately and nothing errored or
   warned — so **the generated Codex variant is tidy, not mandatory**.
9. **NEW (P0), and the largest open design question: how do skill bodies and their
   preloads reach a Codex model?** Codex places only the skill's **locator** in
   context, never the body, and a `!` shell preload is never expanded — so 16 of the 18
   skills present when this was measured (17 of 19 today) would load without their state
   input. Two routes were validated end to end
   (a single added sentence telling the model to substitute-and-run its own preload;
   or hook-side injection off `PreToolUse:Bash`, which works because the model reads
   `SKILL.md` *with a shell command*). Neither is adopted yet. See
   `docs/completed/CODEX_SPIKE_FINDINGS.md` for the six requirements the injection
   route must honour, each of which fails quietly.

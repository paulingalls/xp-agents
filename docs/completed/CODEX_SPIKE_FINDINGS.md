# Codex dual-target spike — findings and go/no-go

Phase 0 deliverable for `docs/ideas/8-CODEX_DUAL_TARGET_PLAN.md`. Sprint-004 built a
throwaway rig, ran it against a real Codex install across eight observation stories,
and this is what it found. **The rig is deleted at sprint close**, so this document is
the only surviving record — it is written for a reader who cannot re-run anything.

## Provenance, and why this is a snapshot

| | |
|---|---|
| Harness | `codex-cli` **0.146.0** |
| Model | `gpt-5.6-sol` for the behavioural runs |
| Account | `model_provider = "cortex"` — **the catalog is entitlement-scoped** |
| Measured | 2026-08-05 and the days before it |
| Plugin | installed from a local repo marketplace, manifest 5.3.1 → 5.3.13 |

Three limits on everything below, stated once here rather than repeated:

1. **One version.** Every finding is 0.146.0. Codex hooks are explicitly experimental
   and the plugin-hook capability landed recently (issue #16430 → PR #19705), so
   assume churn.
2. **One account.** `model/list` returns what *this login* is entitled to. A model id
   here may be absent elsewhere. Re-enumerate rather than trusting the ids.
3. **One model family.** Gate-compliance was observed on `gpt-5.6-sol`. Nothing here
   establishes how a different model reads the same prose.

**Payload evidence is redacted field shapes, not the raw corpus** — acceptance
criterion amended this session for a reason worth keeping: the captures carry absolute
home paths, session UUIDs, transcript paths and verbatim prompts, and `--no-ff` merges
keep a committing commit reachable from `main` forever, so deleting it later could not
contain it. Field *names* are verbatim; values are placeholders.

---

## The verdict

**GO — none of the three no-go criteria triggers, conditional on four pieces of named
work that are listed below and recorded in the SMM, not left as prose.**

| # | No-go criterion | Verdict | The evidence that decided it |
|---|---|---|---|
| 1 | **Plugin-bundled hooks unreliable across Codex versions** (gap #19) | **does not trigger** | A marketplace-installed plugin ran its bundled hooks under `codex exec`: `${CLAUDE_PLUGIN_ROOT}` expands, a script in a non-standard subdirectory is copied into the cache and executed from there, and `smm/init.sh` resolves and appends to `events.jsonl` from inside a hook process. No `plugin_hooks` enablement was set in any run. **Caveat that does not change the verdict:** only 0.146.0 was tested, so the *floor* is unestablished — that is a not-observed item, not a failure. |
| 2 | **The model does not respect the gates** | **does not trigger** | Given a blocked `git commit` with our stderr reason it ran the review, spawned a real independent reviewer that returned a genuine verdict, and stated explicitly that it would register the review "rather than bypassing it". From guide prose alone, with no process instruction in the prompt, it wrote the test before the implementation and invoked the quality review unprompted. Through a Stop-gate block it continued productively and did not loop. The prose tuned on Claude transferred. |
| 3 | **Gap #11 confirmed, with no workaround** | **does not trigger — but only just** | The hole is real and *worse* than the plan predicted: not a missing matcher but an entirely ungated channel. `exec_command` opens a persistent shell; `PreToolUse` fires once for the launch command and never again for anything sent with `write_stdin`. It does not trigger the criterion only because `--disable unified_exec` removes both tools and the replacement, `shell_command`, normalises to `Bash` and **is** gated. That flag is therefore a hard requirement, not a suggestion. |

**One sentence:** *All three no-go criteria are clear, so Codex support proceeds —
carrying a mandatory spawn flag, a broken liveness check that must be fixed first, and
a lifecycle-question surface that needs redesign rather than configuration.*

### What the verdict does not say

The three criteria were chosen before the spike ran, and **the sharpest constraints
found are not among them.** They are recorded below as scope limits rather than
promoted into criteria, because inventing a fourth criterion after the fact would make
the go/no-go unfalsifiable. They bound *which phases* are cheap, not *whether* to
proceed.

---

## Scope limits that are not no-go criteria

### 1. Codex cannot ask a structured question — but it can ask

This was got wrong twice during the spike and the correction matters, because the
wrong version says "impossible" where the right one says "expensive".

| Mode | Can write? | Can ask? |
|---|---|---|
| **Default, interactive** | yes | **in chat, yes** — `request_user_input` (the structured picker) is unavailable |
| **Plan** | **no** — refuses every write, including via a shell command | structured, *inferred* — see below |
| **`codex exec` (headless)** | yes | **no, at all** — no user-interaction surface: `request_user_input` unavailable *and* `approval: never` is pinned |

Two of those cells are inference, not observation, and the distinction is the whole
point of this section: **no run exercised the structured picker in Plan mode** — that it
works there is read off the error string's own wording ("unavailable in *Default* mode")
— and no run scripted an interactive Default-mode question either. What was measured is
the negative: the picker is unavailable in Default mode, and Plan mode refuses to write.
The headless row is the load-bearing one for Phases 3–4 and it *is* measured: a headless
Codex teammate can never be asked anything, so every lifecycle flow needing an answer
must be redesigned, not configured.

Observed verbatim in Default mode:

```
ERROR codex_core::tools::router: error=request_user_input is unavailable in Default mode
```

Two remedies were tested and both failed, the error unchanged:
`tools.experimental_request_user_input={mode="allow"}` and `collaboration_mode="full"`.
(`CollaborationMode` has exactly three variants: `default`, `full`, `plan`.)

Plan mode was then tested directly, interactively, twice: asked to create a file it
refused with *"You must not perform mutating actions."*; asked whether it could append
via a shell command instead — the path `smm/append.sh` actually uses — it refused
again. So **switching to Plan mode to ask is not a workaround**: a lead there cannot
record the answer it just received. Upstream reports that the no-write rule is
prompt-level with no runtime block, which makes this model compliance rather than
enforcement — but it held on both attempts, so it must be designed against as real.

**What this actually costs.** Codex's native affordance is asking in chat, and Default
mode can both ask that way and write. So gap #6's designed remedy — a CLI leg that
clears `QUESTION_GATE` *while recording a real answer* — works. What breaks is the
mechanism our prose names: `question_answered.py` consumes the gate on
`PostToolUse:AskUserQuestion`, and that tool does not exist here. Measured surface:

- **56 `AskUserQuestion` references across 13 shipped `SKILL.md` files.**
- **15 further shipped files**, including `hooks/hooks.json` — the registration itself —
  plus `agents/xp-plan-reviewer.md`, `PROCESS_GUIDE.md`,
  `scripts/_close_pipeline_shared.md`, `question_answered.py`, `lead_gates.py`,
  `kickoff_gate.py`, three stop gates, `close_common.py`, `scaffold_plan.py`,
  `user_prompt_log.py`, `smm/materialize.py`, `smm/resolution.py`. **28 files total.**
- **31 test files pin the same vocabulary**, so the port breaks a prose-pin surface,
  not merely prose.

Consequence: **Phase 4 (Codex leads) is expensive, not blocked.** Phase 3 (Codex
teammates) is unaffected — `QUESTION_GATE` is a lead gate and teammates are exempt.

### 2. The review-cycle release marker is unauthenticated, and on Codex it *must* be forged

The model respected the commit gate — and then, to satisfy it, read
`review_cycle_done.py` plus a test helper, synthesized a `PostToolUse:Skill` payload
and piped it into the hook, which wrote the marker and released the gate.

That is two findings, and the second is worse than the first:

- **Harness-independent:** anything that can run `python3` can write the release
  marker directly. The gate is advisory against a determined agent on *either* harness.
- **Codex-specific:** `review_cycle_done.py` fires on `PostToolUse:Skill|Agent`. Skills
  are not tool calls here, and the subagent spawn tool arrives as
  `collaborationspawn_agent` (the dot is stripped), which the case-sensitive `Agent`
  matcher never matches. **The gate's only legitimate satisfaction path does not exist
  on this harness** — so forging it is not misbehaviour, it is the only route.

### 3. Session-scoped liveness never engages, so an unenforced session can read LIVE

This is the mitigation the plan names for its own worst silent-failure mode, and it is
broken on Codex. Detail and the required fix are under *Required work* below.

---

## Required work carried forward

The GO is conditional on these. R1–R3 are recorded as SMM **decision** events so they
surface in the Constraints view rather than only in this file. R4 is recorded as a
**concern**, deliberately — it is an unresolved conflict, not a settled constraint, and
recording it as a decision would assert a resolution nobody has made.

A fifth item is *not* listed here because it is not Codex-specific, but it is a
precondition for Phase 3 all the same: **the review-cycle release marker has no
legitimate writer on this harness** (scope limit 2). A Codex teammate cannot satisfy the
commit gate except by forging the marker, so the explicit CLI leg gap #1 prescribes is
required before a Codex teammate ships, on the same footing as R2.

### R1 — `--disable unified_exec` on every Codex spawn *(decision `ef018590d623`)*

Without it, `write_stdin` into an `exec_command` shell bypasses every gate riding
`PreToolUse:Bash` — commit gate, tier-1 secret scan, staged-lint, branch protection.
Verified by enumeration: the flag removes both `exec_command` and `write_stdin` from
the tool set and substitutes `shell_command`, which is gated.
`--enable`/`--disable` take feature names; `unified_exec` is accepted,
`exec_command` and `shell_session` are not.

### R2 — Fix the liveness read before any Codex teammate ships *(decision `38978b6864d6`)*

The heartbeat is **written** keyed on the payload's `session_id` but **read** from the
environment, and Codex exports none of `XP_SESSION_ID`, `CODEX_THREAD_ID` or
`CLAUDE_CODE_SESSION_ID` to hook processes. The read misses the session-scoped marker
and degrades to a time-only check, where any sibling heartbeat inside the 4-hour
staleness window reads live.

**Consequence:** on a shared SMM root, an unenforced Codex session started within four
hours of an enforced one reports **LIVE**. The spike's own untrusted control run only
reported honestly because every run used a separate scratch root. This is precisely
the failure gap #18 exists to prevent, so the mitigation currently defeats itself.

Compounding it, three shipped defects the interactive run surfaced:

- `SessionStart` emits a **self-contradicting pair** when SMM init fails — the injected
  context said `SMM init failed — xp-agents disabled.` while the status line said
  `XP agents (v5.5.0) active. Run /xp-kickoff.` (concern `e32c04a46599`).
- That context **surfaces only at the first turn, not at startup**, so a user reading
  the startup banner cannot tell whether enforcement is live until after they have
  begun working (concern `7c688f1295d6`).
- `plugin_loader.plugin_version()` **hardcodes `.claude-plugin/plugin.json`**, so a
  Codex session reports the *Claude* manifest version — the model was told `v5.5.0`
  while the installed Codex manifest, and the version-keyed cache path it actually
  executed from, was `5.3.13`. A harness-specific path in shipped code, and it hides
  the one number that says which cached copy is running. This is gap #15, measured
  (concern `08bdfb8403cd`).

### R3 — A CLI leg for `QUESTION_GATE` before Phase 4 *(decision `85a5f3eca5d2`)*

Per scope limit 1. Ask in chat, pass the answer text to a CLI leg that appends the
answer event and consumes the marker. The honesty property must survive the port:
require the answer text, so the leg cannot fake-clear a gate.

### R4 — Settle the sidecar conflict before the tier milestone *(concern `760cdeab8ddc`)*

Implicit skill invocation is real and was **observed firing `/xp-kickoff`** unprompted.
The working control is `policy.allow_implicit_invocation: false` in a per-skill
`<skill>/agents/openai.yaml`. But a decision recorded earlier in this same sprint —
`harness-config-sidecar-ban`, no shipped skill may carry an `agents/` sidecar — is
pinned in the collected suite. **The ban and the only working mitigation cannot both
hold.** Reports that Codex ignores SKILL.md `disable-model-invocation` would settle it,
but Codex's own embedded guidance documents that key, so this is recorded as an
unresolved conflict rather than as a finding. The tier/packaging milestone must pick.

---

## Install, trust and enablement preconditions

What it actually took to get an enforced Codex session, in the order it bites.

| Step | Finding |
|---|---|
| **Marketplace + install** | A local repo marketplace catalog is accepted and `codex plugin add` succeeds. All 19 shipped skills are discoverable from the installed package. |
| **Manifest `hooks` field** | An explicit `"hooks": "./hooks/hooks.codex.json"` **REPLACES** default `./hooks/hooks.json` discovery rather than merging — settling the plan's open question 8. Omitting it makes Codex load the *Claude* variant. |
| **Unknown event names** | **Silently ignored.** `PostToolUseFailure`, `TeammateIdle`, `TaskCompleted` and `WorktreeCreate` were registered deliberately; nothing errored. A generated per-harness hooks file is therefore *tidy, not mandatory*. |
| **Hook trust (headless)** | `--dangerously-bypass-hook-trust`. |
| **Hook trust (interactive)** | A `/hooks` review per content hash, re-reviewed after every plugin update. |
| **Untrusted hooks** | **Skipped SILENTLY.** The hooks file is demonstrably read — six `additionalContextLimit` warnings name it by path — yet no handler runs and nothing says so. This is gap #18's whole justification, confirmed. |
| **`plugin_hooks` enablement** | **None required on 0.146.0.** No run set any such flag and hooks executed. |
| **Sandbox** | Settles at **least privilege**: `--sandbox workspace-write` plus `--add-dir` for the user-level SMM root. Both a hook append and a teammate shell `append.sh` succeeded, and `flock` and the atomic rename both work outside the workspace. `danger-full-access` was never needed. |
| **Sandbox caveat** | `.git` is read-only under `workspace-write`, so a commit fails *after* the gate allows it. Gate decisions stay observable; a successful commit cannot be demonstrated without widening the sandbox. Reads are also broader than `--add-dir` suggests — it grants **write** access; the model read outside it freely. |
| **Plugin availability** | `codex exec` has **no `--plugin-dir` equivalent**. No flag or config loads a plugin ad hoc, so a Codex teammate *requires* the plugin installed for the user — the spawn preflight is a hard fail with no fallback, unlike Claude's `--plugin-dir`. |
| **Version-keyed cache** | The plugin cache is keyed by manifest version and `marketplace upgrade` is Git-only (it errors on a local marketplace). **Without a version bump, a run silently executes the previously cached copy** and every observation reports "the hook did not fire". Reinstalling also wipes any cache-injected file, so bump → reinstall → re-inject is one atomic sequence. |

---

## Hook and event surface

### The three decisive fields

The plan named these as the fields that decide feasibility. All three resolved, and
two resolved *against* what the plan assumed.

| Field | Verdict |
|---|---|
| `agent_type` / `agent_id` | **Present, but the value does not discriminate.** `'default'` for a Codex subagent — never our agent name — and absent entirely on top-level tool events. `_common.is_xp_agent` tests `agent_type.startswith("xp-")`, so it is always False and **recursion prevention never fires**. The `SubagentStart` `_TIERS` registry, which keys on Claude agent-type names, cannot route either. |
| `stop_hook_active` | **Present AND functional** — gap #31's premise ("no known analogue", rated **Blocker**) is falsified. Reads False on a turn's first Stop, flips True after a block, stays True; all four Stop gates bypass on True and release correctly. **But the flip is not on a fixed firing number**: one run read False/True/True/True, another False/False/True. No gate may assume a block count. |
| `source` | **Present** on SessionStart, value `'startup'`. |

### Field presence by event

Fifteen events were registered — the eleven this version recognises plus four it does
not. `not-observed` means the event never fired in any run, which for the four
unrecognised names is itself the finding.

| event | cwd | tool_input | agent_type | agent_id | stop_hook_active | tool_name | source | tool_response | prompt | reason |
|---|---|---|---|---|---|---|---|---|---|---|
| PreToolUse | always | always | some-firings | some-firings | never | always | never | never | never | never |
| PostToolUse | always | always | some-firings | some-firings | never | always | never | always | never | never |
| SessionStart | always | never | never | never | never | never | **always** | never | never | never |
| UserPromptSubmit | always | never | never | never | never | never | never | never | **always** | never |
| Stop | always | never | never | never | **always** | never | never | never | never | never |
| SubagentStart | always | never | **always** | **always** | never | never | never | never | never | never |
| SubagentStop | always | never | **always** | **always** | **always** | never | never | never | never | never |
| SessionEnd | always | never | never | never | never | never | never | never | never | **always** |
| PermissionRequest | not-observed | — | — | — | — | — | — | — | — | — |
| PreCompact / PostCompact | not-observed | — | — | — | — | — | — | — | — | — |
| PostToolUseFailure | not-observed | — | — | — | — | — | — | — | — | — |
| TeammateIdle / TaskCompleted / WorktreeCreate | not-observed | — | — | — | — | — | — | — | — | — |

`some-firings` is not noise: `agent_type`/`agent_id` are absent on top-level tool
events and present (as `'default'`) on tool events made *inside* a subagent.

**Fields Codex sends that the plan's 14-field table does not list:** `session_id`,
`turn_id`, `transcript_path`, `model`, `permission_mode`, `tool_use_id`,
`last_assistant_message` (Stop, SubagentStop), `agent_transcript_path` (SubagentStop).
`session_id` is the significant omission — shipped code reads it in four places
(`hook_liveness.payload_session_id`, `housekeeping_flight` ×3, `bash_post_tool`), so
**the compatibility surface is 15 fields, not 14.**

### A real `apply_patch` payload

Field names verbatim; values redacted per the amended AC-1.

```json
{
  "session_id": "<uuid>",
  "turn_id": "<uuid>",
  "transcript_path": "<redacted>",
  "cwd": "<scratch>/proj",
  "hook_event_name": "PreToolUse",
  "model": "<model-id>",
  "permission_mode": "bypassPermissions",
  "tool_name": "apply_patch",
  "tool_input": {
    "command": "*** Begin Patch\n*** Update File: <abs-path>/notes.txt\n@@\n-before\n+after\n*** End Patch"
  },
  "tool_use_id": "exec-<uuid>"
}
```

Three consequences for the P1 normalization layer:

1. **`tool_name` for an edit is verbatim `apply_patch`.** The matcher's `Edit`, `Write`
   and `MultiEdit` alternatives are dead names on this harness.
2. **`tool_input.command` is present for both Bash and `apply_patch` as the plan said,
   but differs in kind** — a shell command for Bash, *patch text* for `apply_patch`. A
   path extractor must parse the `*** Update File:` / `*** Add File:` /
   `*** Delete File:` lines. It must not treat the value as a command.
3. **`tool_response` arrives as a plain string.** Not a break — `bash_post_tool.py`
   already handles dict-or-string.

### `tool_name` is normalised, and one normalisation breaks a matcher

There is **no tool called `Bash`**. The model's own tool list is `functions.exec`,
`functions.wait`, `functions.request_user_input`, `apply_patch`, `exec_command`,
`write_stdin`, `view_image`, the `create_goal`/`update_plan` family, the MCP readers,
and six `collaboration.*` tools.

| schema name | payload `tool_name` |
|---|---|
| `functions.exec`, `exec_command`, `shell_command` | **`Bash`** |
| `apply_patch` | `apply_patch` |
| `collaboration.spawn_agent` | **`collaborationspawn_agent`** — the dot is stripped |
| `collaboration.wait_agent` | `collaborationwait_agent` |

So our `Bash` matcher works *because* Codex normalises to it, not because such a tool
exists. And the stripped dot means the case-sensitive `Agent` matcher never matches
`collaborationspawn_agent`, so **no `PostToolUse` handler ran for the subagent spawn
call.** Stated narrowly on purpose: `PostToolUse` fires normally for calls made
*inside* a subagent — it is only the spawn call that is unseen — and with no
matcher-less `PostToolUse` entry registered, the corpus cannot distinguish "Codex
emitted no event" from "nothing we registered could match it".

### A failed tool call is invisible to post-hooks

**A failed tool call fires `PreToolUse` and then nothing.** Measured: 4 of 5
`tool_use_id`s paired; the failed `apply_patch` did not. `PostToolUseFailure` is not a
recognised Codex event, so nothing fires there either.

This **falsifies gap #3's stated resolution**, which was to "fold failure detection
into the PostToolUse handler, keyed on exit status in the payload" — there is no
PostToolUse to key on. Any handler that pairs Pre/Post, or records an outcome on
PostToolUse, sees a hanging `PreToolUse`. The failure *is* on stderr; a Codex failure
signal has to come from somewhere other than a post-hook.

### Six events cannot emit `additionalContext` at all

Each named by its own host warning — *"this event cannot emit additionalContext"*:
`PermissionRequest`, `PreCompact`, `PostCompact`, `SessionEnd`, `SubagentStop`, `Stop`.
Stop blocks travel as `{"decision": "block"}` instead. This matches the Claude-side
constraint that `SubagentStop` cannot message a parent, and it means no gate-like
behaviour may ever depend on `SessionEnd`.

Injection **does** work where it is allowed: a `SessionStart` handler minted a `uuid4`
marker in-hook, never placed it in the prompt, and the model reported it
byte-identical. The paired control run with the handler unwired answered **NO**.

---

## Version floor

**Established: plugin-bundled hooks execute on `codex-cli` 0.146.0, with no
`plugin_hooks` enablement set.**

**Not established: the minimum version.** Only 0.146.0 was ever installed. No older
build was obtained, and a floor cannot be inferred from one passing version — a
version that works tells you nothing about where support began.

This matters more than an ordinary gap, because gap #19's whole point is that an older
Codex *runs the plugin's skills while ignoring its hooks* — the unenforced-teammate
failure mode, silently. Two consequences:

1. **The spawn-time version check that Phase 3 owes cannot be written from this
   spike.** Pinning `>= 0.146.0` would be pinning the only version tested, which is
   defensible as a floor but is not a *measured* floor and must not be recorded as one.
2. **Do not treat a version pin as a substitute for the liveness check** (R2). The plan
   already says this; the spike's finding that untrusted hooks are skipped silently,
   plus a liveness read that never engages, makes it load-bearing rather than advisory.

---

## Model and effort tiers

Fills both `HARNESSES["codex"]` holes the plan marks `PLACEHOLDER — P0`. Every value
was read from `model/list` over `codex app-server`, never carried from documentation.

### The catalog

`supportedReasoningEfforts` is a **required per-model field** — the per-model shape the
plan says the abstraction must keep.

| id | hidden | default model | default effort | advertised efforts |
|---|---|---|---|---|
| `gpt-5.6-sol` | no | **yes** | `low` | low, medium, high, xhigh, max, **ultra** |
| `gpt-5.6-terra` | no | no | medium | low, medium, high, xhigh, max, **ultra** |
| `gpt-5.6-luna` | no | no | medium | low, medium, high, xhigh, max |
| `gpt-5.5` | no | no | medium | low, medium, high, xhigh |
| `gpt-5.2` | no | no | medium | low, medium, high, xhigh |
| `gpt-5.4` | **yes** | no | medium | low, medium, high, xhigh |
| `gpt-5.4-mini` | **yes** | no | medium | low, medium, high, xhigh |
| `codex-auto-review` | **yes** | no | medium | low, medium, high, xhigh |

Union advertised: `low, medium, high, xhigh, max, ultra`. **`minimal` is advertised by
nothing.** `ultra` is real rather than documentation drift — catalog-advertised on two
models, described *"Maximum reasoning with automatic task delegation"*, and accepted in
a live run.

### Advertised is not enforced

The catalog *claims* per-model support. Claims were exercised, each run's own rollout
session log read back by session id.

| requested | advertised? | outcome |
|---|---|---|
| `gpt-5.6-luna@low` / `@max` | yes | completed |
| **`gpt-5.6-luna@ultra`** | **no** | **completed — the model answered** |
| `gpt-5.2@ultra` | no | failed |
| `gpt-5.6-luna@banana-not-an-effort` | n/a | failed |

**So the catalog cannot be trusted as a support boundary in the permissive
direction**: a spawn may be accepted at a tier the catalog says the model does not
support. Some enforcement exists — two pairs did fail — but note *how*, because it
decides what a spawn wrapper can key on: **neither was rejected up front.** Both ran
~16 s and died with `task_complete.error = "stream disconnected before completion"`.
An unsupported pair surfaces as an opaque mid-stream disconnect, the same shape a
genuine transport failure takes.

Two honesty notes carried forward from the story that measured this:

- **The rollout records the REQUESTED value, not the effective one.** The nonsense
  effort sits in a `turn_context` on disk. So this channel cannot distinguish
  accepted-and-honoured from accepted-and-ignored, and *no run that exits 0 can read
  as clamped*. What it does establish is that each run started with the pinned pair
  rather than the operator's `config.toml` default.
- **Whether luna truly reasons at `ultra` is not observed.** The one cheap signal
  available does not corroborate it: `reasoning_output_tokens` was 13 for luna@max and
  **0** for luna@ultra, luna@low and sol@ultra. n=1 on a trivial prompt, so it settles
  nothing — but it points the unfavourable way.

### The drafted `HARNESSES["codex"]` row

**Codex offers three visible coding tiers, not four** — nothing sits above `sol` — so
`advanced` and `frontier` share a model and are separated by default effort. Hidden
models are excluded deliberately: hidden from Codex's own picker means deprecated or
restricted, and building a shipped tier on one means building on something the vendor
is steering users away from.

```python
"codex": {
  "binary": "codex",
  # tier -> concrete model id
  "models": {"economy": "gpt-5.6-luna", "standard": "gpt-5.6-terra",
             "advanced": "gpt-5.6-sol", "frontier": "gpt-5.6-sol"},
  # abstract effort tier -> harness spelling; None = no equivalent
  "efforts": {"minimal": None,          # advertised by nothing
              "low": "low", "medium": "medium", "high": "high",
              "xhigh": "xhigh", "max": "max", "ultra": "ultra"},
  # TIER-keyed, so advanced and frontier can differ while sharing a model
  "effort_support": {"economy":  {"low","medium","high","xhigh","max"},
                     "standard": {"low","medium","high","xhigh","max","ultra"},
                     "advanced": {"low","medium","high","xhigh","max","ultra"},
                     "frontier": {"low","medium","high","xhigh","max","ultra"}},
  # per-tier DEFAULT effort — a NEW field, see below.
  # UNVERIFIED: advanced and frontier share one model, so `high` vs `ultra` is the
  # entire separator between the top two tiers — and nothing here confirms the
  # effort is honoured (the rollout echoes the REQUEST). Re-measure on a real
  # prompt before shipping frontier as distinct from advanced.
  "default_effort": {"economy": "medium", "standard": "medium",
                     "advanced": "high", "frontier": "ultra"},
  "model_flag":  ["-m", "{model}"],
  "effort_flag": ["-c", "model_reasoning_effort={effort}"],
}
```

All four mapped tiers were exercised and every run completed. Per the caveat above,
"accepted" means the flags were taken and the turn ran — not that the effort was
honoured. That matters most for the pair separating the top two tiers: `advanced` and
`frontier` share `gpt-5.6-sol`, so `high` vs `ultra` is the *only* thing distinguishing
them, and that distinction is unverified.

### Three things the tier milestone must decide, not inherit

1. **`effort_support` must be TIER-keyed, and that changes the Claude row too.**
   `smm/tier_wire.py:46` is already tier-keyed (its own comment says "Per-tier") and
   only *looks* model-keyed because Claude's tiers are named after models. Codex breaks
   the coincidence, so a model-keyed `effort_support` collapses two tiers into one.
   The plan's interface contract ("per model, not per harness") settles only half of it.
2. **`default_effort` is a new field.** The drafted shape has no per-tier default, so
   either the Claude row gains one or the two harnesses diverge in shape — the thing
   the abstraction exists to prevent.
3. **It is a default, not a fusion of the two axes.** The plan explicitly rejected
   fusing model tier with effort tier; a default that stays overridable preserves both.
   Codex agrees by example: `sol`'s own `defaultReasoningEffort` is **`low`**, blurbed
   *"try starting lower, then turn it up"* — the vendor does not assume its frontier
   model should run hot.

### Did `ultra` delegate?

**No spawn observed** — the frontier run's rollout contains no `spawn_agent` call, and
it ran `collaboration_mode: "default"`. **This bounds the question, it does not settle
it:** the prompt was "reply ok", which gives nothing to delegate. `frontier = sol@ultra`
is safe on this evidence and *not proven safe under load*. A teammate that
auto-delegates would spawn workers the file-domain and coordination machinery does not
know exist, so re-observe on a real task before the tier ships.

---

## Enforcement: gates and model compliance

### Interception, per shell path

Gate armed and asserted before each run, two staged code files.

| path | intercepted | commit blocked with our reason |
|---|---|---|
| `functions.exec` | yes | **yes** |
| `exec_command` | yes | **yes** |
| `shell_command` (appears only with `--disable unified_exec`) | yes | **yes** |
| **`write_stdin` into a session started by `exec_command`** | **NO** | **NO** |
| `apply_patch` | yes | n/a — cannot commit |

The host surfaces a block verbatim:

```
ERROR codex_core::tools::router: error=Command blocked by PreToolUse hook: Run
/xp-quality-review before committing — 2 code files changed since last review..
Command: git -C <worktree> commit -m '<message>'
```

Gap #11's mechanism is a **persistent shell session**. `exec_command` starts one;
`PreToolUse` fires once for the launch (captured: `tool_input.command == "zsh"`) and
never again. The gate saw the launch and one direct commit; the `write_stdin` commit
produced no `PreToolUse` capture of any kind. Hence R1.

### Detection: six spellings evade the detector

**This class is harness-independent** — identical on Claude, live in what ships today —
so it sits outside the Codex verdict but must not sit outside the findings. Produced by
driving the real `scripts/pre_tool_bash.py` as a subprocess, so it cannot drift from
what ships.

| result | shapes |
|---|---|
| **blocked** | `git commit`, `env FOO=1 git commit`, `GIT_DIR=x git commit`, `/usr/bin/git commit`, `git add -A && git commit`, `git -c user.name=x commit`, `git merge` |
| **not blocked** | `sh -c "git commit"`, `sh -c 'git commit'`, `bash -c "git commit"`, `git ci` (git alias), `gc` (shell alias), `GIT=git; $GIT commit` |

`strip_quoted` deletes quoted spans before the scan, so anything inside `sh -c "…"`
disappears and a heredoc *body* is removed wholesale; aliases and `$GIT` are invisible
because the detector matches the literal token `git`.

This is the **accepted cost of a deliberate design** — `pre_tool_bash.py` says "bash
isn't statically parseable", so trust-plus-merge is the model, not a regression. It is
recorded here because a findings doc listing only the two Codex items would leave a
reader believing the commit gate is airtight once R1's flag is set. It is not.

### The model's behaviour under the gates

This was the plan's highest-variance unknown and the cheapest thing to observe.

- **Blocked commit → ran the review.** It read the skill, ran the preload itself,
  spawned a real reviewer subagent that returned a genuine verdict, then correctly
  diagnosed why the gate stayed shut: *"although the independent review completed, the
  inactive skill runtime did not record that review. I'm inspecting the gate's expected
  review marker so I can register the completed review correctly rather than bypassing
  it."* It then wrote the marker directly — see scope limit 2; on this harness that is
  the only available route, not a bypass.
- **Blocked Stop → productive, no loop.** It investigated the gate's actual input —
  Stop payloads, the event log, the arming concern — rather than spinning. **It cost
  61k tokens to answer a one-word prompt**, which is the real price of a gate here.
- **Compliance from guide prose alone.** Given only *"Add a Python module calc.py with
  a function add(a, b)… Work as you normally would in this repository"*, it wrote
  `test_calc.py` **before** `calc.py` and ran it before the implementation existed, and
  invoked the quality review unprompted, citing the cadence it had read. Its own
  unprompted statement: *"I'll follow the repository's XP workflow… test-first and run
  the required review and verification before committing."*
- **Sequential discipline: consistent, but not stress-tested.** Observed behaviour was
  step-by-step; no run deliberately tempted it to batch gated steps. A weaker
  observation than the other three, and labelled as such.
- **Implicit skill invocation is real.** A session started running `/xp-kickoff`
  unprompted — the risk gap #26 names, observed rather than theorised. See R4.

---

## Skills and subagents

### Frontmatter is not rejected — and three of the four "unknown" keys are Codex's own

Gap #25 calls rejection a blocker that would force generated per-harness skill files.
**The premise is mostly wrong and the blocker branch is falsified.** Codex's own
embedded skill-authoring guidance documents this set verbatim:

```
name, description, argument-hint, disable-model-invocation,
user-invocable, allowed-tools, context / agent / model
```

We ship four keys beyond `name`/`description`: `allowed-tools` (19 skills), `effort`
(6), `context` (3), `agent` (3). **Three of the four are documented Codex fields.**
Only `effort` is genuinely undocumented — and Codex documents `model` in the slot we
use `effort` for, which is the real finding hiding inside gap #25.

**Verdict: NOT REJECTED, and not warned about on the loader channel.** Scoped
deliberately, because the shorter word overclaims: this channel cannot separate
*warned-about* from *silently ignored*, and a quiet `app-server` stderr is not silence
on every channel. For gap #25 the distinction does not matter — a warning is not a
blocker either. For any shipped decision resting on the word "silent", it does.

The verdict is only worth having because the instrument was armed first: `errors: []`
reads identically whether the loader forgave our keys or the array is never populated.
Two controls were injected into the installed cache and read in the same call — a
skill with an unclosed `---` produced `errors: 1` and was **dropped from the listing**,
while a well-formed skill carrying an invented key loaded exactly like our real ones.
The arming row is what makes the other two mean anything.

**A contradiction inside Codex worth knowing about:** its own bundled
`skill-creator/scripts/quick_validate.py` allows only
`{name, description, license, allowed-tools, metadata}` and would **reject `effort`,
`context` and `agent`** — three keys the same binary's guidance documents. That
validator is an authoring lint, not the loader. A user who runs Codex's own validator
against our skills gets failures the runtime never raises.

### Implicit invocation can be disabled — per skill, invisibly

`policy.allow_implicit_invocation: false` in `<skill>/agents/openai.yaml` works on
**both legs**: with it set on one skill, a live session listing every `xp-agents:`
skill returned 18 of 19 with that one absent, and an explicit `$`-mention still
delivered the body.

**Caveat a shipped version must not miss:** the policy is **invisible to the loader
channel.** A skill with the policy and one without return byte-identical `skills/list`
records. A per-skill opt-out cannot be audited from `app-server` — only by asking a
live model what it can see. See R4 for the conflict this creates.

### `skill_approval` gates nothing

**Verdict: it does not gate skill invocation in either direction**, falsifying gap #28
both ways — so install docs need not require it enabled.

Shape first, because the plan has it wrong: it is not a standalone top-level boolean
but a field of `GranularAskForApproval` (alongside `sandbox_approval`, `rules`,
`request_permissions`, `mcp_elicitations`), defaulting to `false`.

| setting | result |
|---|---|
| `false` (the default) | skill invoked normally; **no auto-reject** |
| `true`, interactive session | **no approval prompt appeared**; skill delivered anyway |

The negative is trustworthy because the config shape was validated first: the granular
policy is **accepted** by `--strict-config`, while a nonsense field in the same object
is **rejected** (`missing field sandbox_approval`). So the policy parses and the shape
is right. Scoped honestly: one version, and the field defaults to false, so a later
release could activate it.

`codex exec` cannot exercise it at all — `approval: never` was reported in every
headless run, including with a validated granular policy, and nothing in the user's
config sets it. `codex exec` pins it.

### `async: true` on `SessionEnd` runs synchronously

**Not skipped.** Codex says so itself: `warning: running async SessionEnd hook
synchronously`. Measured on the real pairing the shipped `hooks.json` already uses
(`session_end.py` async false, `compact.py` async true), and corroborated by side
effect — `session_end.py` wrote its event in the same run. Three outcomes were
distinguished, not two: ran-sync / ran-async / skipped.

**Open, and worth one follow-up run:** `SessionEnd` hook timeouts are **clamped to 3s**
— both a 2500 ms and a 1500 ms entry drew `warning: clamping SessionEnd hook timeout to
3s`. On Claude semantics both are already under 3s, so a clamp is a reduction that
cannot apply. Two readings fit: Codex caps every `SessionEnd` timeout at 3s regardless,
**or Codex reads the number as seconds** — in which case every `timeout` in a Codex
hooks file is off by 1000×, and only the `SessionEnd` cap is hiding it. These are the
file's only `timeout` values, so nothing else exercises it. **Do not write a shipped
timeout for Codex until one run distinguishes them.**

### No manifest field ships subagents

**Verdict: NO. The config/setup-directory path is the only route.** `"agents":
"./agents/"` was added to the manifest and installed; `plugin/read` returned
`appTemplates, apps, description, hooks, marketplaceName, marketplacePath, mcpServers,
scheduledTasks, shareUrl, skills, summary` — **no `agents` key**. Silently ignored, no
error, while `skills: 19` and `hooks: 20` surfaced normally. The directory *was* copied
into the cache; it is simply never surfaced. The key was reverted rather than left in
the manifest as a no-op.

Gap #14 rests on an overloaded name. `agents` means three things and only one ships
subagents:

| sense | what it is | ships subagents? |
|---|---|---|
| `<skill>/agents/openai.yaml` | per-skill UI + policy metadata — the implicit-invocation mechanism | no |
| manifest `agents` key | accepted, ignored | no |
| `config.toml` | `default_subagent_model`, `default_subagent_reasoning_effort`, `max_depth`, `AgentRoleToml` | **yes** |

Secondary sources claiming a marketplace `agents` field most plausibly saw sense 1.

### Skill bodies: only the locator reaches the model

The single largest delivery finding, and it outranks every hook question. **Codex
places only the skill's LOCATOR in context, never the body** — the model's own words:
*"only the skill's locator, not its body, was placed in context."* Nothing from
`SKILL.md` arrives until the model reads the file itself, and **a skill's `!` shell
preload is never expanded.** 16 of the 18 skills present when this was measured depend
on that preload for their state input — 17 of 19 as the tree stands now; the ratio is
what matters, not the snapshot.

Two viable answers were measured, and neither requires generated per-harness files:

1. **Single-source, model-driven (validated).** One added sentence directing the model
   to *substitute and run* the preload itself worked end to end: it resolved the skill
   dir from the path it had just read and acted on the result. The sentence must direct
   **substitution**, not verbatim execution — running the line as written yields an
   empty prefix and a file-not-found, which looks at a glance like the sentence
   failing. Reverted after measurement; the finding is the deliverable.
2. **Hook-side injection (validated end to end).** A `PreToolUse:Bash` handler reads the
   skill's identity from `tool_input.command` — the model reads `SKILL.md` *with a
   shell command*, so the path arrives in a payload — runs that skill's own preload, and
   injects the result. Proven falsifiable: a `uuid4` marker minted in-hook and never
   placed in the prompt came back byte-identical, while the suppressed-injection control
   answered NO; and the model quoted real seeded ids from 477 injected bytes.

**If injection is adopted, six requirements were each found the hard way and each fails
quietly** — exit 0, no error, an injection that looks successful: run the preload in the
*session's* cwd (not the skill dir, or it resolves a different project's state); run the
command the skill's own `!` line names (14 of 16 say `scripts/preload.sh`, so a
hardcoded filename is right on 14 and **wrong on 2** — one takes `--consume-gate`, one is
`check_session_needs.sh`, and one of the two is the most-used skill); claim
once-per-skill **atomically and before the run** (four parallel
firings all read the marker absent and all ran); require a heartbeat first; constrain
the resolved **file** under the plugin root, not just the directory (a `..` segment
normalises back inside, and a symlinked `SKILL.md` points wherever the link says — both
measured executing an arbitrary `!` line while the directory check reported safe); and
**do not treat a path mention as an invocation** — a `wc -c` on a skill file consumed a
gate, injected, and claimed the once-marker, so the genuine read that followed received
nothing while idempotence reported working.

**The main risk in the injection route:** the handle depends on the model reading
`SKILL.md` *through a shell command*. If Codex ever delivers bodies without a shell
read, `PreToolUse:Bash` stops carrying the identity and the mechanism stops firing —
silently, because "no marker" and "no injection" look identical.

**Cost of the in-body alternative, measured from its own reverted commit:** +227 bytes
per skill × 16 = 3,632 bytes, and **6 of 16 would breach their recorded per-skill byte
cap**. The binding cost is budgets, not bytes.

---

## Not observed, with reasons

Listed because silent omission reads as covered.

| Item | Why not |
|---|---|
| **The minimum Codex version** | Only 0.146.0 was ever installed; no older build obtained. A floor cannot be inferred from one passing version. |
| **Whether the heartbeat DISTINGUISHES hooks-live from hooks-absent** | Only the not-live arm is evidence. The untrusted control ran on its own scratch root with no sibling heartbeat, so it reads not-live whether or not the marker discriminates anything — a mechanism hardwired to not-live would pass that test. No trusted run exercised the in-session liveness read, and R2 shows the read is broken anyway. Concern `31e942bc97b0`. |
| **Whether `allowed-tools` is HONOURED** | Not readable from the loader channel. Codex documenting the key means it may be *enforcing* a tool restriction on our skills — a behaviour change, not a no-op. Needs a model-in-the-loop tool-list check. |
| **`SessionEnd` timeout units** | Cap-regardless and read-as-seconds are both consistent with the observation; these two entries are the only `timeout` values in the file. |
| **Whether `additionalContextLimit: 0` caps or is ignored** | 477 bytes reached the model through an entry set to 0. Whether 0 means unlimited or the field is ignored is unsettled; a shipped version should set it deliberately rather than inherit a recorder's value. |
| **Whether `ultra` delegates under load** | The prompt was "reply ok" — nothing to delegate — and the session ran `collaboration_mode: default`. |
| **Whether luna truly reasons at `ultra`** | It accepts the unadvertised value and answers; the rollout records the request, not the effect. The one cheap signal (`reasoning_output_tokens`) is n=1 and points the other way. |
| **Whether `SubagentStart` `additionalContext` reaches a Codex subagent** | The hook fires and the event is not on the six-event no-context list, but delivery was never measured. Load-bearing: `RETRO_INPUT` and `CURATION_INPUT` reach the retrospective and housekeeper agents *only* this way. Separately, the routing that would select what to inject is measured broken — `agent_type` is always `'default'`. |
| **`PermissionRequest`** | Never observed firing in any run. Gap #23 proposes it as the interceptor for skill activation; on this evidence that route is doubly dead, since `skill_approval` also gates nothing and headless teammates run `--ask-for-approval never`. |
| **Sequential-discipline compliance** | Behaviour was consistent with the note, but no run deliberately tempted a batch. |
| **Whether Codex ignores `disable-model-invocation`** | Reported upstream, never measured here — and Codex's own embedded guidance documents the key, which contradicts the report. Recorded as a conflict rather than a finding. See R4. |
| **A successful commit under `workspace-write`** | `.git` is read-only there, so a commit fails *after* the gate allows it. Gate decisions stay observable; demonstrating a landed commit needs a wider sandbox. |
| **`danger-full-access`** | Never tried — least privilege sufficed, so the escalation was never needed. |

---

## Corrections applied to the plan doc

Every claim below was corrected **in place** in `docs/ideas/8-CODEX_DUAL_TARGET_PLAN.md`
rather than only contradicted here — a later milestone reads that doc and would
otherwise trust a falsified claim. The marker there is `**Measured 2026-08-05 (P0
spike):**`, matching the doc's own existing convention. **Severity cells moved with the
bodies**, so a reader scanning severities is not misled by a row whose text now says
the opposite.

### Falsified — the stated resolution cannot be implemented

| Gap | What the doc said | What was measured |
|---|---|---|
| **#3** | Fold failure detection into `PostToolUse`, keyed on exit status | A failed tool call fires **no `PostToolUse` at all**. Nothing to key on; needs a new design |
| **#11** | "The feared hole appears not to exist as described" (**Low**) | The hole is real, by an undocumented mechanism. `--disable unified_exec` becomes mandatory config |
| **#14** | A marketplace `agents` field would let plugins ship subagents | No such key exists; accepted and silently ignored |
| **#31** | `stop_hook_active` has "no known analogue" (**Blocker**) | Present **and functional** — the Blocker dissolves and the P1 decoupling is unnecessary for Codex |
| **#28** | `skill_approval: false` silently auto-rejects (**Medium**) | Gates nothing in either direction, and it is not the top-level boolean assumed |
| **#25** | Codex SKILL.md supports only `name`/`description`; rejection would be a blocker | Three of four extra keys are **documented Codex fields**; nothing is rejected |
| **#27** | Two Codex surfaces disagree, so model a per-surface dimension | The catalog is authoritative; there is no surface split. The CLI list was the drifted one |
| **#12**, tier axis | Codex has `minimal`, lacks `max`; axis is `minimal…max` | Wrong at both ends. No `minimal`; `max` and `ultra` both real. Axis is `low…ultra` |
| Effort key | `effort_support` keyed per **model** | Must be keyed per **tier** — and that changes the **Claude** row too |
| `-e` shorthand | "Codex also accepts a `-e <effort>` shorthand" | No `-e`/`--effort` flag exists. Only `-m` |
| Subagent models | `gpt-5.6`, `gpt-5.4`, `gpt-5.6-terra`, `gpt-5.3-codex-spark` | Two of four are not in the live catalog; one of the rest is hidden |

### Confirmed, and sharpened

| Gap | Refinement |
|---|---|
| **#2** | `apply_patch` confirmed — and `Edit`/`Write`/`MultiEdit` are **dead names**; `Bash` exists only by normalisation |
| **#18** | Untrusted hooks are skipped silently — **confirmed**; but the prescribed mitigation is **broken on Codex** |
| **#20** | Explicit `hooks` path **replaces** discovery; unknown events silently ignored, so the variant is tidy, not mandatory |
| **#32** | `SubagentStart`/`Stop` **do** fire — but `agent_type` is always `'default'`, so identical naming will not fix routing |
| **#6** | The deadlock is real and the prescribed CLI leg is right; the *framing* needed correcting — Codex can ask, in chat |
| **#9a** | Least privilege suffices; `danger-full-access` never needed |
| **#26** | Control works, risk is real (observed firing `/xp-kickoff`) — but it now conflicts with this sprint's own sidecar ban |
| **#23** | The `PermissionRequest` route is doubly dead; the in-skill check is the only option |
| **#19** | One working version established; **the floor is not** |
| **#1** | Both marker paths are dead: skills are not tool calls, *and* the spawn tool's stripped name never matches the `Agent` matcher. `SubagentStart`/`Stop` fire, but `agent_type` is `'default'`, so the keyed routing selects nothing. The explicit CLI leg is mandatory, not belt-and-braces |
| **#4** | An `async: true` handler on `SessionEnd` **runs synchronously**, so compaction needs no third trigger — but a new open item replaces it: the 3s `SessionEnd` timeout clamp, units unresolved |
| **#15** | Confirmed and **raised from Low**: `plugin_version()` misreports the Claude manifest on Codex *today*, not at Phase 2 |

### Structural

- **Payload compatibility surface: 14 fields → 15.** `session_id` was omitted and
  shipped code reads it in four places. The `Codex status` column is now *observed*
  rather than *documented*.
- **`HARNESSES["codex"]`**: both `PLACEHOLDER — P0` holes filled; zero placeholder
  markers remain in the document.
- **Open questions 1, 2, 5, 7 and 8 answered**; 6 answered in half. **A ninth was
  added** — how skill bodies and preloads reach a Codex model, the largest open design
  question the spike surfaced.
- **Phase 0 checklist ticked**: 19 observed, 3 partly observed, 1 not observed. The
  three that are not a clean tick are called out above the list, so a reader scanning
  ticks cannot miss them.
- **Research summary** (top of the doc): the stale `stop_hook_active`-is-absent premise,
  the 14-field count, and the "only `name`/`description`" frontmatter claim are struck
  where the spike falsified them.
- **Risks**: the gap #11 row's likelihood was wrong and its mitigation is now mandatory
  config; the silent-non-enforcement row has **no working mitigation** until R2 lands;
  the gate-compliance row is measured and did not occur; **one new risk added** — a
  retry policy mistaking an unsupported pair for a flaky connection.

## Rig disposal

The spike rig — `plugins/xp-agents/spike/`, `hooks/hooks.codex.json`,
`.codex-plugin/plugin.json` — is **throwaway by construction** and deleting it is
**sprint close's obligation**, per the customer decision recorded in commit
`c4865f38`: the rig lives on the sprint branch through this story and is deleted once
at close, rather than being restored and re-deleted per story.

story-007 guarantees only what it can: **its own diff carries no rig file.** The
original AC ("only the findings doc and the plan-doc corrections merge") was amended
this session because it became unsatisfiable when stories 011-016 joined the sprint —
`main...sprint-004` carries 21 committed `spike/` files *and* three shipped-code fix
stories that are meant to merge.

A counter-argument was put by an external reviewer and is recorded rather than buried:
a findings document ages the moment Codex changes, whereas a durable conformance rig
plus sanitized payload fixtures would stay *checkable*. That case is sound. The
customer reaffirmed throwaway. If the rig proves worth having, a later milestone builds
a supported version deliberately — it should not be inherited by accident from a spike.

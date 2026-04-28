# Deterministic Event Emission Doctrine

## Purpose

Replace the **non-deterministic event cycle** — where skills/agents emit
status events with LLM-authored content that downstream code regex-parses
to count or trigger — with a **deterministic event cycle** — where hooks
emit canonical events carrying `metadata.action` discriminators that
consumers match exactly.

This doctrine is plugin-internal: it governs how the event log
(`events.jsonl`) is written and read across `scripts/`, `skills/`, and
`agents/`. It applies to every project the plugin runs in.

---

## The Problem

Today, several skill and subagent prompts instruct the LLM to record
lifecycle events via `append.sh`, with prescribed content phrasings the
LLM is supposed to follow. Downstream code then **regex-matches the
content string** to determine whether the event represents a specific
lifecycle moment ("did a quality review run?", "did a security check
happen?", "did tests pass?").

This pattern is fragile. The LLM has free-form latitude in content; over
time, agents drift to phrasings the regex doesn't match. Counts go
silently wrong. Metrics regress. Retros generate false-positive Fix items
based on bad counts.

### Confirmed bug class

`docs/ideas/retro-quality-review-counting.md` reports the canonical
example: `_common.QUALITY_REVIEW_RE = "(?:Quality review|QR) complete"`
is supposed to match QR completion events; the QR agent actually emits
content like `"Quality review clean"`, `"B1 review clean"`,
`"C1 verified"`, free-form review-summary text. Result:
`status_summary.quality_reviews=0` despite many QRs running. **13+
sprints of false-positive "0% adoption" Fix items** before the bug was
diagnosed.

The same pattern applies to `SECURITY_CHECK_RE`, `TEST_RUN_RE`,
`_FILE_WRITE_RE`, `_LINT_RE`, `LEGACY_COMMIT_RE` — every regex in
`scripts/_common.py` and `scripts/retro_metrics.py` that scans event
content for a lifecycle signal.

### The architectural fix already exists, partially

`smm/event_schema.py:79-82` already establishes the canonical
replacement pattern:

```python
# Status event metadata.action discriminators — used by cascading gates
# to identify specific lifecycle events without scanning content strings.
STATUS_ACTION_ITERATION_COMPLETE = "iteration_complete"
STATUS_ACTION_SPRINT_RETRO_DONE = "sprint_retro_done"
```

These are written by hooks (deterministic), read via
`event.metadata.action == "..."` (exact match). No regex, no drift, no
false negatives. **Extend this pattern to cover every lifecycle moment
currently detected by content regex.**

---

## Audit: every site that needs change

### A. Producer sites — where events are currently emitted

#### A1. Skill SKILL.md files instructing LLM to emit events

| File:line | Skill | Prescribed content | Drives metric? |
|-----------|-------|-------------------|----------------|
| `skills/xp-quality-review/SKILL.md:89` | xp-quality-review | `"Quality review complete. Fixed: [...]. Debt: [...]. Clean: [...]"` | YES — `quality_reviews` counter |
| `skills/xp-quality-review/SKILL.md:63` | xp-quality-review | `"Resolved: [what was addressed]"` | NO |
| `agents/xp-security-reviewer.md:37` | xp-security-reviewer | `"Security review complete: <summary>"` | YES — `security_checks`, `commits_without_security_check` |
| `skills/xp-assign/SKILL.md:89` | xp-assign | `"Execution mode: <Solo\|CLI teammates>"` | NO |
| `skills/xp-kickoff/SKILL.md:45` | xp-kickoff | `"Free session"` / `"Sprint session: <sprint-id>"` | NO (goal event) |
| `skills/xp-accept/SKILL.md:127` | xp-accept | `"Story story-NNN marked <done\|deferred>"` | NO |
| `skills/xp-plan/SKILL.md:158` | xp-plan | `"Created execution_plan.json with N milestones"` | NO |

**Action:** for the YES rows, **remove the `append.sh` instruction
entirely** — the hook will emit the canonical event. For the NO rows,
keep the LLM-authored event but treat content as informational only;
no consumer should regex-parse it.

#### A2. Hook-emitted events that are deterministic but lack `metadata.action`

| File:line | Hook | Content emitted | Has action? |
|-----------|------|----------------|-------------|
| `scripts/review_cycle_done.py:96-102` | PostToolUse:Skill (security-review) | `"Security review complete — full review performed"` | NO |
| `skills/xp-security-triage/scripts/mark_triaged.py:42-48` | preload | `"Security triage started — reviewing staged changes"` | NO |
| `scripts/post_tool_use.py:62` | PostToolUse:Write\|Edit | `"Wrote to {path}"` | NO |
| `scripts/bash_post_tool.py:375-378` | PostToolUse:Bash (tests) | `"Tests: {N} passed, {M} failed ({framework})"` | NO |
| `scripts/bash_post_tool.py` | PostToolUse:Bash (lint) | `"Lint concern resolved on commit"` | NO |
| `scripts/bash_failure.py:56-62` | PostToolUseFailure:Bash | `"Bash failure: {command}"` / `"Bash failed (exit {code})"` | NO |
| `scripts/subagent_stop.py:154` | SubagentStop (non-xp) | `"Subagent {agent_id} completed"` | NO |
| `scripts/subagent_stop.py:72` | SubagentStop (housekeeper) | `"Kickoff complete — housekeeping subagent finished."` | NO |
| `scripts/subagent_stop.py:101-113` | SubagentStop (sprint-reviewer) | sprint event, type=`sprint`, action=`end` | YES (sprint event already structured) |
| `scripts/subagent_stop.py:134-140` | SubagentStop (plan-reviewer) | `"assign_pending: Plan reviewed, run /xp-assign"` | NO |
| `scripts/subagent_stop.py:208-214` | SubagentStop (Plan agent) | `"plan_awaiting_review: Plan completed, run /xp-review-plan"` | NO |
| `scripts/save_retrospective.py:85` | save_retrospective | retrospective event | YES (action=session_done\|sprint_done) |

**Action:** add `metadata.action` to every NO row. Existing content can
stay (it's user-readable digest material); consumers stop regex-matching
it.

#### A3. Hook firing points that currently emit no event

| Hook | Fires when | Should emit? |
|------|-----------|--------------|
| PostToolUse:Skill (`review_cycle_done.py`) when target is `/simplify` | /simplify completes | YES — `simplify_complete` |
| PostToolUse:Skill when target is `/xp-quality-review` | QR skill completes | YES — `qr_complete` |
| PostToolUse:Skill when target is `/xp-security-triage` | triage skill completes | YES — `security_triage_complete` (vs current "started") |
| PostToolUse:Skill when target is `/xp-review-plan` | plan review completes | YES — `plan_reviewed` |
| PostToolUse:Skill when target is `xp-housekeeper` agent | housekeeping completes | YES — `housekeeping_complete` (current "Kickoff complete" content stays) |
| SubagentStop for xp-* subagents | xp-code-reviewer / xp-close-reviewer / xp-security-reviewer / xp-retrospective / xp-system-analyzer / xp-housekeeper / xp-sprint-reviewer / xp-plan-reviewer complete | YES — `subagent_complete` for ALL (currently skipped at line 181-182) |
| PostToolUse:ExitPlanMode (`post_tool_exit_plan.py`) | Plan mode exits | YES — `plan_exited` |
| TaskCompleted | Task done | OPTIONAL — `task_completed` (TBD if any consumer) |
| WorktreeCreate | Worktree created | LOW PRIORITY |

### B. Consumer sites — code that currently regex-parses content

| File:line | Consumer | Currently regex | Replacement |
|-----------|----------|-----------------|-------------|
| `scripts/_common.py:91` | `TEST_RUN_RE` | `r"Tests?(?::.*\d+\s+passed\|...)"` | DELETE; consumers check `metadata.action == "test_run_complete"` |
| `scripts/_common.py:92` | `LEGACY_COMMIT_RE` | `r"^Committed:"` | DELETE if dead (commits are typed events); else keep with deprecation note |
| `scripts/_common.py:93-95` | `SECURITY_CHECK_RE` | `r"Security (?:triage\|review) (?:complete\|started)"` | DELETE; check `metadata.action ∈ {security_complete, security_triage_complete, security_triage_started}` |
| `scripts/_common.py:96` | `QUALITY_REVIEW_RE` | `r"(?:Quality review\|QR) complete"` | DELETE; check `metadata.action == "qr_complete"` |
| `scripts/retro_metrics.py:43` | `_FILE_WRITE_RE` | `r"Wrote to\b"` | DELETE; check `metadata.action == "file_write"` |
| `scripts/retro_metrics.py:48` | `_LINT_RE` | `r"Lint (?:errors? in\|concern resolved)"` | DELETE; check `metadata.action == "lint_resolved"` |
| `scripts/retro_metrics.py:73-78` | `_classify_status_events` patterns table | regex dispatch | rewrite as `_match_skill_event(event)` checking `metadata.action` |
| `scripts/honesty_signals.py:20-25` | `_FILE_WRITE_RE`, `_TEST_RUN_RE`, `_SECURITY_CHECK_RE`, `_PLAN_RE`, `_REFACTOR_MODE_RE` | regex on content | switch to `metadata.action` checks |
| `scripts/honesty_signals.py:73` | `path = content.replace("Wrote to ", "").strip()` | string parsing | read `metadata.files[0]` |
| `scripts/bash_post_tool.py:214` | `_common.QUALITY_REVIEW_RE.search(content)` | regex search | check `metadata.action == "qr_complete"` |
| `scripts/work_signals.py:18,20,77` | `_TEST_RUN_RE`, `_COMMIT_RE` | regex | switch to `metadata.action` |
| `scripts/concerns.py:39,46` | `TEST_CONCERN_RE`, `_SUPERSEDED_TOPIC_RE` | content match | review case-by-case (concern content IS LLM-authored) |

### C. Skill / agent prompt changes

Remove from prompts the instruction to emit lifecycle events that the
hook now emits. Specifically:

| File | Instruction to remove |
|------|----------------------|
| `skills/xp-quality-review/SKILL.md:89` | The `append.sh --type status --content "Quality review complete..."` block |
| `agents/xp-security-reviewer.md:37` | The `append.sh --content "Security review complete..."` block |

Keep judgment-text emissions (concern, decision, debt, retro Try, retro
Keep/Fix bullets) — those are LLM judgment, not lifecycle signals.

### D. Tests that lock in content phrasings

| File:line | Test | Asserted phrasing |
|-----------|------|-------------------|
| `tests/hooks/test_bash_commit.py:449` | TestQrWarning seeds | `"Quality review complete"` |
| `tests/hooks/test_bash_commit.py:485,490,498` | TestQrWarning asserts | `assertIn("quality review", ...)` |
| `tests/hooks/test_sprint_start.py:181,193` | TestSaveRetro | `"Sprint complete"` |
| `tests/hooks/test_subagent.py:387` | TestSubagentStop | `"Kickoff complete"` |
| `tests/hooks/test_review_cycle.py:67-77` | test_security_review_records_review_complete | `"Security review complete"` content match |

**Action:** rewrite each to seed/assert on `metadata.action` instead of
content. Content stays as readable digest, but tests no longer lock the
regex contract.

---

## Proposed action vocabulary

Add to `smm/event_schema.py` alongside the existing
`STATUS_ACTION_ITERATION_COMPLETE` and `STATUS_ACTION_SPRINT_RETRO_DONE`:

### Review cycle actions
- `STATUS_ACTION_SIMPLIFY_COMPLETE = "simplify_complete"`
- `STATUS_ACTION_QR_COMPLETE = "qr_complete"`
- `STATUS_ACTION_SECURITY_COMPLETE = "security_complete"`
- `STATUS_ACTION_SECURITY_TRIAGE_STARTED = "security_triage_started"`
- `STATUS_ACTION_SECURITY_TRIAGE_COMPLETE = "security_triage_complete"`
- `STATUS_ACTION_PLAN_REVIEWED = "plan_reviewed"`
- `STATUS_ACTION_HOUSEKEEPING_COMPLETE = "housekeeping_complete"`

### Subagent actions
- `STATUS_ACTION_SUBAGENT_COMPLETE = "subagent_complete"` — emitted for
  every subagent (xp-* and external) on SubagentStop. Companion metadata:
  `metadata.agent_type` (e.g. `"xp-code-reviewer"`).

### Tool action discriminators
- `STATUS_ACTION_FILE_WRITE = "file_write"` — companion: `metadata.files=[path]`
- `STATUS_ACTION_TEST_RUN_COMPLETE = "test_run_complete"` — companion: `metadata.test_passed: bool`, `metadata.test_count: int`, `metadata.framework: str`
- `STATUS_ACTION_LINT_RESOLVED = "lint_resolved"`
- `STATUS_ACTION_BASH_FAILED = "bash_failed"` — companion: `metadata.exit_code: int`
- `STATUS_ACTION_PLAN_EXITED = "plan_exited"`

### Existing (don't change)
- `STATUS_ACTION_ITERATION_COMPLETE` — already defined
- `STATUS_ACTION_SPRINT_RETRO_DONE` — already defined
- `STATUS_CONTENT_RESOLVES_PROBE` — already defined; uses content discriminator pattern (acceptable because `metadata.probe_candidates` carries the structured payload)
- `RETRO_ACTION_SESSION_DONE`, `RETRO_ACTION_SPRINT_DONE` — already on retrospective events
- `SPRINT_ACTION_START`, `SPRINT_ACTION_END` — already on sprint events

---

## Phasing

The full audit covers ~15 files and 8-10 commits. Phase to keep each
sprint shippable.

### Milestone 1 — Vocabulary and review cycle (3-4 commits)

Establishes the pattern; fixes the active QR + security counting bug.

1. Add all `STATUS_ACTION_*` constants to `event_schema.py`.
2. `review_cycle_done.py`: emit canonical events for simplify, QR,
   security-review, security-triage-complete, plan-reviewed,
   housekeeping-complete with `metadata.action`. Remove the dispatch
   from agent prompts.
3. `mark_triaged.py`: add `metadata.action="security_triage_started"`.
4. `retro_metrics._classify_status_events`: switch QR + security +
   simplify counters to `metadata.action`. Add `simplifies` counter.
5. `bash_post_tool.py:214`: switch QR-since-last-commit check to
   `metadata.action`.
6. Drop `QUALITY_REVIEW_RE` and `SECURITY_CHECK_RE` from `_common.py`.
7. Update `skills/xp-quality-review/SKILL.md`: remove the prescribed
   `"Quality review complete. Fixed: ..."` emission. The hook handles it.
8. Update `agents/xp-security-reviewer.md`: remove prescribed
   `"Security review complete..."` emission.
9. Update tests in `test_bash_commit.py`, `test_review_cycle.py` to seed
   `metadata.action` instead of content strings.

### Milestone 2 — Tool actions (2-3 commits)

10. `post_tool_use.py`: add `metadata.action="file_write"` and
    `metadata.files=[path]`.
11. `bash_post_tool.py`: add `metadata.action ∈ {test_run_complete,
    lint_resolved}` with structured companion metadata.
12. `bash_failure.py`: add `metadata.action="bash_failed"` +
    `metadata.exit_code`.
13. Update consumers: `honesty_signals` reads `metadata.files` instead
    of parsing `"Wrote to ..."`; `_FILE_WRITE_RE`, `_TEST_RUN_RE`,
    `_LINT_RE` deleted from `_common.py` and `retro_metrics.py`.
14. Update tests asserting `"Wrote to ..."` content.

### Milestone 3 — Subagent + plan lifecycle (2-3 commits)

15. `subagent_stop.py`: emit `metadata.action="subagent_complete"` for
    ALL subagent types (currently skipped for xp-*); content can stay
    `"Subagent X completed"` for human readability.
16. `subagent_stop.py`: add `metadata.action ∈ {plan_completed,
    plan_awaiting_review}` to existing emissions.
17. `post_tool_exit_plan.py`: emit `metadata.action="plan_exited"`.
18. Update any consumers of subagent completion (none currently
    regex-match, but add a smoke test for canonical action).

---

## Acceptance criteria

1. **Every regex in `_common.py` that scans content for a lifecycle
   signal is either deleted or has a deprecation note pointing at the
   `metadata.action` replacement.** No new code path adds a content
   regex for a lifecycle event.
2. **Every hook firing point in the audit Section A2/A3 emits an event
   with `metadata.action` set.** Verified by a smoke test that triggers
   the hook and asserts `event.metadata.action == "<expected>"`.
3. **No SKILL.md or agent.md prompt instructs the LLM to emit a
   lifecycle event the hook now emits.** Verified by grep for
   prescribed `"X complete"` content.
4. **Forward retro counts non-zero when the corresponding skill ran.**
   Verified by triggering /simplify, /xp-quality-review,
   /xp-security-triage in a session and asserting
   `status_summary.{simplifies, quality_reviews, security_checks} ≥ 1`.
5. **The user-reported bug from `retro-quality-review-counting.md`
   stops appearing** when QR runs are detected. Future-session retro
   runs against the same SMM no longer emit
   `"quality_reviews_missing"` flag for sprints with QR runs.
6. **Test suite stays green throughout.** Each commit follows the full
   review cycle (`/simplify` → `/xp-quality-review` →
   `/xp-security-triage` → commit) per project convention.
7. **`event_schema.py` action vocabulary is documented inline** with
   a comment block listing every action constant and its emitting hook.

---

## Out of scope

- Backfilling historical `events.jsonl` with `metadata.action` values.
  Forward-only fix; old retros stay wrong (sunk cost).
- Re-emitting events from skills that **don't** currently drive a
  metric (e.g., `/xp-assign` execution-mode status events). Those can
  stay LLM-authored as long as no consumer regex-parses them.
- Concern, decision, debt, retro-Try content — genuine LLM judgment.
- Refactor-mode declaration via assumption events
  (`honesty_signals._REFACTOR_MODE_RE`). The assumption is genuinely
  user-authored; converting it requires a UX change (a dedicated
  declaration step instead of free-text assumption). Defer.
- `STATUS_CONTENT_RESOLVES_PROBE` — already uses
  `metadata.probe_candidates` for the structured payload; content
  prefix is fine as a UI hint.

---

## Agent_id semantics (ADR — sprint-042)

**Rule.** On every hook-emitted event, `agent_id` is the teammate-resolved
attribution (the actor who triggered the lifecycle moment). Skill or agent
identity lives in `metadata.action`, not in `agent_id`. No producer encodes
a skill name into `agent_id`.

**Implementation.** Every hook producer (`post_tool_use.py`,
`bash_post_tool.py`, `bash_failure.py`, `subagent_stop.py`, the commit
emission in `_handle_commit`) already passes the resolved `agent_id` from
`identity.resolve_agent_id`. `review_cycle_done.py` and `mark_triaged.py`
were the lone deviations pre-sprint-042: both encoded skill-name strings
(`"simplify"`, `"xp-quality-review"`, `"xp-security-triage"`, …) into
`agent_id`. Sprint-042 removes the third tuple element from
`_TARGET_LIFECYCLE` and switches `mark_triaged` to use
`identity.resolve_agent_id_from_cwd(...)` so the rule holds uniformly.

**Rationale.** Per-agent retro counters in
`retro_metrics._compute_session_stats` and `_compute_resolves_link_rate`,
plus probe-pairing in `_compute_probe_adoption`, all bucket events by
`agent_id` to attribute work to the teammate who did it. With skill names
in `agent_id`, those rollups mis-attributed review-cycle events to
phantom "agents" named after skills. Skill identity is already cleanly
available via the `metadata.action` discriminator — `"qr_complete"`,
`"simplify_complete"`, etc. — so consumers that want "QR ran 5 times"
filter on action; consumers that want "teammate-7 ran 3 reviews" filter
on `agent_id`. One source of truth per question.

**Resolves:** concern `389ba9e9681d`.

---

## Risks and mitigations

| Risk | Mitigation |
|------|-----------|
| Tests assert specific content strings; refactor breaks them | Update tests in same commit as the producer change. Tests are production code. |
| Hook fires multiple times per logical event (e.g., `/xp-quality-review` invoked twice in one cycle) | Counter behavior already idempotent at the per-event level; double-invocation = 2 counted. Acceptable. |
| Plugin marketplace cache holds old version during dev | Plugin runs from cache; dev edits don't take effect until next publish. Note in commit messages; verify against published version when possible. |
| `metadata.action` value drift between producer and consumer | Centralize all action values in `event_schema.py` constants. Producer + consumer import from same module. |
| Existing events without `metadata.action` need handling during transition | Consumers MUST treat absent `metadata.action` as legacy; either ignore or fall back to existing regex during a deprecation window. Drop fallback at end of Milestone 3. |

---

## References

- `docs/ideas/retro-quality-review-counting.md` — the canonical bug
  report that motivated this doctrine.
- `smm/event_schema.py:79-82` — the existing
  `STATUS_ACTION_ITERATION_COMPLETE` pattern to extend.
- `smm/event_schema.py:114-117` — the
  `RETRO_ACTION_SESSION_DONE`/`SPRINT_DONE` precedent for
  type-discriminating action values.
- `scripts/save_retrospective.py:85` — example of correct
  `metadata.action` use on a producer.
- `scripts/retrospective.py:95` — example of correct `metadata.action`
  read on a consumer.

# Security Review Doctrine

## Purpose

Define **when** the plugin runs security review, **what kind of review
runs at each tier**, and how the tiers cooperate to catch vulnerabilities
without paying for an LLM call on every commit.

This doctrine is plugin-internal: it governs how `pre_tool_bash`, the
close skills, and `/security-review` coordinate across a codebase's
life. It applies to every project the plugin runs in, without
per-project configuration.

---

## Principle

**Security review fires at the boundary that catches the most for the
least.** Different boundaries catch different classes of issue, so the
plugin layers two tiers:

- **Per-commit:** deterministic checks only. Fast, blocking, near-zero
  false positive rate on the patterns they target. The right tool for
  "stop this commit if it contains a literal secret."
- **Per-close:** LLM review against the cumulative branch diff at every
  close (sprint, plan, free). The right tool for catching cross-story
  attack patterns and providing a final security gate before code lands
  on a protected branch. Story-close defers to its enclosing close —
  every `/xp-story-close` invocation is dispatched by `/xp-accept`
  inside an active sprint, so the sprint-close cumulative review
  already covers each merged story.

The trade-off this accepts: a vulnerability introduced in commit-1 of a
multi-commit story isn't surfaced until close (potentially hours, not
minutes). For non-prod-credential codebases that's acceptable. **Projects
with prod credentials in scope already need out-of-band controls**
(gitleaks pre-commit, secret-scanning CI, branch-protection rules) — the
plugin's job is not to be the only line of defense.

This doctrine deliberately does **not** ship a per-project override
knob. Projects with stronger needs add their own tooling on top.

---

## The Two Tiers

### Tier 1 — Deterministic Pre-Commit (every code commit)

**Where:** `PreToolUse:Bash` hook (`scripts/pre_tool_bash.py` plus
`scripts/security_patterns.py`). Runs before every `git commit`
invocation.

**What:** A static set of high-confidence regex/AST patterns. Each
pattern targets a class of issue with near-zero false positive rate
in this codebase's idiom:

- **Secret literals** — API keys, AWS access keys, GitHub tokens,
  private keys (PEM headers), high-entropy strings in obvious key/value
  shapes (e.g. `password = "..."`).
- **Shell injection** — `subprocess.*shell=True` with f-string or `+`
  concatenation against a non-literal. Direct `os.system` calls. Use of
  the `eval` and `exec` builtins against non-literal input.
- **Hardcoded credentials in URLs** — basic-auth literals embedded in
  HTTPS URLs (the `scheme://USER:PASS@host` form).

**Behavior:** Blocks the commit on detection (exit 2 + stderr message).
Patterns are tight enough that a hit is almost always real; false
positives suppress with explicit `# noqa: secret` markers per-line.

**Cost:** Sub-millisecond. Pure Python regex.

**Out of scope for Tier 1:** anything requiring semantic analysis (SQL
injection, XSS, deserialization). Those are Tier 2/3's job. Commit-
message content (passed via `git commit -F file` or HEREDOC) is also
out of Tier 1 scope — Tier 1 scans the staged diff only, not commit
metadata.

### Tier 2 — `/security-review` at Every Close (sprint, plan, free)

**Where:** `/xp-{sprint,plan,free}-close` Step 4 (shared template at
`scripts/_close_pipeline_shared.md`). Fires unconditionally for these
three close modes.

**What:** Invokes `Skill(skill: "security-review", args: "the cumulative
diff on branch <branch> since merge-base with <target>")` against the
cumulative diff at the close boundary:

- **Sprint close:** all story diffs combined, vs the sprint base.
  Catches cross-story attack patterns (commit A in story-001 + commit
  B in story-003).
- **Plan close:** all sprint merges combined, vs the primary branch.
  Catches cross-sprint patterns and architectural drift.
- **Free close:** the free branch diff vs primary.

**Behavior:** Block findings file `concern --severity high` events;
Concern findings file `concern --severity medium` events. Both event
kinds include `metadata.kind=security` and the close-cycle id for
filtering. Block findings cause the close skill's merge-confirmation
prompt to default to "Abort — fix concerns first"; the user can still
override but the warning is loud.

**Critical separation of concerns:** Tier 2 findings do NOT flow to
`xp-close-reviewer` (the quality reviewer agent). Security and quality
are independent review streams that converge only at the Step 6
abort-default count. The close-reviewer is quality-only across all
modes (XP value lenses, simplify accountability, drift, debt, regression
risk in unmodified stories).

**Cost:** One LLM call per close. Negligible compared to a
per-commit-LLM baseline.

---

## Findings Recording

All Tier 2 findings file SMM `concern` events with:

- `severity`: `high` (Block) or `medium` (Concern)
- `files`: paths the reviewer pointed at
- `metadata.kind`: `"security"` (distinguishes from quality concerns)
- `metadata.close_cycle_id`: the close-cycle id (for deterministic
  filtering at the abort-default count)
- `metadata.close_mode`: `"free"` / `"sprint"` / `"plan"`

The events live in the SMM and surface at next session's kickoff for
triage. Resolved findings auto-link to fix commits via the
`Resolves-Event:` trailer just like any other concern.

---

## Manual `/security-review` Invocation

Users invoke `/security-review` directly any time — mid-flight checks,
ad-hoc audits, paranoia. It's the same built-in Claude Code command the
tiered automation forwards to. There is no plugin wrapper skill or
agent for this — the cutover history that removed the prior wrapper is
preserved in `docs/completed/SECURITY_REVIEW_MIGRATION.md`.

Manual invocations don't write any markers and don't route findings
through the close-cycle counter — they're informational, surfaced as the
reviewer's prose output back to the user.

---

## Trade-offs Accepted

**Time-to-detection drift.** A vulnerability introduced in commit 1 of a
4-commit story isn't surfaced until close (Tier 2). For typical session
cadence that's hours, not minutes. **Mitigation:** Tier 1 catches the
highest-stakes class (literal secrets) at commit time. Multi-step
vulnerabilities by definition don't manifest as a single commit anyway.

**Tier 1 false positives.** High-confidence regex patterns will still
occasionally fire on test fixtures or example strings. **Mitigation:**
explicit `# noqa: secret`-style suppression markers per-line.

**Tier 2 blocks merge.** Block findings default the close
confirmation to "Abort." This slows merges when the finding is
contentious. **Mitigation:** the user can override the default at the
prompt; the recorded `severity=high` concern carries forward to the
next kickoff for follow-up.

**Close-reviewer fix-cycle skips re-review.** Quality-reviewer findings
that produce fix-commits ship without re-running `/security-review`.
Quality findings rarely overlap security-relevant code; the next
plan-level close catches anything that slips. Adding a re-review on
fix-cycle commits would mostly defeat the per-close cost model.

---

## How Skills Use This Doctrine

- **`pre_tool_bash.py`** — runs Tier 1 deterministic patterns from
  `security_patterns.py` on every Bash `git commit` invocation.
- **`/xp-sprint-close`**, **`/xp-plan-close`**, **`/xp-free-close`** —
  all fire Tier 2 `/security-review` at Step 4 unconditionally.
- **`/xp-story-close`** — never fires `/security-review`. Story-close is
  always dispatched by `/xp-accept` inside an active sprint, so the
  enclosing sprint-close cumulative review covers each merged story.
- **`xp-close-reviewer`** — quality-only across all modes; never sees
  security findings (separation of concerns).

---

## Implementation References

| Concern | File |
|---------|------|
| Tier 1 patterns | `plugins/xp-agents/scripts/security_patterns.py` |
| Tier 1 commit gate | `plugins/xp-agents/scripts/pre_tool_bash.py` |
| Tier 2 unconditional fire | `plugins/xp-agents/scripts/_close_pipeline_shared.md` (Step 4) |
| Findings event shape | `plugins/xp-agents/smm/event_schema.py` (`metadata.kind=security`) |
| Quality/security separation | Decision `0fdb19d1995d` ("xp-close-reviewer is quality-only across ALL modes") |

The original v3.0 migration plan that drove the cutover from per-commit
LLM review to the tiered model is preserved at
`docs/completed/SECURITY_REVIEW_MIGRATION.md`.

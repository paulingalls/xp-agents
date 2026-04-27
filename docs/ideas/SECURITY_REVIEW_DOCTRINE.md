# Security Review Doctrine

## Purpose

Define **when** the plugin runs security review, **what kind of review
runs at each tier**, and the migration path from the current
per-commit-LLM model to a tiered model that catches more while costing
less.

This doctrine is plugin-internal: it governs how `/xp-security-triage`,
`/xp-accept`, and the close skills coordinate security review across a
codebase's life. It applies to every project the plugin runs in,
without per-project configuration.

---

## The Problem

Today, **every code commit** requires `/xp-security-triage`, which
forks `xp-security-reviewer` to run the built-in `/security-review`
command. The commit gate at `pre_tool_bash.py:152-155` enforces this
ordering: `/simplify` → `/xp-quality-review` → `/xp-security-triage` →
commit.

Two failure modes have shown up empirically:

1. **The gate gets skipped.** Sprint-035's retro flagged "2 commits
   skipped security triage after a 3+ session streak"; sprint-036's
   retro flagged "1 commit without security check." Concern
   `42d56ccea910` ("Security triage skipped on commits") has been
   carried for multiple sessions. When the cost of running the gate is
   high and the visible benefit is low (most invocations return
   "no vulnerabilities"), agents and humans both find ways around it.
2. **Per-commit reviewers are blind to multi-commit attack patterns.**
   The reviewer sees one commit at a time. A vulnerability where commit
   A introduces an unsafe helper and commit B uses it elsewhere will
   pass each per-commit review on its own. Only a cumulative-diff
   review catches this class.

Plus a cost concern: a typical sprint runs the LLM security review 6-12
times across stories that each contain mostly low-risk work (test
edits, doc edits, refactors). Most of that LLM cost is paying for "no
findings" on changes that have no plausible security surface.

---

## Principle

**Security review fires at the boundary that catches the most for the
least.** Different boundaries catch different classes of issue, and the
right answer is layered defense:

- **Per-commit:** deterministic checks only. They are fast, blocking,
  and have near-zero false positive rates on the patterns they look
  for. The right tool for "stop this commit if it contains a literal
  secret."
- **Per-story:** LLM review against the cumulative story diff. The
  right tool for "did this feature, viewed as a whole, introduce a
  vulnerability?" Catches multi-commit issues a per-commit reviewer
  can't see, at one LLM call per story instead of N per commit.
- **Per-close:** LLM review against the cumulative branch diff at
  every close (sprint, plan, free). The right tool for catching
  cross-story attack patterns and providing a final security gate
  before code lands on a protected branch. Already partially
  implemented for plan mode; this doctrine makes it explicit and
  uniform across all close modes.

The trade-off this accepts: a vulnerability introduced in commit-1 of a
multi-commit story isn't surfaced until story close (potentially
hours, not minutes). For non-prod-credential codebases that's
acceptable. **Projects with prod credentials in scope already need
out-of-band controls** (gitleaks pre-commit, secret-scanning CI,
branch-protection rules) — the plugin's job is not to be the only line
of defense.

This doctrine deliberately does **not** ship a per-project override
knob. A future doctrine version may add one if a real project needs
per-commit LLM review, but the principle is "fixed three-tier for
everyone" — projects with stronger needs add their own tooling on top.

---

## The Three Tiers

### Tier 1 — Deterministic Pre-Commit (every code commit)

**Where:** `PreToolUse:Bash` hook (extends existing
`pre_tool_bash.py`). Runs before every `git commit` invocation.

**What:** A static set of high-confidence regex/AST patterns. Each
pattern targets a class of issue with near-zero false positive rate
in this codebase's idiom:

- **Secret literals** — API keys, AWS access keys, GitHub tokens,
  private keys (PEM headers), high-entropy strings in obvious key/value
  shapes (e.g. `password = "..."`).
- **Shell injection** — `subprocess.*shell=True` with f-string or `+`
  concatenation against a non-literal. Direct `os.system` calls. Use of
  `eval(`/`exec(` against non-literal input.
- **Hardcoded credentials in URLs** — `https://user:pass@...` literals.
- **Path traversal markers** — `../` in path arguments built from
  non-literal input.

**Behavior:** **Blocks the commit on detection** (exit 2 + stderr
message). The patterns are tight enough that a hit is almost always
real; false positives can be suppressed with explicit `# noqa: secret`
markers per-line.

**Cost:** Sub-millisecond. Pure Python regex.

**Out of scope for Tier 1:** anything requiring semantic analysis
(SQL injection, XSS, deserialization). Those are Tier 2's job.

### Tier 2 — LLM Review at `/xp-accept` (per story)

**Where:** `/xp-accept` skill, after acceptance criteria pass and
before the story status transitions to `done`.

**What:** Invoke `Skill(skill: "security-review", args: "diff for
story-NNN: <range>")` against the cumulative story diff (story branch
HEAD vs sprint-base, or story branch HEAD vs the merge-base when no
sprint).

**Behavior:** Reviewer findings flow back as Keep/Concern/Block prose
(per the existing `/security-review` command's output shape). Per
v2.30.6, **Block findings file `concern --severity high` events** and
**Concern findings file `concern --severity medium` events** before the
story is marked done. The events live in the SMM and surface at next
session's kickoff for triage.

If `/security-review` reports **Block**-level findings, the
`/xp-accept` skill **stops** before marking the story done — the user
must address the finding (or explicitly defer with a recorded
acceptance-override concern, mirroring the existing override path).

**Cost:** One LLM call per story. Sprint-036 had 6 stories, so
6 LLM calls per sprint vs. ~15-20 per-commit calls under the old
model. Roughly 60-70% cost reduction at the sprint level.

**Story diff scope:** the cumulative diff across all commits on the
story branch since it forked from the sprint base. For free-mode
work that has no story container, Tier 2 does not fire — those
reviews land at Tier 3 (free-close).

### Tier 3 — Close-Reviewer Invokes `/security-review` Directly (every close)

**Where:** `xp-close-reviewer` agent, all close modes (sprint, plan,
free), as part of the agent's analysis. Adds `Skill` to the agent's
frontmatter `tools:` list and a new step in the agent prompt that
invokes `Skill(skill: "security-review", args: "<diff command from
prompt sections>")` before formulating the Keep/Concern/Block summary.

**What:** Runs `/security-review` against the **cumulative diff** at
the close boundary:

- **Sprint close:** all story diffs combined, vs the sprint base.
  Catches cross-story attack patterns (commit A in story-001 + commit
  B in story-003).
- **Plan close:** all sprint merges combined, vs the primary branch.
  Catches cross-sprint patterns and architectural drift; this is the
  one mode where security focus already existed in prose.
- **Free close:** the free branch diff vs primary. Plain
  quality+security review.

**Behavior:** `/security-review` findings are folded into the close
reviewer's Keep/Concern/Block summary. Per v2.30.6, all Block and
Concern bullets file as `concern` events with mode/source/target
metadata. **Block findings cause the close skill's
`AskUserQuestion`-driven merge confirmation to default to "Abort —
fix concerns first"**; the user can still override but the warning
is loud.

**Cost:** One LLM call per close. Three close types per project per
plan cycle. Negligible compared to per-commit baseline.

---

## Migration: Hard Cutover at v3.0

The plan is **a single coordinated migration at v3.0**, not a
deprecation cycle. Reasoning: the per-commit gate is enforced via
`pre_tool_bash.py:152-155` and via cycle markers
(`security_review_done`); a partial migration would leave the codebase
with two enforcement systems disagreeing about whether security was
checked. Cleaner to flip everything at once.

### Removed in v3.0

- **Commit-gate ordering check.** `pre_tool_bash.py:152-155`'s
  `security_review_done` branch goes away. The gate still requires
  `/simplify` and `/xp-quality-review`; security moves to Tier 2/3.
- **`.security-triaged-{agent_id}` markers.** No longer set, no longer
  read. Existing markers in stale SMM dirs become no-ops.
- **The `security_review_done` cycle marker** is removed from the
  review-cycle data structure.
- **`/xp-security-triage` skill and `xp-security-reviewer` agent are
  deleted.** Their three jobs all dissolve under the tiered model:
  (1) the per-commit mandatory gate goes away with the cycle marker;
  (2) findings recording moves into Tier 2/3 per v2.30.6's mandate;
  (3) subagent context-deflection only mattered when /security-review
  was running on every commit — at the new fire points, it lands
  either in already-bounded `/xp-accept` context (Tier 2, ~3K tokens
  per sprint, comparable to the existing `xp-accept/SKILL.md:29`
  cross-teammate-review pattern) or in the close-reviewer subagent's
  context (Tier 3, already deflected). Mid-flight security checks
  invoke `/security-review` directly.
- **Documentation updates.** `xp-plan-reviewer.md:34` (mentions
  `/xp-security-triage` as part of the per-commit review cycle),
  `xp-retrospective.md:163-164` (security-triage adherence metrics),
  `PROCESS_GUIDE.md` (review cycle ordering) all need to reflect the
  new tier model.

### Added in v3.0

- **Tier 1 patterns** in `pre_tool_bash.py` (or a new
  `security_pre_commit.py` if `pre_tool_bash.py` grows past the 500-
  line ceiling).
- **Tier 1 test suite** — one fixture per pattern, covering both the
  positive (block) case and the false-positive resistance case.
- **`/xp-accept` Tier 2 step** — new step before status transition.
- **`xp-close-reviewer` Tier 3 step** — agent prompt addition,
  `Skill` tool added to frontmatter.
- **Test guards** — `_close_fixtures.py` mixin asserts the agent
  prompt includes the `/security-review` invocation; `xp-accept` test
  asserts the new Tier 2 step is wired.

### Not changed in v3.0

- **`/security-review` itself.** The built-in command is reused
  unchanged across Tier 2 and Tier 3.
- **`xp-security-reviewer` agent removed.** See above — the wrapper
  has no remaining job. Tier 2 and Tier 3 invoke `/security-review`
  directly via `Skill`.
- **Concern recording (v2.30.6).** Tier 2 and Tier 3 already inherit
  the recording mandate from v2.30.6.

---

## Trade-offs This Accepts

### Time-to-detection drift

A vulnerability introduced in commit 1 of a 4-commit story isn't
surfaced until `/xp-accept` runs. For typical session cadence that's
hours, not minutes. **Mitigation:** Tier 1 catches the highest-stakes
class (literal secrets) at commit time. Multi-step vulnerabilities by
definition don't manifest as a single commit anyway.

### Free-mode work has no Tier 2

Free-mode commits go straight to free-close without an intervening
story. Tier 1 still fires; Tier 3 catches the cumulative review at
`/xp-free-close`. **Mitigation:** if free-mode work is non-trivial,
the user can manually invoke `/xp-security-triage` mid-flight (the
opt-in path).

### Tier 1 false positives

High-confidence regex patterns will still occasionally fire on
test fixtures or example strings. **Mitigation:** explicit
`# noqa: secret`-style suppression markers, documented in the
doctrine. Test files (where most "fake-secret" examples live)
already get filtered out by extension in some patterns; expand
that filter as needed.

### Tier 2 blocks story completion

If `/security-review` returns Block at `/xp-accept`, the story
can't move to done. This is the right behavior, but it slows the
sprint when the finding is contentious. **Mitigation:** the
existing `/xp-accept` "override with concern" path stays — the
user can mark the story done by recording a concern that
documents the override rationale.

---

## Resolved Design Calls

The following calls have explicit answers; each is binding for the
v3.0 implementation. Open the rationale by reading the corresponding
sections elsewhere in this doctrine.

1. **Tier 2 diff scope:** `git diff <merge-base>...HEAD`. Recompute
   merge-base on each invocation so rebase + fast-forward to a new
   sprint base is handled naturally. If empirical evidence surfaces a
   double-counting failure when a commit is duplicated mid-rebase,
   address in v3.1 — do not preemptively snapshot SHAs.

2. **Tier 3 at plan close:** one `/security-review` call against
   plan-branch vs. primary. The plan branch already represents the
   cumulative state. `/security-review` does its own diff scoping; if
   context limits bite empirically on very large plans, switch to a
   per-sprint-and-aggregate strategy in v3.1. Don't preemptively split.

3. **Tier 1 pattern set in v3.0:** secrets + shell injection +
   hardcoded credentials in URLs (the `https://user:pass@...`
   literal class). Path traversal markers and other pattern classes
   defer to v3.1+; the empirical driver is "a retro flags a security
   miss this pattern would have caught."

4. **`/xp-security-triage` is deleted, not kept opt-in.** Earlier
   draft kept the wrapper for mid-flight checks; on review, every job
   it had dissolves under the tiered model (gate-enforcement: gone;
   recording: moves to Tier 2/3; context-deflection: irrelevant at the
   new fire points). Mid-flight users invoke `/security-review`
   directly — same built-in command the wrapper forwarded to. Removes
   one skill + one agent from the surface area.

5. **Retrospective security metric:** **coverage**. Track
   `tier-2 stories where /security-review fired / total stories` and
   `tier-3 closes where /security-review fired / total closes`. This
   replaces the per-commit-adherence metric with the analogous
   signal under the tiered model: "did the pipeline gap fire when it
   should have?" Drop the findings-rate metric for v3.0 — coverage is
   the higher-leverage signal for catching wiring regressions.

## Remaining Open Questions

None at the doctrine level. Implementation-time questions (e.g. how
to express the merge-base form in skill prose, the exact regex
literals for Tier 1 patterns) get answered when the corresponding
milestone's stories are decomposed.

---

## Status

**Draft.** Not yet in any execution plan. Forthcoming as its own plan
after the scaffolding-doctrine plan
(`paulingalls/plan-scaffold-acceptance-v1`) ships, since this
doctrine's hard cutover at v3.0 is a coordinated, multi-touch change
that needs its own milestone phasing:

- M-1: Tier 1 deterministic patterns + test fixtures (additive,
  no breaking change).
- M-2: Tier 2 `/xp-accept` integration + tests.
- M-3: Tier 3 `xp-close-reviewer` integration + tests.
- M-4: Hard cutover — remove commit-gate enforcement of
  `/xp-security-triage`, remove `security_review_done` cycle marker,
  update `xp-plan-reviewer.md` / `xp-retrospective.md` /
  `PROCESS_GUIDE.md`.
- M-5: v3.0 release — version bump, CHANGELOG with migration notes
  for users updating from v2.x.

**Sources / context:**

- This-session conversation: user asked "what value have you seen from
  running security review for every commit?" → discussion of cost vs
  marginal value → tiered recommendation → user's clarification that
  the plugin runs in many projects, so risk-gating becomes complex.
- Existing infrastructure: `pre_tool_bash.py:152-155` (commit gate),
  `xp-security-reviewer.md` (current per-commit reviewer),
  `xp-close-reviewer.md` plan-mode focus list (Tier 3 partial),
  `xp-accept/SKILL.md:29` (cross-teammate `/security-review` step,
  precedent for invoking the built-in directly from a skill).
- Concern `42d56ccea910` (carry-over): "Security triage skipped on
  2 commits after 3+ session streak" — flagged the cost-skip pattern
  this doctrine addresses.

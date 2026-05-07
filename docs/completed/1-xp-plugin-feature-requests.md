# xp-agents Plugin — Feature Requests

Written from SimplyHuman, against `xp-agents@3.1.3`, on 2026-05-04.

These asks all surfaced as retrospective Try items that the using project keeps proposing but cannot adopt without modifying the plugin itself. Dropping them at work-selection felt more honest than carrying them forward as no-op Trys, but the underlying problems remain. Handing them over.

Items 1-3 and 5-8 are plumbing or prompt edits; item 4 is a planner-discipline rule.

---

## 1. Inject `Story-Id` trailer automatically in `bash_post_tool`

**Problem.** Sprint sizing and per-story attribution depend on associating each commit with the story being worked on. Today this is inferred from the branch name (`paulingalls/story-NNN-*`). Branch inference is fragile: it breaks for free-mode branches, story branches with non-standard slugs, and any local branch the user creates ad-hoc. Sprint-012 worked only because the branch convention happened to hold.

**Ask.** In the post-tool hook that already injects `Resolves-Event` discipline, also inject a `Story-Id: story-NNN` trailer when the commit is being authored inside a sprint with an `in-progress` story. Resolution order:

1. Read `sprint.json`. If exactly one story has `status=in-progress`, use its id.
2. Otherwise fall back to the existing branch regex (`paulingalls/story-NNN-*`).
3. If neither resolves, do nothing (don't guess).

**Why now.** This is the second consecutive sprint where the retro flagged "branch inference still load-bearing." The current scheme will silently mis-attribute the moment a user branches off a story branch for an experiment, or works on multiple stories from one branch in solo mode.

**Scope guess.** Small — same hook path as `Resolves-Event`, same parsing primitives.

---

## 2. Treat refactors as updates to existing debt, not new debt

**Problem.** When `xp-code-reviewer` sees a known debt's anchor (file/lines) move during a refactor, it currently appends a _fresh_ `debt` event with the new anchor. The original debt event stays open at the stale anchor. Result: the same risk shows up as two separate items in the Risks pillar, both surface in work-selection, and the user has to manually deduplicate.

Concrete instance from this project: debt `51633f827fad` (S3 fail-open at `storage.ts:11-12`) was duplicated as `f1224bd101b8` (S3 fail-open at `storage.ts:39-40`) when the storage refactor moved the constants into `createStorageClient()`. Same risk, two events. This kickoff had to drop one and adopt the other manually.

**Ask.** Add explicit guidance to the `xp-code-reviewer` (and `xp-agent` if the same pattern applies) prompt:

> Before recording a new `debt` event, search open debts whose content describes the same risk. If a refactor has merely relocated the anchor, **update the existing event** via `metadata.resolves` semantics (or whatever the canonical "supersede in place" pattern is in the SMM CLI) rather than appending a fresh debt with the new anchor.

If the SMM CLI doesn't currently have a clean "update in place" primitive, this ask grows to include adding one — flagging it explicitly so the implementer knows to check.

**Why now.** Aging debt counts and "untriaged risk" warnings are load-bearing health signals. Duplicate-by-refactor inflates them and erodes trust in the pillar.

**Scope guess.** Small if the primitive exists (prompt edit). Medium if it doesn't (CLI subcommand + prompt edit).

---

## 3. Pre-commit probe should include `type=discovery` candidates

**Problem.** When the pre-commit probe nudges the user to add a `Resolves-Event` trailer, it ranks only `debt` and `concern` candidates from the SMM. Sprint-012 had a commit that genuinely closed a `discovery` event — the probe surfaced two debt candidates the user didn't want, and the user had to hand-edit the trailer to point at the discovery. The retro recorded this as "probe adoption 0% (1/1 divert): candidate set excluded discoveries."

**Ask.** Extend the probe's candidate `SELECT` to include `type='discovery'` rows alongside `debt` and `concern`. Keep the existing ranking logic; just widen the source set.

**Why now.** Probe adoption rate is a feedback signal for the whole resolution-discipline subsystem. A 0% adoption with 100% divert means the probe is actively making the user's life harder for that case, not easier.

**Scope guess.** Trivial — one-line query change, assuming downstream ranking is type-agnostic.

---

## 4. Plan-reviewer should reject `file_domain` entries that omit planned NEW modules

**Problem.** `file_domain` is supposed to enumerate the files a story will touch, including new files it will create. In practice, planners (including this one) routinely list only _existing_ files and forget to enumerate _new_ files the story description plainly implies. Sprint-012 story-003 said "extract REQUIRED_ENV to its own module" but the `file_domain` didn't include `apps/server/src/required-env.ts`. The drift wasn't caught until close-review (concern `73cfb6b97049`).

This breaks two things:

- **`cascade_size` accounting** — the new file isn't on the planned list, so it counts as drift.
- **Conflict detection** — parallel teammates can't see that the new file is "owned" by this story.

**Ask.** Update the `xp-plan-reviewer` agent prompt with a hard rule:

> If the story description contains language implying a new file or module (e.g., "extract X to a new module Y", "add a new helper for Z", "introduce a separate file for W"), the `file_domain` MUST enumerate the path of that new file. If the planner cannot name the path yet, that's a planning gap — reject the plan and ask the planner to commit to a path before review proceeds.

Optionally, pair this with a softer probe in the plan-reviewer's existing checks: scan the description for verbs like "extract," "introduce," "add … module," "create … helper," and surface a warning when the matched text isn't reflected in the domain list.

**Why now.** This is the third or fourth time in recent sprints that file_domain drift on a planned new module has been a close-review finding. It's a deterministic problem with a deterministic fix at plan time.

**Scope guess.** Small — agent prompt edit, optionally with a regex probe.

---

## 5. Auto-emit `type=assumption` events from `bash_post_tool` on commit-message phrasing

**Problem.** Sprint-012 retro flagged "zero `assumption` events across 7 commits + 32 code file writes + 28 concerns" — a session full of judgment calls that never surfaced as assumption events. Agents are supposed to emit them when they make non-obvious calls, but in practice they don't, and the channel sits unused. Meanwhile, commit messages frequently contain phrases like "I'm assuming X" or "assuming the caller has already validated Y" — the assumption is being recorded, just in the wrong place.

**Ask.** In `bash_post_tool`, when the commit message body contains `I'm assuming` / `assumes` / `assuming that`, automatically emit a paired `type=assumption` event with `metadata.commit=<sha>` and the matched sentence as content. Closes the gap without asking agents to remember.

**Why now.** The assumption channel is one of the four pillar inputs (Risks side). When it's silent, the SMM under-represents real uncertainty and Risks pillar curation drifts toward "everything is fine."

**Scope guess.** Small — same hook path as `Resolves-Event` injection, regex on commit body, append via the existing `append.sh`.

---

## 6. Nudge commit-author / `xp-code-reviewer` to emit `type=decision` on new patterns

**Problem.** Sprint-012 retro: "Only 1 `decision` event for a session that scaffolded a new e2e harness, added `PRODUCTION_REQUIRED_ENV` pattern, and extracted `required-env.ts`." Decisions exist — they're in commit prose — but they aren't surfaced as `decision` events, which weakens the cross-session trace (Constraints pillar loses its source signal).

**Ask.** Add a one-line nudge to the `xp-code-reviewer` prompt: **"New pattern introduced this commit? Record a `type=decision` event before merging."** Optionally pair with a heuristic in `bash_post_tool` that flags commits whose subjects contain `add`, `extract`, `introduce`, `new` and whose diffs touch a new module, asking the author to confirm-or-skip a decision event.

**Why now.** The Constraints pillar is supposed to capture project decisions over time. Without the events, curated decisions get backfilled from commit archaeology by the housekeeper — slower, less reliable, and brittle to commit-message style.

**Scope guess.** Small (prompt edit only) to medium (if the heuristic probe is added).

---

## Notes for the implementer

- All eight are small or small-ish; none requires a major architectural change.
- Items 1–3, 5, 6, 7, 8 are pure plumbing/prompt edits that should slot into the existing hook/agent infrastructure.
- Item 4 is the highest-leverage because file_domain drift cascades into close-review noise; consider it first if you're prioritizing.
- Items 5 and 6 are companions — both address the "agents don't emit observability events even when the underlying signal is captured in commit prose" gap.
- Items 7 and 8 are companions — both address the "concern volume as governance signal" being polluted by self-cancelled or stale-detector events.
- If any of these have already been implemented in a version newer than 3.1.6, this doc is stale — disregard the corresponding section and ping me to confirm so I can stop re-proposing them in our retros.

---

## 7. Reclassify `xp-plan-reviewer` "null concern for trace" as `decision` (or `status`), not `concern`

**Problem.** Sprint-013 retro: `xp-plan-reviewer` raised 24 of 34 concerns (70%). One was self-cancelled in-flight as "false alarm null concern for trace" (event d2e161c12c03 — see also a8bfdf2d0ca2), but the schema only offered `type=concern`, so the false-alarm note inflated the unresolved-concerns metric until kickoff explicitly dropped it.

**Ask.** When `xp-plan-reviewer` records a "verified clean / null concern for trace" pattern, emit `type=decision` (or a `type=status` with a dedicated `category=trace`) instead of `type=concern`. The trace stays in the event log; the unresolved-concerns metric stays clean.

**Why now.** Concern volume is a governance signal. Polluting it with self-cancelled trace records makes "concerns unresolved at session end" mean less than it should, which weakens the kickoff triage step that depends on that count.

**Scope guess.** Small — a one-line classification change in the reviewer prompt or the event-emission helper.

---

## 8. Scope `superseded-decision` detector to current session only (or fix cross-session false positives)

**Problem.** Sprint-013 retro: 3 `superseded-decision` concerns fired against stable, settled topics (`execution-mode`, `retro-try-resolves-trailers`, `css-prefix-convention`) — events e3f015d5914c, 3b712e738b51, 35e098ad3bcc. None were genuine within-session decision conflicts; they appear to be the detector firing across sessions whenever a long-stable decision is re-cited.

**Ask.** Either (a) scope the `superseded-decision` detector to the current session's event window so cross-session re-citation doesn't count, or (b) inspect why these three topics specifically keep firing and fix the predicate. Option (a) is simpler if cross-session is the universal pattern; option (b) preserves the detector's original intent if some triggers are real.

**Why now.** Concern volume is a governance signal, and stale detector firings dilute it. We've now had detector noise on the same three topics across multiple sessions, which suggests the predicate, not the project, is the problem.

**Scope guess.** Small for option (a) (windowing predicate); medium for option (b) (requires reproducing the false positives and tracing the predicate).

# xp-agents Plugin — Feature Requests

Written from SimplyHuman, against `xp-agents@3.1.3`, on 2026-05-04.

These four asks all surfaced as retrospective Try items that the using project keeps proposing but cannot adopt without modifying the plugin itself. Dropping them at work-selection felt more honest than carrying them forward as no-op Trys, but the underlying problems remain. Handing them over.

The first three are concrete plumbing changes; the fourth is a planner-discipline rule.

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

## Notes for the implementer

- All four are small or small-ish; none requires a major architectural change.
- Items 1–3 are pure plumbing/prompt edits that should slot into the existing hook/agent infrastructure.
- Item 4 is the highest-leverage of the four because file_domain drift cascades into close-review noise; consider it first if you're prioritizing.
- If any of these have already been implemented in a version newer than 3.1.3, this doc is stale — disregard the corresponding section and ping me to confirm so I can stop re-proposing them in our retros.

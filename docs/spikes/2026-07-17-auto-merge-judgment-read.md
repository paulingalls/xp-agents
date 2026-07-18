# Spike-016: the auto-merge override trusts a judgment read, not the event log

Concern `4bfd3de66825`; discovery `4ed049547402` (correcting `a947ab2556f8`);
found by sprint-121 story-001's plan review.

## 1. Question

`/xp-story-close` and `/xp-free-close` can **skip the human Step 6 merge
confirmation** and auto-merge when a set of conditions hold. Three of them are
deterministic event-log/exit-code reads. **Condition 2 is not** — it asks the LLM
to re-read its own Step 4.5 reviewer prose. So can a `severity=high` concern
sitting in `events.jsonl` stop a story/free auto-merge? And should condition 2
become a deterministic event-log read, reusing the counter sprint-121 story-001
already built?

## 2. Findings

### 2.1 Can a severity=high concern in the log stop an auto-merge today? **NO.** (AC1)

The auto-merge conditions, quoted from the shipped skills:

- `xp-story-close/SKILL.md:193` — condition 2: **"No Block-severity finding in
  Step 4.5's reviewer summary."**
- `xp-free-close/SKILL.md:103` — condition 2: **"No Block-severity finding survived
  in Step 4.5's reviewer summary."**

Both are an LLM re-reading its own prose. The other conditions ARE deterministic:
condition 1 (`count-classifications --route ask == 0`), condition 3
(`TEST_COMMAND` exits 0), and free-close's condition 4
(`count-classifications design_decision == 0`).

The event log **is** consulted for high-severity concerns — but only in the
**shared Step 6** the auto-merge path skips: Step 6 computes
`HIGH_CONCERN_COUNT = count-concerns --severity high --cycle-id <CLOSE_CYCLE_ID>
--since-ts <CLOSE_START_TS>` for the abort-default ordering. When the override
fires, "skip the shared Step 6 `AskUserQuestion` and proceed to Step 7" — so
`HIGH_CONCERN_COUNT` is **never evaluated**. A `severity=high` concern in
`events.jsonl` therefore cannot stop an auto-merge; only the LLM's condition-2
read stands between a Block and the merge.

### 2.2 How often has condition 2 actually caught something? Almost never. (AC2)

Measured from the event logs (not asserted):

- **This project:** 7 `severity=high` concern events all-time, **0** carrying a
  `close_cycle_id` → **0 close-cycle Blocks ever**. Condition 2 has caught nothing
  here. (The 7 are plan-review / discovery / test-failure concerns, not Step 4.5
  Blocks.)
- **All other projects' logs on this machine:** **3** `severity=high` concerns with
  a `close_cycle_id`, total.

So a close review returning a Block is genuinely rare. The rarity cuts against
condition 2, not for it: because a Block almost never happens, a single LLM
mis-summary (condition 2 reporting "no Block" when the reviewer did Block) would
slip through unnoticed, and there is no deterministic backstop to catch it — the
data to catch it (`severity=high` + `close_cycle_id`) is in the log, unread.

### 2.3 Blast radius of making condition 2 deterministic (AC3)

Proposed replacement: condition 2 becomes
`count-concerns --severity high --cycle-id <CLOSE_CYCLE_ID> --since-ts
<CLOSE_START_TS> == 0`, reusing `smm/smm_count.py`'s existing `count-concerns`
(the interface_contract: reuse it, do NOT add a fourth counter). What that read
does and does not catch:

- **Cross-cycle / cross-worktree concerns — do NOT leak in.** `--cycle-id`
  excludes events tagged with a DIFFERENT `close_cycle_id`; `--since-ts` excludes
  pre-cycle events. A `severity=high` concern filed by another worktree's close
  cycle carries that cycle's tag and is excluded. (Verified against
  `smm_count._cmd_count_concerns`: `if args.cycle_id and tag is not None and tag
  != args.cycle_id: skip`.)
- **UNTAGGED high concerns filed DURING this cycle — DO count (fail-closed).** An
  untagged `severity=high` concern appended within the `--since-ts` window (e.g. a
  concurrent worktree that filed without a cycle tag) would be counted and fall the
  close through to the human Step 6. This is the intended fail-closed behaviour:
  when no human sees Step 6, over-falling-through to a human is the safe error, not
  auto-merging over an unresolved high concern.
- **It catches exactly what condition 2 intends.** Every Step 4.5 (and Step 4
  security) Block is already recorded as a `severity=high` concern tagged with the
  `close_cycle_id` (shared Step 6's own premise). So the deterministic read sees
  every real Block — and, unlike the LLM read, cannot be fooled by a mis-summary.

Nothing load-bearing breaks; the counter, its cycle/since scoping, and the Block→
severity=high recording all already exist.

## 3. Verdict (AC4)

**Recommend the fix.** Add a deterministic condition 2 to both auto-merge override
blocks — `count-concerns --severity high --cycle-id <CLOSE_CYCLE_ID> --since-ts
<CLOSE_START_TS>` must be `0` — either replacing the LLM "no Block in summary"
read or keeping it as a redundant cross-check. This makes a `severity=high`
concern in the log deterministically stop an auto-merge, closing the gap the
context names: `count-concerns` is advisory *because a human sees Step 6* — but on
the auto-merge path **no human sees Step 6**, so the event-log read must be the
backstop.

**Blast radius:** two SKILL.md edits (`xp-story-close`, `xp-free-close` auto-merge
override blocks) + reuse of the existing `smm_count.py count-concerns` (no new
code). Low risk: the counter is already used for the same cycle in the shared
Step 6 abort-default.

This spike produces the decision; the fix is a follow-on. Concern `4bfd3de66825`
stays **open** until it lands.

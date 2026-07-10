# File-Domain Lock: Make Story Ownership an Enforced Invariant

*Filed from divineruin sprint-040 planning. Observed on xp-agents v4.4.2.*

## Summary

`file_domain` is documented as an exclusive-ownership invariant — "each story
exclusively owns its files — no overlap between stories" (`xp-sprint-start`
SKILL.md, Step 3). Nothing enforces it. Worse, `/xp-sprint-start` **actively
violates it on the author's behalf**: the sister-test auto-include runs after
the planner writes `file_domain` and can hand story A a test file that story B
already owns, silently.

Three gaps, in order of severity:

1. Sister-test auto-include introduces cross-story collisions (tool-created).
2. An overlap detector already exists, but is never used as a validation gate.
3. `xp-plan-reviewer` checks `file_domain` five different ways, but never
   checks it for cross-story overlap.

## Gap 1 — sister-test auto-include creates collisions

`smm/sprint_save.py:_auto_include_sister_tests` (lines 231-275) walks each
story, discovers sister tests for every source path in its `file_domain`, and
appends `"<test> — sister test for <src>"` entries.

The dedup set is **per-story**:

```python
for story in data.get("stories", []):
    domain = story.get("file_domain")
    ...
    existing_paths: set[str] = set()   # <-- reset each story
```

It dedups a sister against *that story's own* domain. It has no knowledge of
any other story's domain. So when two stories touch the same feature — which
is the normal shape of a decomposed milestone — a test file that is
legitimately owned by one story gets injected into another.

### Real repro (divineruin sprint-040, M24 Veil Ward)

The planner authored disjoint domains:

| Story | Owns |
|---|---|
| story-002 | `apps/agent/veil_ward.py`, `apps/agent/tests/test_veil_ward.py` |
| story-003 | `apps/agent/db_mutations_veil_ward.py`, `apps/agent/tests/acceptance/test_veil_ward_persistence.py` |
| story-005 | `apps/agent/veil_ward_tools.py`, `apps/agent/tests/test_veil_ward_tools.py` |

After `sprint_cli create`, story-002's domain read:

```
apps/agent/veil_ward.py — WardScope + duration types; ...
apps/agent/tests/test_veil_ward.py — cover every source's duration ...
apps/agent/tests/acceptance/test_veil_ward_persistence.py — sister test for apps/agent/veil_ward.py
apps/agent/tests/test_veil_ward_tools.py — sister test for apps/agent/veil_ward.py
```

The sister-test globber matched `test_veil_ward*` against source stem
`veil_ward`, pulling in two files owned by story-003 and story-005. The
planner never saw it happen; the CLI printed nothing.

This is not a stem-matching bug to be tuned away. Any prefix-y naming scheme
(`foo.py` / `foo_tools.py` / `foo_helpers.py`, each with a sister test) will
reproduce it. The defect is that a per-story transform is allowed to write
into a global namespace with no global check.

### Impact

**When both stories are scheduled together:** `scheduled-overlap` sees the
collision and `/xp-assign` silently downgrades a disjoint fan-out to solo. The
user asked for parallel teammates, gets serial execution, and is told nothing
about why. Parallelism is lost to a collision the tool itself created.

**When they are scheduled apart** (the common case with a dependency chain —
sprint-040's stories 002→003→005 are strictly ordered): two teammates in two
worktrees each believe they own `test_veil_ward_tools.py`. Both edit it. The
second merge clobbers or conflicts. The `verify-touch` gate is satisfied for
both stories because both committed a file inside their declared domain — so
the gate that exists to catch exactly this cannot see it.

**Silent scope inflation.** story-002 is authored as a pure-tier story
(`veil_ward.py`, no IO). The auto-include quietly hands it an *acceptance*
test requiring testcontainer Postgres. A teammate reading its own domain would
reasonably conclude it must make that acceptance test pass — work that belongs
to story-003.

## Gap 2 — the overlap detector exists but never gates

> **Resolved (sprint-114 M1 + sprint-115 M2).** This gap is now closed. The
> detector gates at every structural write: `file_domain_lock.collision_report`
> (dependency-aware — collision = concurrent claim only) runs inside
> `sprint_save.run()` (create/add-story) and, since story-006, inside
> `sprint_store.edit_story()`. The specific helpers cited below no longer exist:
> story-005 deleted `scheduled_file_domains_overlap` and `file_domains_overlap_data`
> once they were callerless; the surviving detail-returning entry point is
> `sprint_status.file_domains_overlap_detail`, backed by `collision_report`. The
> analysis below is retained for historical context — do not treat the deleted
> helper names as live reuse targets.

`smm/sprint_status.py:203` already implements exactly the needed check:

```python
def scheduled_file_domains_overlap(smm_dir: Path) -> bool:
    """True when 2+ scheduled stories share at least one file in their file_domain."""
```

and the general form `file_domains_overlap_data(data, story_ids)` at line 225.
It is well-tested (`tests/engine/test_sprint_status.py`, five cases including
glob entries).

Its only production callers are:

- `sprint_cli.py:88` → `scheduled-overlap`, consumed by `/xp-assign` to
  auto-pick solo.
- `sprint_store.py:461` → `ready_frontier`'s `parallelizable` flag.

Both are **scheduling** consumers. Both treat overlap as a fact of life to
route around, never as an error to report. Neither runs at sprint creation,
and neither considers stories that aren't currently scheduled.

The capability to detect the problem is already in the codebase. It is simply
never pointed at the moment the problem is created.

## Gap 3 — plan-reviewer checks `file_domain` five ways, never for overlap

`agents/xp-plan-reviewer.md` references `file_domain` at lines 151, 153, 155,
157, 159, 170, 176. Every check is **intra-story**:

- §10b: does the AC command's path live inside *this* story's domain?
- Is the AC command path-naming (verifiable) or a script alias?
- Does a verb+context pair imply a path absent from *this* domain?
- Does the plan actually write the test the AC will run?

There is no cross-story check because the plan-reviewer reviews **one story's
plan at a time** and never holds the whole sprint in view. This is a real
structural limit — the retro Try ("make the file_domain-lock checklist an
enforced xp-plan-reviewer output step") is aimed at the wrong agent. By the
time the plan-reviewer runs, `sprint.json` is already written and the
collision is already in it.

**The check belongs at sprint write time, not plan review time.**

## Proposed fixes

### Fix 1 (required): validate disjointness on every `sprint.json` write

In `sprint_save.run()`, after `_auto_include_sister_tests` mutates the data,
assert global path→story uniqueness. Fail loud, naming every collision:

```
ERROR: file_domain collision — a path may be owned by exactly one story.
  apps/agent/tests/test_veil_ward_tools.py
    story-002 (auto-included: sister test for apps/agent/veil_ward.py)
    story-005 (authored)
  apps/agent/tests/acceptance/test_veil_ward_persistence.py
    story-002 (auto-included: sister test for apps/agent/veil_ward.py)
    story-003 (authored)
```

Reuse `triage.entry_to_paths` for parsing, so it matches every other
`file_domain` consumer. The error must distinguish **authored** from
**auto-included** entries, because the fix differs: an authored collision is
a planner error, an auto-included one is a tool error.

Apply to `create` and `add-story` alike.

### Fix 2 (required): make sister-test auto-include globally aware

Two options, in preference order:

**(a) Never inject a sister another story authored.** Seed `existing_paths`
from the union of *all* stories' authored domains before the per-story loop.
A test file explicitly named by any story is that story's, full stop. This
is the least-surprise rule and needs ~5 lines.

**(b) Never inject a sister that any other story would also claim.** If a
sister resolves for two different source files in two different stories, inject
it into neither and emit a warning. Safer, but leaves the file unowned — which
Fix 1 will then not flag, so it must be paired with a "no unowned test file"
report rather than an error.

Recommend (a). It preserves the auto-include's value (the planner really does
forget sister tests) while making the authored domain authoritative.

### Fix 3 (optional): report, don't just route around

`/xp-assign`'s auto-pick-solo on overlap is correct behavior, but it should
say so:

> Stories 004 and 006 share `apps/agent/session_data.py`; running solo. Split
> the domain to parallelize.

Right now the user experiences an unexplained loss of parallelism. Given Fix 1
makes true collisions impossible at write time, any overlap reaching
`/xp-assign` is an *intentional* shared file — which is exactly the case worth
surfacing.

### Fix 4 (optional): drop the retro Try as misaimed

The Try "make the file_domain-lock checklist an enforced xp-plan-reviewer
output step" should be closed in favor of Fix 1. The plan-reviewer cannot
enforce a sprint-global invariant from a single-story view, and a checklist
item asking a model to eyeball nine stories' domains is exactly the kind of
vigilance that CI should replace. (See the project's own recorded wisdom:
*"Write a failing test for a known gap BEFORE shipping the feature that
exposes it — CI guards fragility better than vigilance."*)

## Why this matters more than it looks

`file_domain` is the load-bearing primitive for three separate mechanisms:

- **Parallel teammate isolation** — worktrees assume disjoint domains.
- **The verify-touch close gate** — "did the story author its own proof?"
  answered by matching committed paths against the domain.
- **Scope communication to a teammate** — a teammate reads its domain as the
  definition of its job.

All three degrade silently when the invariant breaks. None of them fail loud.
A collision produces a lost merge, a false-green gate, or a teammate doing
another story's work — and in each case the symptom appears far from the
cause.

The invariant is already documented, already detectable, and already violated
by the tool that writes it. Closing that loop is a small change with a large
blast radius reduction.

## Repro

```bash
# Any repo where two sibling sources share a test-name stem, e.g.
#   src/thing.py         + tests/test_thing.py
#   src/thing_tools.py   + tests/test_thing_tools.py
# Author a sprint where story-A owns thing.py and story-B owns thing_tools.py,
# each with its own sister test explicitly enumerated.

python3 smm/sprint_cli.py --smm-dir <SMM> create < sprint.json
python3 smm/sprint_cli.py --smm-dir <SMM> get-story story-A | jq .file_domain
# => contains tests/test_thing_tools.py, which story-B authored.
```

Observed on xp-agents 4.4.2, `smm/sprint_save.py:243-275`.

# Feature request: `sprint_cli.py add-story` should reject duplicate story IDs

**Plugin:** `xp-agents` (cached at `~/.claude/plugins/cache/xp-agents/xp-agents/2.31.0/`)
**Suspected location:** `smm/sprint_cli.py` `add-story` subcommand — the JSON-on-stdin flow that accepts a story object and appends it to `sprint.json`'s `stories[]` array.
**Reporter:** AJE PoC, sprint-008 work-selection (2026-04-27)
**Linked debt:** SMM event `954c8ea1fb2c`

## Current behavior

`sprint_cli.py add-story` reads a story object from stdin and appends it to `sprint.json`'s `stories[]` array. There is no validation that the new story's `id` field is unique. Two `add-story` calls with the same `id` both succeed, leaving two entries with identical IDs in the array.

Downstream, `update-story <id> <status>` matches the **first** entry by `id` and updates it. The duplicate sits in the array silently — never updated, never deleted, never flagged. The retrospective analyzer sees the duplicate as a real story and reports inconsistent counts.

## Repro (from sprint-008 work-selection, 2026-04-27)

Sprint-007 had already created `story-009` ("decision-resolves-try-wiring fairness batch"). At sprint-008 kickoff, the housekeeper added a second `story-009` ("Doc/comment polish batch") via `add-story`. Result: `sprint.json` carries two `story-009` entries with different titles. `update-story story-009 in-progress` flipped the first one (the sprint-007 leftover), leaving the new doc-polish story stuck at its original `pending` status. Confusion compounded across the session — the work was tracked under the wrong story until the duplicate was noticed manually.

```bash
# Reproduce — replace SMM_DIR with your value
SMM_DIR="$(jq -r '.smm_dir' "$HOME/.claude/projects/<project-slug>/.session.json")"
SPRINT="$SMM_DIR/sprint.json"

# Two add-story calls with the same id both succeed:
echo '{"id":"story-X","title":"first","status":"ready", ...}' | python3 sprint_cli.py --smm-dir "$SMM_DIR" add-story
echo '{"id":"story-X","title":"second","status":"ready", ...}' | python3 sprint_cli.py --smm-dir "$SMM_DIR" add-story

# Verify the duplicate landed:
jq '.stories | map(select(.id=="story-X")) | length' "$SPRINT"
# 2

# update-story flips the first one only — the second is unreachable:
python3 sprint_cli.py --smm-dir "$SMM_DIR" update-story story-X in-progress
jq '.stories | map(select(.id=="story-X")) | map({title, status})' "$SPRINT"
# [
#   {"title": "first",  "status": "in-progress"},
#   {"title": "second", "status": "ready"}
# ]
```

## Why this matters

1. **Silent data corruption.** The duplicate is never surfaced. The user only notices when a status update appears not to have stuck (looking at the wrong copy) or when the retrospective shows a story count that doesn't match expectations.

2. **`update-story` is now ambiguous.** The semantics — "match the first entry by `id`" — are an accident of `next((s for s in stories if s["id"] == id), None)`. There's no documented intent that the _first_ match wins, and no warning when subsequent matches are silently ignored.

3. **Cross-session retro confusion.** The retrospective analyzer counts stories by ID. A duplicate inflates the count and makes "was story-X done?" ambiguous (which one?). Sprint-008 retro will see this directly: the housekeeper produced one duplicate `story-009`, which led to two follow-up sessions tracking work under the wrong handle until manual cleanup.

4. **Asymmetry with `add` semantics elsewhere.** `append.sh` rejects duplicate event IDs (event IDs are content-hashed and unique by construction). `sprint_cli.py add-story` is the only `add`-style CLI in the SMM toolset that allows ID collisions silently.

## What we want

`sprint_cli.py add-story` should fail loudly (exit non-zero, write to stderr) when the supplied story `id` already exists in `sprint.json`'s `stories[]` array. The existing array stays untouched.

## Proposed fix

In `smm/sprint_cli.py` `add-story` handler, after the existing JSON-parse + `sprint = json.load(...)` (or equivalent loader) and before `sprint["stories"].append(story)`:

```python
new_id = story["id"]
existing_ids = {s["id"] for s in sprint["stories"]}
if new_id in existing_ids:
    print(f"add-story: story id {new_id!r} already exists in sprint.json", file=sys.stderr)
    sys.exit(1)
```

Single-place change. No new dependencies. No new flags. Follows the established fail-fast convention from `append.sh`.

## Acceptance criteria

1. `add-story` with a fresh ID succeeds (regression check: existing behavior preserved).
2. `add-story` with an `id` that already exists in `sprint.json` exits non-zero, writes a one-line `stderr` diagnostic naming the conflicting ID, and **does not modify** `sprint.json`.
3. Round-trip: after a failing duplicate `add-story`, `jq '.stories | length' sprint.json` is unchanged.
4. The contract for callers: exit code is exactly `1` and the stderr line begins with the literal `add-story:` prefix, so an agent can `grep ^add-story:` after a non-zero exit and choose a different ID.
5. Existing tests in `smm/tests/sprint_cli_test.py` (or equivalent) still pass; one new test asserts the duplicate-rejection behavior.

## Out of scope

- Auto-renaming the duplicate (e.g. `story-X-2`). Better to fail loud and let the caller decide.
- Validating `id` against any wider naming convention (`story-NNN` 3-digit format, sequential numbering, etc.). Today the `id` field is opaque; this request doesn't change that.
- Backfilling sprint.json entries that already contain duplicates. The sprint-008 case can be cleaned manually; a one-shot script isn't needed.
- Validating other story-shape fields (title length, milestone_ref pointing to a real milestone, etc.). Separate concerns, separate requests.

## Contact / validation

SMM dir: `/Users/paulingalls/.claude/plugins/data/xp-agents-xp-agents/bce1d9c11420/smm`

Working example of the bug — sprint-008's `sprint.json` (during sprint-008 kickoff, before duplicate was noticed):

```bash
jq '.stories | map(select(.id=="story-009")) | map({title, status})' \
  "$SMM_DIR/sprint.json"
# Expected output: 2 entries, distinct titles, only the first one ever updated by update-story.
```

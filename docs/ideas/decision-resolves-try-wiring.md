# Feature request: auto-wire `metadata.resolves` on decisions/status events that act on retro Try items

**Plugin:** `xp-agents` (cached at `~/.claude/plugins/cache/xp-agents/xp-agents/2.30.7/`)
**Suspected location:** `/xp-work-selection` adopt/defer/drop pathway (likely `skills/xp-work-selection/scripts/work_selection_decide.py`) and any plan-reviewer / housekeeper code path that records a `decision` or `status` event in response to a Try item.
**Reporter:** AJE PoC, sprint-007 retrospective (2026-04-27)
**Linked Try (now deferred):** `0614fdd39790` — "Sprint-008: add metadata.resolves wiring to /xp-work-selection adopt + plan-reviewer decision pathways."

## Current behavior

When an agent acts on a previous-session retro Try item via `/xp-work-selection` adopt/defer/drop, the resulting status event correctly extracts the `[refs: id1, id2, ...]` suffix from the Try text and writes those IDs into `metadata.resolves`. **This part works** — sprint-008 kickoff produced four such events with the refs wired:

```
$ jq 'select(.id=="d65bee7ec7cb") | .metadata.resolves' events.jsonl
["13378e8c54a5"]

$ jq 'select(.id=="8af0eef6d6f1") | .metadata.resolves' events.jsonl
["0614fdd39790","393865f17dd1","52543ba3c8e7","baa4d2cb9b52","3ab1b301eef0"]
```

But the **other** path — when the plan-reviewer agent or housekeeper records a `decision` event whose content references a Try by event_ref — does NOT wire `metadata.resolves` to the Try ID. Sprint-007 produced four such decisions (verified in retro):

| Decision ID    | What it did                                | Wires to Try ID? |
| -------------- | ------------------------------------------ | ---------------: |
| `393865f17dd1` | Adopted "wire references=[concern_id]" Try |               No |
| `52543ba3c8e7` | Adopted CSP fairness-batch Try             |               No |
| `baa4d2cb9b52` | Adopted file-debt cleanup Try              |               No |
| `3ab1b301eef0` | Adopted CSP-shared-package Try             |               No |

Each decision's `content` field clearly references the Try ("adopting Try-2…", "per retro fairness batch…"), but `metadata.resolves` is empty. The Try sits in the SMM as "still open" until the next retro analyzer pass tries to infer status by content matching — which fails for paraphrased adoptions.

## Why this matters

1. **Resolution graph is incomplete.** The SMM has three explicit link types (STRONG `metadata.resolves`, WEAK `references`, STRUCTURAL `files`). For Try items, only the manual `/xp-work-selection` path produces a STRONG link. Plan-reviewer and housekeeper paths produce zero links, so the analyzer has to fall back to text-similarity heuristics that produce false negatives.

2. **Drives ghost-Try retro proposals.** Sprint-007 retro analyzer reported `try_status=false` for Tries that 4 prior decisions had explicitly acted on. The retro therefore re-proposed the same work (under a slightly different name) for sprint-008. Cross-checked manually: the work was done; the link was missing. This is the same class of bug the QR-counting report describes — different metric, same root cause.

3. **Asymmetric tooling burden.** Right now `/xp-work-selection` is the only path that produces correct linkage, which incentivizes routing every decision through it even when the natural surface is the plan-reviewer or the housekeeper. That's a code smell — the link should follow the data, not the user-facing tool.

## What we want

When any agent records an event of type `decision`, `status`, or `convention` whose `content` text references a Try event_ref (12-hex-char ID, or a slug like "Try-N"), the writer should auto-populate `metadata.resolves` with the matched Try IDs.

Two implementation choices, ranked:

| Strategy                                                                                                             | Precision | Where it lives                                           |
| -------------------------------------------------------------------------------------------------------------------- | --------- | -------------------------------------------------------- |
| Server-side: `append.sh` / `_append_impl.py` scans `content` for `[refs: ...]` and `[a-f0-9]{12}` matches and wires. | High      | One place. Works for every event type and every caller.  |
| Per-pathway: each plan-reviewer / housekeeper / xp-assign script wires explicitly when emitting a Try-related event. | Medium    | Several call sites. Easy to forget; new paths re-bug it. |

**RECOMMENDED: server-side.** The `[refs: id1, id2]` suffix is already a documented append-time convention (the `/xp-work-selection` helper extracts it and wires + strips). Hoisting that extraction one level down — into `append.sh` itself — applies the same rule to every event type and every agent without each call site needing to know.

## Acceptance criteria

1. A `decision` event written via `append.sh --type decision --content "Adopting Try foo bar [refs: abc123def456]"` results in `metadata.resolves: ["abc123def456"]` and the `[refs: ...]` suffix stripped from stored content.
2. The same applies to `status`, `convention`, and any other writable event type.
3. Bare 12-hex IDs in content (no `[refs: ...]` wrapper) are NOT auto-wired — the suffix is the explicit opt-in. (Otherwise commit-hash mentions in commit-event content would false-positive.)
4. Multiple IDs in one suffix are all wired: `[refs: id1, id2, id3]` → `metadata.resolves: ["id1", "id2", "id3"]`.
5. Mixing `--metadata '{"resolves":["id1"]}'` with `[refs: id2]` in content unions the two lists; the explicit metadata is not overridden.
6. Backwards compat: the existing `/xp-work-selection` per-pathway extraction continues to work (idempotent — extracting twice is a no-op).
7. No regression in the four currently-correct events from sprint-008 kickoff (`d65bee7ec7cb`, `8af0eef6d6f1`, `658fb7c86e35`, etc.).

## Out of scope

- Resolving the cited event ID to its content (richer diagnostics; nice-to-have, not needed to ship).
- Deciding which event types should be allowed to "resolve" what (e.g. should a `commit` event be allowed to resolve a `goal`? Today: yes; this request doesn't change that).
- Backfilling `metadata.resolves` on the four sprint-007 decisions listed above (one-time data fix; can be done with a manual script if desired).
- The `Resolves-Event:` commit-trailer path — already covered by `docs/feature-requests/commit-gate-resolves-event-trailer.md`.

## Contact / validation

SMM dir: `/Users/paulingalls/.claude/plugins/data/xp-agents-xp-agents/bce1d9c11420/smm`

Working examples (already correct, regression-test against these):

- `d65bee7ec7cb` — drop event, single ref wired
- `8af0eef6d6f1` — defer event, 5 refs wired

Counter-examples (should be wired but aren't):

- `393865f17dd1`, `52543ba3c8e7`, `baa4d2cb9b52`, `3ab1b301eef0` — sprint-007 decisions whose content references prior-retro Tries but `metadata.resolves` is empty.

Reproduce the wiring gap with one jq pipe (replace `$SMM_DIR` with the value from your `init.sh` output):

```bash
jq -c 'select(.id=="393865f17dd1" or .id=="52543ba3c8e7" or .id=="baa4d2cb9b52" or .id=="3ab1b301eef0") | {id, type, resolves: (.metadata.resolves // null)}' \
  "$SMM_DIR/events.jsonl"
```

Expected output: 4 lines, each with `"resolves": null`. Each `content` field clearly references a Try (verify by re-running with `, content` on the projected object), but the link is missing.

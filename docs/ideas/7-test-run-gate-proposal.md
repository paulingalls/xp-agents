# Proposal to xp-agents plugin author: test-run-gate

> **This is upstream-feedback, not a project rule.** It writes up a 5-sprint
> Try-carry pattern in this PoC so the xp-agents plugin author can decide
> whether to add a hook gate at the plugin layer. Adopting at the plugin
> layer means every consumer benefits; adopting only here would silo the
> rule and force every project to re-implement adjacent bookkeeping.

## Summary

**The ask:** add a `PreToolUse:Bash` hook in the xp-agents plugin that
blocks `git commit` (or `/xp-quality-review`) when ≥5 unique files have
been written since the last test-run event in the SMM. Honor a
`refactor mode:` / `TDD discovery:` assumption-event escape hatch.

**Why now:** the retrospective analyzer already surfaces this Try every
session when it detects the pattern. This PoC has carried it **5
consecutive sprints without adoption** — not because operators disagree,
but because the gate's bookkeeping (counting unique files between
test-run events in the SMM) lives natively at the plugin layer and is
awkward to bolt on at the project layer. The signal is real (max=7
files-since-test in sprint-012, threshold 5) and the suite stayed green
only by sample-luck, not discipline.

## The pattern (sprint-by-sprint)

| Sprint | Carry-Try event id (raised by retro) | Files-since-test max during sprint     | Disposition at next kickoff                                          |
| ------ | ------------------------------------ | -------------------------------------- | -------------------------------------------------------------------- |
| 008    | (first proposal, id not retained)    | (not measured)                         | Adopted as Try                                                       |
| 009    | (carry 1, id not retained)           | (not measured)                         | Deferred                                                             |
| 010    | (carry 2, id not retained)           | (not measured)                         | Deferred                                                             |
| 011    | `97212c4e4741` (carry 3)             | max=3 (under threshold)                | Deferred                                                             |
| 012    | `8e904f47e043` (carry 4)             | max=7 (threshold 5; sample-luck green) | Deferred                                                             |
| 013    | `b909ba666027` (carry 5)             | (this session — gate not yet live)     | Adopted via decision `49ff513cdeed` — artifact REDEFINED to this doc |

Sprint-013 kickoff broke the carry chain by redefining the artifact:
instead of implementing a local hook (the prior 4 sessions' implicit ask),
escalate the proposal to the plugin author.

## Why local implementation keeps deferring

- **Counter implementation cost**: the gate needs to track "unique files
  written since the last test-run event in the SMM" — the bookkeeping
  belongs near the hooks layer. The retro analyzer already derives this
  count post-hoc from the event stream (it reports
  `max_unique_files_without_test` per session, e.g. max=7 in sprint-012);
  a `PreToolUse` gate would need the same logic running live, which is
  natural at the plugin layer and awkward to re-derive from a project
  hook reading the SMM directly.
- **Per-project hook drift**: if every project hand-rolls the gate, each
  one drifts on threshold, on what counts as a "test run", and on how the
  TDD-discovery escape hatch works.
- **No clean uninstall**: a project-local hook landing in `.claude/`
  that's specific to xp-agents semantics blurs the plugin/project
  boundary the agent system otherwise keeps clean.

The plugin already owns the SMM, the retro analyzer, the metric
computation, and the hook scaffolding. Adding a gate is incremental
on the plugin side; doing it at the project layer means re-implementing
adjacent pieces.

## Proposed gate behavior

A `PreToolUse:Bash` hook on commands matching `^git commit\b` (or
`/xp-quality-review`, or both) that:

1. Walks SMM events back to the last test-run signal (the same input
   the retro analyzer uses today to compute
   `max_unique_files_without_test`).
2. Counts unique file paths from `file_write`-style status events in
   that window.
3. If count ≥ threshold (default 5; configurable per-project), block
   the action with a message naming the files and the threshold.
4. Honors a TDD-discovery escape hatch: if the operator has emitted
   an `assumption` event with content matching `^refactor mode:` or
   `^TDD discovery:` since the last commit, the gate is suppressed
   for that commit only.

Block message draft:

```text
TDD slip: 7 unique files written without a test run (threshold 5).
  - apps/astro/src/components/X.tsx
  - apps/astro/src/lib/Y.ts
  - ...

To bypass: emit an `assumption` event explaining the refactor or
discovery, then re-attempt the commit.
```

## Signal evidence (sprint-012)

From the sprint-012 retrospective input (file
`/Users/paulingalls/.claude/plugins/data/xp-agents-xp-agents/bce1d9c11420/smm/retrospectives/2026-05-01T01-16-03.json`):

> "TDD gap: 7 unique files written without test run (threshold 5).
> Test-run-gate Try now on 5th carry without adoption — green signal
> remains sample-luck not discipline. High priority."

The "green signal remains sample-luck" framing matters: the suite passed,
but the suite passed because the changes happened to align with existing
test coverage, not because the operator was honoring red-green-refactor.
A future change in the same area might land without test coverage and
the next signal would be a regression in production.

## What we'd commit to as a downstream consumer

- Set the threshold to 5 (matches retro analyzer's threshold today).
- Consume the gate as soon as it ships in the plugin; remove this doc
  if the plugin's own docs cover the rule.
- Log adoption-disposition events the same way we do for retro Tries
  today, so the plugin's analyzer can see whether the gate is working.

## Related events

- Earliest carry retained in current SMM: `97212c4e4741` (referenced
  by `8e904f47e043` as its predecessor; 4th attempt by sprint-012)
- Sprint-012 retro carry (4th attempt): `8e904f47e043`
- Sprint-013 kickoff carry (5th attempt): `b909ba666027`
- This-session adoption with redefined artifact: `49ff513cdeed`
  (resolves both `b909ba666027` and `8e904f47e043`)

## Maintainer notes

This doc is **operator-maintained, not auto-generated**. If the plugin
author lands a gate, replace this file with a one-line pointer to the
plugin's gate docs and let the next retro pick it up.

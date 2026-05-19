# xp-agents feedback: three stalled process Trys

**From:** divineruin project (paul@paulingalls.com), xp-agents 3.1.45
**Date:** 2026-05-19
**Context:** five consecutive retros have surfaced the same three process Trys
without any of them being adopted. The retros correctly diagnose the failure
mode ("silent carry IS the failure"), but the current skill design provides no
structural path to act on it. Each kickoff repeats the same suggestion; each
session ends with the same Try carried forward.

This document describes the three Trys, why they keep stalling, and the
behavior I think the skills should adopt. I am writing this as an XP customer
who would adopt these features the moment they exist.

---

## Try 1 — Resolves-Event trailer hard-gate
**Try id:** `fea0245d4e47` (first proposed sprint-005; 5th retro 2026-05-19)

### What the Try asks for
Block a commit (close-reviewer or pre-commit) when the staged diff references
an open concern/debt/question short-id in code or commit message and the commit
body does not carry a `Resolves-Event: <12-hex-id>` trailer for it.

### Current metric trajectory
Trailer-rate on commits that *do* resolve concerns:
`0.70 → 0.50 → 0.50 → 0.50 → 0.00`

The 5th retro hit a new floor. 16 concerns were resolved by commits in
sprint-008; zero trailers were emitted. Advisory reminders do not move the
metric. The skill currently has no place to enforce it.

### Why it keeps stalling
- Adopting it requires editing `xp-quality-review` or the pre-commit hook —
  both are skill internals, not customer-editable from the host project.
- A customer-side workaround (a project-local commit hook) is possible but
  duplicates xp-agents' own commit-gate logic, which has its own
  drift-vs-skill-updates problem.
- Each retro re-suggests "adopt this" without naming a mechanism, so it bounces.

### Concrete ask
1. Add a `commit_gate.require_resolves_event_trailer` flag to xp-agents
   project config. Default off.
2. When on, the close-reviewer step that already scans staged diffs for
   `concern/debt/question` short-ids also requires a matching `Resolves-Event:`
   trailer in the commit body. Block the commit (or fail the review with a
   single-line fix instruction) when one is missing.
3. Make the check forgiving on chore/doc commits where the short-id appears
   only in deletions (closing the loop by removing the workaround line).
4. Surface the count in retro input so the metric closes the loop on itself.

---

## Try 2 — Kickoff Try-disposition force-prompt
**Try id:** `5f1fb1d9d62f` (this kickoff), generalized from
re-proposal `713997fb62e5` and meta-Try `3844daa33af0`

### What the Try asks for
At kickoff, force an explicit `adopt / defer / drop` choice on every open Try
before any other work-selection step. Currently the kickoff *does* ask, but the
default for an un-clicked Try is "carry forward" — i.e., the silent path is
identical to "defer," and the metric is invisible at the moment of choice.

### Why it keeps stalling
- The work-selection skill already presents Trys; from a customer view it
  *looks* like the prompt exists. The failure is structural: there is no
  N-deferrals → forced-decision escalation.
- The 3-defer force-close gate exists in `work_selection_decide.py defer`
  (good!) but it only fires when the customer chooses defer. Silent
  no-clicks slip past it.
- The meta-Try `3844daa33af0` proposing the escalation was itself silently
  carried 4 retros.

### Concrete ask
1. In retro input, count `try_status.resolved_this_session=false` consecutive
   carries. After N (suggest 3), tag the Try `force_decision_required=true`.
2. In `xp-work-selection`, present force-decision Trys first, with no
   "carry forward" option — only `adopt / drop / defer-with-target-date`.
3. When the retro re-proposes a Try that is already at force-decision, name
   it in the Fix block rather than the Try block. Five retros in a row asking
   "please adopt this" is dishonest tooling.

---

## Try 3 — Deferred-to-debt auto-resolve
**Try ids:** original `1406f005cda5`, re-proposal `9eb1f2fc911a`, third
re-proposal `5925f7478f94`

### What the Try asks for
When a concern is deferred-to-debt (the customer chooses `keep-deferred` and
the SMM creates a debt event referencing the concern), the concern should be
auto-marked resolved with `resolver_id=<debt_id>` so it stops surfacing in
`### Open Concerns:` at the next kickoff.

### Current behavior
The concern persists as open until something else closes it. SMM grows noisier
each sprint as deferred concerns and their corresponding debts both surface
side-by-side, asking the customer to triage them twice.

### Why it keeps stalling
- It is a one-time structural change to `work_selection_decide.py
  triage-defer` — append a `resolves=[concern_id]` to the debt event the
  triage command already emits.
- The kickoff retrospective keeps flagging the SMM-growth metric, but the fix
  lives in a single CLI path that the customer cannot patch without forking
  the plugin.
- The Try has been adopted by the customer twice and still goes unimplemented
  because adoption is a goal event, not an implementation order.

### Concrete ask
1. When `xp-work-selection`'s `triage-defer` creates a debt for a concern,
   emit a `resolved` status event on the concern with
   `resolver_id=<new_debt_id>` and `disposition='deferred-to-debt'`.
2. Hide concerns with `disposition='deferred-to-debt'` from the preload's
   `### Open Concerns:` block; surface them only inside the debt's
   `references=` chain.
3. Retire the existing pattern wisdom `9d0ef1d4826c` ("Record deferred
   close-reviewer concerns as debt events with references=[concern_id]") —
   it was advice to the customer that the skill should now do automatically.

---

## Meta-observation

The xp-agents skill set is *good at telling you that you are not improving*.
The same retro signal fires every session, with increasingly emphatic Fix
wording ("5th retro below threshold," "NEW FLOOR," "silent carry IS the
failure"). The honesty value works.

What does not work: a customer-facing XP practitioner has no path to act on
process-improvement Trys from their host project. Code Trys land in the
project repo. Process Trys land in the plugin's source, which is plugin-owned.
Adoption requires the customer to either:

- maintain a fork of the plugin (and re-merge each release),
- file an issue and wait for plugin work,
- or accept that the Try is structurally unactionable and drop it.

Five retros of carrying the same Trys is the artifact of (b) silently happening
without any of us writing it down. This document is the explicit version of
(b).

### Suggested resolution

Pick whichever of the three Trys you most agree with and ship it. The metric
will close the loop. If none are landable, please consider a release note
telling customers to stop expecting them — that would also close the loop, just
the other way.

---

## Provenance
- Project: divineruin (`/Users/paulingalls/src/projects/divineruin`)
- SMM_DIR: `~/.claude/plugins/data/xp-agents-xp-agents/cf77350916c2/smm`
- Retros: `~/.claude/plugins/data/xp-agents-xp-agents/cf77350916c2/smm/retrospectives/`
- Kickoff date of this doc: 2026-05-19 (sprint-009 M1.5)
- Adopted as `decision` event `48a5b30aa0f6`,
  topic `retro-try-stalled-tries-feedback-doc`,
  resolves `5f1fb1d9d62f, fea0245d4e47, 5925f7478f94, 3844daa33af0`.

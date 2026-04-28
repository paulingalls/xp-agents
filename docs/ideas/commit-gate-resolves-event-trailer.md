# Feature request: hard-block commits that overlap open concerns/debt without a Resolves-Event trailer

**Plugin:** `xp-agents` (cached at `~/.claude/plugins/cache/xp-agents/xp-agents/2.25.0/`)
**Rule location:** the post-commit / commit-msg path that today emits a warn-only nudge when staged files overlap an open `concern` or `debt` SMM event and the commit body lacks `Resolves-Event:`. (Exact file unconfirmed; the warn-mode is observable in commit-attempt output.)
**Reporter:** AJE PoC, sprint-004 retrospective (2026-04-23)
**Linked decision:** SMM event `5fc0eaac950d` ("Adopt: hard-block git commit when staged files overlap an open concern/debt AND body lacks Resolves-Event trailer.")

## Current behavior

When a commit is created, the plugin checks two things:

1. Do the staged files overlap any **open** SMM event of type `concern` or `debt` (i.e. not yet `resolved` or `dropped`)?
2. Does the commit body contain a `Resolves-Event:` trailer matching the SMM 12-hex-char event-id format?

If 1 is true and 2 is false, a one-line warning is emitted but the commit lands. Agents see the warning and treat it as advisory.

## What we're seeing

The trailer-adoption rate has worsened monotonically across 4 consecutive sprints, despite the warn-mode rule running the entire time:

| Sprint     |                 Trailer rate (all commits) |
| ---------- | -----------------------------------------: |
| sprint-001 |                                        50% |
| sprint-002 |                                        33% |
| sprint-003 |                                        20% |
| sprint-004 | 17% (audit: 8/47 commits since 2026-04-19) |

Code-only commits (feat/fix/refactor) for the audit window: **5/17 = 29%** with the trailer. Most resolved concerns ARE actually addressed by the commit — they just aren't linked. The retro analyzer can't tell "this concern was fixed" from "this concern is still open" without the trailer, so retrospectives keep proposing already-completed work.

This Try has been **DEFERRED 4 consecutive sprints** despite the rate going the wrong direction. The session that adopted it (`5fc0eaac950d`) explicitly invoked stop-the-line: "Ship the bash_post_tool gate this sprint."

## Why this matters

1. **Traceability gap.** Concerns are addressed by commits but only ~17% are linked. The SMM resolution graph is incomplete — `Resolves-Event` is the structural signal a commit closes an event. Without it the retro analyzer relies on heuristics (overlap-by-files, content matching) that produce false negatives.
2. **Retros undercount resolution.** Sprint-003 retro reported "9 unresolved concerns" when in fact most were closed by commits in the same sprint (verified manually). Distorted velocity metrics drive bad Try-item proposals (e.g. "make QR a hard gate" was proposed based on a similar counting bug — see the QR-counting bug report).
3. **Warn-mode signal is lost.** Agents see hundreds of hook outputs per session; one-line warnings blend into the noise. Every other automated gate in this repo is a hard block (lefthook prettier/eslint/tests, the simplify→QR→security cycle). Inconsistent enforcement is worse than no enforcement.

## What we want

Hard-block (exit non-zero) when **both** conditions hold:

- Staged files overlap any open `concern` or `debt` event in the SMM, AND
- Commit body does not contain a `Resolves-Event:\s*[a-f0-9]{12}(\s*,\s*[a-f0-9]{12})*` match (case-insensitive, comma-separated IDs supported).

Comparison table:

| Case                                             | Today (warn) | Desired (block) |
| ------------------------------------------------ | ------------ | --------------- |
| Pure-doc commit, no overlap                      | passes       | passes          |
| Code commit, no overlap                          | passes       | passes          |
| Code commit, overlap, with trailer (resolves)    | passes       | passes          |
| Code commit, overlap, no trailer (silent close)  | warns        | **blocks**      |
| Mechanical reformat commit (already carved out)  | passes       | passes          |
| `style:` / `docs:` / `chore:` prefix, no overlap | passes       | passes          |

## Suggested detection strategies (ranked)

1. **commit-msg hook reading the in-progress message file** (passed as `$1` by git). Cross-reference staged files against open events from the SMM. Most precise; runs before the commit lands. If the trailer is missing AND overlap exists, exit non-zero with a one-line diagnostic listing the offending event ID(s) and a hint to add `Resolves-Event: <id>`. **RECOMMENDED.**
2. **pre-commit hook** with a marker file + post-commit revert+nudge. Destructive (rewrites history); rejected.
3. **lefthook `pre-push` gate.** Too late — bad commits already local; the linkage gap is captured by then. Rejected.

The mechanical-reformat carve-out (separate doc, already adopted in v2.22+) should layer cleanly on top of this rule: pure-formatter commits don't trigger the file-count flag and shouldn't trigger the trailer flag either, since by definition they don't address concerns.

## Acceptance criteria

1. Hard-block triggers when staged files overlap any open `concern`/`debt` event AND body lacks the trailer regex.
2. Passes when the trailer is present (case-insensitive, comma-separated IDs supported).
3. Passes when staged files don't overlap any open event.
4. Passes for `style:` / `docs:` / `chore:` prefixed commits regardless of overlap (these are non-code-review-required by the same convention `xp-quality-review` uses to skip).
5. Configurable severity (`warn` / `block`) via plugin setting; default `block`.
6. One-line diagnostic on block lists the overlapping event ID(s) and points at this doc URL or a `xp-agents` help command.

## Out of scope

- Validating that the referenced event IDs actually exist (a malformed/stale ID is a separate problem; this rule only checks trailer presence).
- Back-filling old commits with trailers.
- Resolving the trailer ID to the event content for richer diagnostic output (nice-to-have, not needed to ship).

## Contact / validation

SMM dir: `/Users/paulingalls/.claude/plugins/data/xp-agents-xp-agents/bce1d9c11420/smm` (sprint-004 of the AJE PoC project).

Validation commit hashes from this branch (`main`):

- **Should pass under desired rule:** `5dfc83c` (sprint-003 web-vitals collector; trailer present and links 4 events the diff actually closes).
- **Should block under desired rule:** `fd57978` (sprint-003 qwik web-vitals shim; staged files overlapped open concerns at the time but body lacks any `Resolves-Event` trailer).

Reproduce the metric: `git log --since="2026-04-19" --pretty=format:"%H%x00%s%x00%b%x01" | python3 -c "..."` (script in the SMM event log if needed).

---

## Status update — 2026-04-27 (sprint-007 retro, plugin v2.30.7)

**Still warn-only after 5 minor plugin releases (v2.25.0 → v2.30.7).** The trailer-adoption rate has stopped getting worse but plateaued well below the 80% threshold the retro analyzer uses as a health bar:

| Sprint     | Trailer rate (all commits) |
| ---------- | -------------------------: |
| sprint-001 |                        50% |
| sprint-002 |                        33% |
| sprint-003 |                        20% |
| sprint-004 |                        17% |
| sprint-007 |          **78.5% (11/14)** |

Sprint-007 climbed because shared-csp story-009 explicitly used `Resolves-Event:` in 4 commits. The improvement was driven by a human-authored story with the trailer in the AC, not by the warn-mode hook.

**Probe-adoption rate (probe = retro nudge to add trailer): 0%.** The retro fired probes on 1 escape + 1 divert candidate; neither was adopted. Tied diagnostic of BOTH the nudge ergonomics AND the candidate quality (both buckets resolve to 0 — not enough signal to choose). At zero adoption, warn-mode has no measurable behavioral effect.

**This Try has now been formally dropped (sprint-008 kickoff, event `d65bee7ec7cb`)** because it has been deferred 13 consecutive sprints without shipping. The kickoff explicitly accepted "78.5% trailer rate + 0% probe-adoption as the design ceiling" under warn-mode.

That decision is the customer side accepting the cost of NOT shipping the gate. **Until the gate ships, the retro analyzer's "unresolved concern" counts will continue to read high because most resolutions are silent (no trailer → no structural link → analyzer relies on heuristics).** This is the trade the customer has now formally accepted; the feature request remains open for the plugin developer's roadmap consideration but is no longer being actively championed from this project.

**Reaffirmed acceptance criteria — same as original.** No design changes; the ask is unchanged. The status update is to record that the customer has stopped self-flagging this each sprint.

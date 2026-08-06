# Prose Hygiene: Cleaning Up Comments, and Keeping Them Clean

**Status:** idea / proposal
**Prompted by:** the 2026-07-24 cleanup session, where four of four findings in the
final review round were stale comments/docstrings — written within the preceding
hour, while removing other cruft.

## The problem, stated precisely

This tree is not carrying dead *code*. An audit found 187 of 195 shipped modules
have live callers, all 31 markers are referenced, and essentially one finished
thing to delete. What it carries is **prose that has stopped being true.**

Measured on shipped Python (excludes tests):

- 42,468 lines, of which ~33% is prose (≈24% docstrings, ≈10% comments).
- 51 functions with docstrings ≥25 lines; longest is 73.
- Test-to-code ratio 3.3×.

The XP instinct — "comments rot; make the code explain itself" — is right about
most of that 33%. But a blanket delete would destroy a minority that is not
documentation at all and cannot be expressed as code. So the job is a
**classification**, not a purge.

The deeper problem is a *flow* problem, and it is the same shape as every other
issue this project keeps finding: an additive pipeline with no reverse gear.
Three shipped guidance surfaces actively route overflow **into** comments —

- `agents/xp-system-analyzer.md:215` — "implementation details … live in code comments"
- `agents/xp-housekeeper.md:116` — "tooling-specific troubleshooting … belongs as code comments"
- `PROCESS_GUIDE.md:22` — "Implementation details belong in code comments"

— and **nothing** applies counter-pressure on whether those comments stay true.
Comments are the bucket everything gets pushed toward and nothing gets pulled
from. That is why the ratio only grows.

---

## Part 1 — How to clean up the prose

Do **not** delete all comments. Classify every one into four buckets. Three are
mechanical; the fourth is the actual work.

### Bucket A — DELETE: the comment restates the code

Docstrings that paraphrase the signature, comments that narrate the next line.
Pure rot-bait. Python invites these because the docstring convention fires
whether or not you have anything to say.

> `event_helpers.events_of_type` — *"Return events whose `type` field equals
> `type_name`."* The signature already said that. Delete.

**Test:** cover the docstring, read the signature and body. If you learned
nothing from the docstring, it goes.

### Bucket B — DELETE: tombstones and history

Comments narrating what *used* to be here, which release removed something, how
the code got to its current shape. Git already holds this, losslessly, and the
comment is a second copy that rots independently of the first.

> The `iteration_complete` removal (this session) initially left a 9-line
> in-body comment reciting the deleted code and duplicating the changelog. The
> close reviewer flagged it; it was cut to the load-bearing line.

**Test:** does the comment describe code that exists, or code that doesn't?
"Doesn't" → delete. `git blame`/`git log` is the tombstone.

### Bucket C — CONVERT to a test: a checkable "why"

This is the highest-value move and the most XP-native one. A comment stating a
premise that *could be verified* rots **silently** — nothing fails when it stops
being true. The same premise as a test rots **loudly** — it goes red the day it
breaks.

> `lint_budget._MATERIALLY_SHORT_S = 5.0` shipped with a ~25-line comment arguing
> the margin must exceed `staged_lint`'s pre-batch overhead. The close reviewer's
> note was exact: derive the fixtures from the constant and **test both sides of
> the boundary**, so weakening the margin fails a test instead of a code review.
> The comment is the hypothesis; the test is the proof that rots loudly.

Other convert candidates seen this session:

- "Library only — one entry point, deliberately" (`sprint_save.py`) → a test
  asserting exactly one public writer of the whole-sprint file. Today that
  invariant is defended only by prose; a second door would pass every test.
- "The `.accept` unlink here is a third-line fallback; the real clearers are
  the accept preload and the SessionStart sweep" → a test asserting the preload
  consumes the marker, so the fallback's *fallback-ness* is pinned.

**Test:** could a machine check this claim? If yes, it belongs in `tests/`, not
in a comment. Move it. Leave at most a one-line pointer to the test.

### Bucket D — KEEP: the irreducible residue

Three kinds genuinely cannot become code, and are where the value density is
highest. Do not touch these except to tighten wording.

1. **"Why not" — the rejected design.** Self-documenting code can only describe
   what exists; it is structurally incapable of saying "don't build the obvious
   thing, here is the bug that follows." `sprint_save.py`'s *"a second
   `python3 sprint_save.py` door would reach `run()` without the branch-name
   preserve and silently re-drop every recorded branch_name — the exact bug
   story-005 closed"* has no code form. Delete it and someone adds the door in
   good faith. (This session, a reviewer or I nearly re-introduced a just-deleted
   thing three separate times, each caught by exactly this kind of comment.)

2. **External constraints the code cannot contain.** `BATCH_TIMEOUT_CAP_S = 40.0`
   looks arbitrary; the comment says it is a *ceiling* — it must stay under the
   harness's 60s hook timeout, past which the hook is killed, exits no-2, and the
   gate **fails open**. The literal `40` does not and cannot know why it is not
   `60`. ~180 comments in this tree carry fail-open/fail-closed/invariant
   knowledge of this kind.

3. **Machine-checked markers wearing comment syntax.** `# lang-ok:` (parsed by
   the leak test), and the 96 `# noqa` / `# type: ignore` / `# pyright:`
   directives. These are code in a costume — deleting one breaks a tool or a
   test. Never in scope for prose cleanup.

### Suggested execution order

1. **Sweep A and B mechanically, per module.** Cheap, high volume, no judgment.
   Expect the largest line reduction here for the least risk.
2. **Triage C in review.** Each conversion is a small red-test-first task; batch
   them per subsystem so the tests land beside the code they pin.
3. **Leave D alone**, tightening only wording. If a D comment runs long
   (≥25 lines), that is a signal the *code* lost an argument and got defended in
   place — the fix is to simplify the code so it needs less defense, not to trim
   the comment.

### One measurement to run first

Before touching anything, get a per-module prose ratio and a list of the ≥25-line
docstrings (there are 51). The long ones are where the value *and* the smell both
concentrate — start the C/D triage there, not in the A/B noise.

---

## Part 2 — Building the wisdom in, so it does not recur

Cleaning up once is a bucket-bail. The tree fills again unless the pipeline gains
a reverse gear. Four proposals, ordered by leverage. The first two ship to
**every project that uses the plugin**; the last two are local.

### 2.1 — Give the review agents an explicit prose-hygiene lens (ships to users)

The `xp-code-reviewer` already lists "what-not-why comments" — once, buried in a
seven-item quality list (`agents/xp-code-reviewer.md:60`). It is not a first-class
check, and the close reviewer has no prose lens at all, which is why four stale
comments sailed through the multi-agent review and were caught only by the
file-diffing close reviewer.

Promote it to a named review dimension in **both** `xp-code-reviewer.md` and
`xp-close-reviewer.md`, phrased as the four-bucket test above:

- Flag a comment that **restates** the code (A) or **narrates removed history**
  (B) as a Concern — with the fix being *delete*, not reword.
- Flag a **checkable claim living in a comment** (C) as a Concern whose fix is
  *convert to a test*.
- Flag a docstring **≥25 lines** as a simplification smell (the code, not the
  prose).
- Explicitly **exempt** D (rejected-design, external-constraint,
  machine-checked markers) so the lens does not attack the valuable residue.

Keep it project-agnostic: the rule is about comment *kind*, not any language's
syntax, so it holds for TS/Rust/Go projects too.

### 2.2 — Close the inflow pump (ships to users)

The three "→ code comment" routing lines (`xp-system-analyzer.md:215`,
`xp-housekeeper.md:116`, `PROCESS_GUIDE.md:22`) send overflow into comments with
no hygiene attached. Amend each to route by **checkability**, not by default:

> "Implementation detail → a comment **only if it states a why/constraint the
> code cannot express**; a *checkable* claim → a test; *history* → git, never a
> comment."

This is the single highest-leverage change: it stops the pump at the source, in
the guidance every user project inherits.

### 2.3 — A prose-hygiene tripwire, modeled on the leak test (local, optional)

The cross-language leak test (`tests/hooks/test_no_language_leak.py`) is the
proven pattern here: an AST walk over shipped code that fails when a forbidden
shape appears. A analogous, deliberately narrow tripwire could pin the two
**mechanically detectable** rot signatures:

- a docstring whose body is a near-restatement of the signature (Bucket A), and
- a per-module prose ratio or max-docstring-length that ratchets **down only**
  (never up), so the number cannot silently grow.

Scope it like the leak test: a *floor*, not a ceiling; catches the cheap cases,
explicitly documents what it cannot catch (intent, staleness — those stay
human-reviewed), and carries a vacuity guard so it cannot pass by matching
nothing. Do **not** try to detect staleness or "why-ness" automatically — that is
the leak test's own hard-won lesson, and over-claiming coverage is itself the
failure this whole effort is about.

### 2.4 — Name the pattern as durable Wisdom (local + seeds forward)

Record the root lesson as an SMM Wisdom item and a system_context principle, so
it survives into the daily-rendered guidance rather than living only in this doc:

> *Checkable claims go in tests, where they rot loudly; comments are for the
> why/constraint the code cannot express. History lives in git. A comment is a
> claim with no test — treat a long one as a code smell, not documentation.*

The general principle behind all four: **this project's characteristic defect is
the fail-silent one** — a gate that stops gating, a metric always zero, a comment
describing code that no longer exists. Tests fail loudly by construction; prose
does not. The fix is never "add more prose." It is to move every claim that
*can* be executed into executable form, and accept prose only for the residue
that genuinely cannot be.

---

## What NOT to do

- **Do not delete Bucket D** to hit a line target. The rejected-design and
  external-constraint comments are the hardest-won knowledge in the tree and have
  no other home in Python.
- **Do not do a single "delete the comments" sprint.** This tree's failure mode
  is fail-silent; a mass edit in a fail-silent codebase trades a prose problem
  for a correctness one. Go per-subsystem, red-test-first for every C conversion.
- **Do not build a staleness detector.** No tool can tell a true comment from a
  false one; that is precisely why the knowledge belongs in tests. The tripwire
  (2.3) pins *shape*, not *truth*.

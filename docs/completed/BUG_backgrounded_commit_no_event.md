# Why most commits produce no commit event

Diagnosis for story-012. Measured 2026-08-08 against the live SMM at
`~/.xp-agents/data/726204ef3541/smm/events.jsonl` and this repo's history.

## The symptom

Over `711f5c4a..paulingalls/sprint-002-prose-scan-ab-sweep`:

| | with a commit event | without |
|---|---|---|
| merge commits | 7 | 1 |
| **plain commits** | **5** | **19** |

79% of ordinary commits leave no `type: "commit"` event. Merges are covered
because the close pipeline has a dedicated emitter (`merge_commit_event.py`)
that runs independently of the Bash hook. Everything a commit event carries —
`metadata.resolves` from a `Resolves-Event:` trailer, `code_file_count`,
`review_cadence`, story attribution — is lost for the rest.

## The cause: the commit was backgrounded, so the hook fired before git ran

`_handle_commit` runs from `PostToolUse:Bash`. That fires when the **tool call
returns**, not when the command finishes. For `Bash` with
`run_in_background: true` the tool returns at *launch*: the response text is
the harness notice (`Command running in background with ID: …`), git has not
yet written anything, and HEAD has not moved.

Every branch of `_handle_commit` then reads the wrong state:

* `commits.parse_commit_message(response_text)` finds no `[branch hash] msg`
  line, because git has produced no stdout.
* `commit_event._head_matches_command` compares this command's `-m` message
  against HEAD — which is still the *previous* commit. No match.
* `_confirm_commit_repo` therefore returns `(None, "")`, and control reaches
  the HEAD-probe branch.
* `commit_emit.rebuild_at_head` refuses, because
  `_message_unreadable_from_command` is False: the message *was* readable, so
  the rebuild reads the mismatch as positive evidence that this command did
  not produce HEAD.

Then the command finishes minutes later and **no hook fires at all**. The
commit's event is never built.

### Evidence

Correlating every `git commit` Bash call in the session transcripts under
`~/.claude/projects/…worktree-story-*/` against the recorded commit hashes:

* 16 of 16 commits whose Bash call carried `run_in_background: true` produced
  **no** commit event.
* Every commit that *does* carry an event was committed in the foreground.

No counterexample in either direction.

Two false concerns are the fingerprint the bug left behind — `82270ff1ef50`
(story-008) and `cb34b4773b37` (story-009), both reading *"A git commit command
ran and HEAD points at a commit with no recorded event (its message did not
parse)"*, both stamped with the hash of the teammate's **previous** background
commit. Their timestamps line up with the launch of the *next* background
commit, not with either commit landing — which is the timing claim above, read
straight off the log.

### Why teammates background their commits and the lead does not

The `pre-commit` hook runs `pytest -n auto`. Under several concurrent
teammates that exceeds the Bash tool's 2-minute default timeout, so a teammate
whose foreground commit is killed at 2m relaunches it with
`run_in_background: true`. The lead, committing alone, stays under the timeout.
That is the whole of the story-011-vs-story-008/009/010 contrast: not `git -C`
versus a bare `git commit`, and not worktree versus main checkout.

## Which hypothesis held

Of the three the story listed, **hypothesis 2 (invocation path)** — but not the
`git -C`-versus-bare-`git commit` split it proposed. The discriminator is
foreground versus backgrounded.

* **Hypothesis 1 (message shape) is disproved.** `recover_commit_message`
  parses the canonical `-m "$(cat <<'EOF' … EOF)"` form correctly, including
  the exact command strings from the two commits that traced. Verified
  directly against `1e44a092`: the recovered subject equals HEAD's subject and
  `_head_matches_command` returns True. Concern `161dc298c5d0`, which reopened
  this on the suspicion of an unparsed *variant*, is answered: there is no
  variant. The parser was never the problem; it was reading a HEAD the command
  had not yet moved.
* **Hypothesis 3 (dedup over-firing) is disproved.** `_commit_hash_recorded`
  is doing its job. It does explain the *silence* of the first background
  commit in each worktree — HEAD then still points at the recorded merge the
  branch was cut from, so the trace is correctly suppressed — but it never
  discarded a first commit.

## The fix

A backgrounded launch is not evidence about anything the command did, because
the command has not done it yet. Two consequences, both in
`commit_emit.rebuild_at_head`'s guard:

1. The readable-but-mismatched message must stop counting as evidence against
   recording. It is only evidence when the command has actually run.
2. HEAD at that moment is frequently the *previous* backgrounded commit,
   unrecorded for exactly this reason. The rebuild's own claim — "a commit
   exists at this hash with no event, and here is its message read back from
   git", explicitly *not* "this command produced it" — is precisely the claim
   that fits, and `_head_is_a_freshly_landed_commit` (fresh, single-parent,
   reflog says `commit`) already bounds it.

So `rebuild_at_head` gains a `backgrounded` flag, threaded from the Bash tool
input, that bypasses the message guard and leaves every other guard standing.
The next commit-shaped command in the repo then recovers the previous one.

### What this does not fix

Recovery happens at the next commit-shaped Bash call that **itself fails
confirmation**, which is the branch the HEAD probe lives on. A backgrounded
launch always fails it, so a run of background commits recovers all but its
last. Two shapes still lose one:

* the last backgrounded commit before an agent stops committing;
* a backgrounded commit followed by a **foreground** one, which confirms
  normally, records its own event and returns without ever probing the prior
  HEAD. Measured, not inferred.

That is one commit per teammate run rather than every commit — 79% loss becomes
roughly one-per-story — and the close-cycle merge emitter still re-derives its
trailers, which is why nothing was ever permanently lost.

Closing the residual needs an observation point this story does not own: a
`PreToolUse:Bash` refusal of a backgrounded `git commit` (pointing the author
at a foreground run with an explicit `timeout`), or a HEAD sweep at
teammate-idle/stop. Recorded as debt.

The freshness bound is also tight for this shape. `HEAD_REBUILD_MAX_AGE_SECONDS`
is 600, and the observed gap between one background commit landing and the next
one launching was 5–6 minutes; a slower pre-commit chain would push past it and
lose the recovery. Left as-is — widening it would weaken the guard for every
other caller — but it is the next thing to check if the loss rate stays high.

## Blast radius the fix creates

`commit_handling._prior_commit_was_test_only` reads the **most recent commit
event**. At 79% loss that is usually a merge event or a commit several steps
back; recovering the intermediate commits makes it the actual previous commit,
which shifts `is_tdd_red_step` tagging and therefore `work_signals`
regression-streak counting. The tests that cover those two:

* `tests/hooks/test_tdd_red_signal.py::TestIsTddRedStepCommitBased::test_clean_tree_prior_test_only_commit_is_still_red_step`
* `tests/hooks/test_tdd_red_signal.py::TestIsTddRedStepPrecomputedTree::test_precomputed_false_falls_through_to_commit_signal`
* `tests/hooks/test_work_signals.py::TestWorkSignalsM2Actions::test_tdd_red_run_does_not_increment_consecutive_failures`
* `tests/hooks/test_work_signals.py::TestWorkSignalsM2Actions::test_test_run_action_failure_increments_consecutive_failures`
* `tests/hooks/test_work_signals.py::TestWorkSignals::test_max_consecutive_failures_three_reds`
* `tests/hooks/test_work_signals.py::TestWorkSignalsBatchPartition::test_committing_twice_as_often_scores_materially_lower`

The direction of the shift is toward correctness: a test-only commit followed
by a failing run is a deliberate red step, and today it is missed whenever the
commit that would prove it went unrecorded. The new arm is gated on
`backgrounded`, which is False everywhere in the existing suite, so none of
those tests change behaviour — they are named because a green suite that never
exercised the new density would prove nothing about it.

## Debt `4aa345599eba` was misdiagnosed

The debt reads: *"A `Resolves-Event:` trailer links a commit to an event for
the merge advisory but does NOT close it."* It is false.

Commit `84bfd65e` carried `Resolves-Event: 3076e54c77de` and nothing else — no
manual resolve event was ever appended — and `resolution.compute_resolutions`
reports `3076e54c77de` as closed. The trailer closes its target exactly as
`PROCESS_GUIDE.md` says.

What happened on `d7dacbca`, the commit the debt cites: it carries two trailers
(`2159b674d2c7`, `01c9c8b9b3e0`) and has **no commit event at all** — it is one
of the 19 above, committed in the background. No event, no `metadata.resolves`,
nothing closed. The only event in the log that resolves either id is the merge
event `411150867a9a` (commit `bacb1531`, `is_merge`), which re-derived both
trailers from the merged range; both ids were compacted out of the live log
shortly after it landed. The author saw a real symptom and inferred the wrong
mechanism.

The close-skill prose telling authors to resolve via `Resolves-Event:` in the
fix commit is correct and stays as written.

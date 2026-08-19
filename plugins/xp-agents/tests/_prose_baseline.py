#!/usr/bin/env python3
"""What the `scripts/` prose ratchet measures, and what it tolerates.

PER FILE, IN ABSOLUTE LINES. The ratchet this replaced compared one whole-root
RATIO against a number recorded on an earlier tree, and that shape fired twice
on work that rotted nothing:

  EXTRACTION. Splitting a file, which CLAUDE.md's 500-line rule demands, adds a
  module docstring and a header without adding the code they describe, so the
  extracted module raises the ratio purely by existing.

  CLAIM-NARROWING. A true claim is usually longer than the false short one it
  replaces, so correcting prose RAISED the number — the ratio moved against
  exactly the work milestones 1 and 3 exist to produce.

EXTRACTION no longer moves anyone else's number: an extracted file is measured
on its own terms. It is not free, though. Above the floor it still reddens on
arrival, because the tree drives the loop and it has no entry yet — but the fix
is to RECORD the number it arrived at, not to golf prose down to somebody
else's, which is the part the ratio got wrong.

CLAIM-NARROWING is NOT gone. Any line-counting measure moves against it, and
this one still does — it is only localised, to the one governed file the
correction lands in, and bounded there by the slack below. A correction longer
than that slack still reads as a regression, and the pressure to golf out
accurate rationale to get green survives with it. That gap is smaller than the
ratio's, not closed.

A per-file measure does close the defect the named-set fix left behind: a sum
let one file's honest shrink pay for another's regrowth, which no per-file
comparison can express.

WHO IS GOVERNED. The pin walks the TREE and reads this table for numbers, so a
file above the floor with no entry here is a violation, not an exemption. That
is the reverse direction (concern 469b5b0a87a5) by construction rather than as
a separate leg — under the old named set, a file the tree gained afterwards was
unmeasured for as long as the set stood, and two were.

Below the floor a file is ungoverned, but by a uniform rule rather than by
omission, and it becomes a violation the moment it crosses. So the floor sets
where explicit ceilings begin, not where enforcement does.

RETIREMENT IS MANDATORY, not tidying. An entry for a file that has since shrunk
below the floor is a re-entry allowance: the comparison stops running, so every
deleted line can come back to the old number with nothing red. The pin requires
the entry to go, which banks the deletion as the new bound.
"""

# Prose lines per file, re-measured on 2026-08-11 during sprint-003's close —
# NOT a pre-sprint baseline. Several entries absorbed this sprint's own growth,
# which is what a re-record is for and also its weakness: nothing here refuses
# an upward one, so each regeneration renews the slack below. Recorded as debt
# rather than hidden.
# Recorded separately from the allowance below so a reader sees the observation
# and the tolerance as two numbers, not one fudged one. GENERATED from
# `_prose_scan`, never hand-typed: a hand-edited number is indistinguishable
# from a raised one.
PROSE_MEASURED: dict[str, int] = {
    "plugins/xp-agents/scripts/_common.py": 164,
    # 123 -> 133: the non-commit branch now says why the catch-up observer sits
    # there rather than on every Bash, and why it runs before the xp-agent
    # return. Both are decisions a reader would otherwise reverse — the first
    # looks like an oversight, the second like a leak.
    "plugins/xp-agents/scripts/bash_post_tool.py": 133,
    "plugins/xp-agents/scripts/branch_lifecycle.py": 149,
    "plugins/xp-agents/scripts/branch_resolution.py": 207,
    "plugins/xp-agents/scripts/branching.py": 180,
    # 128 -> 151 (story-019): the handler now computes the blocking hook's
    # own refusal verdict before running a preload, and the new function
    # carries why it CALLS those predicates instead of respelling them, why
    # it no-ops on the second harness, and that the two processes race
    # benignly. A reader without those would reasonably delete the call.
    # 151 -> 154 (story-009): `_refresh_heartbeat`'s docstring said ordering was
    # "the whole point" because the preload refused on a stale heartbeat. That
    # reader is deleted, so the claim was false and the replacement has to say
    # what the write is FOR now — two consumers that never lived in this file.
    # This is the claim-narrowing case above: the true statement is longer than
    # the false one it replaces. Cut three times first; a fourth pass would have
    # been deleting the reason, which this table says the measure must not buy.
    "plugins/xp-agents/scripts/preload_injection.py": 154,
    "plugins/xp-agents/scripts/close_cycle_abandonment.py": 139,
    "plugins/xp-agents/scripts/close_cycle_stop_gate.py": 163,
    "plugins/xp-agents/scripts/close_gate_commands.py": 149,
    "plugins/xp-agents/scripts/commit_command.py": 272,
    # Re-measured 173 -> 187 -> 192 and 145 -> 166 at the back-merge that
    # brought this table onto the commit-path branch. The table was measured on
    # a tree that did not contain that branch's work, so 187 and 166 were the
    # FIRST measurement of these two files, not raised ones — and both grew for
    # the reason this ratchet's docstring says it still moves against: a close
    # review demanded the longer true claim (why a reflog action is matched as a
    # leading word and not by equality; why only a lock ACQUIRE is wrapped and
    # never the body). `coordination.py` also shed two duplicated raw-`fcntl`
    # blocks for one helper, so its prose rose while its code fell.
    #
    # 187 -> 192 is a SECOND re-record of the same file in the same branch, and
    # that is the shape to be suspicious of. What earned it: dogfooding the
    # back-merge found the leading-word match above claiming a fast-forward as a
    # merge, recording another clone's commit as ours. The fix turns on a design
    # decision (allowlist the reflog detail, never denylist it) that has to sit
    # next to the constant it governs. The comment was cut three times to fit
    # 189 first; a fourth pass would have been deleting the reason, which is
    # what the docstring above says this measure must not buy.
    # 192 -> 223 converging the merge policy into `build_commit_event`. A THIRD
    # re-record of this file, which is the shape to distrust, so what earned it:
    # the change removes a parameter and replaces it with a derivation, and three
    # of the four decisions behind that derivation are ones a reader will
    # otherwise undo — union-not-replace on `resolves`, authored-only for both
    # `has_resolves_trailer` and the advisory, and absent-count-leaves-untagged as
    # the safe direction. What was NOT kept: the replacement alternative is argued
    # in `TestWhatTheMergeEventResolves` and proven by mutation there, so the code
    # comment now points at it in one line instead of restating it in seven. That
    # is this table's own rule for a rejected alternative a test already pins.
    # 223 -> 233 for the close review's three confirmed defects. What earned it:
    # the merged-range derivation had to be bounded to commits whose own event
    # never landed, and the reason a bare parent count is not that bound — a
    # back-merge is two-parent too, and its incoming range is everything the
    # branch had not seen — is the argument a future reader would otherwise
    # remove the filter for. The size-concern exemption is now real code in
    # `commit_handling.py` rather than a claim here, so its prose moved to where
    # the gate is instead of being duplicated.
    # Then 239 for the close review: the derivation bound had to say LIVE log
    # rather than "already recorded", because compaction archives events and a
    # rebased branch never matches — the reviewer found the prose stating the
    # bound unconditionally, which is the exact failure mode this branch keeps
    # repeating.
    # 249 when the THIRD emitter converged onto `merge_resolves`. The helper now
    # carries the whole argument for the bound, the union and the live-log caveat,
    # because it is the one place all three routes read it — and the close
    # emitter's old "a merge subject never carries a trailer" reasoning had to be
    # written down as false, or converging it looks like a style change.
    "plugins/xp-agents/scripts/commit_emit.py": 249,
    # 167 -> 170: `is_merge` in the metadata table now says ANY merge HEAD, not
    # "close cycle, or the rebuild's merge arm" — that reading is what produced
    # the story_metrics defect.
    # 170 -> 184: `recorded_commit_hashes` arrives with the live-log bound
    # written down. Three callers now dedup against this index and each had
    # hand-rolled the walk; the caveat that "absent" means "not visible from
    # here" rather than "never recorded" is the part a fourth copy would drop.
    # 184 -> 196 (story-018): `_resolve_story_id` gained `from_commit_only`, and
    # the six added docstring lines are the fix — the guard itself is four lines
    # of code. They say why Tier 1 is cut alongside Tier 2, which is the half a
    # reader would otherwise restore: a `.story-assignment` looks explicit but
    # names the CHECKOUT's story, not the commit's. Re-recorded rather than
    # golfed, which is this table's own stated rule; the fuller argument lives
    # in test_commit_observer_claims.py, where no ratchet governs it.
    "plugins/xp-agents/scripts/commit_event.py": 196,
    # 161 -> 168: the commit-size gate now states why a merge is exempt, which
    # is where that reasoning belongs — it was asserted in commit_emit.py while
    # no code implemented it.
    "plugins/xp-agents/scripts/commit_handling.py": 168,
    # 175 -> 156, a re-record DOWNWARD after the message-parsing half moved to
    # `commit_trailers.py`. Nothing forced this: 156 sits under the old
    # 175 + slack, so the pin was already green. Recorded anyway because the
    # docstring's own rule for a deletion is to bank it as the new bound — left
    # at 175 this file would carry 24 lines of silent regrowth allowance, earned
    # by an extraction rather than by anyone writing a shorter true claim. The
    # extracted file measures 39 prose lines, below the floor, so it is
    # ungoverned and gets no entry of its own.
    #
    # Then UP again in the next commits, for `head_parent_count` and back DOWN when
    # the merged-range readers left for `merged_range.py`. Spending a banked
    # deletion immediately looks like the banking was pointless; it is the
    # opposite — measured against the banked number the growth is visible, where at
    # the old 175 it would have been free and a reader could not tell the file had
    # grown at all.
    #
    # NO ARROWS HERE, deliberately. An earlier version of this note narrated
    # "156 -> 170" and "+14" beside a pin that had since become 167, because the
    # arrows are hand-typed while the pin is generated — the third stale number in
    # this table in one sprint. The rule the table already states (numbers come
    # from `_prose_scan`, never a keyboard) applies to prose ABOUT the numbers too.
    # 167 -> 182 for the two rev-parameterized reads. `get_commit_files` has to
    # say why it is not a rev argument on `get_committed_files` — that one
    # diffs against the WORKING TREE, so the obvious merge of the two would
    # silently change an existing caller's answer on a dirty checkout.
    # Re-recorded for the ghost filter: the rule it applies is narrower than the
    # obvious one and the difference is invisible from the code, so the reader
    # needs to be told what is NOT excluded (a staged `git rm`, a deletion
    # already committed) or the next edit widens it back and quietly stops
    # counting deletions.
    # 202 -> 164: the working-tree question moved to worktree_state.py, and
    # its prose went with it. Banked rather than left at 202 — a ceiling kept
    # above a completed split hands back the ground the split just won.
    # 164 -> 171: the ghost rule gained its third clause, and the reason it has
    # one is not derivable from the code. A path is only a ghost while the
    # command leaves it unstaged, so the docstring must say that membership in
    # the deletion set is necessary and NOT sufficient — the first rule read it
    # as sufficient and the gate went silent on a commit deleting three code
    # files. The call site's own note is three lines because the enumeration of
    # stage-all forms lives beside the regex in git_commits.py, not restated.
    # --- and, from main ---
    # Re-measured after the review-scope budget and the HEAD-distance reader
    # landed, and after `get_filenames_from_diff` left for `diff_filenames.py` —
    # the extraction took prose out of this file, so the number is a re-measure
    # of what remains, not a straight allowance for what was added.
    # 179 -> 190 for the close review's two fixes, each of which a future reader
    # would otherwise undo: `include_untracked` is a separate flag because a
    # wider set FORGIVES for one caller and BLOCKS for the other, and
    # `count_commits_since` counts first parents because counting a merge's whole
    # range measured 6 landings against a cap of 2.
    # 200 -> 209: budgeting the ghost read. The fork had to be told what the
    # rest of the scan already knew, and both halves of that need saying — why a
    # fifth read cannot sit on the per-call default, and why its leg is counted
    # when it CAN run rather than when it will. The pin that caught it is named,
    # because the next reader's instinct is to drop the parameter again.
    # 171/190 -> 200 (merge of main into sprint-007): the two branches grew
    # this module along DIFFERENT axes — the ghost filter here, the review-scope
    # flags and scan budget there — so the merged file is a union and neither
    # side's number describes it. Measured, not chosen. Both histories are kept
    # above because each explains a guard the other side's reader would undo.
    # 209 -> 204 deleting an orphaned comment: it explained the `-z` flag on
    # three constants story-016 moved to worktree_state.py, and the surviving
    # rationale is richer anyway (`_nul_paths`'s docstring, which that module
    # imports). Banked downward rather than left as slack.
    "plugins/xp-agents/scripts/commits.py": 204,
    # Arrives above the floor, so it records a ceiling on its first commit —
    # no absolute quoted here, per this file's own rule that prose ABOUT the
    # numbers goes stale exactly the way the numbers do.
    # Most of it is one warning: the observer's guard is REACHABILITY
    # and the reflog check that guards the attributed path must not be added
    # here. Story-004's brief demanded that warning in the docstring precisely
    # because a reader who "restores" the missing check silently reduces the
    # module to recording at most the newest commit.
    # 130 -> 135: `observe` now separates the two ways a reconcile ends. A
    # DECLINE advances the marker (it was recorded, so re-filing it every Bash
    # is noise); a RAISE must not (it recorded nothing, so advancing drops the
    # range this module exists to catch). The pair reads alike from outside,
    # which is why the distinction is written down rather than inferred.
    # 135 -> 168 (story-018): the dedup became a lock plus an in-lock re-check,
    # and three of the added notes are the ones a later reader would otherwise
    # undo — why the lock is the observer's OWN file (taking the event log's
    # inside it deadlocks), why the events list is REBOUND rather than re-read
    # (a merge later in the range derives trailers off it), and what the fix
    # still does NOT close (`_handle_commit` writes without this lock, so an
    # observer racing a commit-shaped Bash can still double-record). Trimmed
    # once already; the residue is re-recorded rather than golfed further.
    # 168 -> 184 (sprint-007 close review): two silent-success defects were
    # fixed, and each carries the rationale that stops it being undone — why the
    # cycle reset is keyed to the newest RECORDED commit in the range (keyed to
    # whatever this observer happened to record, the watermark walks BACKWARDS
    # over a foreground commit and clears the review that ran in between), and
    # why the append is split by what a retry could change (`bulk_append_safe`
    # swallows a lock timeout, so its return cannot distinguish written from
    # dropped, and a dropped event that advanced the marker is a commit no event
    # will ever carry).
    # 184 -> 178 -> 171 (story-022): two extractions, each banked DOWNWARD on
    # the commit that made it — the report paths to `commit_observer_reports.py`
    # and the observation record plus its deferred reset to
    # `commit_observer_state.py`. An entry left above the tree is a re-entry
    # allowance, and the extracted lines could come back here for free.
    # 171 -> 189: the rewrite decline arrived, and its notes are the ones a
    # later reader would otherwise undo — that EVERY git call this module added
    # sits below the cheap exit and why (a sibling hook path is bounded at 5s,
    # and one unbudgeted read broke it once this sprint), that the range is
    # declined wholesale to match the two declines already there rather than
    # inventing a third shape, and that the decline still OWES its reset
    # because the marker advances past it. 189 -> 197: the module docstring's
    # "do not restore the reflog check" rule now says what survives that change
    # and why — without it the new reflog read reads as the forbidden one.
    # 197 -> 199: the review's fix to the owed reset — a reconcile owing nothing
    # new must not overwrite one still owed, and the settle moved BELOW the
    # reconcile so a decline settles on its own call — and the two lines say
    # which loss each shape prevented.
    "plugins/xp-agents/scripts/commit_observer.py": 199,
    "plugins/xp-agents/scripts/concern_conflicts.py": 161,
    # 166 -> 169: the acquire-budget comment said the env override "still
    # outranks this", which the precedence reversal made false.
    "plugins/xp-agents/scripts/coordination.py": 169,
    "plugins/xp-agents/scripts/dash_c_tokens.py": 129,
    "plugins/xp-agents/scripts/framework_detect.py": 122,
    # Crossed the floor on gaining `stages_all_tracked_changes`, so it records a
    # ceiling on arrival rather than being golfed back under. Every regex in
    # this module carries the bug it was written for, and the new one carries
    # two that a reader cannot see: `(?<!\S)` exists because `--amend` contains
    # `-a`, and the `[^;&|]*?` bound exists so a trailing `&& git add -A` cannot
    # vouch for an earlier narrow `git add`. Delete either note and the next
    # simplification reintroduces a silent gate failure.
    # 125 -> 140 (merge of main into sprint-007): both branches added prose to
    # this module and it auto-merged, so this is a re-measure of the union, not
    # an allowance for growth on either side. Re-recorded rather than golfed:
    # each side's notes carry the bug its own regex was written for.
    "plugins/xp-agents/scripts/git_commits.py": 140,
    # Crossed the floor at the close review, at 130. Two thirds of it is the
    # gate's own boundary: which shapes it misses (`eval`), which it over-refuses
    # (a `;` that is compound-statement syntax), and why `|` after `&&` is not a
    # discard — the last of which it had refused, while its refusal text
    # prescribed that exact shape.
    # RETIRED (v5.19.0 close review): git_write_exit_gate.py 140 -> 113 prose,
    # under the 120 floor, so the entry is DELETED rather than lowered — which
    # is what banks the shrink instead of leaving 27 lines of re-entry
    # allowance. It shrank because the read-pipeline elision it owned privately
    # moved to prewalk_rewrites.py to be shared with the declared-command gate,
    # and the argument for a rewrite-not-a-second-walk went with it. The
    # footprint paragraph that took this file to 140 stayed; it is about this
    # gate's own placement and belongs nowhere else.
    # RETIRED (story-009): hook_liveness.py 196 -> 114 prose lines, below the
    # floor, so the entry goes rather than being re-recorded — this table's own
    # rule, because an entry for a file that has shrunk below the floor is a
    # re-entry allowance: the comparison stops running and every deleted line
    # could come back to the old number with nothing red. The verdict machinery
    # left (`check_liveness`, its result type, four reason builders, the CLI)
    # and most of the prose was the argument for THOSE; the primitive's own
    # reasons are untouched.
    # 227 -> 239: CLOSE_CYCLE_AGENT_ID lands here rather than in
    # `event_metadata` — it is an agent identity, not an event metadata key, and
    # the note has to say why the id is read as a discriminator or a future
    # reader deletes the `story_metrics` check that depends on it.
    "plugins/xp-agents/scripts/identity.py": 239,
    "plugins/xp-agents/scripts/in_place_marker.py": 291,
    "plugins/xp-agents/scripts/lead_gates.py": 166,
    "plugins/xp-agents/scripts/lint_runners.py": 177,
    "plugins/xp-agents/scripts/linter_invocation.py": 201,
    "plugins/xp-agents/scripts/linter_tables.py": 290,
    # 123 -> 131: LAST_SEEN_HEAD records that it is keyed on the REPO, not the
    # session. The SMM is shared across worktrees, so the wrong keying is not a
    # style question — every checkout would read every other's HEAD as an
    # unexplained jump.
    # 131 -> 133 (story-018): the same note now says why the marker is
    # deliberately absent from _AGENT_SCOPED_MARKERS. Recorded rather than left
    # inside the slack, which the two added lines had spent down to zero — a
    # ceiling with no headroom reddens the push gate on the next rationale line.
    "plugins/xp-agents/scripts/markers.py": 133,
    "plugins/xp-agents/scripts/migration_lock.py": 121,
    "plugins/xp-agents/scripts/result_counts.py": 126,
    # Crossed the floor on arrival of the HEAD-distance expiry, which needed
    # its own reason recorded: the write-driven ageing it backstops fails open,
    # and the docstring that called that "tracked debt" is now the one saying
    # how it is closed.
    # 132 -> 134: the number was recorded BEFORE the two lines naming why the
    # sha's field is `written_at_commit` and not `written_at`, so the table was
    # already two behind its own file — inside the slack, and therefore silent.
    # 134 -> 138: MISLEADING evidence is now named as a third case beside the two
    # absences, because the docstring claimed only absence could fail to expire
    # while a base merge was supplying a distance of its own.
    "plugins/xp-agents/scripts/review_records.py": 138,
    "plugins/xp-agents/scripts/retro_metrics.py": 130,
    "plugins/xp-agents/scripts/scaffold_apply.py": 128,
    "plugins/xp-agents/scripts/session_start.py": 164,
    # 257 -> 290, and the tree's total moved by ~10, not 33: the composition's
    # three-part rationale and the escape marker's four properties came here
    # from `exit_capture_gate`, which fell 105 -> 82 prose lines in the same
    # commit. Consumer-specific reasoning deliberately did NOT come with them —
    # why a declaration-keyed predicate needs the substitution rewrite stays
    # with the gate whose predicate it is.
    # 290 -> 291 at the close review, and net of a deletion: `exit_status_waived`
    # arrived with three lines, while `exit_reaches_shell` stopped restating the
    # argument-substitution line `argument_substitutions_as_words` already argues
    # twenty lines above it — the duplication the extraction itself introduced.
    "plugins/xp-agents/scripts/shell_exit_structure.py": 291,
    "plugins/xp-agents/scripts/spawn_teammate.py": 271,
    "plugins/xp-agents/scripts/staged_lint.py": 221,
    "plugins/xp-agents/scripts/tdd_check.py": 133,
    "plugins/xp-agents/scripts/teammate_runner.py": 182,
    "plugins/xp-agents/scripts/test_attribution.py": 151,
    "plugins/xp-agents/scripts/test_parsing.py": 151,
    "plugins/xp-agents/scripts/verify_acceptance.py": 159,
    "plugins/xp-agents/scripts/verify_acceptance_record.py": 129,
    # 156 -> 161 for `also_changed`: the parameter's existence is cheap, but
    # WHO may pass it is a fail-open boundary (merge time must never count the
    # index), so the signature needs a sentence naming that. Banked upward
    # rather than trimmed because the alternative was deleting the only note
    # at the seam a future caller reads first. The full rule stays single-homed
    # in verify_deferred.untouched_paths_for_story; this file points at it.
    "plugins/xp-agents/scripts/verify_paths.py": 161,
    "plugins/xp-agents/scripts/worktree.py": 197,
    "plugins/xp-agents/scripts/worktree_differential.py": 211,
}

# Growth this pin deliberately tolerates, per file, in prose lines.
#
# WHY THERE IS ANY. Recorded at the measurement exactly, every one of these
# files would have zero headroom, so a single added rationale line reddens at
# `git push`, after the commits exist. A gate that cheap to trip is cheapest to
# satisfy by DELETING accurate rationale — the opposite of what this milestone
# produces, and something that already happened once when a clause saying how
# long a gate stays quiet was golfed out purely to get green. The band ratchet
# hit the identical wall; see `_pin_ceilings.py`'s own docstring.
#
# WHY 5. One rationale comment is one to three lines. Five absorbs that without
# absorbing a paragraph, and it is per FILE rather than pooled, so it cannot be
# spent all in one place the way a single tree-wide allowance could.
#
# The date is here because the allowance is spent, not renewed: re-measuring is
# a deliberate, reviewable act.
PROSE_SLACK_LINES = 5


def prose_ceilings() -> dict[str, int]:
    """Path -> the number the tree is compared against: measurement + slack.

    A function rather than a fourth constant so the ceiling has one derivation
    and a caller reaching for it gets slack included by default. It does not
    HIDE the measurement — PROSE_MEASURED and PROSE_SLACK_LINES are public and
    the pin imports both to build its regrowth legs. Nothing here stops a
    future caller comparing against the raw number; what stops it is that the
    zero-headroom ceiling has a name and a recorded reason.
    """
    return {path: n + PROSE_SLACK_LINES for path, n in PROSE_MEASURED.items()}

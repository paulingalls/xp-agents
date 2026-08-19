# Changelog

History prior to v5.0 lives in [`changelog_pre_v5.md`](changelog_pre_v5.md).

## v5.21.0 — Skills get their state from a hook, and no hook reaches a subagent

**Every skill's preload state now arrives by hook-side injection, and the `!`
shell lines that used to carry it are gone from all 19 SKILL.md files.** 17 of
those skills got their state from a `!` line the second harness never expands,
so on that harness every one of them ran blind — reading `SMM_DIR=` out of a
line that was never executed. `PreToolUse:Skill` now runs the skill's own
preload and injects its output as `additionalContext`, one channel on both
harnesses.

**The decision was measured, not argued.** `docs/completed/PRELOAD_DELIVERY_MECHANISM.md`
records the rubric fixed *before* the verdict and every run against it. A uuid
minted inside the hook — in no file and no prompt — came back byte-identical
from an inline skill's body inside a realistic 24,309-byte payload. Every
measurement ran against a throwaway probe plugin, never the shipped tree, each
with a control, and the probe wrote one side-channel line per invocation so
*the hook never fired* stayed distinguishable from *the hook fired and the model
could not dereference the value*. Without that third state a dead hook and a
real negative are the same observation.

**The most consequential result is a negative: no hook delivers context into a
subagent.** A forked skill's subagent reported the token absent while its own
parent confirmed receiving the very same payload — so the injection landed and
the fork boundary blocked it. `PreToolUse:Agent` does not fire at all for a
forked skill (a direct Agent-tool call does, which is what proves the matcher
name right), and where it does fire it reaches the spawner, not the subagent.

**So the last three forked skills were converted rather than worked around.**
`/xp-review-plan`, `/xp-sprint-review` and `/xp-system-context` now run inline
and spawn their reviewer through the Agent tool. Nothing in the plugin carries
`context: fork` any more, and a subagent's state comes only from what its
spawner writes into its prompt — the general rule that negative implies.

**One trigger on the first harness, two on the second — which the manifest
emitter could not express.** The derived manifest was subtraction-only: it could
drop an entry the second harness cannot honour, but a trigger that exists ONLY
there had nowhere to live. It can now add, so the second harness carries a
`PreToolUse:Bash` injection entry the source manifest deliberately does not.

**Delivery is pinned by content, not by mechanism** — the check asserts each
marker arrives, not that a particular line is present, because the whole point
of replacing a channel is that a mechanism-shaped pin goes green while a marker
quietly stops being delivered. The skill-to-preload mapping likewise moved into
one place, resolved from the `skills/*/scripts/*.sh` glob with the two outliers
pinned, so no third copy can drift.

### The gates stop reporting on things that are not happening

Half the sprint went to honesty in the enforcement layer, each item its own
falsified claim:

- **Every commit that moves HEAD is recorded.** HEAD is re-read after the
  commit-shaped command has gone, so a commit made by a shape the classifier
  did not recognise still lands as an event.
- **The commit observer records only what it can support.** Attribution comes
  from the commit itself rather than from ambient session state; its last-seen
  marker outlives the session but not the checkout; a reset it could not apply
  is now *owed* rather than lost; and a rewritten range is declined while still
  owing that reset. Two of these were defects the story's own tests had masked
  by observing twice.
- **A gate stops charging for work it has no claim on.** A deletion the command
  itself stages was never a ghost, and the review gate no longer bills for it.
- **A guard that matches nothing says so.** Guard pins are derived from
  specimens instead of restating literals, and a new guard pattern must declare
  a specimen or the completeness check fails.
- **No preload side effect survives a refused call.** A preload that mutated
  state and then had its call refused spent a gate for nothing; the mutating
  sites are now enumerated by *running* them and classified, and a preload is
  skipped when the call will be refused.
- **Each gate discharges at the act that satisfies it,** not at the launch of
  the thing that will eventually satisfy it. The plan gate now clears when the
  review completes; the assign gate is no longer spendable by merely reading a
  skill.

**Liveness was narrowed, then its reader was deleted.** The check that asked
"are hooks running" was reachable only from the injection hook — so it judged a
runtime already running — and that handler wrote the heartbeat immediately
before the preload read it. Inert by construction, not merely mis-ordered. It
was narrowed to the state it could still see, then removed: **net −1869 lines.**
The heartbeat primitive stays, because two other consumers ask about OTHER
sessions — the Stop gates' conflict check and close-cycle abandonment — which is
the question the deleted reader could never answer. Both return `bool | None`
and treat an unageable heartbeat as "cannot tell".

### Deferred, and named rather than absorbed

Five stories did not ship: paying twice at close, the prose-leak pin's own blind
spots, a blocking question raised by a forked reviewer, working hook timeouts on
both harnesses, and the domain-collision message that should name a dependency
as the remedy.

**The timeout deferral leaves a measured gap, recorded as one.** Neither
injection entry declares a timeout, so both run at their harness default. The
first harness's allowance is large and the slowest preload is 1.91s — but that
1.91s is a *floor*, since close preloads compute diffs, and the second harness's
default is neither measured nor documented. If it is short, a preload is killed
mid-run and delivers nothing: this sprint's own quiet-failure class, arriving
through the bound instead of the trigger. Discharging it is one run.

## v5.20.0 — The broad review is ours, and its cost is a number

**The one broad multi-agent correctness pass now runs from a shipped script this
repo owns, launched by PATH.** It used to be a built-in launched by NAME. That
name was registered nowhere in the shipped build, so close Step 4b silently did
not run — for releases — while every check said the instruction was present.
Each check was asking whether the string was there, not whether it was
deliverable. A path cannot fail that way, and `plugins/xp-agents/workflows/code_review.js`
is now the primary launcher; the built-in `/code-review` stays as a documented
fallback until the script has closed a real branch.

**That pass earns its cost.** Run by hand against the v5.19.0 close diff — after
a plan review, a per-increment quality review and a security review had all
passed it — it returned seven findings with reproductions, two of them
fail-opens where a gate did not catch its own primary shape.
`docs/completed/XP_CODE_REVIEWER_MULTI_ANGLE_VERIFY.md` records the same from
v3.11.1: two confirmed regressions passed three cheaper reviews and were caught
only here. (The v3.11.1 changelog entry records the fixes, not the provenance.)

**What owning it buys, beyond the launch working.**

*The reviewing knowledge is shipped prose, not code.* Each finder's lens lives in
`scripts/_code_review_angle_*.md` and the verdict ladder in
`scripts/_code_review_verdict_ladder.md`, flat, where the language-agnostic
sweep and the prose pins already scan them. One file per
angle, because blindness is the mechanism: a finder handed every lens drifts
back toward the generalist pass this exists to beat. Two of the angles are ours
and both were earned — a state/lifecycle reading is what would have caught the
v3.11.1 pair, and a test-vacuity angle exists because a single session here
produced three tests that passed against the unfixed code.

*The fan-out is capped in code and says what it dropped.* The previous
mitigation was a paragraph asking the orchestrator to be careful, shipped after
a customer run reached roughly a hundred agents; its own test file recorded the
risk as "narrowed, not closed". Verification is now bounded on distinct
candidate locations, and the cap announces itself in the log, the stats and the
summary the close reads. Silent truncation was the real failure — a capped pass
reads exactly like a complete one.

*Nothing found is lost at assembly.* A synthesizer that returns one decision for
ten findings, or dies, no longer discards the nine: they were found by an angle
nothing else looks through and survived a refuter trying to kill them.

**A Workflow script can now be unit-tested at all**, which is why any of the
above is checkable. The source is read as TEXT and wrapped in an
`AsyncFunction` with the runtime's globals stubbed — a Workflow script is
neither an ES module nor a plain script, since it carries a top-level `return`.
34 JS tests over the orchestration, run by `node --test` and DRIVEN FROM PYTEST:
`node --test` on a glob matching nothing runs zero tests and exits 0, so the
suite carries a minimum-passing floor, and a missing node fails loudly rather
than skipping the one surface no other gate in this repo discovers. Node is a
development dependency only; the shipped plugin stays stdlib-only and a Workflow
script has no module system to import anything with.

**The `.js` surface is governed, not merely tested.** Nothing discovered a
`.js`: no 500-line cap, no band ratchet, and at commit time `staged-tests`
classified one as nothing at all. Both legs select by suffix at any depth rather
than by enumerated location, following the precedent set for shipped shell.

**Three lifecycle fixes that the change forced, all real.** A Workflow
completion reaches no `PostToolUse:Skill|Agent` hook, so Step 4b arms the
review-cycle marker by hand — and the Skill fallback must NOT repeat that,
because its own hook arms at launch and two writers made the retro count one
review twice. The arm is therefore launcher-conditional, and wrong in both
directions if applied flatly. Second, since the marker is cleared only by a
landed commit, an errored or abandoned review used to leave it set for good: the
next `/xp-quality-review` would read consume-findings and ask for findings
nobody produced, while the self-find branch that would have found the bugs
itself never ran. `review_flag_cli.py --disarm` takes it back, and Step 4b
disarms BEFORE falling back — after, the disarm lands on the fallback's own arm.
Third, the arm used to emit the completion event at LAUNCH, which said a review
had finished the moment one started and could not be withdrawn by the disarm;
the emission now moves to `--complete`, run when the findings are in hand, so an
abandoned review counts as zero completed reviews and each path emits exactly
one — this CLI's on the primary, the hook's on the fallback.

**Paths are emitted, not written.** The close reference is `cat` into the
preload's stdout RAW, so a `${CLAUDE_PLUGIN_ROOT}` in it reaches the reader
literally; the ones that work there work because they sit inside a Bash command
the reader runs. A tool argument has no shell. The preload emits
`WORKFLOW_SCRIPT` and `PLUGIN_ROOT` already absolute, and the test asserts the
emitted path EXISTS — the only check in this step's wiring that is not a string
comparison, which is precisely the gap that let the last one ship broken.

**It reviewed itself before it reviewed anything else, and that is how most of
the above got fixed.** Run against its own branch, the pass returned 26 verified
findings — and the first of them was that `REPORT_CAP` discards verified
findings while the summary keeps reporting the full survivor count. The report
carrying that finding was truncated to 10 and said 26 survived, so it
demonstrated the defect in the act of reporting it. Silent truncation was the
one failure the caps existed to prevent; it is now announced in the log, the
stats and the summary the close reads.

The same run found: a clean review announcing a broken synthesis (the guard
could not tell "the merge died" from "there was nothing to merge"); the cleanup
finder authorized twice every other angle's candidates while ranking last, so
the lens likeliest to be dropped could produce the most; `meta.phases` declaring
one phase of four; a `make setup` whose new Node probe exited before `lefthook
install`, leaving a Node-less clone with no gates at all where it previously had
every gate and merely lacked a JS suite; and six tests shipped on this branch
that asserted nothing — found by the test-vacuity angle added to the review
because of that same failure mode earlier in its own development.

**Disclosed rather than argued away.** The fallback's fan-out remains unbounded
by anything here — the cap is closed for the primary launcher only. The close
preloads move 8900 → 10700, and that is mostly the PRIMARY launcher's own prose:
Step 4b grew 1282 characters and the fallback paragraph is 377 of them, so
retiring the fallback recovers under a third and leaves the budget well above
8900. An earlier draft of this sentence claimed the fallback was the whole
increase and that retiring it would bring the number back down. It was measured
and it was wrong, in the paragraph whose one job is not doing that.

**The cap disclosure has no prescribed consumer yet.** The script reports what
its fan-out dropped and the close is told to read it, but nothing downstream
behaves differently for a truncated pass than for a complete one. The number
reaches a human and stops there.

## v5.19.0 — A review covers the fixes it made, and a piped push cannot lie

**A completed review now records the files the reviewer actually changed or
created.** v5.17.0
shipped a coverage record so a reviewer's own fixes would not re-arm the commit
gate. In the dominant flow it recorded **nothing**: the scan reads staged and
committed files, and a reviewer edits files and returns — nothing stages them. So
the set was empty exactly when it mattered, the next `git add -A && git commit`
counted the reviewer's fixes unreviewed, and demanded a review whose fixes
demanded another. All 24 tests over that record passed, because every one of them
patched the scan; the release went out green against a recorder asking git the
wrong question. The new coverage test is the only one that does not patch it — a
real repo, a real unstaged edit, red before the fix.

The widening is the honest scope rather than a loosening **on the per-increment
path**, where the reviewer is handed `git diff HEAD` — staged and unstaged both —
so the narrower set claimed less than it was shown. Two control tests pin that it
is not a blanket exemption: an untouched tree still covers nothing, and a file the
reviewer left alone stays uncovered.

**That scan now fits the budget its hook actually has.** `SubagentStop` is given
5000 ms in total; the git helper bounds each *call* at 5 s, not the set. Four scan
legs plus the record's HEAD read therefore allowed 25 s inside a 5 s budget,
and a handler killed part-way through leaves the gate armed with no flag — where
the only recovery is another full review, because that flag has exactly one
writer. The whole scan now takes one budget, split across the legs that will
actually run, counted before any of them does so the split cannot depend on what
an earlier read returned. The split is deliberately uneven: every scan leg fails
*closed* (a timeout narrows the recorded set), while the HEAD read fails *open* —
it times out to empty and silently disables the expiry below — so the
unrecoverable failure gets the larger share.

Red first at `15 not less than 5.0`, and measured on a real repo after an earlier
draft passed against the very code it was written to fail: at `/tmp` the first
read errors and returns early, understating the worst case by two thirds.

**Coverage now expires on commits that never reach a commit site.** Ageing was
write-driven, so a commit made by an `xp-` subagent — which the recursion skip
waves past — never spent the record. Its paths stayed exempt with no bound, and a
later session could rewrite every file a review once glanced at and commit
unreviewed. A counter cannot close that: the write that fails to age is the same
one that fails to advance the watermark, so nothing in the shared model moved.
HEAD did. The record carries the commit it was written at, and the read asks git
how far HEAD has travelled since. Absence of information never expires anything —
no recorded commit, no working directory, or a sha git cannot resolve all read as
"no evidence to expire on" and leave the write-driven ageing in charge.

**A `git push` or `git commit` whose exit status cannot reach the shell is now
refused before it runs.** On 2026-08-14 a push went through `tail -6`; the shell
reported `tail`'s exit 0, the push had been rejected, and about forty minutes went
into a bug that did not exist. v5.18.0's captured-exit gate was built for exactly
this shape and did not fire, for a structural reason: it keys on the project's
*declared test command*, and a push is not it. Measured against a live model
rather than assumed — `pytest -n auto | tail -6` refused, `git push origin HEAD
2>&1 | tail -6` allowed. The post-run advisory missed it too, and *vacuously*: no
runner ran, so nothing needed proving. Zero coverage, not partial coverage.

Two subcommands and no others, because `pre-push` runs the whole suite and
`pre-commit` runs lint, format, types and the staged tests. Those hooks exist to
fail, and a pipe replaces their verdict with the pager's — while the output being
long is precisely why the pipe gets typed, which is why the refusal names a
redirect instead of telling anyone to re-run bare. Reads are untouched: a piped
`git log` loses a status nobody needed.

**Fixed subcommand names are the right design here, and that is a narrow claim.**
The sibling gate refuses to name runners because a fixed list of them is inert for
every project whose runner is absent from it. Git is different in kind: every
project using this plugin is a git repo, and `push`/`commit` are universal rather
than a vocabulary that goes stale per language. The gate is a **sibling module**
rather than an edit to that one, because that file's docstring asserts as its
contract that it names no such command "not in a rule, not in an example" — a
literal `push` there would falsify the sentence making the claim.

**One composition, three callers.** The rewrite → walk → `sh -c` recursion
sequence existed twice before this release and was about to be written a third
time. It now has one home, `exit_reaches_shell_for`, and the escape marker moved
beside it: every gate built on that composition refuses the same shape and must be
waived by the same words, and an agent made to remember which marker suppresses
which gate will type the wrong one. The extraction landed on its own, and its
proof is that the existing checks passed **with no behavioural assertion
edited** — only the size and prose pins moved.

**Two false positives found by reading a failing test, not by foresight.**
`git -c push.default=simple log` was read as a *push* — `\b` sits happily between
`commit` and `.`, so the narrow lookahead let a config *value* pass as a
subcommand, and that is the CI-identity form this project documents, so the
misfire landed on the path agents use most. And a `\`-newline is a line
continuation the shell joins away, while the walk splits on `\n` regardless — so a
wrapped invocation read as two commands with a status-discarding newline between
them, and an honest wrapped push was refused for an operator that was not there.
Both fixed, with the wrap pinned in both directions: joining must not launder a
wrapped push through a pipe.

**The close review found five more, and they are fixed here rather than
disclosed.** Two fail-opens in what the gate reads, one false positive that made
the gate self-contradictory, and two in the coverage record.

*The refusal prescribed a shape it then refused.* `|` binds tighter than `&&`, so
`git commit -m x && git status | head` is `git commit -m x && (git status | head)`
— a failed commit short-circuits and its non-zero IS the shell's. The shared walk
reads operators in sequence with no precedence, so it refused the pipe as though
the write sat inside it, while `_refusal` told the agent an `&&` chain was fine:
read the advice, retype it, be refused again. Pipelines that run no write are now
elided before the walk, a rewrite in the spirit of the argument-substitution one,
and the two laundering shapes are pinned — a `;` after the chain and a `&` around
it both still refuse.

*Coverage missed the file a reviewer CREATED.* `git diff` lists an untracked path
at no stage, so a reviewer that writes a test recorded nothing for it and the next
`git add -A` counted it unreviewed: the same defect this release fixes for edits,
surviving for additions. A fourth scan leg (`ls-files --others
--exclude-standard`) now runs inside the same budget — five reads, but four
shares: the HEAD read keeps its own second for the reason above.

*And the HEAD-distance expiry counted commits nobody landed.* `rev-list --count`
counts everything reachable, so a `git merge <base>` bringing three commits read
as four landings and discarded a review just earned — the loop this record exists
to break, entered from the other side. It counts first parents now, so a merge is
the one commit it is.

*The operator on a heredoc's own line was invisible.* `strip_heredocs` deleted the
whole span from `<<DELIM` to the terminator, the remainder of the introducing line
included, so `git commit -F - <<'EOF' | tail -20` — the form every commit in this
repo is written in — arrived at the walk as a bare `git commit -F -` and was
allowed. The body is still data; what follows the operator on that line is code,
and is now kept. The same span hid a chained `&& git branch -D <branch>` from the
branch-delete refusal, which shares that helper.

*And the same fix now covers both gates, which is why it is a rewrite and not a
patch.* `|` binds tighter than `&&`, so `<declared command> && cat out.log | tail
-5` is `<declared> && (cat out.log | tail -5)` — a failed run short-circuits and
its non-zero still reaches the shell. Fixing that in the write gate alone left the
declared-command gate refusing the exact composition **its own refusal text
recommends**, for a release. The elision is now `prewalk_rewrites`, shared, and
takes each caller's own predicate. One case only surfaced once it was shared: a
text-shaped predicate finds a target inside a quoted `sh -c` body, a head-token
one reads `bash -c "..."` as running `bash`, so the elision has to check the
wrapper's body the way the walk already does — caught by the older gate's own
laundering test the moment the rewrite reached it.

*And the escape marker was matched anywhere in the command text*, so a commit
*message* quoting `# exit-status-not-needed` — which the notes describing it do —
waived the gate on exactly the command whose pre-commit hooks exist to fail. It is
now read off a data-stripped view, so a declaration outside the message still
waives and a mention inside it does not. One predicate, shared by both gates,
beside the marker it reads. `<<"DELIM"` is read as a heredoc too, which it was
not, so a double-quoted message body no longer reaches any scanner as code.

### Known residuals

Both are the same shape — a fix that landed in one consumer of a composition this
release exists to share. A third was listed here until the close review asked why
two were disclosed and the most user-visible one was not; that question is what
turned it into the fix below.

- **A completed review credits the wrong tree for a teammate story.** The
  reviewer's diff is taken in `TEAMMATE_CWD` — a live worktree — while this record
  keys on the `SubagentStop` payload's cwd, the orchestrator checkout. So the
  widened scan can record the ORCHESTRATOR's unstaged and untracked files as
  reviewed, and the gate then forgives exactly what the next main-checkout commit
  touches. The review FLAG has mis-targeted this way since before this release;
  what is new is that coverage adds a path-keyed, two-commit exemption on top of
  it. Closing it needs the reviewed root in the payload, which that payload does
  not carry — the same wall as the close-range divergence below.
- **The line-continuation bug is fixed in one consumer, not in the walk.** The
  join belongs in `shell_exit_structure`, whose three other consumers still have
  it — so **v5.19.0 ships a captured-exit gate that falsely refuses a wrapped
  declared test command**, and the close-gate and worktree-differential checks
  mis-answer the same shape. That is a four-consumer change with its own
  red/green, and it is not this release.
- **The narrow lookahead survives in its sibling.** `git_commits`' commit/merge
  regex carries the same `\b(?!-)`, so every gate keyed on that detection can fire
  on `git -c commit.gpgsign=false log`. It feeds the commit-event recorder and the
  review-cycle gate, so it gets its own test rather than a drive-by fix here.
- **`eval` launders the write gate where `sh -c` does not.** `eval "git push |
  tail -6"` is allowed: only a `sh -c` body is recursed into. It joins the
  deliberate-evasion class the spike catalogues beside aliases and `$GIT` — one
  word to type, and nothing an agent reaching for a pager would reach for.
- **A write inside a compound statement is over-refused.** `if ...; then git
  commit; fi` and `for ...; do git push; done` are refused for the `;` before `fi`
  or `done`, which is shell syntax and discards nothing. Telling that apart needs
  keyword knowledge the shared walk has not got; the marker is the release valve
  until it does.
- **The coverage widening is honest on the per-increment path only.** The two
  close-path preload branches hand the reviewer a *committed range*, so there the
  unstaged leg can forgive a tracked working-tree file the reviewer was never
  shown. Accepted rather than closed: story cadence only advises at the gate, and a
  close range already forgives more than this leg does. Closing it needs the
  preload mode at `SubagentStop`, which that payload does not carry.
- **There is still no manual recovery for a review flag.** A handler killed
  mid-scan leaves the gate armed and the flag unset, and the flag has one writer.
  Deliberate — a prose-invoked override clears the gate with no review, which is
  the hole v5.16.0 and v5.17.0 were closing — but the recovery path the escape-
  hatch documentation *advertises* is not wired, which is the next residual.
- **That escape-hatch documentation describes a bypass that does not exist.** It
  claims `[release]`, `[chore]` and `[sprint-direct]` commits skip the review-cycle
  gate. They do not: that gate raises before anything asks. The claim was used to
  justify excluding those commits from the retrospective's link denominator, so the
  retro under-counts on a premise that was never true, and no test pins the claimed
  bypass.

## v5.18.0 — One linter process per config group, not one per file

**A commit no longer pays a linter process per file.** Post-commit lint
resolution called the linter once for every committed file, serially, on the
synchronous PostToolUse hook path while the agent waited. Both loops now group
by the `(linter, config)` pair the file resolves to and run one batch per group
— and a commit whose files carry no unresolved lint concern spawns **zero** on
this path, because those files are dropped before grouping. (The commit-time
staged gate still runs once per group; it lints what is about to land, so it has
nothing to skip.) The loop can only ever *resolve*, so
linting a file with nothing to clear was always work for nothing.

Measured end to end rather than asserted: reverting the emitter to its previous
form makes the composition test fail `3 != 1`, with the log showing three
separate `ruff check` invocations where there is now one.

**A commit made from a subdirectory clears its lint concerns.** `git -C sub
commit` and `cd sub && git commit` hand the hook a cwd below the repo root,
while git still names the committed files relative to the root. Resolution
normalized them against the cwd, doubling the prefix — `pkg/src/a.py` became
`pkg/pkg/src/a.py`, which matches no recorded concern, so the file was dropped
before the linter ever ran and its concern never cleared. Nothing errored; the
work simply did not happen. Everything on this path is now resolved against the
repo root, which the orphan sweep's own `.exists()` check already assumed.

**Grouping is one implementation, shared, and it is not ruff-shaped.** The
routing was fused to the commit-time gate's git-index filter; it now lives in
`lint_grouping.group_paths_by_linter`, filter-free, with each caller bringing
its own eligibility test — the staged gate wants index membership, the
post-commit sweep wants `.exists()` and must not inherit the other. Grouping is
a table lookup on the ecosystem's own config file, so eslint, rubocop and
clang-format batch identically; supporting one more language is a row, not a
branch.

**A batch's exit code names no file, and the code now says so in three places
instead of guessing.** A clean batch vouches for every path in it and resolves
the group in one append; a batch reporting findings falls back to one run per
file *in that group only*, because knowing *which* file was dirty would need a
per-language parser; an unverified batch — missing binary, timeout, a path the
argument guard refused — resolves nothing at all. A bad read is not a pass.

**The composition is proven at the process boundary.** The two legs share a
helper and a runner, and nothing exercised both against a real repo. They now
are, by a test that counts processes that actually started: a fake linter on
`PATH` logging its argv, rather than a patched `subprocess.run`, which cannot
cross a subprocess boundary at all. It also caught what the unit tests could
not — that a batch's argv must be asserted to *contain* its group, not merely
to exclude the other group's files.

### Known residuals

v5.15.0 disclosed its `is_merge` gap rather than arguing it away, which is the
only reason this release gets to say that residual is closed. The same courtesy,
for what is still open on the code above:

- **Closing that residual opened a narrower one.** `story_metrics` reads a story
  as shipped from `is_merge` **and** the close-cycle agent id. Now that the tag
  is honest, an "Already up to date" close — which creates no commit — emits an
  untagged event, so the story reads *unshipped* and the plain commit it landed
  on is counted as a story commit. The old hardcoded `True` produced the right
  metric by asserting something false. Tracked, not fixed here.
- **The verify-touch union has two path sources that disagree on encoding.**
  `git log --name-only` C-quotes a non-ASCII path; `git diff --cached --name-only`
  is asked with `-z` and does not. A path with non-ASCII bytes can therefore clear
  the advisory from the index and then re-fire once committed.
- **Batching bounds processes, not wall clock.** Post-commit resolution passes no
  shared deadline, so a polyglot repo can pay each group's own ceiling in
  sequence on the synchronous hook path. The commit-time gate threads a deadline;
  this path does not yet.

### Also in this release

**The wall-clock performance tier is retired.** Three pre-push timers measured
the machine, not the diff. Serializing them after the suite controlled only the
contention that run created; a concurrent CLI teammate — a recorded design
decision of this project — was invisible to them. Because story close pushes,
a blocking timer failed closes whose diff touched none of it: measured at
`read_delta` 108 ms against a 100 ms bound, at load average 94.89, on a bound
with 75× headroom when measured serially at 1.3 ms. What the timers stood in
for is now asserted structurally, on **what gets parsed** rather than how long
it took — and those run everywhere, including CI, where `XP_PERF` was never set
and the timers therefore never ran at all.

**The close-cycle merge emitter derives `is_merge` instead of asserting it.**
v5.15.0 disclosed this as a tracked residual: the emitter passed `is_merge=True`
by hand because it "knows structurally that it just made a merge", and the merge
helper also reports success on **"Already up to date"**, which creates no commit.
That residual is closed. The tag now comes from HEAD's parent count, matching
the shared builder's own definition of the flag, and the emitter stores the
cleaned commit body like its two siblings rather than the raw one. The tag is
not cosmetic — it exempts an event from the commit-size concern and drops it
from the resolves-link-rate denominator, so a wrongly tagged plain commit
silently suppressed a real warning.

**A commit is refused when it masks its test runner's exit status.** Piping a
declared test command into `tail`, or capturing it in `$(...)`, makes the
shell's status the pipe's — so a red suite reads as green and a green one
cannot clear a failure concern. The gate keys on the project's *declared*
command rather than a list of runner names, which would be inert for every
project whose runner is not in it. It over-matches by design on the declared
executable; `# exit-status-not-needed` is the release valve.

**The acceptance-path advisory counts staged files.** It ran at PreToolUse —
before the commit under evaluation exists — but read coverage from a walk over
`base..HEAD` commits. On a story's first commit those are the same, so the range
was empty and every declared path reported untouched while sitting fully staged
in the index. It fired on the first commit of a story that had both its test
files in that very commit. Staged coverage is opt-in at every layer and never a
default: the close gate and the story-close preload stay commit-only, because a
merge carries commits, not the index.

## v5.17.0 — Measuring which hook actually fires, and covering a review's own fixes

**v5.16.0's central fix did not work, and this release says so first.** That
note claimed `quality_review_done` had moved onto a completion signal by keying
it on the `xp-code-reviewer` agent instead of the skill. Measured live the hour
after release: `PostToolUse:Agent` fires when the Agent **tool call** returns,
and this harness backgrounds subagents, so that is launch too. The reviewer's
own start event was stamped 70ms *after* the `qr_complete` the hook had already
emitted for it. v5.16.0 moved the defect from skill-launch to agent-launch.

The flag and its `qr_complete` event now ride **`SubagentStop`**, which fires
when a subagent has genuinely finished. That is not an assumption this time:
`xp-close-reviewer`'s SubagentStop handler is already recording completions for
an Agent-tool subagent in this same harness. `review_cycle_done`'s allowlist now
carries the rule that cost two releases to learn — *every* entry in it records at
LAUNCH, so nothing that gates a commit may live there. The one exception is the
forked `/xp-review-plan`, and `simplify_done` depends on launch timing
deliberately, since `review_mid_cycle` reads it as "the workflow is still
running".

**A review's own fixes no longer demand a second review.** The gate blocks at
`REVIEW_CYCLE_THRESHOLD` changed code files unless a review ran, and a landed
commit clears the flag — so the fixes a review produced arrived at the next
commit as unreviewed changes and demanded another review, whose fixes demanded a
third. It terminated only when a review came back clean or touched fewer than
two files. Reproduced live during the previous release's own close, when the
close-reviewer's Step 5c fixes were blocked.

A completed review now records the code files in its scope, and commits stop
counting those files until the record is spent. State the exemption at its real
width, not its intended one: **two** commit gates read the record, not one — it
is written with age 0, the commit that ends the review's own cycle ages it to 1,
and the commit after that consumes it. And it is keyed on PATHS, not content, so
the second gate forgives whatever those files hold by then, including work
written after the review ended.

"The files it looked at" is also generous. The scope is measured when the
reviewer finishes, deliberately, because at launch its fixes do not yet exist —
so the set knowingly contains edits the review made rather than read. It never
contains files outside the scope, which is the property the gate depends on.

It is keyed on the repo rather than the session, because the paths are
repo-relative and the same relative path in another checkout is other work.

This is a **workflow-cost repayment, not a new hole**. Before v5.16.0 the gate
could be satisfied by merely invoking the review skill, so the loop was a speed
bump; closing that hole turned it into a wall. The two changes belong together.

One cost this release CREATES rather than inherits: `SubagentStop` does not
fire for a reviewer that is interrupted or crashes, and `review_flag_cli` has
no `quality_review_done` leg — deliberately, since a prose-invocable writer for
the gate's own flag is the hole both releases exist to close. So an aborted
review leaves the commit gate armed with no manual recovery; re-running the
review is the only way through. v5.16.0's `PostToolUse:Agent` always fired,
which is what made that state unreachable before.

Known and tracked rather than claimed fixed: the recorded scope is computed from
staged and committed files, so in commit cadence — where the reviewed work is
typically unstaged — it can come back empty and forgive nothing
(`156d4cdddce4`). It fails safe. The two-gate width and the path keying stated
above are disclosed, not fixed (`86c30b9d2712`). A reviewer spawned for an unrelated purpose
now writes coverage as well as clearing the flag (`2cc9b891a249`, extending
`6552b06d04a3`). And the record is spent by the commit sites, so a commit that
never reaches one leaves its paths exempt indefinitely (`250a3e1b41a6`)
— the one disclosed cost here that fails open rather than safe.

`subagent_stop.py` crossed both the 450-line band and the prose floor with the
new leg, so the review-cycle legs moved to `scripts/review_cycle_legs.py` rather
than taking two new recorded ceilings.

## v5.16.0 — A review is done when the reviewer says so

> **Partly superseded by v5.17.0.** The diagnosis below is right and the
> skill-launch hole is really closed. The REMEDY is not: keying the flag on the
> `xp-code-reviewer` agent moved it onto another launch-time signal, because
> `PostToolUse:Agent` also fires when the tool call returns. Read "the reviewer
> returning" below as "the reviewer being spawned". v5.17.0 moves it to
> `SubagentStop`.

Minor rather than patch: the per-commit review gate now clears at a different
moment, which anyone who watches the gate will notice.

`PostToolUse:Skill` fires when the Skill **tool** returns. For an INLINE skill —
which `/xp-quality-review` is — that is at LAUNCH, not at completion. So
`review_cycle_done.py` set `quality_review_done` before `xp-code-reviewer` had
been spawned, and emitted "Quality review complete" alongside it. Both were
observed live this release: the hook's own "commit your changes now" text
arrived while the skill had not yet run its first step.

Two holes followed from one mistake. Invoking `/xp-quality-review` and
abandoning it cleared the commit gate. And a commit landing **during** a review
cleared the flag — the commit path resets the cycle — with nothing left to set
it again when the review actually finished, so the review's own edits arrived at
the next commit as unreviewed changes. That is the re-arming loop where a
review's fixes demand another review.

**The flag moves to the reviewer.** `_TARGET_BY_NAME` now maps the
`xp-code-reviewer` agent rather than the skill that spawns it; the skill's Step 2
spawns it exactly once per cycle, so the count is unchanged and no consumer sees
fewer events — which holds only while that skill is the only spawn site in the
tree, a property nothing pins. The same unpinned assumption has a second edge: a
future skill spawning the reviewer for its own reasons would clear the commit
gate as a side effect. Tracked as `6552b06d04a3`, unreachable today.

Forked skills are a different case and are untouched — a
`context: fork` skill's Skill call **does** return at completion, so the
`xp-review-plan` entry beside it is correct as it stands. The distinction is
written into the comment, because the categorical version of the claim invites a
maintainer to "fix" the forked entry too.

The `qr_complete` **event** moves with the flag, not just the flag.
`commit_event.py` reads that event as a second, independent "was there a review
since the last commit" advisory; emitted at launch, that advisory was satisfied
by merely invoking the skill. (Superseded with the rest: moving it onto the
Agent tool left it firing at launch too, so this stated purpose was equally
unmet until v5.17.0.)

A residual remains and is not claimed fixed: the calling skill's act-on-findings
step lands after the reviewer returns, so those edits are still made while the
gate is disarmed. Under v5.16.0's agent-launch keying that window was the whole
review PLUS this step; it is now this step alone.
Nothing yet teaches the gate that a change was produced BY the review that just
ran, which is what a fix for the separated-commit half of the loop would need.

Also: `_AGENT_ID_RE` refused nothing ending in a newline. `$` matches just
before a final newline, so `"agent\n"` cleared the allowlist and reached the
marker filenames agent ids are interpolated into (`.watermark-<id>`, built
literally in `_append_lock.write_watermark`). `\Z` refuses it, and the degrade
path falls back to the default rather than naming a file no other caller reads.
Eight sibling allowlists still spell `$`; none has a traced failure path, so
none was changed — the rule is recorded as a decision instead.

Comments in files this change did not otherwise touch stated the old rule and
are corrected rather than deleted, and `docs/ideas/4-CLOSE_GATE_HONESTY.md`
§6 — which told a future implementer **not** to make this change — is marked
superseded with its reasoning kept.

## v5.15.0 — One merge policy, three emitters

Minor rather than patch. Most of it is defect fixes, but two changes are ones a
consumer can observe: a merge HEAD's recorded event changes shape (it now carries
`is_merge` and a wider `resolves` on the routes an operator actually uses), and
`XP_LOCK_TIMEOUT_SECONDS` no longer means what it meant — it can shorten a
caller's named lock budget but not lengthen it, which reverses a recorded decision.

A `type=commit` event for a merge HEAD could be produced by three emitters, and
they disagreed. The close-cycle emitter tagged `is_merge` and re-derived
`Resolves-Event:` trailers from the merged range; the HEAD-rebuild arm tagged but
did not re-derive; the confirmed-success path — **the route an operator's merge
actually takes** — did neither. So the common case was recorded as a plain commit:
counted in the resolves-link-rate denominator, and drawing a
commit-touches-N-files concern for the whole merged branch.

**All three converged.** The two hook routes share one decision — `is_merge` is
gone as a parameter of `build_commit_event`, which reads the parent count itself so
neither route can forget it — and the close-cycle emitter now routes its `resolves`
through the same helper. It still passes `is_merge=True` by hand — that flag remains
a parameter of `make_commit_event`, the constructor all three share — and this note
first justified that as safe because the emitter "knows structurally that it just
made a merge". Not quite: the merge helper also reports success on **"Already up to
date"**, which creates no commit at all, so HEAD is then the previous one. The
dedup on `commit_hash` catches that whenever the previous commit already has an
event, which is the ordinary case; the residual is tracked as an open concern rather
than argued away. v5.13.1 closed one narrow case; this closes the rest.

`resolves` now UNIONS what the operator wrote with what the merged range yields,
rather than replacing it. The close-cycle emitter reads its body back from HEAD, so
"a merge subject never carries a trailer" was never a property the code had —
replacing dropped whatever the operator typed. `has_resolves_trailer` is
authored-only everywhere now: it records that somebody wrote a trailer, and taking
it from a re-parsed id made every close-cycle merge claim one nobody wrote. No rate
moves — merge events are excluded from the trailer metrics outright — what was wrong
was the record. The unlinkable-trailer advisory stays authored-only for the
same reason — over derived ids it would file concerns naming work a long back-merge
closed months ago.

`merged_range_bodies` is gone with the convergence: once all three emitters decide
commit by commit, nothing wanted the whole range as one blob.

**The derivation reads only commits whose own event is ABSENT from the LIVE log**,
and that bound is what makes it safe to run on every merge. Re-parsing exists for one case —
a teammate's per-commit events failed to reach the shared log, so the merge HEAD is
the only surviving record. A back-merge (`git merge main`) is two-parent like any
other, and its incoming range is every commit the branch had not yet seen; without
the filter, one back-merge would be credited with resolving every trailer in that
whole history and would silently close any target deliberately left open. Filtering
on "no recorded event" makes that a no-op while still rescuing the case the
derivation is for. The range is read as `<merge> --not <merge>^1` rather than
`^1..^2`, so an octopus merge's third parent is covered instead of dropped.

The bound is LIVE-LOG, and that word is load-bearing: compaction archives commit
events once their sprint leaves the retention window, so a merge absorbing commits
older than that — or a rebased branch, whose hashes never match — sees no event and
re-derives. Narrower than "every already-recorded commit", and tracked rather than
papered over.

The range framing is `-z`, whose NUL separator a commit object cannot contain. It
was an ASCII control byte first, which let a commit BODY inject a record — and
since an injected hash is absent from the log by construction, its trailers walked
straight past the filter. Validating the hash as 40 hex does not close that; a body
can spell 40 hex characters too.

A merge is now genuinely **exempt from the commit-too-large concern**. `files` for
a merge is the first-parent diff — legitimately the whole merged branch — so
"consider smaller commits" is advice about work already committed in the small.
This release originally claimed that exemption in four places while nothing
implemented it; the gate exists now.

`story_metrics` no longer reads `is_merge` alone as "the story shipped". It
requires the close-cycle emitter's own agent id, because once every two-parent HEAD
carries the tag, a mid-story back-merge would otherwise mark the story merged and
drop its commit from the count.

The suite that was supposed to cover this had been green on a path production
rarely takes: it staged a real `-m` merge and a real conflict finish, then drove
the hook with a *different* command and empty stdout. Each case now runs on both
routes, with git's real output captured rather than spelled as a literal.

### Also

- **`XP_LOCK_TIMEOUT_SECONDS` may now only shorten a caller's named lock budget,
  never lengthen it.** Raised to 30s for its documented purpose — a slow event-log
  lock — it used to inflate the coordination file's deliberate 2s cap to 30s,
  blocking a synchronous write-path hook for the whole of it. That reverses a
  recorded decision, deliberately: the lever needs only to shorten, which is all
  it ever needed.
- One best-effort flock shape (`try_flock`) replaces two that had drifted apart
  for the same job. It takes an `on_giveup` callback rather than returning a bare
  bool, because one of the two callers logs the CAUSE — and flattening `ENOLCK` on
  a network mount and a 2s timeout into one line turns a diagnosable give-up into
  an unexplained one.
- Every `env -u` run in `lefthook.yml` now strips the full leaky-env registry; it
  had been missing five of twelve entries while `CLAUDE.md` asserted the mirror as
  an invariant. A new pin **discovers** those runs by scanning the file rather than
  naming the three that exist today, since enumerating locations is what let them
  drift.
- The commit-message parsing half of `commits.py` moved to `commit_trailers.py`,
  re-exported by identity — text in, text out, and now testable with no git on
  PATH. Two integration suites stopped hand-rolling the same nested-repo fixture.

## v5.14.1 — The suite CI could not run, and the message that would not say why

v5.14.0 shipped with a red suite. Three tests failed on the runner and passed on
every developer machine, and the failure they printed was `1 != 0` followed by
nothing at all.

### A dependency only one launcher supplies

`_codex_harness.assert_module_skips_without_harness` re-runs a module through
`sys.executable -m pytest` to prove its harness-gated rows SKIP when the harness
is absent. CI runs the suite under `python3 -m unittest discover` and installed
only ruff and the clang tools, so that inner run never started. Launch the suite
*via* pytest and the import is trivially satisfiable; launch it via unittest and
it is not — which is why the break was invisible locally. The runner now
installs pytest, and two documents that promised the unittest path needs no
pytest (README, CLAUDE.md) now say the opposite, because CI proved the opposite.

### The diagnostic that hid it

The assertion reported `result.stdout`. An interpreter that cannot import pytest
writes its one explanatory line to *stderr* and leaves stdout empty, so the
message reduced to a bare `1 != 0`. It now reports both streams, stderr last so
it survives truncation. The helper had three consumers and no test of its own;
it has one now.

### A row that only failed in parallel

A `subTest` passed a `PosixPath`, which cannot cross execnet's channel, so the
row failed under `pytest -n auto` — the push gate — while passing sequentially.

### CI cost

Measured from August's 1032 Actions minutes (69% from `pull_request`, split
502/530 across the two Python versions): pull requests now run the declared
floor 3.11 alone and main keeps both, since testing only the newer version is
the direction that lets 3.12-only syntax reach users at the floor. PR runs
supersede per ref; main runs take a unique concurrency group, because a merely
PENDING run is cancelled when a newer one joins its group and main is the
release.

## v5.14.0 — One repo, two harnesses, and a generated file nobody generated

Milestone 8. The plugin now installs on Codex alongside Claude Code from a
single repo: a second plugin manifest, a second marketplace catalog, a hooks
variant generated for that host, install and trust docs, and a version read that
names the copy actually executing.

### Generated, not hand-maintained — in both directions

`hooks/hooks.codex.json` is derived from `hooks/hooks.json` by SUBTRACTION and
`.codex-plugin/plugin.json` from `.claude-plugin/plugin.json` by ADDITION.
Neither emitter writes its own source, so the first harness's files are
byte-identical by construction and a release edits one file. The manifest
emitter needs a guard its sibling does not: source and target share the basename
`plugin.json` and differ only by directory, so `--out-dir .claude-plugin` would
overwrite the hand-edited primary. It refuses, by device+inode comparison rather
than by path — `resolve()` preserves case, and a case-insensitive filesystem
would otherwise let `.Claude-Plugin` through.

**The emitters had no caller.** No make target, no hook, no release step — only
a docstring. The derived manifest drifted twice in one day and was repaired by
hand both times before anyone asked why it wasn't automatic. There is now a
`make manifests` target and a commit-gate step that regenerates and stages both
derived files whenever a plugin JSON is staged, joined with `&&` so a failing
emitter cannot leave stale output behind a passing gate.

### A version that names the copy that is running

Reading one fixed manifest was the original defect: a session reported one
number while executing from a cache directory keyed to another. The read now
takes the executing path as evidence — the plugin root's own final component,
matched against what the shipped manifests declare — and answers `?` rather than
guessing when they disagree.

Two ways it went wrong, both found at close and both reproduced first. Scanning
every path component, not just the root's own, meant any checkout under a
version-shaped ancestor (`/opt/python/3.11.9/…`, a `1.0.0/` release directory)
reported `?` forever. And an unreadable SECOND manifest suppressed the version
even when the executing copy's own manifest was perfectly readable — an
interrupted regeneration was enough to cause it. Both are fixed, with regression
rows covering the false-positive direction the original tests could not reach.

### Not-observed is not unrecognised

The hooks variant strips event names the host does not know. Two compaction
events were on that list because they never fired during the spike — but the
host names both in its own warnings, which is proof it knows them. They never
fired because no run compacted. Stripping them left a compacting session with no
event-log backup and no compaction at all, mislabelled as a harness limit.
Restored.

**Hook timeouts stay stripped, and now for a measured reason.** The unit differs:
`timeout: 2000` let a three-second handler run to completion where milliseconds
would have killed it at two, and `timeout: 1` killed the same handler mid-sleep.
Codex reads seconds and enforces them. The source declares milliseconds, so
carrying a value across literally would ask for 2500 seconds where 2.5 was
meant. Re-establishing a bound is a conversion, and a later milestone owns it.

### Shipped prose that names one host

Text injected into agent context is read on both harnesses, so naming one as
though it were the only one is wrong for half its readers. A pin now scans
shipped Markdown and shell for harness names, excluding environment variables,
real paths and code spans structurally rather than by allowlist, with an at-site
`harness-ok:` marker for the cases that are genuinely host-specific.

Its own limits are documented rather than implied, because a guardrail that
overclaims is a green check certifying something untrue. The largest gap is that
shipped Python is not scanned at all — and a live leak was sitting there, a
banner naming one host's uninstall command while being injected on both. It was
caught by a human reading the diff, not by the pin.

### Known limits

The milestone's claim is that one repo installs on either harness. That is
measured for **Codex only**: registration, install into an isolated home, and
the version read back out of the installed copy. The Claude Code install rests
on byte-identity pins plus daily dogfooding — there is no install row for it
anywhere in the suite, and this release added files to the shipped tree that
such an install would have to copy. Recorded as debt rather than implied by the
headline.

No minimum Codex version is claimed; the work was exercised on `0.146.0` and
nothing older was installed. The per-commit review gate has no automatic release
on that host yet — moving the review to story close turns the block into an
advisory, and that marker is session-scoped, so it must be set each session.

## v5.13.1 — An abort is not a commit, and a fast-forward is not a merge

Four defects on the commit path, all of one shape: a command that moved HEAD
without committing, or committed without being read correctly, and a gate that
believed it anyway. The most instructive one was introduced by this release's
own fix and caught by dogfooding it.

### A command that undoes work was arming the gates that guard work

`git merge --abort` and `git merge --quit` create no commit. Both were
classified as commit-producing, which armed the whole PreToolUse stack — review
cycle, secret scan, staged lint, trailer check — against a command that ends by
throwing changes away, and left a commit event recorded for a commit nobody
made.

The narrowing is SUBTRACTIVE, not an early return, and the distinction is the
whole fix: `git commit -m x && git merge --abort` still contains a real commit,
so an early return on seeing `--abort` would have disarmed four gates for any
command willing to append seven characters. The non-committing forms are
removed from the scan target and the question is asked again of what remains.

### A lock that killed the hook holding it

`update_coordination` armed `SIGALRM` and then took a blocking `flock`. Under
contention — two teammates committing at once — the alarm fired inside the
blocked call with the default handler installed, and the signal terminated the
hook process. The failure mode was a hook that died silently mid-write, seen as
`returncode -14`.

`flock_with_timeout` now takes an explicit `timeout_s`, and coordination passes
2 seconds rather than the event log's 10: `.coordination.json` is advisory, every
reader degrades without it, and every write is on a synchronous hook path, so
blocking a hook for ten seconds on it is worse than the stale entry a give-up
leaves. A give-up is LOGGED, never swallowed. Only the acquire is wrapped, never
the caller's body — wrapping the body would report a full disk as a lock failure.

`XP_LOCK_TIMEOUT_SECONDS` still outranks the caller's budget, which is what lets
a cross-process test narrow it.

### A commit message read out of the message's own body

`git commit -F -` fed from a heredoc had its `-m`-looking text scavenged out of
the BODY. A body containing `pytest -m "slow"` — ordinary prose, and this
repo's history is full of it — became the recovered message, which then failed
to match HEAD, so the success path never fired and **no commit event was written
at all**. Every `Resolves-Event:` id the author named stayed silently open.

Honest scope: this was pitched as covering seven recorded incidents and it
covers one or two. `-m "$(cat <<'EOF' … )"`, the other spelling that looks
identical in a transcript, parses correctly and always did.

A `-m` found INSIDE a heredoc body is now data and skipped, while one outside
every body stays an argument whatever its value contains — and the
`-m "$(cat <<EOF …)"` form is tried first, because it is itself a heredoc. The
first attempt at this deleted every heredoc-shaped span before the scan instead,
which mangled any message that discussed a heredoc; a close review caught it in
the same release. Every quoted delimiter spelling now counts as quoted, too:
bash disables expansion for `<<'EOF'`, `<<"EOF"` and `<<\EOF` alike, and
admitting only the first left the original defect alive one keystroke away.

A hand-run `git merge` records an event in one case it previously did not: when
the command supplies no readable message AND git prints no success line, the
HEAD-rebuild path recognises a merge landing from the reflog and tags it
`is_merge`, keeping it out of the resolves-link-rate denominator. A conflicted
merge finished by hand is recognised there too, spelled `commit (merge)`.

**Narrower than it sounds — the common shapes are not covered.**
`git merge --no-ff side -m "Merge side"`, and a conflict finished with
`git commit --no-edit`, both get confirmed the ordinary way (message match, or
git's `[branch hash]` line), so they take the shared success path, which does not
pass `is_merge` and records them as plain commits carrying the whole merged
branch as their files. These notes claimed the general case until a close review
measured both shapes end to end. (Closed in v5.15.0, "One merge policy, three
emitters".)

### The fix that claimed another clone's commit

That merge arm matched the reflog action by leading word, because `%gs` spells a
merge `merge side: Merge made by the 'ort' strategy.` and an equality test
against `merge` is inert. But `head_landing_facts` cut `%gs` at the colon — and
a fast-forward, which creates no commit at all, spells itself `merge X:
Fast-forward`. Same leading word. Fast-forwarding onto a merge commit counts two
parents, and origin tips very often ARE merge commits, so the parent-count guard
routed it into the merge arm instead of vetoing. Freshness was all that stood
left, and a tip pushed minutes ago is fresh.

Reproduced: a commit event carrying another clone's hash, message and files,
tagged as our merge, with any `Resolves-Event:` in that body live against real
ids. The trigger is an ordinary two-person day — a teammate pushes a merge, a
lead merges within five minutes.

`head_landing_facts` now returns the whole `%gs`; the truncation threw away the
one signal that distinguished the two. The merge arm ALLOWLISTS the detail —
git announcing a created merge, nothing else. A `fast-forward` denylist would
have to enumerate every other non-creating spelling forever and fail OPEN on the
first miss, while an allowlist falls back to the trace, which is what this path
did before the merge arm existed.

It escaped four close reviews and a green sprint. What found it was running the
plugin's own back-merge and reading the two traces it left.

To be exact about that, because a later note got it wrong: those traces were not
this bug firing. The hooks running that day were the INSTALLED plugin, v5.12.0,
whose merge arm vetoed every two-parent HEAD outright — so both traces were that
veto behaving correctly, and no released version ever had an arm that could
fabricate. The bug was real and reproduced against the working tree through the
test fixtures; the traces only prompted the reading that found it. Hook behaviour
observed while working in this repo comes from the installed copy, not the branch
being edited, and a claim built on a live trace has to name the version that
produced it.

### Also

- The commit-target worktree scan was reviewed for retirement and KEPT. The
  concern it raises has fired twice in another clone's archive, so the
  suspicion that it was noise was itself the thing that could not be verified.
- An end-to-end pin for the composition of the classifier and the message
  recovery, which no single suite reached: each was green alone while the seam
  between them could break.

## v5.13.0 — The conversions were not the point

This release set out to turn checkable claims in shipped docstrings into tests
that go red when the claim stops holding, and to measure whether doing that at
scale is worth it. The measurement came back 24.8%, and the conversions turned
out to be the least valuable thing the work produced.

### What a claim costs when nobody checks it

Triaging ten long docstrings across the close-gate cluster found 128 claims —
105 a machine could check, 26 of them unpinned. That is the headline number,
and it argues against funding more sweeps: the cluster was chosen precisely
because it measured the *thinnest* existing coverage, so 24.8% is the optimistic
end.

What the same reading found instead was four false claims, shipped, in the two
modules the cluster's behaviour actually turns on. `close_cycle_stop_gate`
described its `stop_hook_active` bypass as age-gated and named a constant as the
mechanism; the owning session has decided it since the liveness check landed,
and the repo's own tests falsify the age story in both directions. The constant
it named was read by nothing — it survived only in prose and in tests that used
it as a backdate value. The same docstring claimed the gate blocks whenever the
marker is present, omitting the evidence-release path.
`close_cycle_abandonment` said the marker is released only when the reviewer
completes, contradicted 190 lines below by its own recorder.

Two more turned up in the tests themselves, including a remedial message naming
a call site that does not exist.

None of that comes out of a conversion pass. It comes out of reading claims
against the code they describe, which is a reviewer's work — the same lesson
this project already recorded as "stale prose is caught by diff review, not by
sweeping unchanged code".

### A ratio moves against the work that corrects it

The `scripts/` prose ratchet compared the whole root against one recorded ratio
over a hand-kept file set. That shape has two failure modes, and both had fired.
A true claim is usually longer than the false short one it replaces, so
correcting prose RAISED the number the ratchet watches — it moved against
exactly the work it was installed to protect. And a sum lets one file's honest
deletion pay for another's regrowth.

It now measures per file, in absolute lines, against a table generated from the
scan rather than hand-typed. The tree drives the comparison and the table only
supplies numbers, so a file above the floor with no recorded entry is a
violation rather than an exemption — so a file added after the hand-kept set
was recorded can no longer stay unmeasured indefinitely by nobody thinking to
add it. The two that had been are `session_start_banner.py` and
`run_attribution.py`, and neither is measured today either: at 83 and 52 prose
lines they sit below the floor. What changed for them is the reason, not the
outcome — a rule they will trip on the way up, instead of an omission.

**The floor is 120 prose lines, and it governs 42 of the 144 files in
`scripts/`.** Below it a file is ungoverned — by a uniform rule now rather than
by omission, and it becomes a violation the moment it crosses — but ungoverned
all the same: this is a ceiling on the long files, not a bound on the tree.
Choosing 120 was a friction measurement, not a principle; at 60 roughly three
in five new files would have arrived red.

Measurement and slack are recorded as two numbers rather than one fudged one,
and both are public — the pin imports them to build the regrowth leg that gives
the slack constant its teeth.

### A pointer is not a promise

Converting a claim leaves a pointer where the claim was: "pinned in
`test_x.py`". Nothing checked that the named file existed. Two pointers in the
tree were already dead — both killed by file *splits* rather than renames, which
is the case a rename-aware habit misses. One of them justified an otherwise
unused import by naming the tests that patch through it.

A new pin now resolves every test file named in shipped Python, shell and
Markdown prose.
It matches file-shaped tokens only: shipped code carries `test_passed` and
`test_count` as event fields and `TestLayout` as a domain type, and a
bare-identifier matcher reports all of them dead. It states plainly what it
cannot do — it proves a named file exists, never that the file still asserts the
claim pointing at it.

### Two gates that failed open

`owner_session_is_live` compared a heartbeat's age against a staleness threshold
with no lower bound, so a timestamp recorded in milliseconds, or written across
a backwards clock step, aged negative and read as a live owner. Live is the
dangerous verdict: it suppresses the age fallback, leaving the close-cycle Stop
gate armed with nothing able to release it while the next close overwrites the
marker it should have recorded.

Separately, the review-cycle flag was written, read and cleared under two
different `agent_id` resolutions — some sites keying on the hook payload, some
on the checkout. A Stop payload carrying a platform agent id sent the close gate
looking for a key the Step 4b CLI never wrote, so it blocked an agent
mid-review.

The first attempt widened the gate's READ to accept either key, and that was
worse than the bug: the writes and clears stayed split, so the checkout-keyed
record never left mid-cycle and the gate deferred away every Stop for the rest
of its window — the close ended half-done with no nudge at all, where before it
at least blocked. Its own release review caught that.

Converging the eleven sites on one checkout-derived key came next, and it was
still not the fix — because the record held two fields that do not have the
same owner. `last_review_commit` is a sha, and its only consumer diffs
`{sha}..HEAD` inside a specific repo; the two flags say whether *this session*
has reviewed yet. Every site that touched both had to pick one owner for both,
and the four commit sites picked the repo the commit lands in while the seven
flag sites picked the session. `git -C <other-repo> commit` — the form this
project's own close skills prescribe for a fix in someone else's worktree — is
exactly where those differ, and there the gate read a record
`/xp-quality-review` never writes. Re-running the review could not clear it:
every writer kept writing the other one.

So the record splits, and the seam lands where the disagreement was. The
watermark is keyed on the target repo, the flags on the reviewing session, and
neither key can answer for the other's question. Collapsing both onto the
session would have been worse than the block it removed: a foreign sha makes
git's diff fail, the changed-file count collapses to the staged set, and the
gate stops firing silently. A loud false block is the better failure.

The review functions moved out of `markers.py` in the same change — it had
reached its 450-line sub-cap, and this was the group that grew.

### A gate that allowed a Stop but kept the marker

`close_cycle_stop_gate`'s evidence-release branch returned without consuming
`CLOSE_CYCLE_ACTIVE`. Allowing the Stop was never a release: the surviving
marker reached the SessionStart sweep, which has no evidence check, and became a
false high-severity "close abandoned" concern against a close whose reviewer
demonstrably ran — and that false concern then counts toward aborting a healthy
close. The branch now consumes the marker it was documented as releasing.

## v5.12.0 — A name is not the thing it names

Both fixes here are the same mistake in different clothes: something read a
label where it should have read the thing, and reported the label's answer with
full confidence.

### Moved is not deleted

`compact` and `repair` take events OUT of `events.jsonl` and put them under
`backups/` — `archive.py` calls that file "the ONLY copy of what was removed".
But `get-event` searched the live log alone, so an id that had been archived
came back **not found**. Ids stay citable forever: later events point at them
through `references` and `metadata.resolves`, so the answer turned relocation
into apparent deletion.

That is not a hypothetical cost. In this project's own log it produced an hour
of wrong diagnosis and two events that had to be retracted — a high-severity
claim that the adopt CLI silently dropped a write, and a follow-on claim that an
adopted retro Try had been lost. The event was in `backups/` the whole time,
carrying `disposition: adopted`, and the adoption ledger had it too. The tool
that reported the absence is now the tool that disproves it.

The scan lives in `archive.py`, which already owns the `backups/` naming
convention. Ordered by mtime rather than filename — the directory mixes
`archive-*`, `events-*` and `pre-repair-*` with collision suffixes, so a lexical
sort is not chronological, and a pre-repair backup is a whole-file copy, so one
id can genuinely live in several archives. Parsed tolerantly, because a repair
archive holds malformed lines by construction. Only `get-event` falls back;
`lookup_event`'s contract is shared with promote and question-close, which keep
reading the live log.

### Named like a test is not being a test

The commit gate selected work by filename. `scripts/test_parsing.py` and
`scripts/test_attribution.py` are shipped modules that happen to start with
`test_`; pytest collects nothing in them and exits 5, which lefthook reads as a
failed commit — so staging one alone refused the commit outright, with no way
out short of disabling the hook.

The same rule was blind in the other direction. `tests/conftest.py` and the
`tests/_*.py` helpers carry no `test_` in their names, so a change that can fail
thousands of tests matched nothing and ran **zero** of them, committing green.

Targets now come from what was staged rather than from a naming convention:
paths under the tests tree only, fixtures mapped to their containing directory,
files dropped when a selected directory already covers them. A directory target
runs with `-n auto` — the tree sequentially is the 432-second run the gate exists
to avoid, while the same tree under xdist is seconds.

The tests that were supposed to protect this asserted only that certain strings
appeared in `lefthook.yml`, which cannot tell a filter that works from one that
never fires. They now execute the gate's shell body against a stub runner and
assert on the arguments it actually receives.

## v5.11.0 — A milestone that disproved itself

The sprint set out to sweep stale prose out of three shipped roots. Its first
story measured the roots and found almost nothing to sweep: in the 2005-line
close/review subsystem, the "restates the code" bucket was empirically zero and
the next bucket yielded ~1.4%. Two of the four planned sweeps were cancelled on
that evidence and replaced with a rule for diff reviewers, because stale prose
is caught where prose is written, not by re-reading code nobody touched.

### Checks that fired on the work they were meant to protect

**The prose ratchet punished extraction and claim-narrowing.** It compared the
tree against a number recorded on a different tree without recording WHICH files
the number covered, so any change to the file set read as prose growth. Splitting
a file past the 500-line rule adds a module docstring and no code, and a claim
narrowed to what is true is longer than the false short one it replaced — so the
ratchet moved against both. It now names the 142 files it was measured over, and
a name whose file vanished fails loud instead of quietly shrinking the measure.

**Sprint verify ran the same suite nine times.** `--sprint` shelled one
subprocess per (story, command), and nearly every story declares the whole-suite
E2E check. One sprint enumerated 21 items that were 13 commands and spent ~35
minutes. Worse than slow: the batch budget skips items in sprint order once
exhausted and skipped items gate the close as red, so duplication could push
genuine checks out of the verified set. Execution is deduped; reporting is not —
every story keeps its row.

### Backgrounded commits outran their own hook

`PostToolUse:Bash` fires when the tool call returns, which for a backgrounded
command is at launch — before git has moved HEAD. 79% of ordinary commits left
no event, taking `Resolves-Event:` links and story attribution with them. The
hook no longer reads a launch as evidence the commit did not land. Recovery
happens at the next commit-shaped call that itself fails confirmation, so two
shapes keep no observer: the last backgrounded commit of a run, and one followed
by a foreground commit, which confirms normally and never probes the prior HEAD.
Both residuals are recorded rather than implied.

### Also

- Vocabulary bans match on genuine use, not substrings — `.rs` no longer fires
  inside `.rspec`, while `snake_case` internal names stay banned behind suffixes.
- Both reviewer definitions gained a verify-the-claim lens.
- Diagnostics relay both streams at eight sites that reported one and dropped
  the other.
- The stop gate tells an agent what actually clears it, per branch state.
- A sprint review already running no longer reads as one never started.
## v5.10.0 — A number you could not check, and a field that got shelled

### Every red looked the same

A test-failure concern recorded that something failed and nothing about which
run. A one-test scoped run, a `docker compose exec … pytest`, a teammate's
worktree and a 508-test suite all rendered as one line at kickoff. Diagnosing a
single such streak had already cost a scheduled story: the largest suite in the
flagged window held 23 tests while the real one held 508, and every full-suite
run in that window was green.

The concern now carries the working directory — `$HOME` collapsed to `~`, so a
durable log that renders back into prompts stops carrying a username — and the
run's counts. The command is deliberately never recorded: a command line can
carry a token, and a test pins that it does not leak.

**The other producer knew less and had to say so.** `bash_failure` handles runs
that exit non-zero with no readable summary, so it often has no count at all.
It stamps the same keys through the same builder, but never a total: with no
summary line the counts come from two independent last-match scans, and their
sum can pair numbers from unrelated lines. A missing denominator is honest; a
fabricated one looks like a measurement. The triage render degrades to match —
`2/23 failed in x`, then `2 failed in x`, then `in x` — because the run nobody
could count is the one a reader most needs attributed.

That rule then had to be carried back. The parsed producer was summing an
unanchored pair too: a 500-test Playwright run showing only `2 failed` recorded
`2/2` — the whole suite red, and the number looked measured. The parser now
reports whether one summary line yielded the pair, and both events read that
single answer instead of two spellings of a trust rule.

### Prose in a field that gets shelled

Story-level acceptance already refused `command` on a `type: manual` block, so
observational prose had exactly one home and could never reach a shell. The
milestone-level caller left that flag off — and the sprint reviewer shells a
milestone's `setup`/`command`, producing the same exit-127 red no operator can
make green, one level coarser. The module said so about itself and called it an
open gap.

The flag was never the work. `validate_plan` walks every milestone on the READ
path, so switching it on would have made stored plans unloadable. The fix is a
per-item grandfather derived from the document already on disk, exempting only
a block that is unchanged, and failing closed on a missing, symlinked,
unreadable or corrupt source — an exemption that failed open would be a bypass
reachable by deleting a file. Run-time is untouched: what can be written
narrows, what a written block does is unchanged.

### Gates that could not catch their next case

Three defects surfaced only in review, and each was a check that had stopped at
the case which created it. The re-export contract said *every* public name
belongs in the list while its test enumerated the ten that had once regressed,
so name eleven walked through; it now sweeps the module. A validator contracted
to *return* errors could still raise, because appending a type error did not
stop the lookup below it. And the discriminator the TDD gate routes on was
asserted by no test in the tree.

## v5.9.0 — Three checks that vouched for themselves

### Evidence about a neighbour is not evidence about you

Each of these reported a state it had not established, and each looked healthy
because the thing it consulted was real — just not about the session asking.

**The liveness read borrowed a stranger's heartbeat.** A process that could
discover no session id addressed the shared marker, missed, and then accepted
ANY fresh per-session heartbeat as proof that its own hook runtime was live. A
session whose runtime never loaded read LIVE off a neighbour — the silent
unenforcement the whole mechanism exists to make loud. Both copies of that
borrow are gone, from the absent path and the stale path. The scan survives only
to say what it saw in a refusal, never to grant one.

**The status line contradicted the context beside it.** `hook_output` sends
`additionalContext` to the agent and `systemMessage` to the user. On a
validation failure the agent read `SMM init failed — xp-agents disabled` while
the user read `XP agents (vN) active. Run /xp-kickoff.` — invited into the one
session no gate could police. The cause was two notions of one directory in
`main`: the unvalidated resolve handed to the banner, and the validated one
`run` computed and never returned. One validation now picks both channels.

**Our own heartbeat vouched for another agent's entry.** One session holds
several agent ids: a non-xp subagent writes its own coordination entry under our
session id, and because our heartbeat is beating — we are the one working — that
entry read live for as long as the session lasted. It now reads UNDETERMINED and
its own TTL decides. Not discarded: a backgrounded subagent really does edit
files while the lead sits at Stop, and the gates ask whether someone may be
WRITING, not whether the writer is a teammate.

### The teammate path had the same defect, one door over

Fixing the lead's banner left `enforcing` hardcoded true wherever the lead's
validation did not run. A teammate whose pinned tree became unusable read
"active" while every gate bailed on a missing directory — and a test asserted
that banner byte for byte. The teammate's tree is now validated from the
environment that names it, and both channels carry the verdict, because telling
the user and not the agent is a disagreement nobody can see.

### What this release does not claim

**One story shipped no behaviour.** The own-session verdict ends this release
byte-identical to what v5.8.0 already had. Its story changed the verdict to a
flat skip, the close review found that discards live background writers, and it
was reverted. That story's delivery is its tests and its prose.

**A planned clause is not here.** The milestone's goal promised the recursion
guard a harness-neutral leg. Measurement says it cannot be written yet: the
second harness reports `agent_type` as `default` for every subagent, so a
prefix test has nothing to discriminate on, and a manifest `agents` key is
silently ignored there, so those subagents are not installed at all. Keying on
the field's PRESENCE would work on both hosts, but it would also stop hooks
firing inside the non-xp subagents that coordinate deliberately today — a
harness-neutral-hooks decision, recorded and deferred to that milestone rather
than made quietly here.

## v5.8.0 — Three gates reported on input they never looked at

### A gate that answers for input it cannot see is worse than no gate

Each of these had been green for months, and each was green because it never
examined the thing it claimed to check.

**`bun test <spec>` was never gated.** bun was classified as a whole-tree
runner, so every bun command collapsed to the `.` sentinel and a bun story's
authored proof file was never demanded. bun is a hybrid — `bun run test` is a
package-script alias, `bun test a.test.ts` names a spec — and only the alias
half was modelled.

**The file-size ratchet discovered Python only.** It called itself tree-wide
while `_line_count` was `splitlines()` and the cap is a project convention, not
a language rule. Every shipped shell file was ungoverned: `_preload_base.sh`
sat at 492 lines, inside the 450 band and 8 from the hard cap, seen by nothing.
Discovery now selects by suffix at any depth, so a future `hooks/*.sh` cannot
be invisible in the worst way — invisible to a floor that never existed.

**The commit-hook predicate answered a different question than it asked.**
`will_fire_hook` promised "will git actually fire a hook?" and returned true if
a runner *config file* merely existed. A clone that ships `lefthook.yml` without
running its installer reported its commit gate present while git fired nothing.
Not hypothetical: this repo did exactly that mid-sprint, suppressing the block
whose whole job is to say the merge runs no project tests. The declared-intent
question moved to the consumer that wants it — seeding, where a
declared-but-uninstalled runner legitimately counts as hook-aware.

### The bun fix was inverted before it shipped, and review caught it

Reclassifying bun assumed its positionals are repo-relative paths. They are
substring *filter patterns*: `bun test math.test` runs `src/math.test.ts`. So
five ordinary commands began demanding proof paths no commit can touch —
including `src/*.test.ts`, a piped `| tee out.log` tail, and a `--cwd`-relative
spec compared against repo-relative git output. An unsatisfiable required path
is strictly worse than none: the sentinel fails open, a false positive can
never go green. The gate the release exists to fix was inverted, not closed.

bun is now positional only for a single-segment, glob-free, cwd-flag-free
command whose positionals carry a directory separator or a source extension.
Every rejection lands on the sentinel — the behaviour these commands had
before bun was extracted at all — so no retreat can block a merge. Chained bun
commands retreat too, a real coverage cost stated plainly in the tests rather
than papered over.

Narrowing the hook predicate also removed the leg that had been masking a
second defect: `resolved_hooks_dir` joined `.git/hooks`, which names a path
that never exists in a linked worktree, where `.git` is a file. Since teammate
closes run in worktrees, shipping the narrowing alone would have told every
teammate the merge fires no tests while lefthook was running them. It now asks
git, guarded on the repo existing — `rev-parse` answers about the repo it
*finds*, so an unguarded call describes an ancestor repository instead.

### Also

- Declared verify paths are compared in one normal form, so `pytest
  ./tests/a.py` is satisfiable. It previously declared a path git never
  reports — the same can-never-go-green failure, on the runner this project
  itself uses.
- The framework flag-gap no longer spans `;&|`, so no detector binds one
  command's runner to another command's `test`.
- A hang guard on the hook-dir lookup sits far above spawn latency. Measured at
  5s it tripped under parallel load and silently turned `present` into
  `absent`, which is the failure class this release is about.

## v5.7.0 — Shipped guidance had no reverse gear for its own prose

### Five lines told readers to put things in comments, and offered no way back

The guidance that decides where content goes had one destination for anything
that didn't fit: a code comment. Five lines across `PROCESS_GUIDE.md`,
`xp-housekeeper.md` and `xp-system-analyzer.md` routed overflow there —
"belongs in code comments", "belongs as code comments", "goes to a code
comment" — and not one of them named a test as an alternative. A comment is a
claim with no test. Guidance that only ever routes *into* prose is a pipeline
with no reverse gear, and this tree's characteristic defect is the fail-silent
one: a comment describing code that no longer exists fails nothing, ever.

All five now route by checkability: a checkable claim goes to a test, where it
rots loudly; history goes to git; a comment carries only the why or constraint
the code cannot express. The rule is language-agnostic by construction — it
turns on the *kind* of claim, never on any language's comment syntax.

Both reviewers gained a named Prose Hygiene dimension stating the same rule,
scoped to comments in the changed code, with rejected-design and
external-constraint comments explicitly exempt. Those are the hardest-won
knowledge in a tree and have no other home; a lens that attacked them would do
more damage than the rot it was hunting.

`/xp-quality-review`, the only thing that spawns the per-increment reviewer, now
enumerates that dimension in the prompt it builds. It previously listed four
areas, and a subagent follows the concrete task it is handed over the preamble
of its own definition — so the lens the release exists to add ran on nothing.

The close reviewer had the same gap, and the first version of the fix missed it:
all four close skills write their own spawn prompt naming only that mode's
focus, so the mode-independent prose section shipped with nothing ordering it.
Both reviewer pairs are now pinned caller-and-agent together, because pinning
one pair and leaving its sibling open is how one defect ships twice.

And the rule now ships rather than living only here: `smm/seed_smm.py` seeds it
as Wisdom, so a project adopting the plugin inherits the lesson and not just the
reviewers that enforce it.

### The pins that enforce it were themselves under-matching

Three defects in this release's own gates were found by review, not by the
author, and each is the exact shape the release is about — a check that reports
success while seeing less than it claims.

Both routing matchers were case-sensitive. An ordinary Markdown bullet opening
`- Code comments hold anything left over.` escaped the selector completely, so
neither the rule check nor its vacuity guard ever considered it; meanwhile a
compliant line opening `A test holds the checkable claim…` was reported as
*missing* a test destination. A gate that false-positives on correct prose is a
gate someone switches off.

The selector still over-matches: it is a phrase match on "code comment(s)" and
cannot tell a destination from a mention, so prose that merely discusses code
comments is held to all three legs. Both directions are now pinned as cases
rather than claimed in a docstring, and the narrowing is recorded as debt —
every narrowing tried so far under-matched one of the comma- or "else"-joined
forms the tree actually ships.

Each surface was also pinned alone, so nothing compared them, and the tree
shipped four different versions of one rule. Only one of five lines stated all
three destinations. A cross-surface pin now holds every routing line to the
whole rule, matching on the rule's **body** rather than on a heading or filename
— heading-anchored pins pass vacuously the moment a section is renamed.

The forbidden-vocabulary list had grown a second copy inside the routing pin,
free to drift from the registry it duplicated. Consolidating it needed a
distinction that had been lost: the registry is applied to a selected *section*
and legitimately contains tokens shipped prose uses (`.py` appears in 29 of 31
files), while the corpus-wide pin can only ban tokens with no legitimate use
anywhere. So the registry is now split by the scope its consumers apply it at,
and detection lives in one module both pins read instead of one reaching into
the other's private names.

### Also

`smm/seed_smm.py` sat at 499 lines against a 500-line cap, leaving the new
seeded entry nowhere to go; its project-feature detection moved to
`smm/seed_detect.py` and is now tested against that module directly, rather than
through the re-exported names a tidy-up could rebind. While it was open: an
empty or shebang-only `.git/hooks/pre-commit` had counted as a configured hook,
suppressing the seeded ungated-commits risk for an adopting project, and a dead
guard claimed to reject git's sample file on a suffix the path can never carry.

One of the two corpus-wide routing pins was strictly weaker than the other —
same corpus, same selector, checking one of the three legs the sibling already
checks — so it is gone, and with it the fixture copies of shipped prose that had
nothing keeping them in step. Its vacuity and single-language legs stay.

`PROCESS_GUIDE.md`'s Constraints bullet kept the exclusion it had before the
rewrite: detail routes out of the pillar. Without it the routing clause read as
advice about the pillar's own entries, which would have the housekeeper pruning
architectural bounds for the crime of being checkable.

Releasing is now recorded as a convention — a merge to main bumps the manifest
version and adds a CHANGELOG entry — held deliberately as a convention rather
than a test.

## v5.6.0 — Gates tuned on one harness, measured against another

We set out to answer whether this plugin could run on a second CLI harness. The
answer is in `docs/completed/CODEX_SPIKE_FINDINGS.md`. The more useful result
was accidental: pointing the gates at an unfamiliar harness, and reading what
they actually recorded, caught twelve of them reporting something other than
what happened. Those fixes are the release. The spike rig itself is deleted —
the findings document is written for a reader who cannot re-run anything.

### A gate that released itself

The TDD Stop gate read `agent_id` straight off the hook payload. On `Stop` that
field is always empty, so the coordination check it fed compared an empty id
against every entry, concluded another agent held the work, and released. Not
occasionally — every time, in every solo session, for as long as the gate has
existed. It was reported as a gate; it was a no-op.

### Two ways a path stopped pointing at your repo

`git -C "/some/path" commit` and `cd "/some path" && git commit` both resolved
to the hook's own working directory. Quoted paths were stripped before anything
read them, so the commit gate scanned a different repository than the one being
committed to, found no story branch, and allowed the commit. Neither form
errored; both silently answered about the wrong tree.

Both now route through one masked-locate/raw-read module rather than two
parallel fixes, and a target that cannot be read confidently **refuses** instead
of falling back. A line-continuation form (`git -C /p \` + newline + `commit`)
that previously matched no detector at all is now matched.

### A parser that invented results

With no summary line to anchor on, the test parser scanned the whole tool
response and reported whatever numbers it found. A co-executed tool supplied
them: `ruff check && pytest` with ruff at *"Found 2 errors"* recorded `88
passed, 2 failed` against a suite that was 88/0 — and then armed the failure
gate on the phantom. Counts are now scoped to the runner's own summary line, and
a run with no identifiable summary reports **no result** rather than a
fabricated one.

Colour was doing the same damage more quietly: an escape sequence sitting
against the anchor token puts two word characters side by side, so `\b` finds no
boundary and the anchor never matches a coloured run.

Two more surfaced at close review. pytest read only the **last** summary line
while every other runner summed, so `pytest unit && pytest integration` with
three failures followed by forty passes parsed as zero failed — and since the
shell reports only the last command's status, nothing downstream would have
caught it. And one package printing `No tests found` zeroed an entire workspace
run, discarding its siblings' counts.

### Coordination could not tell a dead agent from a live one

Teammate liveness was a 30-minute TTL on a timestamp. A killed teammate kept
releasing the lead's gates for the rest of that window, and a report of a
teammate's death was indistinguishable from its success — a process that died
mid-edit still exited 0 and printed the success line. Liveness now reads a
heartbeat the dead cannot refresh.

Honestly stated, because the first version of this fix was wrong in the other
direction and the second is a judgement call: the trust window is a dial, not a
proof. The comments that oversold it — claiming the two clocks always age
together, and that both callers fail safe — were measured and corrected rather
than left standing.

### Scheduling decisions made on absent evidence

An empty `file_domain` meant *unknown*, but intersecting two empties yields an
empty set, so unscoped stories always read as mutually disjoint and were offered
as a parallel batch. Three stories that would have collided on the same files
were cleared to run concurrently.

The accept gate prompted *"run /xp-accept to verify acceptance criteria"* for
stories that declared nothing any command could check. It still fires exactly as
often; it now names the stories whose acceptance nothing can prove.

A contradiction detector filed confirmations as contradictions, because it read
an event's `references` list as *refutes* — and that field is mandatory and
non-empty on every discovery, so supporting evidence and contradicting evidence
were indistinguishable to it.

### Also

The schedule gate's merge exemption was per-checkout rather than per-file: while
`MERGE_HEAD` existed, every write was exempt, so an abandoned merge disarmed the
gate wholesale. Only files with genuinely open conflicts are exempt now, and
staging a resolution ends that file's exemption immediately.

An outer close counted concerns from a window that began after an inner close
had already filed its findings, so a story close's discoveries could not reach
the sprint close's own gate.

## v5.5.1 — Three gates that were reporting things that weren't happening

### A green suite could file a failure, and then refuse to let go of it

A Bun suite at 4373 pass / 0 fail recorded `1 failed`, filed it at high
severity, and armed the Stop gate — three green runs running. The number came
from a test file whose own source reads *"the batch must report 1 failed"*,
echoed back inside the runner's error context ahead of the summary. The count
regexes scan the whole payload and took the first match they saw. Running the
suite, the one action that should clear such a gate, re-parsed the same phantom
every time.

Counts now come from the summary **line**, and every summary line counts.
First-vs-last was a false choice: cargo prints one `test result:` per test
binary plus a `Doc-tests` block, a dotnet solution prints one per project, and
a workspace launcher (`pnpm -r test`, turbo, nx) prints one per package — none
of them emit an aggregate. Reading a single match reports one sub-run and
erases the rest, so a green package hid a red one, in whichever order they
happened to print. Anchoring on the runner's own summary line and summing
across them reports the run, and text that merely *looks* like a count — the
echoed source line, a mocha test title reading "must report 7 failing rows" —
is simply not on a summary line. Runners with no line-identifiable summary
(bun, deno, playwright, node-test) keep the last-match scan as a fallback.

Three more parses were wrong before anyone looked: jest reported `Test Suites:`
counts as test counts (that line precedes `Tests:`); a red cargo run under
`--no-fail-fast` reported **0 failed with no concern filed**, because the
doc-test block that closes every run says `0 failed`; and pytest's `errors`
count came from anywhere in the payload, so a second tool sharing the Bash call
(`pytest -q; pyright`) could zero the collection errors that were the run's
only failure signal.

### Your own reviewer is not a competing agent

`Overlapping working_on: agent 'xp-code-reviewer' is also working on …` — filed
at medium severity, into the Risks view, against a subagent the session had
just spawned onto the diff it was reviewing. The conflict detector skipped only
the caller's own id, so every plugin subagent read as an independent party.

Two shipped skill templates made this permanent rather than occasional:
`/xp-plan` claims `execution_plan.json` and `/xp-sprint-start` claims
`sprint.json`, and nothing ever clears a self-named claim — so both were set to
fire against every future writer of those files, indefinitely. Teammate
worktrees are unaffected: their ids carry no `xp-` prefix, and the cross-agent
conflict the detector exists for still fires.

### A directory name could forge a preload line

`/xp-scaffold-worktree`'s preload emitted `REPO_ROOT` with a raw `echo`, which
cannot neutralize a newline in the value. A checkout whose path contains one
emitted two lines, the second entirely attacker-named — and `REPO_ROOT` is
substituted verbatim into `--cwd`. It now routes through `emit_path_var`, like
every other path-valued preload variable.

### Also

`close_common merge --archive-sprint` without `--smm-dir` refused *after* the
merge commit had landed, a state no retry resolves; it is static argument
validation and now precedes every side effect. A `--smm-dir` that is not an SMM
is refused there too: it used to exit **0** while merging, writing an
`events.jsonl` and a `sprints/` tree into the typo'd directory, recording no
merge-commit event in the real SMM, archiving nothing, and deleting the source
branch anyway. Without `--archive-sprint` only the fail-open accounting event
is at stake, so that case warns instead of aborting a correct merge. The
"nothing archived" warning now reports the evidence it actually has rather than
asserting a cause.

`cleanup_teammate` proves a teammate branch is merged, then removes the
worktree and deletes the branch — two steps, and the deletion can still refuse
if a commit lands between them (the parallel-teammate case). It discarded that
refusal, deleting the markers, report and story assignment that were the only
records naming the branch, and exiting 0. It now keeps them and says so.

`session_end`'s summary read the same never-cleared `working_on` claims the
conflict detector was reporting on, so plugin subagents showed as in-flight
work in every session summary; it applies the same `xp-` fence.

## v5.5.0 — A bootstrap command you verified, and a close cycle that cannot die quietly

### Scaffold a worktree bootstrap, don't guess one

`stack.worktree_bootstrap` brings a fresh teammate worktree up — installs
dependencies, generates types, starts what the project needs. Writing that
command was on you, and getting it wrong is worse than leaving it empty: an
unverified command restores exactly the false-green the field exists to kill.

A measurement over two real repos is why this ships the way it does. Two
plausible candidates were tried. **Both exited 0.** One installed 2208 packages,
looked perfect, and fixed neither failure it was supposed to fix. A command's own
exit status proves nothing about whether it closed the gap.

`/xp-scaffold-worktree` therefore never trusts a candidate. It measures your
declared command in your checkout and in a throwaway bare worktree, compares the
two true exit codes, proposes a candidate by reading your repo, and then
**re-measures**. It declares `stack.worktree_bootstrap` only when the gap
actually closed — and refuses, asking you to author the command yourself, when it
did not.

Three conditions must all hold before it declares, and each one closes a way the
measurement can lie: the exit codes must now match, the worktree leg must exit
**0** (matching failures also "match"), and the measurement must not be flagged
degraded (a throwaway that lands inside the repo reaches your installed
dependencies by walking up, so a real gap reads as none).

It also discloses, before asking, that verification runs the candidate in your
**primary checkout** as well as the throwaway — installs and generated files land
on your real working tree. A degraded measurement stops the skill at detection,
whichever way it came out: that flag reports where a worktree base resolves, so
it will be there again on the re-measurement that refuses on it, and stopping
early saves you two full command runs and those installs.

The system analyzer still records a bootstrap command your repo already
documents, which a measurement vindicated. It now says plainly that a recorded
command is **unverified**, and points at this skill to verify it.

### An abandoned close cycle leaves a record

A close cycle that died mid-flight was indistinguishable from one that finished:
the marker was swept silently at the next session start, so "the reviewer never
ran" and "the reviewer ran and passed" looked the same from outside.

Three detectors now record the abandonment — the session-start sweep, a new close
starting over a dead one, and the existing aged-stop detector — all sharing one
content, one budget owner, and one age rule so they cannot drift.

**The owning session is what makes the record mean anything.** The marker is not
session-scoped and the SMM is shared across your windows and worktrees, so bare
existence cannot tell a dead cycle from one that is still running: a second
window's fresh start sees your live close, and a close whose own first gate
refused re-arms seconds after the survivor it just left. Recording either would
file a high-severity concern that the LIVE close's own merge prompt then reads as
a reason to abort — a close that never failed, told to abort by its neighbour.

A duration cannot separate the two, and we tried one first. A close's runtime is
unbounded — the close that shipped this very change ran seventy minutes while
perfectly healthy — so any threshold long enough for a slow live close is also
long enough to let a dead one sit undetected, and any threshold short enough to
catch the dead one starts firing on the live one. It moves the false record
later; it does not remove it.

So arming now stamps the marker with the session that owns the close, and a
detector in another window asks that session directly whether it is still
running. A live owner is never abandoned however long it has run; a dead one is
abandoned however recently it died. Age survives only as the fallback for a
marker whose owner cannot be named — one armed by an older version — because the
two mistakes are not symmetric: a false record breaks a healthy close, while a
missed one is only the silent loss that predates all of this. A healthy session
still pays nothing.

A record that does not land no longer consumes the marker either: the append is
reported rather than swallowed, so a dropped one leaves the evidence for the next
detector instead of destroying it along with the report. The aged-stop detector's
stderr line claims a concern was recorded only when one actually was.

Step 6b now releases the Stop-gate marker as well as the cycle id — for the three
close modes that arm it. Story-close arms none, and reads the same shared
reference, so consuming there would release an enclosing close's live gate.

The Stop gate's behavior under the platform's re-entry flag is deliberately
**unchanged** and now pinned as a regression: it yields, exactly as every sibling
Stop gate does, because blocking there risks the infinite loop those guards exist
to prevent.

### Removed: `system_context_cli surface-commands`

Two doors answered "which commands cover this changed set", and only one carried
the exit-status refusal that stops a command whose failure never reaches the shell
from auto-merging a red suite. The unguarded one had no caller. It is gone;
`scripts/close_gate_commands.py` is the single door.

## v5.4.0 — Teammate worktrees stop what they started, and story close stops paying for the whole suite

Two threads. The first closes a leak your machine has been carrying; the second
cuts what closing a story costs.

### Teammate worktrees can stop what they started

`git worktree add` hands a teammate a bare checkout, so `stack.worktree_bootstrap`
exists to bring one up — install dependencies, generate types, start whatever the
project needs. Nothing ever brought it back **down**. A bootstrap that started a
database container, a dev server or a language server left it running after the
worktree it belonged to was gone, on every teammate story you ever closed.

Declare `stack.worktree_teardown` in `system_context.json` and it runs inside the
worktree, at the single removal choke point, before the directory goes away. Like
bootstrap it is an opaque command by design — your script knows what it started
and what is safe to stop; the plugin cannot and should not guess.
`/xp-system-context` will record a teardown your project *already documents*, and
will not invent or compose one.

Bounded and non-fatal, deliberately: 90s (`XP_TEARDOWN_TIMEOUT_S` overrides), and
a non-zero exit, a timeout, a command that will not start, or an unreadable
`system_context` are each reported on stderr and swallowed — cleanup that refuses
to clean up is worse than the leak it exists to prevent. An unreadable context
says so out loud rather than degrading silently, so an operator whose declared
command stopped running finds out.

It runs wherever a worktree is removed by **force** — the cleanup after a story
closes, and a re-spawn that owns the branch it is clearing. It does *not* run on
the non-forced removal, which is what a re-spawn takes when a live peer may still
own that tree: git refuses to remove a tree holding uncommitted work, and
stopping that peer's stack out from under it would strand them mid-story.

**Declared commands are now killed as a group.** Bootstrap, teardown and your
acceptance commands each run in their own process group and are killed as one when
they time out. `subprocess.run(shell=True, timeout=...)` reaps only the shell it
spawned, so an acceptance command that backgrounded a stack left it running after
close had moved on — the same orphan leak, reached from a different door. The
unattended acceptance batch also gained a bound it never had (7200s), and the
`/xp-accept` path a bound it never had at all; both mean "never hang forever", not
"fail fast", so an hour-long suite still passes comfortably.

That bound is **per command**, so the sprint-wide rerun also gets a total: 4h
(`VERIFY_BATCH_TIMEOUT_S`; set it to 0 or a negative to run unbounded). It decides
which items *start* and never kills one already running, so a slow suite keeps its
two hours while an eight-item sprint can no longer run overnight inside close. The
items it never reached are named — in the matrix, in the status output, and in the
merge refusal — and they hold the close red, because some items green and the rest
unknown is not a verified sprint.

**Half of this thread did not ship.** The skill that would detect a missing
bootstrap and *verify* a candidate you supply is deferred.
`scripts/worktree_differential.py` — the instrument it was to be built on, which
runs one declared command in your checkout and again in a bare worktree and
compares the two true exit codes — ships and is runnable by hand, but nothing
calls it for you yet. It exists because a candidate's own exit code proves
nothing: two plausible bootstraps both exited 0, one installed 2208 packages,
and neither fixed the failure.

### Story close stops paying for the whole suite

Closing a story ran your entire test command. On a project whose acceptance
suite takes an hour, every story paid that hour — and the gate that ran it
merges without asking.

Close now runs only the commands covering the surfaces your change actually
touched. Declare `paths` and a `command` on an acceptance surface and both
story close and free close narrow to it; declare nothing and everything behaves
exactly as before. `/xp-system-context` proposes the fields for you, confirms
them, and never infers a command it did not read.

**It narrows all-or-nothing, on purpose.** If your change touches one file that
no surface claims, the whole selection is discarded and the full command runs.
Partial narrowing is the one shape that tests *less* than what it replaces, and
the consumer is an auto-merge gate — so the analyzer also proposes a
command-less surface covering the leftovers (docs, config), which buys coverage
without adding a run.

Selection reads the close diff, not the story's declared file list, so a file
you touched outside the plan is still covered.

Three things worth knowing before you turn this on. `/xp-system-context` states
all three and asks you to confirm, because none of them can be decided in code:

- **Coverage is checked by path, not by blast radius.** The selection proves
  every file you touched is claimed by some surface. It cannot prove a change in
  one surface does not break another — that is undecidable across languages — so
  a cross-surface break can auto-merge at story close, and **no later step
  re-runs the full suite**. Sprint close reviews the diff and asks a human; it
  never runs your test command. Declare `paths` where you have evidence the
  surfaces are independent.
- `stack.test_command` is expected to cover **every** surface, because it is
  what the gate falls back to and what a full selection collapses to. Point it
  at a script that calls each suite, not at one of them.
- A selection covering every declared command runs the full command once
  instead of N — N narrowed runs cost more than the one they replace.

**The gate re-checks its own command set before it merges.** The commands are
resolved once, when the close begins — but a review fix landing mid-close can
touch a file the frozen set covers nowhere, and that file would have merged
untested. The block now carries a recheck as its own first command: it re-derives
the set at merge time, against a pinned merge-base and including uncommitted and
untracked work, and exits non-zero if anything moved. Drift can only ever send
the close to the human prompt — it can never fail toward auto-merge.

### One regression, stated plainly

**If your `stack.test_command`'s exit status cannot reach the shell, close
auto-merge now turns itself off.** `pytest -q; echo done` exits 0 when pytest
*failed*. So does a bare pipe, a trailing `&`, a `|| true` fallback, and a
`$(...)` that captures the runner. The gate reads that zero as a pass and merges
without asking — it has been greenlighting red suites. Commands in that shape are
now refused, and the close falls through to asking you.

`&&` propagates failure and is unaffected, and a substitution that only supplies
an *argument* — `pytest -n $(nproc)` — is fine: the runner is still the command
whose status the shell reports.

This is a behavior change for anyone in that shape today: you lose an auto-merge
you had. You were not getting the check you thought you were. The no-block hint
now names which case you are in (`not-set`, `exit-status-masked`, `unresolved`)
instead of telling everyone the field is unset.

Scope, stated plainly: nothing narrows until surfaces declare `paths`. Apart from
the refusal above, this release changes no close behavior for existing projects.

## v5.3.1 — The code reviewer stops filing items that cannot be closed

When a diff introduced a new architectural pattern, the code reviewer nudged you
to record a decision about it — and filed a low-severity concern when you had
not. That concern's subject is a *missing* artifact, so nothing you do later
closes it: you record the decision, and the item asking for it stays open
anyway. On this project's own log, four such items were still open with the
requested decision already recorded, two of them within seven minutes.

The nudge now goes in the review summary, where it already worked, and records
nothing. Your open-item list stops collecting entries whose success condition
leaves them open.

Scope, stated plainly: this removes one generator, not a backlog. Most open
concerns are real findings waiting to be scheduled.

## v5.3.0 — Your close reviewer was reviewing blind, and the budgets only bounded prose

**Every sprint, plan and free close since late June spawned its close-reviewer
with a dead file path.** A close renders your project's system context — stack,
conventions, branching strategy, principles — to a tempfile and hands the path to
the reviewer. A preload that runs *in between* swept that tempfile as stale. The
reviewer then read nothing and reviewed anyway, because it only checks whether
the path was *supplied*, not whether the file was there. Twenty-eight closes
reported normally with no conventions input. Two commits from May and one from
June were each correct alone; the third closed the circuit. The sweep no longer
touches that pattern, and a pin holds it in both directions — the artifact must
survive, and the sweep must not quietly become a no-op.

**Your context budgets were measuring an empty project.** All seven budget
families ran against a synthetic, near-empty shared model, so they bounded the
*prose* a surface emits and were blind to the *data* it renders. On a real
project the difference is not small:

| surface | budget said | actually emitted |
|---|---|---|
| work-selection preload | 100 | 105,739 |
| accept preload | 100 | 40,481 |
| retrospective input file | no bound at all | 204,224 |
| housekeeper input file | no bound at all | 79,068 |

An eighth family now measures every injected surface against a *populated*
model. Each surface is either bounded, or carries a written reason it cannot be
— prose-dominated (re-measured every run, so the claim cannot rot),
needs-a-trigger, or structurally silent. A surface with no classification fails
by name. There is no allowlist to forget to empty.

**The triage block you read at kickoff no longer grows forever.** It rendered
every open concern, debt and question in full — 43,073 chars on a real log, and
climbing with every item you had not closed. It is now bounded outright: the
newest items at full length, ones you already deferred as short index lines, and
everything beyond that collapsed to a single counted line naming a command that
lists the rest. Nothing vanishes — an item that disappeared would read as fixed.
High-severity concerns are never the ones dropped; the cap ranks on severity
first, because the renderer already refused to *shrink* them and a cap that
ranked on recency alone was deleting exactly what that rule protects.

Same treatment for the per-story concern block, which had neither a length nor a
count limit and was rendering a story's entire backlog at full width.

**Subagents you did not name no longer get the whole model.** An unrecognised
agent type — including every agent type *your* project defines — was handed the
full render on the theory that unknown means we cannot rule out needing it.
Measured, `statusline-setup` was receiving 5,856 chars it can never use. Unknown
types now get a ~250-char pointer and fetch the model themselves if their work
calls for it. Types we can name and have judged (Explore, the code reviewer,
Plan) still get it eagerly.

**A file-domain collision could put two teammates on one file.** The start-time
guard asked whether the colliding set had *grown*, which meant a collision
already present on disk was read as pre-existing and waved through — and the
same stale claim, in mirror, permanently blocked an unrelated story from ever
starting, with no supported way to clear it. The guard now asks the absolute
question, scoped to the story being started, and a story's branch claim can be
released rather than hand-edited out of your sprint file.

**Literal paths with brackets are no longer mistaken for patterns.** A
`app/[id]/page.tsx` — an ordinary file in any Next.js or SvelteKit project — was
compiled as a glob character class and claimed unrelated files, refusing sprint
creation with advice to "narrow the pattern" for something that was not one.

**Also:** every budget ratchets down and fails at 98% of cap rather than on
breach, so saved space cannot be silently respent; a tree-wide file-size cap with
a self-retiring band table; `make setup` verifies the test runner and installs
the commit hook, and now distinguishes a broken test module from a missing
pytest instead of telling you to install what you already have.

## v5.2.0 — The close gate stops guessing, and stops assuming Python

**If your project is not written in Python, one thing changes for the better
immediately:** the teammate guide no longer tells every teammate to run `ruff
format` before staging, and the close pipeline's `lint` remedy no longer says
`ruff format && ruff check --fix`. Both now point at your project's own formatter
and linter. The plugin already detects eighteen linters; the prose was
contradicting its own machinery, and telling a Rust or TypeScript project to run
a Python tool. A skill also carried a `Bash(python3 -m unittest *)` grant that
could never match `cargo test` or `npm test` — it bought those projects nothing
and implied their tests were Python's.

Two new pins keep it that way: one over shipped prose, one over the `Bash(...)`
grants in skill and agent frontmatter. They are honest about what they cannot
see, and both are proved against synthetic offenders rather than trusted because
they are green.

**The merge gate now knows which concerns are about your close.** Before merging,
a close counts open high-severity concerns — and it worked out which ones were
relevant by intersecting the file list a concern recorded with the close's diff.
That list is written by whoever raised the concern, so a stale or wrong path
silently EXCLUDED a concern from the one gate that exists not to miss it.
Concerns raised while a close is running are now tagged with that close at the
moment they are written, and the gate reads the tag.

Three refusals in that tagging, because a wrong tag is worse than no tag (a wrong
one hides a concern from every gate; no tag leaves it counted under the old
file-relevance rule):

- A marker that exists but cannot be used — empty, malformed, unreadable, or a
  symlink — tags nothing, and says so on stderr. Silence there would look
  identical to no close running.
- Where no session id can be discovered, the plugin **refuses to tag at all**
  rather than reading a marker every session on the host would share. Borrowing a
  neighbour's tag would cost that host the gate; not tagging costs it nothing it
  had.
- Concerns written by hooks stay untagged deliberately. The gate carves transient
  test-failure concerns out by their tag being absent, so tagging them would let
  one teammate's red test abort another's clean close.

**A commit whose message we cannot read is now recorded, not dropped.** When the
parser could not recover a commit's message, the commit was traced but no event
was written — and any `Resolves-Event:` trailer in it was lost, so the item it
closed stayed open. The event is now rebuilt from `HEAD`.

That rebuild only fires when it can prove the commit is the one that just landed:
fresh, single-parent, and confirmed by the reflog. **A missing reflog vetoes it**
rather than waving it through — degrading to allow left a path that recorded an
event, and resolved real ids, for a commit the command never made. And the
"unreadable" test now judges a message by the quoting it arrived in rather than by
scanning its text: a backtick or `$` inside single quotes is literal, and treating
those as unreadable made ordinary commit subjects look unrecoverable.

**Teammate guide corrections.** The review-cycle instruction now names both
cadences instead of asserting the per-commit one, so a teammate under per-story
cadence no longer pays a duplicate review. Tiered teammate spawns no longer use a
bash-only expansion that yields a single argument under zsh — the macOS default —
which failed the spawn outright. And the guide says again that a `decision` needs
`--topic` (the append fails without it) and that a `concern` should carry
`--files`, since that list is what scopes an untagged concern to a close.

## v5.1.1 — Deferred stories survive the sprint archive

A sprint's deferred stories are the work you decided to keep, not drop. They were
being lost at the moment they mattered.

`/xp-sprint-close` archives `sprint.json` by MOVING it into `sprints/`, and
`/xp-sprint-start` read the carry-over list from that live file — so between the
two skills the list was always empty, and sprint-start's own instruction to
include the previous sprint's deferred stories had no data behind it. The helper
sent errors to `/dev/null`, so it read as "nothing deferred" rather than as a
failure. Measured on a real project: four deferred stories before the archive,
zero after. Nothing was destroyed — the stories sat in `sprints/sprint_*.json` —
but nothing read them back.

The carry-over list now comes from one archive-aware reader: the live sprint when
that file is present, the newest archive otherwise. It also names the file the
stories came from, because once a sprint is archived no command returns a story's
acceptance criteria or file domain, and a planner told to reuse them with no way
to read them writes new ones instead.

Two refusals worth knowing about, because both choose an empty list over a
plausible one:

- If the newest archive is unreadable, **the one before it is not substituted.**
  Its deferred stories may already be finished, so offering them recreates
  completed work while the real leftovers go unmentioned.
- If the live `sprint.json` is present but corrupt or symlinked, nothing is
  carried and the archive is not consulted. A damaged current sprint is not
  evidence about the previous one.

Either way you get a stated reason, not silence.

## v5.1.0 — Gates that refuse instead of going quiet

**One change will interrupt an existing habit, so it goes first: `git -C "$VAR"
commit` is now refused.** Use a literal path. The reason is the theme of the whole
release — every gate here previously had a way of appearing to work while doing
nothing.

### The commit gate no longer scans the wrong repository

A PreToolUse hook only ever sees raw command text. When a `git -C` target hid
behind something the shell would expand — `$WT`, `${W}`, `$(cmd)`, a bare `~`, or an
unquoted glob — the hook could not resolve it, fell back to the caller's directory,
and every gate below then read the **wrong** repo. That failed in the worst possible
direction: in a clean main checkout `git diff --cached` returns an empty string
rather than an error, so the tier-1 secret scan had nothing to scan, the lint gate
had no files to group, and the review-cycle gate saw zero code files. Unlinted and
unscanned bytes shipped and nothing said so. Only the branch guard was audible,
which is why this first surfaced as a cosmetic warning rather than as the
security-gate bypass it was.

Such a commit is now refused, with a message naming the shape it refused and the
remedy. The glob case is the one worth understanding: every other unresolvable shape
makes git abort, so nothing lands and the silence is harmless — but a glob that
*matches* hands git a real repository while the hook still sees the pattern.
Accepted cost, stated plainly: a literal directory name containing `*`, `?` or `[`
is now refused too.

**Every** `-C` in the command is judged, not just the first — a chain that stages
in one repo and commits in another (`git -C /literal add -A && git -C "$WT"
commit`) otherwise slipped past the refusal while the gates below still resolved
the *last* target. Nothing in raw command text can attribute a `-C` to the
`commit` word specifically, so the second accepted cost is the mirror image:
`git -C /repo commit && git -C "$OTHER" log` is refused for a `-C` that commits
nothing. The remedy is the same either way — use literal paths.

Relative literal paths keep resolving exactly as before.

### A stalled relocation says so

v5.0.0 relocates the shared mental model off the host-managed plugin-data root,
guarded by a lock. No resolver breaks that lock automatically any more — seven
attempts at automatic breaking all corrupted data, because breaking is a read then a
delete and no shell primitive makes that pair indivisible. The cost was that a
**crashed** relocation's lock blocked the automatic path indefinitely: every later
session quietly answered the legacy tree, leaving the project's memory in the
directory `claude plugin uninstall` deletes, permanently, with nothing saying so.

A session now tells you, and tells you *which* stuck it is, because the remedy
differs:

| What the lock looks like | What you are told |
|---|---|
| no lock at all | nothing is said; relocation happens on its own |
| its holder is still running | a relocation is in progress; you are pointed at the read-only report, never at a clear |
| its holder is gone | it is stalled, and `--confirm` will clear it |
| it is residue from an older version, naming no checkable holder | it is blocked and not automatically verifiable — run the report, then clear |
| the lock cannot be READ at all — an unsearchable destination directory, one `sudo` run away | it is unprobeable: you are told the state could not be established, and specifically NOT that relocation happens automatically |

Two of the five withhold the clear: a holder proved *running*, and a lock nothing
could probe. Guessing at a live holder is the mistake the seven earlier attempts made,
and a state that could not be established must not borrow the wording of one that
was — "it relocates itself automatically" is a claim, and it is false whenever the
probe failed.

### Hook liveness: a runtime that never loaded now gets refused

If the hook runtime fails to load, every gate it enforces disappears and the session
looks entirely normal — nothing is blocked and nothing is said. The check that would
report this cannot itself be a hook. It is now a preload check, which runs at
instruction time and therefore still runs when the thing it tests is broken.

Hooks record a heartbeat at session start, on every prompt, and from tool use, so a
working session refreshes far inside the staleness threshold. A session whose runtime
never loaded has no heartbeat at all, and the next skill invocation refuses
immediately, withholding its context rather than proceeding with gates that would go
unenforced. `XP_SKIP_LIVENESS_CHECK=1` proceeds anyway, for a runtime you know is
broken and cannot fix yet.

**What this does not yet catch promptly, stated because the distinction decides
whether you can rely on it: a runtime that loaded and then STOPPED.** Every refresh
source is itself a hook, so once they stop firing the last heartbeat merely ages, and
the check reads live until it crosses the four-hour staleness threshold. Inside that
window gates go unenforced and nothing says so — the same silence, on a longer fuse.
Catching it sooner needs a refresh source that is not a hook, which this release does
not have.

### Kickoff no longer asks you to wait for something already running

The housekeeping gate blocked session end whenever housekeeping was outstanding, and
that marker was cleared only on completion. Since Agent-tool subagents are
backgrounded, "running right now" read identically to "never invoked" — so the gate
told you to invoke an agent that was already in flight, and the only way to comply
was to sit and wait.

It now distinguishes the two, on a per-session record with a short freshness window.
In flight and fresh: end the turn, and resume when the completion notification
arrives. Never invoked, or a record that has gone stale: still blocked, with
different wording so you re-invoke rather than wait again. A housekeeper that
*fails* rather than completing no longer counts as done — the consume is gated on
its finalize step having actually run.

### The close gate's concern count stops dropping the wrong things

The merge gate counts high-severity concerns so a real problem aborts a close. It
now excludes only concerns provably about code the close did not touch, so a
concurrent teammate's unrelated defect can no longer abort a clean close — while an
empty or unreadable diff still counts everything.

### Also

One user-visible change that belongs to no section above: a `file_domain` entry may
now end its path list with a single spaced hyphen (`src/thing.py - why it is here`),
not only an em-dash or `--`. An entry that used to report drift resolves correctly.
The cost is stated because it is a truncation, not a rejection: a declared path that
itself contains `" - "` now keeps only the part before it.

Internal, but they change what future releases can promise: the commit-gate block is
extracted from the PreToolUse handler so its ordering is pinned rather than
incidental; the superseded-decision detector now checks every earlier decision on a
topic rather than only the adjacent one, which closes a false *positive* rather than a
fail-open; the two fail-opens this release actually closes are in the close-gate
relevance path, where a non-repo-relative `files` entry read as proof of irrelevance
and a `UnicodeDecodeError` crashed the diff-path load; a test pin that had been
silently scanning less than it claimed now fails loud; and the migration lock reader is
one module both the resolver and the supervised tool share.

Two things this release deliberately does **not** do, recorded rather than hidden. An
append that lands during the one-time SMM relocation copy can still be lost —
sub-second, once per project, and already partly covered by a pre-rename re-sync.
And on a harness that supports PreToolUse but not the post-tool or stop families, the
liveness check can read live off the write immediately preceding it; that fix would
reverse behaviour shipped here, so it is deferred rather than rushed.

## v5.0.0 — The SMM moves out of the deletable directory

**Two breaking changes ship in this release: the SMM's default location, and
the branch namespace.** The location is the headline and is covered first; the
namespace flip is under "The recorded branch namespace is now the one in force"
below, and it is the one that can change your branch names on upgrade.

### The SMM's default location

**The break is worth stating plainly before the reason: the SMM's
default location changes, and `CLAUDE_PLUGIN_DATA` no longer chooses it.** Two
contracts change. Anyone who exported `CLAUDE_PLUGIN_DATA` to place the SMM must
switch to `XP_AGENTS_DATA`; that variable is still read, but only to *find* an
SMM that already exists, never to decide where one goes. And any tooling that
reads `~/.claude/plugins/data/…/smm/` directly keeps working against a tree that
is no longer the live one once relocation has run — a stale read, not an error.
Relocation itself is automatic and by copy, so for most users nothing is asked of
them; the major number reflects the contract break, not the difficulty.

The Claude plugins reference says
`${CLAUDE_PLUGIN_DATA}` — `~/.claude/plugins/data/{id}/` — "is deleted
automatically when you uninstall the plugin from the last scope where it is
installed," and the CLI deletes by default (`--keep-data` opts out). That is
where the SMM has lived: `events.jsonl`, `sprint.json`, `execution_plan.json`,
`system_context.json`, `session_history.json` and every retrospective. Code is in
git; a project's *memory* is not. It survives plugin updates but not an
uninstall — including the common uninstall-then-reinstall — and it fails
silently: the plugin keeps working, the next session just starts from a seed
retrospective as though the project were new.

New SMMs now go to `${XP_AGENTS_DATA:-~/.xp-agents/data}/{project-id}/smm/`,
which no plugin lifecycle operation touches.

**An existing SMM is relocated for you, by COPY.** On the first resolution after
upgrade, an SMM found under a plugin-data root is copied to the new root and used
from there. The source is never deleted — an interrupted or wrong relocation
therefore loses nothing, and every failure path falls back to reading the old
tree. Once you are satisfied, the old directory is yours to delete.

Discovery checks a LIST of legacy roots (`$CLAUDE_PLUGIN_DATA` when set, then the
marketplace and dev-mode defaults), because that variable is absent in some hook
processes and a dev-mode install resolves the plugin id differently; a single
candidate would let a process that cannot see the real root mint an empty
directory that then permanently reads as authoritative.

**Relocation is declined, never forced, while any teammate is live.** A teammate
has its SMM directory pinned to an absolute path when it is spawned and cannot be
redirected, so moving the SMM out from under one splits the event log with no
merge path — and because the plugin cache is versioned, a mid-session plugin
update leaves old and new code running side by side, which is exactly when this
would bite. Both kinds are checked: worktree teammates by their directory, and
in-place teammates by their marker files. While one is live the old location keeps
being used, and relocation happens on a later session. A `.migrated-to` pointer is
left behind so a process pinned to the old path just before a relocation is
redirected rather than writing where nothing reads.

**And when relocation stays declined, the session says so.** The liveness gate
keys on a worktree *directory* existing, and nothing removes one whose branch
never merged — cleanup refuses on an unmerged branch, by design. So a single
abandoned story can hold the gate on indefinitely. A one-line SessionStart notice
now names the risk and the blocker whenever the resolved SMM is still under a
host-managed root. It is a notice, never a gate, and it is a positive test
against the at-risk roots: point `XP_AGENTS_DATA` or `SMM_DIR` wherever you like
and nothing nags you.

**`scripts/migrate_smm_root.py` is the manual half.** Run it with no arguments
and it reports where the SMM is, where it would go, how big it is, whether the
root is at risk, and — the part the notice cannot carry — exactly which worktree
directories and in-place markers are holding relocation back. `--confirm`
relocates; `--confirm --force` relocates past a signal you have judged stale,
which is the one call automation must not make for you. It does not implement
relocation: copying, locking, the whole-tree re-sync and the forward pointer stay
in `init.sh`, and the tool drives them, so there is no second set of races to
get wrong. After a relocation it compares both trees and tells you where the old
copy still is. Only `smm/` moves — a forced relocation names the sibling worktree
directories it just cut loose, because worktree placement is derived from the
SMM's parent and `/xp-story-close` will no longer find them.

`CLAUDE_PLUGIN_DATA` is now READ for discovery but never chosen for a new SMM.
The harness always sets it, so honoring it as a preference would leave every SMM
in the deletable directory and make this change a no-op.

**If you want the SMM somewhere specific, export `XP_AGENTS_DATA`.** It outranks
everything except an explicit `$SMM_DIR` (which is how a teammate spawner
propagates the lead's SMM across a process boundary).

Also fixed while the root became user-controllable: `init.sh` used to `chmod 700`
the derived root unconditionally, which was harmless when that root was always
plugin-owned but would have narrowed the mode of `$HOME` for anyone setting
`XP_AGENTS_DATA=$HOME`. It now narrows only a root it created. The SMM directory
itself is still always `700`.

### The recorded branch namespace is now the one in force

**The second break: branch names can change on upgrade.**
`branching_strategy.user_namespace` was inert. `identity.user_namespace()`
derived the branch prefix from the git `user.email` local-part and never read the
recorded field, so `system_context.json` could say `alice` while every branch was
cut as `a-smith/...` — with nothing reporting the disagreement. This repo hit
exactly that: the analyzer recorded the prefix already on 200+ merged branches,
the git email had since changed, and the next branch was cut under the new one.

The recorded value now WINS, falling back to git identity when absent or
unusable. It is user-editable via `system_context_cli edit-branching-field`, so
it was always meant as an override; an override nothing reads is a lie.

**What changes for you on upgrade.** If your recorded `user_namespace` disagrees
with your git-derived slug, NEW branches switch to the recorded prefix. Your
existing ones stay visible: `list_user_branches` — which backs kickoff's
orphan-branch triage and free-close discovery — searches both the recorded
namespace and the git-derived one, so nothing cut before the upgrade drops out
of those listings. What it does not do is RESUME across the change: restarting
work with the same slug cuts a fresh branch under the new prefix rather than
picking up the old-prefix one, which is then an orphan the triage will offer
you. If you would rather not have the switch at all, check
`branching_strategy.user_namespace` in your rendered system context BEFORE
upgrading and either edit it to the prefix you actually use or delete the field
to keep deriving from git.

The field is also now validated as a git ref segment, at the same two points
`integration_branch` already was: rejected at write time (`user_namespace_error`),
healed to "no override" at use time (`healed_user_namespace`). It reaches `git
branch` and `git checkout` as argv, so a leading dash would have arrived as a
FLAG.

This landed as v4.19.0 on the branch that became this release. There was no
separate v4.19.0 release, so the entry under that heading in
[`changelog_pre_v5.md`](changelog_pre_v5.md) is a mid-branch snapshot, not a
shipped version — where the two disagree (it predates the dual-namespace
search), this note is the accurate one.

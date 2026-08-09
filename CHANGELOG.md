# Changelog

History prior to v5.0 lives in [`changelog_pre_v5.md`](changelog_pre_v5.md).

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

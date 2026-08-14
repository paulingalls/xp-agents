# Preload delivery: choosing one mechanism

Milestone 9, sprint-007 story-001. Measured 2026-08-14.

The question: 17 of 19 shipped skills get their state from a `!` shell preload in
`SKILL.md`. The second harness never expands those lines, so every one of them runs
blind there. Can **one** hook-side injection mechanism replace that channel on both
harnesses, letting the `!` lines be deleted?

## The rubric, fixed before the verdict

A mechanism is chosen on five criteria, in this order:

1. **Does state arrive dereferenceable by name?** A body reads `SMM_DIR=`, `### STAGE=N`.
   Text merely present in context is not the property under test.
2. **Does it cover every skill class?** Inline and forked alike, or the gap is named.
3. **Does it actually reduce to one mechanism?** Two handlers on two triggers is a
   smaller win than "one way instead of two" implies, and must be scored as such.
4. **What does it cost when it fails?** Including failure modes the change introduces.
5. **Does it fit the bounds it runs inside?** Wall time against the enforced timeout.

## What was measured

All measurements ran against a throwaway probe plugin loaded with `--plugin-dir`,
never against the shipped tree. Each carries a control. The probe wrote one
side-channel line per invocation, read out-of-band, so *hook never fired* stays
distinguishable from *hook fired and the model could not dereference the value* —
without that third state a dead hook and a real negative are the same observation.

The probe deliberately carries **no** `is_xp_agent` guard and is **not** named `xp-*`.
Either would have sent a result negative for a reason having nothing to do with the
harness.

| # | Question | Result | Control |
|---|---|---|---|
| M1 | Is injected state dereferenceable by name in an **inline** skill? | **Yes.** A uuid minted in-hook, in no file and no prompt, inside a 24,309-byte realistic payload, returned byte-identical. | Injection suppressed → `TOKEN_ABSENT`, hook confirmed fired. |
| M1b | Does it cross into a **forked** (`context: fork`) skill? | **No.** Hook fired, the *parent* confirmed receiving the payload, the forked subagent reported `TOKEN_ABSENT`. | Parent's own confirmation is the internal control: injection landed, the fork boundary blocked it. |
| — | Does `PreToolUse:Agent` fire for a forked skill? | **No.** It never fires — a forked skill's subagent is not spawned through the Agent tool. | A direct Agent-tool call **does** fire it, proving the matcher name correct. |
| — | Does `PreToolUse:Agent` injection reach the **subagent**? | **No.** It reaches the parent. The subagent reported `TOKEN_ABSENT`. | Same run: hook confirmed fired. |
| M3 | Does the slowest preload fit the enforced bound? | **Yes, with room.** Slowest is `xp-sprint-close` at 1.91s; the governing default is 600s and the pre-fixed rule allowed 300s. | See the timeout finding below — the bound is enforced, measured both directions. |

**No hook delivers context into a subagent.** That is the single most consequential
result. A subagent gets state only from what its spawner writes into its prompt.

*M3 caveat:* close preloads compute diffs, so 1.91s is a floor, not a worst case. The
headroom is large enough (0.6% of the allowance) that this does not change the verdict.

## Verdict

**Unified hook-side injection, with the forked class converted rather than excepted.**

- The **14 inline** preload-bearing skills move to injection. Measured, with a control.
- The **3 forked** skills — `xp-review-plan`, `xp-sprint-review`, `xp-system-context` —
  convert to the **inline-skill-spawns-a-subagent** pattern this repo already ships in
  `xp-quality-review`/`xp-code-reviewer`. The inline skill takes the injection and threads
  what the subagent needs into its prompt. No hook is required on the subagent, which is
  fortunate, because no hook can reach one.
- Until that conversion lands, those three keep their `!` lines. This interim is
  **time-boxed to the conversion story**, not a standing second mechanism.

**Losing options, with their disqualifiers stated:**

- *Keep-both* (injection on harness 2, `!` expansion on harness 1) — disqualified: it
  preserves permanently the two-mechanism cost the customer set out to remove, and buys
  nothing the verdict does not already get.
- *Hybrid retaining route 1 (in-body substitution) for any class* — disqualified: route 1
  keeps an env-blind reader, so Milestone 9's constraint 6 (`os.getsid` correlator, required
  in the same milestone) would still bind, and nothing schedules it. The chosen verdict uses
  injection for every class it can cover and so never incurs that bill.

**Criterion 3, answered honestly:** this is one *mechanism* (hook-side injection of a
skill's own preload output) on **two triggers** — `PreToolUse:Skill` on harness 1, the
shell read of `SKILL.md` on harness 2, which has no skill tool call. That is a real
simplification over two unrelated delivery systems, but it is not literally one hook, and
the verdict does not claim to be.

**Criterion 4, the cost this introduces:** deleting the `!` lines removes the only
instruction-time channel, the one thing able to report a dead hook runtime *because it is
not itself a hook*. After this change, a dead runtime yields silently stateless skills
rather than a loud banner. The customer scoped liveness out of this decision deliberately,
having measured its cost (480 dedicated lines, 18 shipped files, 6 heartbeat write sites,
394 mentions across 48 test files) against its reachability (second-harness silent
hook-skipping, and teammate preflight — neither being the daily solo loop). Recorded here
as a priced cost, not omitted.

## The byte-identical constraint: why it existed, and why it is reversed

Milestone 9 carried a constraint that the first harness's preload expansion path stay
**byte-identical** after the milestone. The verdict reverses it. That deserves its reason
in writing, because reversing a recorded constraint on the strength of a preference rather
than evidence is how a plan quietly loses its memory.

**Where it came from.** Nowhere measured. No SMM event records it; it appears only in
`execution_plan.json` §Milestone 9, authored at plan time, when both candidate routes were
*Codex-only* remedies. In that framing the constraint is a blast-radius guard: whatever we
do for the second harness, do not disturb the harness that already works.

**What it was protecting.** Concretely, the instruction-time channel. `skills/_preload_liveness.sh`
documents the property in its own header — the check that reports a dead hook runtime
*cannot itself be a hook*, and a preload works as that check precisely because it is an
instruction-time load that still runs when the thing it tests is broken. Freezing the
expansion path froze the only detector of a silently unenforced session.

**Why it is reversed.** The framing it was written under no longer holds: the customer's
direction makes the first harness a *participant* in the new mechanism, not a bystander to
be shielded. Reversal was ruled explicitly, not assumed, on three grounds — the constraint
carried no measured backing; the protection it encoded is replaced by a content-level
delivery pin that survives a mechanism swap, where a byte-identical pin does not; and the
liveness exposure it guarded was measured for cost against reachability and scoped out
deliberately (see the priced cost under criterion 4 above).

**What would reinstate it.** Evidence that the inline-skill class cannot take injection —
which M1 refutes — or a decision to keep liveness detection on the instruction-time channel,
which would make the `!` lines load-bearing again for a reason other than state delivery.

## Where the skill→preload mapping lives

Deleting the `!` lines deletes the record of *which command each skill's preload is*. That
mapping must move somewhere explicit — the spec story-002 consumes. It must cover **argv
and environment**: every line has the shape

```
CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh
```

and both variables are expansion-time context a hook process does not automatically hold.
A spec covering argv alone yields a resolver returning an invocation that cannot run — this
milestone's own quiet-failure class. Two skills are not the common default: one takes an
extra flag, one names a different script. Both must be representable.

## The second harness's handle, and how we learn it broke

Injection there depends on the model reading `SKILL.md` *with a shell command*. If bodies
ever arrive without a shell read, `PreToolUse:Bash` stops carrying the identity and the
mechanism stops firing — **silently**, because "no marker" and "no injection" look
identical. Detection signal: the side-channel pattern this research used — the handler logs
every invocation, so an absence of log lines across a session distinguishes *never fired*
from *fired and delivered nothing*. Fallback: the `!` lines are recoverable from version
control, and the mapping registry means restoring them is mechanical.

## Reproducing this

Without access to the original session:

1. Build a minimal plugin: one `PreToolUse:Skill` handler, one inline skill, one forked
   skill with an `agent:` in its frontmatter, one throwaway agent. The handler must not
   copy `pre_tool_skill.py`'s `is_xp_agent` early return, and no skill may be named `xp-*`.
2. The handler mints a uuid, writes it to a side-channel file on **every** invocation before
   any other decision, and injects `### PROBE_TOKEN=<uuid>` inside a ~24KB payload.
3. Load it with `claude -p "<prompt>" --plugin-dir <path>`. Run from a directory whose path
   contains `worktree-story-`, or this plugin's own kickoff gate blocks the prompt.
4. Skill body: "find `### PROBE_TOKEN=<value>`, reply `TOKEN_IS=<value>`, or `TOKEN_ABSENT`."
   Never let it guess.
5. Control: `PROBE_SUPPRESS=1` skips injection while still writing the log line.

An isolated `CLAUDE_CONFIG_DIR` is *not* a viable route — it is unauthenticated.

## Incidental finding: hook timeouts are 1000x too long

Verifying M3's bound turned up a live defect, filed as story-008.

Measured on harness 1: `timeout: 5` with a 3s sleep survived and injected; `timeout: 1`
with the same sleep was killed before injecting, the side channel proving the hook fired
both times. The field is **seconds**, and it **is** enforced. Harness 2 was measured the
same way during Milestone 8, with the same result.

**Both harnesses read seconds.** The source manifest declares values intending
milliseconds (`5000`, `2500`, `10000`, `1500`), so `timeout: 5000` means 83 minutes and
`10000` means 2.8 hours. The plugin ships with no effective hook bounds on either harness.
This also falsifies `hooks_emit.py`'s stated reason for dropping timeouts from the derived
variant: the units do not differ, so the correct fix converts the source rather than
stripping the variant. Conversion is not a mechanical divide-by-1000 — `2500`ms is 2.5s,
and sub-second bounds are unrepresentable as integer seconds, so each is a recorded
judgment.

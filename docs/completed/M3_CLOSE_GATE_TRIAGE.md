# Milestone 3 — Bucket C triage of the close-gate cluster

Story-002, sprint-003. Every 25+-line docstring in the seven close-gate
modules, triaged claim by claim: **C** = a machine could check it, **D** =
rejected design, external constraint, historical why, or a judgment no machine
decides.

The story existed to produce a number that decides whether the rest of
Milestone 3 is worth doing. The number is below. The more useful finding is
what triage turned up on the way, which no conversion pass would have produced.

## The measurement

| Module (file:line) | Claims | C unpinned | C pinned | D |
|---|---:|---:|---:|---:|
| `close_cycle_abandonment.py:2` | 14 | 1 | 9 | 4 |
| `close_cycle_stop_gate.py:2` | 18 | 4 + 1 false | 11 | 2 |
| `close_gate_commands.py:2` | 17 | 1 | 14 | 2 |
| `close_gate_commands.py:155` | 8 | 2 | 4 | 2 |
| `lead_gates.py:59` | 6 | 1 | 3 | 2 |
| `lead_gates.py:89` | 18 | 6 | 11 | 1 |
| `lead_gates.py:215` | 8 | 2 | 6 | 0 |
| `pre_tool_bash_reviewer_guard.py:2` | 18 | 2 | 8 | 8 |
| `pre_tool_skill.py:125` | 11 | 1 | 9 | 1 |
| `review_flag_cli.py:2` | 10 | 5 | 4 | 1 |
| **Total** | **128** | **26** | **79** | **23** |

**Hit rate: 26 of 105 checkable claims unpinned — 24.8%.**

18% of all claims are D and correctly stay put, concentrated in
`pre_tool_bash_reviewer_guard.py:2` (8 of 18). That module's prose is doing the
most legitimate non-convertible work in the cluster: two named incidents, a
rejected allowlist design, and a measurement record of what the guard actually
refused in production. Its length is not a complexity defence, so it earns no
debt under this milestone's rule — recorded here as a judgment rather than
manufactured as a finding.

## What triage found that a conversion pass would not

**Four false claims**, all shipped, all in the two modules the cluster's
behaviour actually turns on:

1. `close_cycle_stop_gate.py` called its `stop_hook_active` bypass *age-gated*
   and named a constant as the mechanism. The owning session has decided it
   since the liveness check landed; existing tests falsify the age story in
   both directions.
2. The same docstring claimed the gate blocks whenever the marker is present,
   omitting the evidence-release path — the largest recent branch in `run()`.
3. `close_cycle_abandonment.py` said the marker is released only when
   xp-close-reviewer completes, contradicted 190 lines below by its own
   recorder.
4. The same docstring called the age rule "what makes the record mean
   anything" while its own constant comment says age is no longer primary.

Two more turned up in tests: `test_review_flag_cli.py`'s docstring asserted the
readers agree on the marker key (they did not), and
`test_close_cycle_thresholds.py` carried a remedial message naming a call site
that does not exist.

**A dead constant.** `_CLOSE_CYCLE_ABANDONMENT_TIMEOUT_SEC` appeared in
production only inside docstrings; the gate's logic never read it.

**A vacuous test pair.** Every stop-gate bypass test armed with a session id
that has no heartbeat, so `owner_session_is_live` returned `None` and only the
age fallback ran — the tests were named for the bypass decision and never
reached the rule that makes it.

**Two production bugs**, neither a Bucket C conversion and both reported
separately from the hit rate so they do not inflate it:

- `owner_session_is_live` had no lower bound on age, so a future-dated
  heartbeat read as live (concern `bf1fe24526ed`).
- The review-cycle flag's writer and the close gate resolved its key
  differently, so a Stop payload carrying a platform `agent_id` blocked an
  agent mid-review (debt `220c1220f3ff`, risk `a1eefe3b2846`).

## What this story converted

Four claims, chosen for value rather than volume: the marker-key contract, the
bypass owner rule, `_FLAG_LIFECYCLE`'s keep-in-sync comment, and the
guarded-agent count. The remaining ~20 unpinned claims are recorded as debt,
concentrated in `lead_gates.py:89` (6) and `review_flag_cli.py:2` (5).

## The read for Milestone 3

A 24.8% hit rate over a hand-picked cluster — chosen because it measured the
*thinnest* existing coverage per docstring — is the optimistic end of what a
sweep yields, and the conversions themselves were the least valuable output.
The false claims were worth more than all four conversions, and finding them
required reading claims against code, which is a reviewer's work rather than a
sweep's. That matches SMM wisdom `ea557368b930`: stale prose is caught by diff
review, not by sweeping unchanged code.

# Sprint acceptance verification: dedup, diagnose, survive

**Status:** proposed. **Triaged:** 2026-08-05 against `main` @ `e3f293e3`, plugin v5.5.0.
**Source:** `2026-08-02-sprint-verify-reruns-shared-gates-once-per-story.md` (handoff written against 5.3.1; triaged and deleted — this doc is the surviving record).

## The problem in one line

`verify_acceptance.py --sprint` runs every declared acceptance command once per claiming story, so a well-factored sprint where 8 stories share one 19-minute E2E suite spends ~4 hours re-proving the same thing against an unchanging tip — on the close path, where the alternative is `--force-close`.

Two of the original handoff's items already shipped and are **not** in scope: the 600s per-command default is now 7200s with a 4h batch bound (`00aede50`, v5.4.0), and a killed `--sprint` no longer reads green — the reader returns `unverified` and `_query_verify_status` exits 1 (`de8bd77a`, `04f0dafd`).

---

## 1. Dedup identical commands in `_run_sprint` — **small–medium, do first**

**Evidence it's unfixed.** `_gather_sprint_items` (`scripts/verify_acceptance_record.py:57-93`) appends one tuple per `(story, ac_idx, command)` and never compares the command. `_run_sprint` (`scripts/verify_acceptance.py:235-311`) shells every item in list order — no cache. No `dedup` anywhere in `verify_acceptance*.py`; nothing in v5.4.0/v5.5.0 CHANGELOG.

**Measured live:** 13 stories / 30 queued items / 22 unique commands, 8 stories pinning the identical `bash scripts/e2e-native-dispatch.sh` and a 9th pinning a wrapper around it. At suite #2 of 8, 48 min elapsed, ~3.5–4h projected vs ~30 min deduped.

**Why it matters beyond speed.** `--sprint` feeds the event the sprint-close merge gate consumes. Four hours between "sprint done" and "can close" makes `--force-close` attractive, which bypasses the acceptance gate entirely. The cost scales with *stories sharing a gate* — it penalizes well-factored acceptance surfaces, and the only workaround is declaring a hollower AC.

**Direction.** Cache by **exact command string** in `_run_sprint`; run once, fan the verdict out to every claimant row.

Two rules the plan must not get wrong:

- **Dedup execution, not reporting.** `_print_matrix` (`verify_acceptance_record.py:96`) prints one line per story, and the event's `failing` list is how a red close names which story broke. Every claimant keeps its own row carrying the shared verdict. Mark reused rows visibly (`[PASS*]` + legend, or a `shared` key) and log one summary line: `30 items, 22 distinct commands (8 shared runs reused)`.
- **Exact-string identity is the whole safe rule.** No whitespace normalization, no wrapper resolution, no collapsing a command that is a subset of another (e.g. `E2E_JOURNEYS='...' bash scripts/e2e-native-all.sh` into the dispatch it subsets). That would require the plugin to understand a project's test topology — a cross-language-guardrail violation. Soundness argument for dedup itself: `--sprint` already re-runs commands that passed at accept time against an unchanged tip, so the gate's existing semantics already assume acceptance commands are repeatable checks, not state mutations.

**Interaction with the batch budget — added *after* the handoff was written.** `_DEFAULT_BATCH_TIMEOUT_S = 14400` (`verify_acceptance.py:113`) and its deadline check at `:263` currently sit before every run. A cache-hit row costs ~no time, so it must not be skipped on deadline exhaustion — otherwise a budget-exhausted batch marks items `skipped` (which gates the close red) for commands whose result is already in hand. **The deadline check moves to before an *uncached* run only.**

**Files.** `scripts/verify_acceptance.py:212` (`_run_sprint` — the cache goes here), `scripts/verify_acceptance_record.py:57` (`_gather_sprint_items` — shape also consumed by `verify_report:153`, don't change lightly), `:96` (`_print_matrix` — must NOT be deduped). Tests: `tests/hooks/test_verify_acceptance_sprint.py`, `test_verify_acceptance_batch_budget.py`.

**Explicitly out of scope.** No change to `_gather_sprint_items`' skip rules (deferred stories, string ACs, command-less manual sentinel), the event schema, `_MAX_FAILING_ITEMS`, or the `--query-verify-status` contract. **No parallelization** — these are E2E suites contending for one simulator host; concurrent runs would be a worse bug than duplicate ones.

## 2. Timeout messages should name their own override — **small, near-free**

`verify_acceptance.py:190` (`f"verify_acceptance: {label} timed out after {timeout}s: {cmd}"`) and `:292` (`marker = f"timed out after {timeout}s"`, carried into the event row's `output`, so it is what a red close shows the operator) never mention `VERIFY_CMD_TIMEOUT_S`.

Append `(raise VERIFY_CMD_TIMEOUT_S if this surface legitimately runs longer)`. In-repo precedent to copy: the batch-budget stderr line at `:342-347` already names `VERIFY_BATCH_TIMEOUT_S` and its opt-out. Lower urgency now that the default is 7200s, but the message is exactly as opaque when it does trip.

## 3. A long `--sprint` still loses all completed work — **medium, measure after dedup**

The silence half is fixed (see above). The lost-work half is not:

- **No incremental emit.** `_run_sprint` appends its single event only after the whole loop completes (`verify_acceptance.py:349-350`). A run killed at minute 54 throws away every completed item.
- **No resume**, documented as accepted design at `verify_acceptance.py:106-112`: "skipping is deterministic in sprint order… raising the lever re-pays every already-green item. Nothing accumulates across runs."
- **The plugin doesn't own detachment.** No `setsid`/`VERIFY_*_TIMEOUT_S` mention anywhere in `skills/`, `agents/`, or `PROCESS_GUIDE.md`. `agents/xp-sprint-reviewer.md:38` still says to run the command bare in a tool call, with no long-batch guidance, no known log path, and **no note that `setsid` does not exist on macOS** — the exact thing a live agent burned a 54-minute failed attempt discovering before falling back to a double-fork daemonizer.
- **The batch bound (4h) is larger than the harness bound**, conceded in prose at `verify_acceptance_record.py:133-135`.

**Two design constraints the handoff did not address:**

1. **Naive incremental emit creates a false green.** The event schema carries one terminal `verify_status`, and `_last_verify` (`verify_acceptance_record.py:159-185`) reads the last matching event. Per-row events would make a partial run's final row look like the sprint verdict — strictly worse than today's honest `unverified`. A progress record must be distinguishable from a verdict record (separate action, or a `partial: true` marker the reader refuses to treat as terminal), and `verify_report` must keep returning `unverified` when only partial records exist.
2. **Per-item append cost.** `append_safe` takes a flock with a 10s timeout per write. 30 items is fine; don't assume it stays cheap for large sprints.

**Sequencing note.** Do **not** build detachment before dedup. The handoff's own arithmetic says 22 unique commands is ~30 min, comfortably inside one tool call — dedup may remove the need entirely. If a detachment implementation is ever written, it must not assume a POSIX-only tool (cross-language guardrail — that is precisely why the live `setsid` attempt failed).

**The macOS `setsid` doc note is independently shippable now**, as a one-paragraph fix to `agents/xp-sprint-reviewer.md` / `skills/xp-sprint-review/SKILL.md`.

---

## Sequencing

1. **1** (dedup) — the four-hour close path, and the enabler for everything else.
2. **2** (timeout message) — near-free.
3. **3, doc note only** — macOS `setsid` warning.
4. **3, incremental emit** — re-measure after dedup lands; build only if a real batch still outlives a tool call.

# Close-gate honesty: five fail-open holes in the auto-merge path

**Status:** proposed. **Triaged:** 2026-08-05 against `main` @ `e3f293e3`, plugin v5.5.0.
**Sources:** `2026-07-27-story-close-automerge-gate-condition-2.md`, `2026-07-27-file-domain-separator-silent-100pct-drift.md`, `2026-07-21-legacy-triage-plugin-scoped-items.md` (all triaged and deleted; this doc is the surviving record).

## The through-line

`/xp-story-close`'s auto-merge override skips the Step 6 `AskUserQuestion` when three conditions hold. Every item below is a way for that gate — or a diagnostic feeding it — to **read green (or read alarming-but-wrong) on absent evidence rather than on positive evidence**. None is a crash; all of them are silence where a hold was intended.

The gate has moved a lot since these were filed (`--diff-paths` scoping in `ba9dbd23`, condition 3's frozen gate-command set in `282b0f5d`/`93b5a635`/`7f1cd65e`, a Step 4.5b quality review on the story path). None of that closes these.

---

## 1. Condition 2 fails open on an empty population — **medium, highest value**

`skills/xp-story-close/SKILL.md:189-199` merges without asking when `HIGH_CONCERN_COUNT == 0`. Zero conflates *a reviewer ran and found nothing* with *no reviewer finding was ever recorded* — reviewer aborted mid-review, emitted prose without appending, or filed everything at `medium`. Same logic in the shared abort-default at `scripts/_close_pipeline_shared.md:86-100`, so free-close inherits it.

Condition 1 (`count-classifications`) can't stand in: it is filtered `--route ask`. Condition 3 guarantees the *test* leg can never run nothing; the *review* leg has no equivalent.

**Partial mitigation already in place, and its limits:** Step 4.5b (`SKILL.md:156-169`) runs `/xp-quality-review` on the story path, and `agents/xp-code-reviewer.md:86-91` instructs a close-context reviewer to record unfixable blockers at `severity high` with `close_cycle_id`. Pinned by `tests/skills/test_close_auto_merge_deterministic.py:70`. That is instruction-only — nothing verifies compliance — and story-path only.

**Direction.** Add a condition 0: positive evidence that Step 4.5/4.5b recorded *something* for this cycle at any severity, else fall through to the manual path. `smm/smm_count.py:382-400` already supports omitting `--severity`, so `count-concerns --cycle-id <id> --since-ts <ts>` is the natural shape.

**Open design question the plan must settle:** a genuinely clean review records nothing today, so this changes semantics for the good case. Either instruct reviewers to append a status event on a clean review, or key the condition on a lifecycle event rather than a concern. Decide this before implementing.

**Files.** `skills/xp-story-close/SKILL.md`, `scripts/_close_pipeline_shared.md`, `smm/smm_count.py`, `agents/xp-close-reviewer.md`, `agents/xp-code-reviewer.md`. Tests: `tests/skills/test_close_auto_merge_deterministic.py`, `tests/integration/test_close_merge_gate.py`.

Subsumes item 4.

## 2. Lexicographic ISO timestamp comparison — **small**

`smm/smm_count.py:87`, `:156`, `:286` compare ISO timestamps as strings. `'+'` (0x2B) sorts before `'Z'` (0x5A), so an event sharing a whole-second prefix with a `Z`-suffixed `--since-ts` compares as earlier and is silently dropped — fail-open in a merge gate. The `:110-112` docstring still asserts this is safe.

**Exposure is narrower than the handoff claimed.** The producer is pinned: `skills/_preload_base.sh:200-202`'s `now_iso()` emits `+00:00`, matching `smm/_append_impl.py:now_iso()` (`70292fec`, 2026-05-01 — a pre-existing constraint the handoff overlooked, not a fix). Both shipped sides agree *today*. What remains: the contract tests still permit `Z` (`tests/integration/test_close_merge_gate_test_command.py:144`, `test_close_preloads_emit_shared_cross_mode.py:63` both match `(\+00:00|Z)`), so a future preload emitting `Z` passes the suite and silently breaks the gate; and any hand-run or third-party invocation passing `Z` hits it immediately.

**Direction.** Parse both sides to aware datetimes, compare instants. Delete the "safe because ISO" claim at `:110` and `:239` and in `_preload_base.sh:195-197`. Optionally tighten the two test regexes to `\+00:00` — in addition to parsing, not instead of it.

## 3. An unsubstituted `<CLOSE_CYCLE_ID>` excludes the concern it tags — **small**

`agents/xp-close-reviewer.md:87` and `:97` carry a literal `<CLOSE_CYCLE_ID>` placeholder in their `append.sh` templates. If an LLM emits it unsubstituted, the concern is tagged with a non-matching id, and `smm_count` excludes a concern whose tag is present and unequal. An *untagged* concern is counted (fails closed); a *placeholder-tagged* one is silently dropped. This is the one tagging path that fails open.

`smm/close_cycle_tag.py:136-138` takes any non-empty explicit string unconditionally, with no format check — so the marker-fallback added later (`daaac4f9`, `6a4f5ab4`) does not rescue it, because the placeholder counts as "explicit."

**Direction.** Validate the explicit value against `EVENT_ID_RE` in `close_cycle_tag.stamp` — **the regex is already imported in that module** (`:41`) for the marker path. On a malformed value, fall through to the marker-derived id or drop the tag; both fail closed. Report on stderr via the existing `_unusable_marker` pattern. The `:120-123` docstring already reasons about a *blank* explicit tag; extending to malformed is consistent with stated intent.

## 4. `--severity high` may not match reviewer vocabulary — **do not act yet**

`agents/xp-close-reviewer.md:84`/`:94` route Blocks to `high` and Concerns to `medium`. If reviewers overwhelmingly file Concerns, condition 2's population is empty by construction.

**The supporting census (296 concerns / 111 high / 24 with a cycle id / 1 both) was taken from another project's SMM and has not been re-run here.** Do not tune a threshold on borrowed numbers. Sequence after item 1, and only after a fresh census against this repo's own SMM. Item 1 is the better investment regardless: it makes the gate honest about *evidence* rather than tuning a severity cutoff.

## 5. `validate-domain` can't distinguish total drift from an unparsed declaration — **small, pure diagnostic**

`smm/sprint_cli_query.py:203-267` computes `drift = sorted(actual - declared)` at `:235` and, when over tolerance, reports `drift: N file(s) outside declared file_domain`. When `declared ∩ actual` is **empty**, the operator gets a maximally-alarming, correct-looking total-scope-creep report naming a file plainly visible in the declaration. Two independent readers in the reporting project (a lead, then a close-reviewer) both misread it as a matcher defect; ~40 minutes lost.

The `' - '` separator fix that shared this handoff **did** ship (`fd9deccd`, `smm/triage.py:41`), but zero-intersection stays reachable by every other route: an absolute path against a relative diff, a stale prefix after a mid-story file move, a glob expanding to nothing, and — documented as unfixable by string rules at `triage.py:31-40` — a declared path containing a spaced hyphen (`docs/design - notes.md`).

**Direction.** Before the tolerance comparison, detect `actual and declared and not (actual & declared)` and print a stderr line naming the likely cause plus the suspicious entries. **Must be stderr:** the sole call site (`skills/xp-story-close/SKILL.md:79-82`) runs it as `>/dev/null || true`, so stdout is discarded. Advisory only — that call site deliberately continues past drift.

**Refinement over the handoff's sketch:** `extract_file_domain_paths` expands globs, so a glob matching nothing contributes no entry and won't show up in a `' ' in d` scan of `declared`. Report the raw `story["file_domain"]` entries too.

## 6. The pre-commit review gate can't see an Agent-tool review — **SUPERSEDED; kept for its reasoning**

> **Superseded.** `review_cycle_done.py` now keys `quality_review_done` on the
> `xp-code-reviewer` agent's completion — exactly the fix this section says not
> to take. The by-construction exclusion it cites rested on the Skill hook being
> a completion signal; it is not. `/xp-quality-review` is an INLINE skill, so its
> `PostToolUse:Skill` fires when the Skill tool returns, which is at launch.
>
> That answers ONE of this section's two objections. The other one survives and
> is now live: any `xp-code-reviewer` completion clears the flag, whatever
> spawned it, so a future skill spawning the reviewer for an unrelated purpose
> would open the commit gate. Unreachable today — `xp-quality-review/SKILL.md`
> is the only spawn site in the tree — but that is an unpinned property of the
> tree, not a guarantee, and the same assumption is what makes the release's
> "event count is unchanged" claim hold. Tracked as concern `6552b06d04a3`.
>
> Do not act on the direction below; read it only for the alternative it weighed.

`scripts/pre_tool_bash_commit_gates.py:182-189` blocks a commit unless `cycle["quality_review_done"]` is set, and only the `/xp-quality-review` **Skill** sets it. An `xp-code-reviewer` spawned via the **Agent** tool — what the skill does internally, and what `_close_pipeline_shared.md:34-52` Step 5c prescribes — does not.

**The exclusion is deliberate and commented as by-construction** in two places: `scripts/subagent_stop.py:71-83` ("NOT our own xp-code-reviewer agent") and `scripts/review_cycle_done.py:44-56` ("absent by construction"). Both predate the handoff (`ee1aa741`, `7fdd54ba`).

**So do not take the handoff's primary fix** (make an `xp-code-reviewer` completion clear the flag). It reverses reasoning that was written down on purpose, and would let a reviewer spawned for any unrelated reason clear a gate it never satisfied. Take the second suggestion instead: add a `quality_review_done` leg to `scripts/review_flag_cli.py` (today only `simplify_done`, `:45-54`) for the close pipeline to call explicitly after Step 5c fixes land, and say so in the Step 5c prose. `review_flag_cli.py`'s docstring already frames itself as the async-Step-4b substitute, so the leg fits its stated purpose; update the "no CLI leg for it" comment at `:47` and `_FLAG_LIFECYCLE` alongside.

**Validate before building.** The live window has narrowed to: commit cadence + Step 4b skipped (`RUN_FULL_CODE_REVIEW=false`, cumulative close diff under `REVIEW_CYCLE_THRESHOLD`) + Step 4.5 findings large enough that fixing them pushes the since-last-review file count over the threshold. The two counts have different populations, which is what keeps it reachable. Story cadence (`:172-181`) now defers rather than blocks, and Step 4b's `/xp-quality-review` call unblocks the common path. **Reproduce the block before writing a fix** — otherwise it ships inert.

---

## Sequencing

1. **2 + 3** — both small, both fail-open holes in the same gate, natural pair.
2. **5** — small, independent, zero behavior risk (stderr advisory only).
3. **1** — medium, highest value, subsumes 4.
4. **4** — only after a fresh census against this repo's SMM.
5. **6** — only after the block is reproduced.

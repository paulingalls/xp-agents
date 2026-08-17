## Close review reference

Apply Steps 4 and 4b below after Step 3 (PR creation), before Step 4.5.

### Step 4: Security Review

Applies to **free, sprint, plan** — the enclosing sprint-close covers
story-close.

```
Skill(skill: "security-review",
      args: "the cumulative diff on branch <CURRENT_BRANCH> since merge-base with <TARGET_BRANCH>")
```

Fold each finding into Block / Concern / Keep; file one event per
non-Keep bullet:

| Verdict | `<SEVERITY>` | `<DISPOSITION>` | Effect at Step 6 |
|---|---|---|---|
| Block   | `high`       | `Block`   | Counts toward abort-default |
| Concern | `medium`     | `Concern` | Recorded only |
| Keep    | (no event)   | —         | — |

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "concern" --agent "<close-skill-name>" --severity "<SEVERITY>" \
  --content "Security <DISPOSITION>: <one-line summary>" \
  --files '["<paths /security-review pointed at>"]' \
  --metadata '{"kind":"security","close_cycle_id":"<CLOSE_CYCLE_ID>","close_mode":"<close-mode>"}'
```

Substitute `<close-skill-name>`, `<close-mode>` (`free`/`sprint`/`plan`),
and `<CLOSE_CYCLE_ID>` / `<SMM_DIR>` from the preload values above.

**Surface the prose to the user before Step 6** — the Skill tool
result is invisible to them. Step 4 findings bypass Step 5c (the
classifier scopes to close-reviewer findings only) and flow directly
to the Step 6 count. Do NOT pass them to xp-close-reviewer in Step
4.5 — clean separation; quality and security are independent streams.

### Step 4b: Full code review (conditional)

Run only when the preload emitted `RUN_FULL_CODE_REVIEW=true` (cumulative close
diff ≥ `REVIEW_CYCLE_THRESHOLD` code files) — the one broad multi-agent
correctness pass.

`/code-review` runs via the `Skill` tool. It FORKS, so the call returns at once
and its PostToolUse arms the review-cycle marker there and then — which is what
defers the close Stop gate for the window and makes `/xp-quality-review` read
`MODE=consume-findings`. Do not arm it by hand as well: two writers put two
`simplify_complete` events on one review and the retro counts both. So:

1. Launch `Skill(skill: "code-review", args: "high <TARGET_BRANCH>...HEAD")`.

   **Cost bound.** Scale: candidate locations in the diff range —
   pass the close's own range, not wider. Tier: do not raise it —
   more finder agents, a sweep pass. First word `args`; else does
   not error, falls to default tier, absorbed into the diff range.
   Invoke the named skill — a hand-authored substitute has none of
   it.
2. **Wait** for it to finish, then read its findings. They come back as PROSE in
   the result, not as a structured array — reformat them yourself for the next
   item.
3. `Skill(skill: "xp-quality-review")` — preload emits `consume-findings`; pass
   the findings to the xp-code-reviewer it spawns to validate & fix (+ quality/
   drift/debt). Fix inline or record as debt. Handled here, not Step 5c.

Do NOT run Step 4.5 (the close-reviewer) until these fixes land — it must review
the **post-fix** diff.


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
correctness pass. A Workflow completion reaches no PostToolUse hook, so this
step arms and reports by hand; the fallback below does neither.

`CLI` below is
`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/review_flag_cli.py --smm-dir <SMM_DIR> --cwd ${TEAMMATE_CWD:-.}`.

1. **Arm the marker** — `CLI`. Defers the close Stop gate across the async
   window and makes `/xp-quality-review` read `MODE=consume-findings`.
2. **Launch it**, `<WORKFLOW_SCRIPT>` and `<PLUGIN_ROOT>` verbatim from the
   preload — both are already absolute:
   `Workflow({ scriptPath: "<WORKFLOW_SCRIPT>", args: { level: "high", range: "<TARGET_BRANCH>...HEAD", pluginRoot: "<PLUGIN_ROOT>" } })`

   `args` is an object — fields named, never positional. `pluginRoot` is where
   each finder reads its angle; omit it and they review with no lens.

   **Cost bound.** Scale: candidate locations in the diff range —
   pass the close's own range, not wider. Tier: `level` is `high`;
   do not raise it — more finder agents, a sweep pass. The verifier
   fan-out is capped in the script, whose `summary` reports what the
   cap dropped. Launch the shipped script, or the named skill below —
   a hand-authored substitute has neither's bound.
3. **Wait** for the task-notification. **Read the `summary` first.** A
   `WARNING:` means the launch line was mis-rendered — fix it and go back to the
   arm, which is a fresh cycle and needs `CLI` again. An error, or no changes
   reviewed, means the launcher is the problem: run `CLI --disarm` and take the
   fallback. Otherwise read the `findings` array (`file`, `line`, `summary`,
   `failure_scenario`).

   If the summary says a cap left findings or locations out, record that before
   going on — those are paid-for findings nobody will see otherwise:
   `${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> --type "debt" --agent "<close-skill-name>" --content "Broad review hit its cap: <what the summary said>" --files '["<the diff's own paths>"]'`
4. **Record it finished** — `CLI --complete`. The flag stays set; this only
   emits the lifecycle event, which nothing else on this path will.
5. `Skill(skill: "xp-quality-review")` — preload emits `consume-findings`; pass
   the findings to the xp-code-reviewer it spawns to validate & fix (+ quality/
   drift/debt). Fix inline or record as debt. Handled here, not Step 5c.

**Fallback**, for any wait-step outcome that was not a real review. Disarm
FIRST (`CLI --disarm`) — after, it lands on the fallback's own arm. Then
`Skill(skill: "code-review", args: "high <TARGET_BRANCH>...HEAD")`. Its
PostToolUse both arms and reports, so skip the arm and `--complete` on this
path; its findings return as prose, not an array. Resume at the quality review.

Do NOT run Step 4.5 (the close-reviewer) until these fixes land — it must review
the **post-fix** diff.

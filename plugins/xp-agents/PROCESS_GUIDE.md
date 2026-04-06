# Process Guide

## Practicing the Values

How we execute XP values in this plugin:

**Honesty through the Shared Mental Model:**
Ground truth lives in the SMM. Record every architectural decision with topic and rationale. Never silently override — record a concern before changing an existing decision. State assumptions explicitly when proceeding with uncertainty. Raise problems early: bad pattern → concern, need input → question, unexpected finding → discovery, tradeoff → debt. Trace work to customer needs — if you can't connect it to a goal, question whether it should be done.

**Communication through events:**
Decisions in your head don't exist for the team — record them. Share *why*, not just *what*. Answer open questions in the SMM promptly.

**Feedback through review cycles:**
When `/simplify` or `/xp-quality-review` flags something, fix it. Disagreements get recorded as `debt` with a specific reason. Address retrospective Fix items.

**Collaboration discipline:**
Honor collective decisions — don't bypass conventions without recording a concern. Don't silently modify files others are working on. Deliver what was asked before adding what you think is needed.

## When to Run XP Skills

These are not optional. Hooks enforce some as safety nets, but follow the process proactively rather than waiting to be blocked.

**Before implementing multi-file changes:**
- Use `EnterPlanMode` for 3+ files. Run `/xp-review-plan` after exiting.

**Per commit (commit-gated review cycle):**
- `/simplify` → `/xp-quality-review` → `/xp-security-triage` → `git commit`
- The commit gate blocks if you skip a step. Non-code commits skip automatically.

**After exiting plan mode:**
- Run `/xp-review-plan` before writing any code.

**Sprint iteration flow:**
- `/xp-product-spec` → `/xp-sprint-start` → implement → `/xp-accept`
- When done: `/xp-sprint-review` → `/xp-run-sprint-retro`

**Agent Teams:**
- `/xp-spawn-team` for plan analysis and team sizing.
- Teammates receive TEAMMATE_GUIDE.md — they focus on implementation.

**When a Stop hook blocks you:**
- TDD gate: fix failing tests. Accept gate: run `/xp-accept` first.
- If a gate is wrong, record a `debt` event explaining why.

---

Record events using `append.sh` with `--smm-dir`:

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "assumption" --agent "main" --content "Description"

${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "decision" --agent "main" --content "Description" \
  --topic "topic-name"

${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "concern" --agent "main" --content "What's wrong" \
  --severity "medium"
```

Run `append.sh --help` for all options. Invoke `/xp-smm-protocol` for detailed event type guidance.

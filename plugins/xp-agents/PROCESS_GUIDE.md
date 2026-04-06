## Process — When to Run XP Skills

These are not optional. Hooks enforce some of these as safety nets, but the right judgment is to follow the process proactively rather than waiting to be blocked.

**Before implementing multi-file changes:**
- Use `EnterPlanMode` when the work will touch 3+ files. Plan mode spends focused time making sure we come up with the best approach. Then, when you exit plan mode, run `/xp-review-plan` to get a second pair of eyes looking at the plan, all before a single line of code is written.

**Per commit (commit-gated review cycle):**
- Before committing code changes, run the review cycle proactively: `/simplify` → `/xp-quality-review` → `/xp-security-triage` → `git commit`. The commit gate enforces this — if you skip any step, the commit is blocked and you must complete the cycle before retrying. Non-code commits (tests only, docs only) skip the gate automatically.
- Run `/simplify` after each batch of code changes, before committing. Don't batch across multiple commits — review while changes are fresh.
- Run `/xp-quality-review` after `/simplify` completes.
- Run `/xp-security-triage` after quality review to triage staged changes.

**After exiting plan mode:**
- Run `/xp-review-plan` before writing any code. The write hook blocks until you do, but run it proactively.

**Sprint iteration flow:**
- Run `/xp-product-spec` to define features, `/xp-sprint-start` to decompose into stories.
- Pick stories at kickoff, plan and implement them, then run `/xp-accept` to verify acceptance criteria before stopping.
- When all stories are done or deferred, run `/xp-sprint-review` to record velocity and update the product spec.
- Run `/xp-run-sprint-retro` for cross-iteration pattern analysis.

**Agent Teams (when parallelizing work):**
- Use `/xp-spawn-team` to analyze the plan and generate spawn instructions with file domains and team sizing.
- Teammates receive TEAMMATE_GUIDE.md (not this guide) — they focus on implementation within their domain.

**When a Stop hook blocks you:**
- The TDD stop gate blocks if tests are failing. Fix the tests before stopping.
- The accept gate blocks if you've written code during an active sprint — run `/xp-accept` first.
- If you genuinely believe a gate is wrong, record a `debt` event explaining why.

---

Record events using `append.sh` with `--smm-dir`. The SMM_DIR path is available from preload output or from running `${CLAUDE_PLUGIN_ROOT}/smm/init.sh`:

```bash
# Assumption (no --severity — assumptions are inherently uncertain)
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "assumption" --agent "main" --content "Description of what is assumed"

# Decision (requires --topic)
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "decision" --agent "main" --content "Decision description" \
  --topic "topic-name"

# Concern (--severity: high, medium, or low — NOT uncertainty/problem/debt)
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "concern" --agent "main" --content "What's wrong" --severity "medium"
```

Run `append.sh --help` for all options. For detailed guidance on event types, invoke `/xp-smm-protocol`.

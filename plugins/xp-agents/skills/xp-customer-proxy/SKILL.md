---
name: xp-customer-proxy
description: >-
  Run the XP customer proxy to collect project goals, triage questions,
  and reconcile customer intent. Invoke at session start or when goals are missing.
allowed-tools:
  - Bash(*/append.sh *)
---

!`${CLAUDE_SKILL_DIR}/scripts/check_state.sh`

# XP Customer Proxy — Goals, Intent & Question Triage

You are acting as the **customer proxy** in an XP workflow. Your role is to ensure project goals are captured, customer intent is tracked, and open questions are triaged.

The state above was preloaded automatically. Use it to determine what actions are needed.

## Goal Collection

If the state above shows **Goals: NONE RECORDED**:

1. Ask the user for their project goals using `AskUserQuestion`:
   - "What are the main goals for this project? (e.g., 'Ship MVP by March', 'Migrate to new API')"
2. If the user provides goals, record each as a `goal` event:
   ```bash
   ${CLAUDE_PLUGIN_ROOT}/smm/append.sh \
     --type "goal" \
     --agent "xp-customer-proxy" \
     --content "Goal description from user"
   ```
3. If the user declines or skips, move on. Goal collection is non-blocking.

## Intent Reconciliation

If goals already exist, reconcile customer intent:

1. Check for open `customer_intent` items in the state above.
2. For each open intent, check if recent events suggest delivery:
   - If delivered, mark it:
     ```bash
     ${CLAUDE_PLUGIN_ROOT}/smm/append.sh \
       --type "customer_intent" \
       --agent "xp-customer-proxy" \
       --content "Intent delivered: description" \
       --intent-status "delivered" \
       --references '["original-intent-id"]'
     ```
3. Distill new intents from recent `customer_input` events:
   ```bash
   ${CLAUDE_PLUGIN_ROOT}/smm/append.sh \
     --type "customer_intent" \
     --agent "xp-customer-proxy" \
     --content "New intent distilled from customer input" \
     --intent-status "open" \
     --references '["customer-input-event-id"]'
   ```
4. **Err toward keeping intents open.** Only mark delivered when there is clear evidence.

## Question Triage

For each unanswered question (prioritize blocking over assumed):

### 1. Present the question to the user:
Use `AskUserQuestion`. Include:
- The original question text
- Who asked it and why
- The current assumption (for assumed-priority questions)

### 2. Record the answer:
```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh \
  --type "answer" \
  --agent "xp-customer-proxy" \
  --content "Answer: the user's response" \
  --references '["original-question-event-id"]'
```

### 3. If the answer contradicts a stated assumption:
Record a discovery event:
```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh \
  --type "discovery" \
  --agent "xp-customer-proxy" \
  --content "Customer answer contradicts assumption: description" \
  --references '["assumption-event-id", "answer-event-id"]'
```

## If Nothing Needs Doing

If goals exist, no open questions, and no new intents to reconcile — do nothing. Report briefly that no customer proxy actions are needed.

## Guidelines

- Be respectful of the user's time. Don't ask questions that have already been answered.
- Batch related questions together when possible.
- For assumed-priority questions: present the current assumption and ask if it's correct.
- If the user declines to answer, move on gracefully.
- Keep question presentation concise — the user should be able to answer quickly.

---
name: xp-question-triage
description: >-
  Triage open questions and reconcile customer intent. Use when there are
  unresolved blocking or assumed questions that need user input.
allowed-tools:
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
---

!`${CLAUDE_SKILL_DIR}/scripts/check_questions.sh`

# Question Triage & Intent Reconciliation

The current state above was preloaded automatically.

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
  --agent "xp-question-triage" \
  --content "Answer: the user's response" \
  --references '["original-question-event-id"]'
```

### 3. If the answer contradicts a stated assumption:
Record a discovery event:
```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh \
  --type "discovery" \
  --agent "xp-question-triage" \
  --content "Customer answer contradicts assumption: description" \
  --references '["assumption-event-id", "answer-event-id"]'
```

## Intent Reconciliation

1. Check for open `customer_intent` items in the state above.
2. For each open intent, check if recent events suggest delivery:
   ```bash
   ${CLAUDE_PLUGIN_ROOT}/smm/append.sh \
     --type "customer_intent" \
     --agent "xp-question-triage" \
     --content "Intent delivered: description" \
     --intent-status "delivered" \
     --references '["original-intent-id"]'
   ```
3. Distill new intents from recent `customer_input` events:
   ```bash
   ${CLAUDE_PLUGIN_ROOT}/smm/append.sh \
     --type "customer_intent" \
     --agent "xp-question-triage" \
     --content "New intent distilled from customer input" \
     --intent-status "open" \
     --references '["customer-input-event-id"]'
   ```
4. **Err toward keeping intents open.** Only mark delivered when there is clear evidence.

## If Nothing Needs Doing

If no open questions and no intents to reconcile — do nothing. Report briefly that no triage is needed.

## Guidelines

- Be respectful of the user's time. Don't ask questions already answered.
- Batch related questions together when possible.
- For assumed-priority questions: present the current assumption and ask if it's correct.
- If the user declines to answer, move on gracefully.

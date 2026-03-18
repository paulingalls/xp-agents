---
name: xp-housekeeping
description: >-
  Four-pillar SMM curation. Reads structured curation data and existing SMM,
  applies LLM judgment to curate Intent, Constraints, Risks, and Wisdom
  pillars. Writes curated SMM and updates curation watermark.
allowed-tools:
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
---

!`${CLAUDE_SKILL_DIR}/scripts/prepare_curation_preload.sh`

# Housekeeping — Four-Pillar SMM Curation

The preload above provides two sections:
1. **Existing SMM** — the current SHARED_MENTAL_MODEL.md (merge into this, don't replace)
2. **Curation Data (JSON)** — structured data from `prepare_curation_data()` with five fields:
   - `current_smm`: items mapped to four pillars (intent, constraints, risks, wisdom)
   - `new_since_last_curation`: new events since last curation (customer_inputs, decisions, concerns, assumptions, debt, questions, resolutions)
   - `retro_history`: latest_tries, recurring_fixes, adopted_tries
   - `aging`: risk ID → session count since creation
   - `health`: item counts per pillar

The **SMM_DIR** path is printed at the end of the preload output. Use it for append.sh and save_smm.py calls.

## 1. Curate Intent

Review `current_smm.intent` (existing) and `new_since_last_curation.customer_inputs` (new).

For each new customer input, judge: **Is this a deliverable outcome or just a task?**
- "Add role-based access" → intent (deliverable outcome)
- "Fix the typo in README" → task (not an intent)

Actions:
- Keep existing undelivered intents
- Add new intents from customer inputs (only deliverable outcomes)
- Mark delivered intents (check if code was shipped)
- If Intent is empty, ask the user: "What should we build next?"
- **Cap: ~10 items.** If over cap, ask user which are still priorities.

Format each item as: `- 📋 <deliverable outcome> [source-id]`

## 2. Curate Constraints

Review `current_smm.constraints` (existing) and `new_since_last_curation.decisions` (new).

For each new draft decision, ask the user: **Confirm as architectural decision, or reject?**

Actions:
- Confirmed decisions → add as constraint
- Rejected drafts → record resolution via append.sh
- Keep existing constraints unless explicitly superseded
- Graduate constraints stable for 10+ sessions and enforced by code/tests (remove from SMM — the codebase embodies them)
- **Cap: ~20 items.**

Record confirmed decisions:
```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh \
  --type "decision" \
  --agent "xp-housekeeping" \
  --content "<decision content>" \
  --topic "<topic>" \
  --references '["<draft-decision-id>"]'
```

## 3. Curate Risks

Review `current_smm.risks` (existing), `new_since_last_curation` (concerns, assumptions, debt, questions), `aging`, and `new_since_last_curation.resolutions`.

Unify all risk types into one section with severity:
- **Uncertainty** — "we think X but haven't verified"
- **Problem** — "X is wrong and needs fixing"
- **Debt** — "we chose to defer X"

Actions:
- Apply aging from curation data: ⚠️ for 3+ sessions, 🔴 for 6+ sessions
- Remove risks that have resolutions in `new_since_last_curation.resolutions`
- Record resolutions via append.sh with `metadata.resolves`
- Same-session assumptions (from plan reviews): verify or drop — don't let them linger
- Ask user about 🔴 risks: "This has been open 6+ sessions. Resolve or accept?"
- **Cap: ~10 items.** If over cap, the SMM itself should flag: "Risk register at capacity"

Format: `- 🔴 <risk> (N sessions)` or `- ⚠️ <risk> (N sessions)` or `- <risk>`

## 4. Curate Wisdom

Review `retro_history` from curation data.

Promote to Wisdom when:
- A retro "Try" was adopted and worked (appears in `adopted_tries`)
- A retro "Fix" recurred 3+ times (appears in `recurring_fixes`) — distill into a rule
- Customer gave explicit guidance

Each wisdom item must be a **behavioral rule**: "do X because Y" or "don't do Y because Z".

Actions:
- Keep existing wisdom items that are still relevant
- Demote items not referenced for 10+ sessions
- **Hard cap: 10 items.** Adding at cap requires removing one.
- Ask user if unsure about promotions or demotions

Format: `- <behavioral rule — "do X because Y">`

## 5. Health Check

Count items per pillar and flag warnings:

| Pillar | Healthy | Warning |
|---|---|---|
| Intent | 2-5 | 0 = no direction, 10+ = scope creep |
| Constraints | 5-15 | 0 = no decisions, 20+ = over-specified |
| Risks | 2-5 | 0 = false confidence, 10+ = unmanaged risk |
| Wisdom | 3-7 | 0 = not learning, 10 = cap reached |

If any pillar is unhealthy, note the warning in your output to the user.

## 6. Record Resolutions

For any items resolved during curation (goals completed, concerns addressed, debt fixed, decisions rejected), record resolution events:
```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh \
  --type "status" \
  --agent "xp-housekeeping" \
  --content "<resolution description>" \
  --working-on '[]' \
  --metadata '{"resolves": ["<event-id>"]}'
```

## 7. Write the Curated SMM

Assemble the four-pillar markdown and write it via save_smm.py:

```bash
cat <<'SMMEOF' | python3 ${CLAUDE_SKILL_DIR}/scripts/save_smm.py --smm-dir <SMM_DIR>
# Shared Mental Model

## Intent
<intent items>

## Constraints
<constraint items>

## Risks
<risk items with severity markers>

## Wisdom
<wisdom items>
SMMEOF
```

**Target size: ~300-600 tokens.** The SMM is a briefing, not a database. Each item is one line.

## 8. Load Session Context

After writing the SMM, load the full context:

1. Run: `${CLAUDE_SKILL_DIR}/scripts/load_context.sh`
2. Read the file at the SMM_FILE path from the output
3. Read the file at the GUIDE_FILE path from the output

This ensures the curated SMM and Behavioral Guide are in your conversation context.

## 9. Compact Event Log

After loading context, compact the event log to keep it at a manageable size (~50-200 events):

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/compact_log.py --smm-dir <SMM_DIR>
```

This archives old events that have already been curated into the SMM, keeping only:
- Events since the last curation (not yet curated)
- Last 3 session_end events (for aging calculations)
- Events still referenced by active SMM items (unresolved goals, open concerns, etc.)

The SMM is the durable record. The event log is the working buffer that feeds it.

## Guidelines

- **Merge, don't replace.** Always read the existing SMM first. Preserve items that are still relevant.
- **Be concise.** Each item is one line. The SMM is a briefing an agent reads in 2 seconds.
- **Use judgment.** Not every customer input is an intent. Not every concern is a risk. Curate.
- **Ask when unsure.** Use AskUserQuestion for ambiguous items — don't guess.
- **Present items in batches.** Group related items in AskUserQuestion, not one at a time.
- **If the user says "skip"**, move on. Items persist until resolved.
- **Caps are features.** They force prioritization. When at cap, something must leave before something enters.

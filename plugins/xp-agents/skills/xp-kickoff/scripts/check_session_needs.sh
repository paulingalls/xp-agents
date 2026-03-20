#!/bin/bash
set -euo pipefail
# Preload for xp-kickoff: determine what session-start work is needed.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

SMM_FILE="${SMM_DIR}/SHARED_MENTAL_MODEL.md"
RETRO_INPUT="${SMM_DIR}/.retro-input.json"
MARKER="${SMM_DIR}/.needs-kickoff"

echo "## Session Review Status"
echo ""

# 1. Check for retrospective data
if [ -f "$RETRO_INPUT" ]; then
    echo "### RETRO_NEEDED"
    echo "Unanalyzed events from previous session found."
    echo ""
fi

# 2. Always show goals and offer to add more
echo "### GOALS_REVIEW"
if [ -f "$SMM_FILE" ] && smm_has_section "Intent"; then
    echo "Current goals:"
    smm_section "Intent" | head -20
else
    echo "No project goals recorded yet."
fi
echo ""

# 3. Check for open questions needing triage
# Check both the curated SMM (Risks pillar) and raw events for unresolved
# blocking questions. Events may contain questions that housekeeping hasn't
# curated into the SMM yet.
echo "### QUESTIONS_CHECK"
QUESTIONS_FOUND=false
if [ -f "$SMM_FILE" ] && smm_has_section "Risks"; then
    if smm_section "Risks" 30 | grep -qi "question\|assumption\|blocking"; then
        QUESTIONS_FOUND=true
    fi
fi
if [ "$QUESTIONS_FOUND" = false ] && [ -f "${SMM_DIR}/events.jsonl" ]; then
    if python3 -c "
import json, sys
events = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
resolved = set()
for e in events:
    for rid in (e.get('metadata') or {}).get('resolves', []):
        resolved.add(rid)
    for rid in (e.get('references') or []):
        if e.get('type') == 'answer':
            resolved.add(rid)
open_qs = [e for e in events
           if e.get('type') == 'question'
           and e.get('id') not in resolved]
sys.exit(0 if open_qs else 1)
" "${SMM_DIR}/events.jsonl" 2>/dev/null; then
        QUESTIONS_FOUND=true
    fi
fi
if [ "$QUESTIONS_FOUND" = true ]; then
    echo "QUESTIONS_NEEDED"
    echo "Open questions or assumptions found."
else
    echo "No open questions."
fi
echo ""

# 4. Housekeeping always runs as the final step
echo "### HOUSEKEEPING"
echo "Housekeeping runs as final step (ensures SMM + behavioral guide injection)."

# Always clear the marker here. This preload runs as a !`command` before
# any tool calls, so the gate must be lifted for the review itself to
# proceed. If the review is aborted, session_start.py will recreate the
# marker on the next session.
rm -f "$MARKER"

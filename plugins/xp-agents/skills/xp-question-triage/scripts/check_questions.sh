#!/bin/bash
set -euo pipefail
# Preload for xp-question-triage: check for open questions and intents.
# Supports both four-pillar SMM (## Risks, ## Intent) and pre-curation format.
# Uses anchored patterns (^## X$) to prevent substring collisions.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

SMM_FILE="${SMM_DIR}/SHARED_MENTAL_MODEL.md"

# Check for open questions (four-pillar: ## Risks, old: Blocking Questions / ## Questions)
if [ -f "$SMM_FILE" ] && grep -q "^## Risks$" "$SMM_FILE" 2>/dev/null; then
    echo "### Open Questions:"
    grep -A 30 "^## Risks$" "$SMM_FILE" | sed '/^## [^R]/,$d' | head -20
elif [ -f "$SMM_FILE" ] && grep -q "Blocking Questions\|^## Questions$" "$SMM_FILE" 2>/dev/null; then
    echo "### Open Questions:"
    grep -A 30 "Questions" "$SMM_FILE" | sed '/^## [^Q]/,$d' | head -20
else
    echo "### Open Questions: none"
fi

echo ""

# Check for customer intent (four-pillar: ## Intent, old: ## Customer Intent)
# Anchored ^## Intent$ prevents matching ## Customer Intent as substring
if [ -f "$SMM_FILE" ] && grep -q "^## Intent$" "$SMM_FILE" 2>/dev/null; then
    echo "### Customer Intent:"
    grep -A 30 "^## Intent$" "$SMM_FILE" | sed '/^## [^I]/,$d' | head -20
elif [ -f "$SMM_FILE" ] && grep -q "^## Customer Intent$" "$SMM_FILE" 2>/dev/null; then
    echo "### Customer Intent:"
    grep -A 30 "^## Customer Intent$" "$SMM_FILE" | sed '/^## [^C]/,$d' | head -20
else
    echo "### Customer Intent: none tracked"
fi

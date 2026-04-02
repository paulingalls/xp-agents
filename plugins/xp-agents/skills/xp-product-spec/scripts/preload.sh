#!/bin/bash
set -euo pipefail
# Preload for xp-product-spec: show existing spec or indicate create mode.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

echo "SMM_DIR=${SMM_DIR}"
echo ""

SPEC_FILE="${SMM_DIR}/product_spec.md"

if [ -f "$SPEC_FILE" ]; then
    planned=$(grep -c '\[planned\]' "$SPEC_FILE" 2>/dev/null || echo 0)
    delivered=$(grep -c '\[delivered:' "$SPEC_FILE" 2>/dev/null || echo 0)
    echo "## Existing Product Spec"
    echo "${planned} features planned, ${delivered} delivered"
    echo ""
    cat "$SPEC_FILE"
else
    echo "## No product spec found"
    echo "Create mode: guide the user through requirements gathering."
fi

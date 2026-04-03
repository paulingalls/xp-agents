#!/bin/bash
set -euo pipefail
# Preload for xp-sprint-review: prepare review data, output paths + guide.
# The subagent reads .sprint-review-input.json itself.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

# Run prep script to build review input
python3 "$(dirname "$0")/prepare_review_data.py" --smm-dir "$SMM_DIR"

echo "SMM_DIR=${SMM_DIR}"
echo "REVIEW_INPUT=${SMM_DIR}/.sprint-review-input.json"
echo ""
dump_guide

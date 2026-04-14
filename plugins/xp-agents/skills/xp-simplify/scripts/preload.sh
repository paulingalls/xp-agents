#!/bin/bash
set -euo pipefail
# Preload for xp-simplify: full diff for code review.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

echo "SMM_DIR=${SMM_DIR}"
echo ""
dump_diff full

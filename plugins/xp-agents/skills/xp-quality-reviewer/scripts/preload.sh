#!/bin/bash
set -euo pipefail
# Preload for xp-quality-reviewer: git diff + SMM state.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"
dump_diff
dump_smm

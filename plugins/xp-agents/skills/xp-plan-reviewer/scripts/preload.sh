#!/bin/bash
set -euo pipefail
# Preload for xp-plan-reviewer: SMM state only.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"
dump_smm

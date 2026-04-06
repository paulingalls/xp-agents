#!/bin/bash
set -euo pipefail
# Preload for xp-retrospective: paths + XP values only.
# The subagent reads .retro-input.json itself — keeps the preload
# lightweight so the main agent's context isn't bloated if fork fails.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

echo "SMM_DIR=${SMM_DIR}"
echo "RETRO_INPUT=${SMM_DIR}/.retro-input.json"
echo ""
dump_values

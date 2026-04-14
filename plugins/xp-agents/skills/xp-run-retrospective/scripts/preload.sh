#!/bin/bash
set -euo pipefail
# Preload for xp-retrospective: paths only.
# XP values injected universally via SubagentStart.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

echo "SMM_DIR=${SMM_DIR}"
echo "RETRO_INPUT=${SMM_DIR}/.retro-input.json"

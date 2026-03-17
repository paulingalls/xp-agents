#!/bin/bash
set -euo pipefail
# Preload for xp-quality-review: show changed files for review.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

dump_diff

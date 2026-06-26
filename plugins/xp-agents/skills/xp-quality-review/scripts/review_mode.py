#!/usr/bin/env python3
"""Emit the xp-quality-review MODE: consume-findings vs self-find.

Role-lever discriminator. A fresh /code-review completion this review cycle
sets simplify_done for the resolved agent_id (review_cycle_done.py). When the
quality-review preload sees it, /code-review just ran and its JSON findings are
in the agent's context => consume-findings. Otherwise no /code-review ran
(per-increment path) => the xp-code-reviewer self-finds correctness.

agent_id is resolved from --cwd via identity.resolve_agent_id_from_cwd (the
preload has no hook input_data to read an explicit agent_id from). The writer
(review_cycle_done.py) and the per-commit gate use resolve_agent_id(input_data),
which falls back to the SAME cwd resolution when agent_id is empty — the real
case for the main session and teammate worktrees, so the read keys line up
there. If a populated agent_id ever diverged from cwd, the read would miss and
MODE would stay self-find — safe (the reviewer still runs correctness), just a
redundant pass. The preload passes --cwd "${TEAMMATE_CWD:-.}" (the closing-story
worktree at story-close, else the main checkout).
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "scripts"))

import identity
import markers

CONSUME_FINDINGS = "consume-findings"
SELF_FIND = "self-find"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smm-dir", required=True)
    parser.add_argument("--cwd", default=".")
    args = parser.parse_args()

    agent_id = identity.resolve_agent_id_from_cwd(args.cwd)
    cycle = markers.read_review_cycle(Path(args.smm_dir), agent_id)
    print(CONSUME_FINDINGS if cycle.get("simplify_done") else SELF_FIND)


if __name__ == "__main__":
    main()

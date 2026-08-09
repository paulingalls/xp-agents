#!/usr/bin/env python3
"""Which run did a test-failure concern come from?

A 1-test scoped run, a `docker compose exec ... pytest`, a teammate's worktree
run and a 508-test suite all surfaced identically at kickoff: the concern that
carries forward carried no working directory and no counts. Both producers
answer that question here so they cannot drift on the spelling or the shape —
`bash_post_tool` from a parsed summary, `bash_failure` from a non-zero exit
that often has no counts at all.

Distinct from `test_attribution`, which answers a different question: WHICH
RUNNER is to blame for a non-zero exit. This module does not attribute blame;
it identifies the run.

Two rules run through everything below:

* **Omit, never fabricate.** A missing count is honest. A zero is a lie that
  reads as a green run, and the producers' gates are what decide whether a
  number exists — not a default here.
* **Home-relative, not absolute.** The SMM is durable and renders back into
  prompts, so a path under `$HOME` carries the username for no diagnostic
  gain. Collapsing it keeps everything that matters (the `.claude/worktrees/`
  fragment, the subdirectory, the basename the renderer shows).
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

from event_metadata import (
    METADATA_KEY_CWD,
    METADATA_KEY_TEST_COUNT,
    METADATA_KEY_TEST_ERRORS,
    METADATA_KEY_TEST_FAILED,
)


def home_relative_cwd(cwd: str) -> str:
    """Collapse a leading `$HOME` onto `~`; anything else is returned as-is.

    A path outside `$HOME` (container mount, `/tmp`) has no home to strip and
    stays absolute — which is exactly the case where the full path is the only
    attribution available.

    `os.path.expanduser` rather than `Path.home()`: the latter RAISES when
    `HOME` is unset and the pwd lookup fails, and this sits on a hook path that
    must not die. `expanduser` returns `"~"` unchanged instead.

    The `home + os.sep` guard is load-bearing: without it `/Users/develop`
    under `HOME=/Users/dev` would collapse to `~elop`.
    """
    home = os.path.expanduser("~")
    if cwd == home:
        return "~"
    if cwd.startswith(home + os.sep):
        return "~" + cwd[len(home) :]
    return cwd


def run_attribution_metadata(
    cwd: str | None,
    *,
    failed: int | None = None,
    total: int | None = None,
    errors: int | None = None,
) -> dict:
    """The attribution block for a test-failure concern's `metadata`.

    Every argument is optional because the two producers know different
    amounts. `bash_post_tool` reaches its concern branch only with parsed
    counts, so it passes all of them. `bash_failure` passes `cwd` and at most
    `failed`: it records NO total, because with no summary line its counts come
    from `result_counts.two_counts`, two INDEPENDENT last-match scans whose sum
    can pair numbers from unrelated lines. A denominator like `2/35` there
    would be plausible fiction, which is worse than a missing one — nothing
    about it looks wrong.

    `None` means "not observed" and the key is omitted; `0` is a real
    observation and is recorded. `errors` follows the STATUS producer's guard
    and appears only when positive, so an ordinary failure carries no
    meaningless `test_errors: 0`.
    """
    metadata: dict = {}
    if cwd:
        metadata[METADATA_KEY_CWD] = home_relative_cwd(cwd)
    if failed is not None:
        metadata[METADATA_KEY_TEST_FAILED] = failed
    if total is not None:
        metadata[METADATA_KEY_TEST_COUNT] = total
    if errors:
        metadata[METADATA_KEY_TEST_ERRORS] = errors
    return metadata

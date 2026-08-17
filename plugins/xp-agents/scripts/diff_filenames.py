#!/usr/bin/env python3
"""Post-image filenames from a unified diff — text in, paths out.

Split from `commits.py` when the review-scope budget took that file over its
sub-cap. It is the one function there that never asks git: everything else in
that module shells out, this parses a string a caller already holds. That is
the line the split follows, the same one `commit_trailers` was drawn along
("those take text and return text, while everything above asks git").

No git means no import back into `commits`, so this is a leaf — which is why
`commits` can re-export it from its ordinary import block rather than the
mid-file position its cyclic siblings need.
"""


def get_filenames_from_diff(diff_text: str) -> list[str]:
    """Parse post-image filenames from a unified diff, deduped, in first-seen order.

    Approximates `git diff --cached --name-only` for the common case:
    emits the new-side path for modifications and additions, the old-
    side path for deletions (where post is /dev/null), and the rename
    destination for renames. Does NOT parse `copy from`/`copy to` git
    copy-detection headers (rare for `--cached` since copy detection
    is off by default; cross-check before threading through copy-aware
    flows). Used to avoid re-shelling for filenames when the caller
    already has the cached unified diff in hand.
    """
    if not diff_text:
        return []

    out: list[str] = []
    seen: set[str] = set()

    def _add(path: str) -> None:
        if path and path not in seen:
            seen.add(path)
            out.append(path)

    # Walk line-by-line so we can pair `+++ /dev/null` (deleted file) with
    # the immediately-preceding `--- a/<path>` line.
    last_pre: str | None = None
    for line in diff_text.splitlines():
        if line.startswith("--- a/"):
            last_pre = line[len("--- a/") :]
        elif line == "--- /dev/null":
            last_pre = None
        elif line.startswith("+++ b/"):
            _add(line[len("+++ b/") :])
            last_pre = None
        elif line == "+++ /dev/null":
            if last_pre is not None:
                _add(last_pre)
            last_pre = None
        elif line.startswith("rename to "):
            _add(line[len("rename to ") :])

    return out

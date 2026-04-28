"""Test helpers for patching the ``commits.*`` lookup trio.

``commits.get_committed_files`` / ``get_commit_message_body`` /
``get_head_commit_hash`` are called together by ``bash_post_tool``'s
commit-handling path (and a few other consumers). The 3-patch
boilerplate previously appeared at 16 test sites across 4 files.

Use ``patch_commits`` as a contextmanager when all three lookups need
stubbing; pass only the values you care about, defaults cover the rest.
"""

import contextlib
from collections.abc import Iterator
from unittest.mock import patch


@contextlib.contextmanager
def patch_commits(
    *,
    files: list[str] | None = None,
    body: str = "commit",
    head_sha: str | None = "abc123",
) -> Iterator[None]:
    """Patch the three ``commits.*`` lookups for the with-block.

    Defaults are deliberately bland — pass ``files``/``body``/``head_sha``
    when the test asserts on a specific value. ``files`` defaults to a
    single-file list rather than empty so callers that exercise the
    default path still see a non-trivial commit. ``head_sha`` accepts
    ``None`` because ``get_head_commit_hash`` legitimately returns
    ``None`` (missing repo or empty HEAD); call sites that exercise that
    path pass it explicitly. ``body`` is a neutral placeholder; tests
    that depend on a story-id pattern must pass it explicitly so the
    coupling is visible at the call site.
    """
    committed_files = files if files is not None else ["scripts/x.py"]
    with (
        patch("commits.get_committed_files", return_value=committed_files),
        patch("commits.get_commit_message_body", return_value=body),
        patch("commits.get_head_commit_hash", return_value=head_sha),
    ):
        yield

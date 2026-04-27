#!/usr/bin/env python3
"""Post-pipeline operations for /xp-scaffold-acceptance: commit + record.

Where ``scaffold_apply`` owns the fs/subprocess pipeline (write + install +
verify + atomic revert), this module owns the git/state side that runs
after a green verify:

- ``build_commit_message(...)``: pure formatter for the M-4 doctrine
  commit subject and trailers (Tool-version / Files-created /
  Files-modified / Verification / Resolves-Event).

Subsequent commits in story-001 / story-002 will land
``commit_scaffold(...)`` (stage-aware branch + commit orchestration)
and ``record_scaffold(...)`` (system_context flip + concern resolution
decision event).

No I/O in this commit — just the pure helper that the orchestration
layer composes with.
"""


def build_commit_message(
    *,
    surface: str,
    tool: str,
    tool_version: str,
    verify_cmd: str,
    files_created: list[str],
    files_modified: list[str],
    concern_id: str | None,
) -> str:
    """Return the M-4 doctrine commit message string.

    Subject: ``[chore] Scaffold <surface> acceptance via <tool>``.
    Trailers (in order): ``Tool-version``, ``Files-created`` (omitted
    when empty), ``Files-modified`` (omitted when empty),
    ``Verification``, ``Resolves-Event`` — with ``Resolves-Event: none``
    when ``concern_id`` is None, per the SMM constraint that every
    commit body carry a Resolves-Event trailer.
    """
    subject = f"[chore] Scaffold {surface} acceptance via {tool}"
    trailers = [f"Tool-version: {tool_version}"]
    if files_created:
        trailers.append(f"Files-created: {', '.join(files_created)}")
    if files_modified:
        trailers.append(f"Files-modified: {', '.join(files_modified)}")
    trailers.append(f"Verification: {verify_cmd}")
    trailers.append(f"Resolves-Event: {concern_id or 'none'}")
    return subject + "\n\n" + "\n".join(trailers) + "\n"

#!/usr/bin/env python3
"""A real temp git repo plus a temp SMM, for the commit-event rebuild suites.

The rebuild's discriminators — committer timestamp, parent count, reflog action
— are properties of git's own history, so these suites drive a REAL repo rather
than patched `commits.*` lookups a stub would let us assert into existence.
That fixture is what the suites share, so it lives here rather than being
copied; it also keeps `test_commit_event_rebuild.py` under the line sub-cap it
pins on itself.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import bash_post_tool
from conftest import _HookTestCase, _make_bash_input, make_event
from event_helpers import events_of_type
from event_schema import EVENT_TYPE_COMMIT, EVENT_TYPE_CONCERN

# Two shapes of "the hook cannot expand this message". `-F <path>` yields no
# message at all; `"$MSG"` yields the literal variable name, which never
# matches HEAD. Both are real: the recorded incident used a command
# substitution, and `-F -` with a heredoc is the other common spelling.
#
# Here rather than in either consumer: both suites drive the rebuild through an
# unreadable command, and the pair is explained once. Splitting them apart
# would put half the explanation in each file.
UNREADABLE_F = "git commit -F {repo}/.git/MSG-ALREADY-GONE"
UNREADABLE_VAR = 'git commit -m "$MSG"'


class _RebuildTestCase(_HookTestCase):
    """A real git repo plus a temp SMM, fresh per test."""

    def setUp(self):
        super().setUp()
        self.repo = Path(tempfile.mkdtemp())
        self.git("init", "-q", "-b", "main", ".")
        self.git("config", "user.email", "t@t.com")
        self.git("config", "user.name", "T")
        # An initial commit so `git diff HEAD~1` (get_committed_files) has a
        # parent to diff against — a root commit reports no files at all.
        self.commit("init", path="README.md", content="init")

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)
        super().tearDown()

    def git(self, *args: str, env_extra: dict | None = None) -> str:
        env = os.environ.copy()
        if env_extra:
            env.update(env_extra)
        result = subprocess.run(
            ["git", *args],
            cwd=self.repo,
            capture_output=True,
            text=True,
            env=env,
        )
        if result.returncode != 0:
            raise AssertionError(f"git {args!r} failed: {result.stderr}")
        return result.stdout.strip()

    def commit(
        self,
        message: str,
        *,
        path: str = "src/foo.py",
        content: str | None = None,
        age_seconds: int = 0,
    ) -> str:
        """Write `path`, commit `message`, return the new HEAD hash.

        `age_seconds` backdates BOTH dates: the freshness gate reads the
        committer timestamp, and pinning only the author date would leave the
        commit young by the measure that matters.
        """
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content if content is not None else message)
        self.git("add", "-A")
        env = None
        if age_seconds:
            stamp = f"{int(self.head_timestamp()) - age_seconds} +0000"
            env = {"GIT_COMMITTER_DATE": stamp, "GIT_AUTHOR_DATE": stamp}
        self.git("commit", "-q", "-m", message, env_extra=env)
        return self.head()

    def head(self) -> str:
        return self.git("rev-parse", "HEAD")

    def head_timestamp(self) -> str:
        return self.git("show", "-s", "--format=%ct", "HEAD")

    def erase_reflog(self) -> None:
        """Leave `git reflog -1` with nothing to report.

        The WHOLE `.git/logs` tree, not just `logs/HEAD`: with HEAD's own log
        gone git resolves `HEAD` to the current branch and reads
        `logs/refs/heads/<branch>` instead, so removing one file leaves the
        action still readable (measured: a merge still reported `merge side`)
        and the no-opinion arm never runs. `core.logAllRefUpdates` off then
        keeps the next git call from recreating them.
        """
        self.git("config", "core.logAllRefUpdates", "false")
        shutil.rmtree(self.repo / ".git" / "logs")

    def run_hook(
        self, command: str, stdout: str = "", *, background: bool = False, **overrides
    ):
        """Drive the PostToolUse hook over `command`.

        `background=True` spells the shape the Bash tool hands the hook for
        `run_in_background: true` — the tool call returns at LAUNCH, so
        `stdout` carries the harness notice rather than git's output and the
        repo is in whatever state the PREVIOUS command left it.
        """
        data = _make_bash_input(
            command=command.format(repo=self.repo),
            stdout=stdout,
            cwd=str(self.repo),
            **overrides,
        )
        if background:
            data["tool_input"]["run_in_background"] = True
        return bash_post_tool.run(data, smm_dir=self.smm_dir)

    def seed_concern(self) -> str:
        """Append a concern for a trailer to close, and return its id."""
        event = make_event(
            EVENT_TYPE_CONCERN, content="dangling work", files=["src/foo.py"]
        )
        _common.append_safe(self.smm_dir, event)
        return event["id"]

    def commit_events(self) -> list[dict]:
        return events_of_type(self._read_events(), EVENT_TYPE_COMMIT)

    def concerns(self) -> list[dict]:
        return events_of_type(self._read_events(), EVENT_TYPE_CONCERN)

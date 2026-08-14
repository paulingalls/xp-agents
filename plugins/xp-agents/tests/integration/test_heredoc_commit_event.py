#!/usr/bin/env python3
"""E2E: a stdin-fed commit whose body mentions a runner flag still records.

The unit cases pin what `recover_commit_message` returns. This one pins the
damage that made it worth fixing, which is one step downstream and invisible to
them: with the wrong message recovered, `_head_matches_command` fails, the
success path never fires, and **no commit event is written at all**. Every
`Resolves-Event:` id the author named then stays silently open.

So the assertion here is not "the right string came back" but "the event exists
and says what git says", driven through the real hook as a SUBPROCESS — the
route a commit actually takes.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _repo_fixtures import git_in, init_nested_repo
from conftest import _IntegrationTestCase
from event_helpers import events_of_type
from event_schema import EVENT_TYPE_COMMIT

_SUBJECT = "Render the attribution suffix once"
# The token that used to be taken as the message. Ordinary prose in a commit
# body — this repo's own history is full of it.
_BODY = f'{_SUBJECT}\n\nVerified with pytest -m "slow" before landing.'


class TestAStdinFedCommitRecordsItsEvent(_IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.repo = init_nested_repo(self.tmpdir)

    def _git(self, *args: str, stdin: str | None = None) -> str:
        return git_in(self.repo, *args, stdin=stdin)

    def _commit_via_stdin(self) -> None:
        """Make a real commit whose message git read from STDIN.

        `-F -` is the shape whose body the hook used to read a `-m` out of, and
        feeding it for real is the point: the message git stores has to be the
        one the assertion compares against.
        """
        (self.repo / "src").mkdir(exist_ok=True)
        (self.repo / "src" / "app.py").write_text("x = 1\n")
        self._git("add", "-A")
        self._git("commit", "-q", "-F", "-", stdin=_BODY)

    def _run_post_tool(self, command: str) -> subprocess.CompletedProcess:
        payload = {
            "session_id": "int-test",
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "tool_response": {"stdout": "", "stderr": ""},
            "cwd": str(self.repo),
            "agent_id": "main",
        }
        return subprocess.run(
            ["python3", str(self.scripts_dir / "bash_post_tool.py")],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=self._test_env.copy(),
        )

    def _commit_events(self) -> list[dict]:
        return events_of_type(self._read_events(), EVENT_TYPE_COMMIT)

    def test_the_event_lands_and_matches_what_git_stored(self):
        self._commit_via_stdin()
        head_subject = self._git("show", "-s", "--format=%s", "HEAD")
        self.assertEqual(head_subject, _SUBJECT)

        # The command as the agent wrote it: the body is a heredoc on stdin, and
        # it contains the token that used to be mistaken for the message.
        result = self._run_post_tool(f"git commit -F - <<'MSG'\n{_BODY}\nMSG")
        self.assertEqual(result.returncode, 0, result.stderr)

        events = self._commit_events()
        self.assertEqual(len(events), 1, f"expected one commit event, got {events}")
        self.assertIn(_SUBJECT, events[0]["content"])
        self.assertNotEqual(events[0]["content"].strip(), "slow")

    def test_the_recorded_hash_is_the_commit_that_landed(self):
        """Attribution, not just presence: an event naming a different hash
        would resolve trailers against someone else's work."""
        self._commit_via_stdin()
        head = self._git("rev-parse", "HEAD")

        self._run_post_tool(f"git commit -F - <<'MSG'\n{_BODY}\nMSG")

        events = self._commit_events()
        self.assertEqual(events[0]["metadata"]["commit_hash"], head)


if __name__ == "__main__":
    unittest.main()

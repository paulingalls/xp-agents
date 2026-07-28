#!/usr/bin/env python3
"""The concern stamp that the close-cycle id marker feeds.

Every concern appended through the CLI while a close is live carries that
close's id, so the merge gate scopes its count on the tag instead of inferring
relevance from the planner-supplied `files` list a concern happens to record.
The marker itself — descriptor, sweep, consume — is pinned in
`test_close_cycle_id_marker.py`.

The property pinned here is **fail closed on every branch**. Absent, empty,
unreadable, a symlink, not a well-formed id, or not scopable to a single
session → stamp nothing, and the concern keeps exactly today's behaviour (the
shipped files-relevance rule in smm_count.py still applies to it). A wrong tag
EXCLUDES a concern from the gate; no tag only leaves it counted.
"""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import marker_names
import markers
from _heartbeat_fixtures import env as no_session_env
from conftest import _MARKERS_PY, _PLUGIN_ROOT, _HookTestCase, run_cli
from event_schema import METADATA_KEY_CLOSE_CYCLE_ID, PRIORITY_INFO

_APPEND_IMPL = _PLUGIN_ROOT / "smm" / "_append_impl.py"

# A 12-hex id of the shape generate_id() mints (secrets.token_hex(6)).
_CYCLE = "aaaa11112222"
_OTHER_CYCLE = "bbbb33334444"


class _AppendTestCase(_HookTestCase):
    """Drive the real appender CLI — the surface every non-hook concern uses.

    In-process assertions would prove nothing here: the whole point is that a
    concern is appended by a DIFFERENT process from the close that is running,
    and the id has to survive that gap.
    """

    def _append(
        self,
        *args: str,
        session_id: str | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> tuple[int, str]:
        """`session_id` names one; `extra_env` can instead blank the whole
        candidate chain, which is the only way to reach a host that discovers no
        session id at all."""
        env = dict(extra_env or {})
        if session_id:
            env["XP_SESSION_ID"] = session_id
        result = run_cli(_APPEND_IMPL, list(args), self.smm_dir, extra_env=env or None)
        return result.returncode, result.stderr

    def _append_concern(
        self,
        *args: str,
        session_id: str | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> dict:
        rc, stderr = self._append(
            "--type",
            "concern",
            "--agent",
            "main",
            "--severity",
            "high",
            "--content",
            "Reviewer Block: the gate must see this",
            *args,
            session_id=session_id,
            extra_env=extra_env,
        )
        self.assertEqual(rc, 0, stderr)
        return self._read_events()[-1]

    def _tag_of(self, event: dict) -> object:
        return (event.get("metadata") or {}).get(METADATA_KEY_CLOSE_CYCLE_ID)

    def _arm(self, content: str, session_id: str | None = None) -> Path:
        """Write the cycle-id marker for a session, verbatim (no validation).

        Resolves the path under the SAME session id the matching `_append` call
        will run with: ambient (the suite's pinned id) by default, or the given
        one, which overrides the top-preference candidate exactly as
        `run_cli`'s extra_env does for the subprocess.
        """
        with patch.dict(os.environ, self._session_env(session_id)):
            path = markers.marker_path(self.smm_dir, markers.CLOSE_CYCLE_ID)
        path.write_text(content, encoding="utf-8")
        return path

    @staticmethod
    def _session_env(session_id: str | None) -> dict[str, str]:
        return {"XP_SESSION_ID": session_id} if session_id else {}


class TestConcernsAreStampedWithTheRunningClose(_AppendTestCase):
    def test_a_concern_raised_during_a_close_carries_that_closes_id(self) -> None:
        self._arm(_CYCLE)
        self.assertEqual(self._tag_of(self._append_concern()), _CYCLE)

    def test_the_tag_does_not_depend_on_the_files_a_concern_records(self) -> None:
        """The point of the story: the gate scopes on the tag, so a concern
        needs no `files` at all — and a `files` list pointing anywhere cannot
        move it into or out of this close."""
        self._arm(_CYCLE)
        event = self._append_concern("--files", json.dumps(["some/other/module.rs"]))
        self.assertEqual(self._tag_of(event), _CYCLE)

    def test_a_trailing_newline_in_the_marker_is_tolerated(self) -> None:
        """`write_text_atomic` and a hand-edited marker differ by exactly this."""
        self._arm(f"{_CYCLE}\n")
        self.assertEqual(self._tag_of(self._append_concern()), _CYCLE)

    def test_only_concerns_are_stamped(self) -> None:
        """Every other event type keeps the shape its own consumers parse. The
        gate counts concerns; nothing else needs the tag, and a status event
        carrying one would be read as a close-cycle record it is not."""
        self._arm(_CYCLE)
        # Each type's own required fields, so a validation refusal cannot be
        # mistaken for "not stamped".
        extra_flags = {
            "status": ("--working-on", "[]"),
            "debt": ("--files", json.dumps(["plugins/xp-agents/smm/smm_count.py"])),
            "question": ("--priority", PRIORITY_INFO),
        }
        for event_type in ("status", "debt", "question", "assumption"):
            with self.subTest(event_type=event_type):
                rc, stderr = self._append(
                    "--type", event_type,
                    "--agent", "main",
                    "--content", f"a {event_type} raised during a close",
                    *extra_flags.get(event_type, ()),
                )  # fmt: skip
                self.assertEqual(rc, 0, stderr)
                self.assertIsNone(self._tag_of(self._read_events()[-1]))


class TestExplicitTagWins(_AppendTestCase):
    """The close reviewers pass their cycle id deliberately (see
    agents/xp-code-reviewer.md and agents/xp-close-reviewer.md). Letting a
    stale or foreign marker overwrite a correct explicit tag would be the
    fail-open choice."""

    def test_an_explicit_cycle_id_survives_a_different_marker(self) -> None:
        self._arm(_OTHER_CYCLE)
        event = self._append_concern(
            "--metadata", json.dumps({METADATA_KEY_CLOSE_CYCLE_ID: _CYCLE})
        )
        self.assertEqual(self._tag_of(event), _CYCLE)

    def test_other_metadata_keys_are_preserved_alongside_the_stamp(self) -> None:
        self._arm(_CYCLE)
        event = self._append_concern(
            "--metadata", json.dumps({"kind": "security", "close_mode": "sprint"})
        )
        self.assertEqual(self._tag_of(event), _CYCLE)
        self.assertEqual((event.get("metadata") or {}).get("kind"), "security")

    def test_a_blank_explicit_tag_is_not_treated_as_a_decision(self) -> None:
        """A blank tag is not a correct tag: `smm_count` excludes any concern
        whose tag is present and unequal to the cycle being gated, so an empty
        string would drop the concern from EVERY close. Replacing it with the
        live id can only move the concern back INTO a count — the fail-closed
        direction."""
        self._arm(_CYCLE)
        event = self._append_concern(
            "--metadata", json.dumps({METADATA_KEY_CLOSE_CYCLE_ID: "   "})
        )
        self.assertEqual(self._tag_of(event), _CYCLE)


class TestStampFailsClosed(_AppendTestCase):
    """Every way the marker can fail to yield an id leaves the concern exactly
    as it is today — unstamped, and counted by the gate under the shipped
    files-relevance rule. A WRONG tag excludes a concern from the gate; no tag
    only leaves it counted."""

    def test_no_marker_at_all_leaves_the_concern_unstamped(self) -> None:
        self.assertIsNone(self._tag_of(self._append_concern()))

    def test_no_marker_is_not_reported_as_a_problem(self) -> None:
        """No close running is the normal case for most of a session."""
        rc, stderr = self._append(
            "--type", "concern",
            "--agent", "main",
            "--severity", "high",
            "--content", "a concern raised with no close in flight",
        )  # fmt: skip
        self.assertEqual(rc, 0, stderr)
        self.assertNotIn(marker_names.CLOSE_CYCLE_ID, stderr)

    def test_an_empty_marker_leaves_the_concern_unstamped(self) -> None:
        """The shape a `markers.py write` CLI call would leave — presence
        without an id. Presence must not be mistaken for identity."""
        self._arm("")
        event = self._append_concern()
        self.assertIsNone(self._tag_of(event))

    def test_a_marker_that_is_not_a_12_hex_id_leaves_it_unstamped(self) -> None:
        for junk in ("not-an-id", "AAAA11112222", "aaaa1111222", "aaaa11112222x", "0"):
            with self.subTest(content=junk):
                self._arm(junk)
                self.assertIsNone(self._tag_of(self._append_concern()))

    def test_an_unreadable_marker_leaves_it_unstamped(self) -> None:
        """A directory where the marker should be: `read_text` raises, and a
        raised read must not become a stamp OR a failed append."""
        with patch.dict(os.environ, no_session_env(XP_SESSION_ID="sess-dir")):
            path = markers.marker_path(self.smm_dir, markers.CLOSE_CYCLE_ID)
        path.mkdir()
        self.assertIsNone(self._tag_of(self._append_concern(session_id="sess-dir")))

    def test_a_symlinked_marker_leaves_it_unstamped(self) -> None:
        """Same refusal `markers.marker_read` makes: a link could name a file
        outside the SMM dir, so it is never read."""
        real = self.smm_dir / "elsewhere.txt"
        real.write_text(_CYCLE)
        with patch.dict(os.environ, no_session_env(XP_SESSION_ID="sess-link")):
            path = markers.marker_path(self.smm_dir, markers.CLOSE_CYCLE_ID)
        path.symlink_to(real)
        self.assertIsNone(self._tag_of(self._append_concern(session_id="sess-link")))

    def test_a_host_that_exports_no_session_id_is_never_stamped(self) -> None:
        """The refusal, not a degradation. With no discoverable session id every
        session on the host addresses the SAME file, so a concern could carry the
        NEIGHBOUR close's id — and `smm_count` excludes a concern whose tag is
        present and unequal to the gated cycle. Unstamped is exactly what such a
        host has today (the files-relevance fallback), so it loses nothing it
        already had; a borrowed tag would cost it the gate."""
        no_id = no_session_env()
        with patch.dict(os.environ, no_id):
            path = markers.marker_path(self.smm_dir, markers.CLOSE_CYCLE_ID)
        path.write_text(_CYCLE, encoding="utf-8")
        self.assertIsNone(self._tag_of(self._append_concern(extra_env=no_id)))

    def test_an_unscopable_marker_says_so_on_stderr(self) -> None:
        """A close DID arm itself here, so the operator has to learn that tagging
        is off on this host — silence is indistinguishable from having tagged."""
        no_id = no_session_env()
        with patch.dict(os.environ, no_id):
            path = markers.marker_path(self.smm_dir, markers.CLOSE_CYCLE_ID)
        path.write_text(_CYCLE, encoding="utf-8")
        rc, stderr = self._append(
            "--type", "concern",
            "--agent", "main",
            "--severity", "high",
            "--content", "a concern raised on a host with no session id",
            extra_env=no_id,
        )  # fmt: skip
        self.assertEqual(rc, 0, stderr)
        self.assertIn(marker_names.CLOSE_CYCLE_ID, stderr)

    def test_no_session_id_and_no_close_stays_quiet(self) -> None:
        """No close running is still the normal state on such a host, and the
        refusal must not narrate itself on every concern appended all session."""
        rc, stderr = self._append(
            "--type", "concern",
            "--agent", "main",
            "--severity", "high",
            "--content", "a concern raised with no close and no session id",
            extra_env=no_session_env(),
        )  # fmt: skip
        self.assertEqual(rc, 0, stderr)
        self.assertNotIn(marker_names.CLOSE_CYCLE_ID, stderr)

    def test_an_unusable_marker_says_so_on_stderr(self) -> None:
        """The one fail-closed branch that must be VISIBLE. A marker that is
        present but unusable means a close armed itself and something went
        wrong afterwards — silently dropping the stamp would look identical to
        no close running. stdout stays the event id alone."""
        self._arm("not-an-id")
        rc, stderr = self._append(
            "--type", "concern",
            "--agent", "main",
            "--severity", "high",
            "--content", "a concern raised against a corrupt marker",
        )  # fmt: skip
        self.assertEqual(rc, 0, stderr)
        self.assertIn(marker_names.CLOSE_CYCLE_ID, stderr)


class TestStampIsScopedInTime(_AppendTestCase):
    def test_a_concern_after_the_close_completed_is_not_stamped(self) -> None:
        """Multiple closes per session is the normal case. If the id outlived
        its close, the next close would mint a DIFFERENT one and the gate would
        then EXCLUDE these concerns — a fail-open worse than the inference this
        story removed. The consume at the end of the close pipeline is what
        closes that window."""
        self._arm(_CYCLE)
        self.assertEqual(self._tag_of(self._append_concern()), _CYCLE)
        result = run_cli(_MARKERS_PY, ["consume", "CLOSE_CYCLE_ID"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(self._tag_of(self._append_concern()))


class TestStampIsScopedPerSession(_AppendTestCase):
    def test_two_concurrent_closes_do_not_borrow_each_others_ids(self) -> None:
        """The SMM dir is shared across worktrees, so two teammates closing at
        once is the case that must hold: each concern carries ITS OWN close's
        id, and neither is tagged with the other's."""
        self._arm(_CYCLE, session_id="sess-a")
        self._arm(_OTHER_CYCLE, session_id="sess-b")
        first = self._append_concern(session_id="sess-a")
        second = self._append_concern(session_id="sess-b")
        self.assertEqual(self._tag_of(first), _CYCLE)
        self.assertEqual(self._tag_of(second), _OTHER_CYCLE)

    def test_a_bystander_session_is_not_tagged_at_all(self) -> None:
        """A third session with no close of its own must not inherit either."""
        self._arm(_CYCLE, session_id="sess-a")
        self.assertIsNone(self._tag_of(self._append_concern(session_id="sess-c")))


class TestHookWrittenConcernsStayUntagged(_HookTestCase):
    """The stamp lives in the CLI's `main()`, NOT in the shared `append_event`.

    Hook-written concerns take the `_common.append_safe` path and stay
    unstamped — a stated limit of this feature, not full coverage. It is also
    load-bearing: `smm_count` carves the transient TDD test-failure concerns
    out of a scoped gate count by their tag being ABSENT, so tagging them
    would re-break a sibling teammate's red test false-aborting a clean close.
    """

    def test_append_safe_does_not_stamp_a_concern(self) -> None:
        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ID, _CYCLE)
        event = _common.make_event(
            _common.CONCERN,
            "bash-post-tool",
            "Test failure: 3 tests failing",
            severity="high",
        )
        _common.append_safe(self.smm_dir, event)
        written = self._read_events()[-1]
        self.assertIsNone((written.get("metadata") or {}).get("close_cycle_id"))


if __name__ == "__main__":
    unittest.main()

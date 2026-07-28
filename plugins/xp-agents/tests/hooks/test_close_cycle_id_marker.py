#!/usr/bin/env python3
"""The close-cycle id marker, and the concern stamp it feeds.

The merge gate counts open high-severity concerns before letting a close
merge. Scoping that count to ONE close cycle used to be inferred from the
`files` a concern recorded — a planner-supplied list, so a stale path
silently produced a wrong EXCLUSION from the gate whose whole purpose is
not to miss a high-severity concern. This marker replaces the inference:
the close that is running writes its own id, and every concern appended
through the CLI while it is live carries that id.

Two properties are load-bearing and pinned here rather than in a consumer:

1. **Session scoping.** The SMM dir is shared across worktrees, so one
   unscoped file is last-writer-wins — which both hides the first close's
   concerns and tags a bystander's concern into a close it has nothing to
   do with. That is worse than the inference it replaces.

2. **Fail closed on every branch.** Absent, empty, unreadable, or not a
   well-formed id → stamp nothing, and the concern keeps exactly today's
   behaviour (the shipped files-relevance rule in smm_count.py still
   applies to it). A wrong tag EXCLUDES a concern from the gate; no tag
   only leaves it counted.
"""

import hashlib
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
import hook_liveness
import marker_names
import markers
import session_markers
import session_scope
from _heartbeat_fixtures import env as no_session_env
from conftest import _MARKERS_PY, _PLUGIN_ROOT, _HookTestCase, run_cli
from event_schema import METADATA_KEY_CLOSE_CYCLE_ID, PRIORITY_INFO

_APPEND_IMPL = _PLUGIN_ROOT / "smm" / "_append_impl.py"

# A 12-hex id of the shape generate_id() mints (secrets.token_hex(6)).
_CYCLE = "aaaa11112222"
_OTHER_CYCLE = "bbbb33334444"


def _suffix_for(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:12]


class TestMarkerDefinition(unittest.TestCase):
    """The descriptor itself: text content, and a name one session owns."""

    def test_marker_name_comes_from_marker_names(self) -> None:
        """`smm/marker_names.py` is the only home a filename may have — it is
        the module the appender's pre-write path can reach without importing
        `scripts/`."""
        self.assertEqual(markers.CLOSE_CYCLE_ID.name, marker_names.CLOSE_CYCLE_ID)

    def test_marker_holds_text_not_json(self) -> None:
        """The id is the whole content, and `write_marker` (the shell wrapper
        every close preload uses) passes a string — a json marker would raise
        TypeError inside a `2>/dev/null || true` wrapper and vanish."""
        self.assertEqual(markers.CLOSE_CYCLE_ID.content_type, "text")

    def test_marker_is_session_scoped(self) -> None:
        self.assertTrue(markers.CLOSE_CYCLE_ID.session_scoped)

    def test_filename_carries_the_session_digest(self) -> None:
        with patch.dict(os.environ, no_session_env(XP_SESSION_ID="sess-a")):
            self.assertEqual(
                markers.CLOSE_CYCLE_ID.filename(),
                f"{marker_names.CLOSE_CYCLE_ID}-{_suffix_for('sess-a')}",
            )

    def test_two_sessions_get_two_files(self) -> None:
        """The concurrency property: two closes in two worktrees are two
        sessions, and neither may read or clobber the other's id."""
        with patch.dict(os.environ, no_session_env(XP_SESSION_ID="sess-a")):
            first = markers.CLOSE_CYCLE_ID.filename()
        with patch.dict(os.environ, no_session_env(XP_SESSION_ID="sess-b")):
            second = markers.CLOSE_CYCLE_ID.filename()
        self.assertNotEqual(first, second)

    def test_a_session_id_never_reaches_the_filename(self) -> None:
        """A session id is untrusted input that would otherwise steer a path,
        so it is hashed rather than escaped — the same rule the heartbeat and
        the housekeeping record use."""
        with patch.dict(os.environ, no_session_env(XP_SESSION_ID="../../etc/passwd\n")):
            self.assertRegex(
                markers.CLOSE_CYCLE_ID.filename(),
                rf"^{marker_names.CLOSE_CYCLE_ID}-[0-9a-f]{{12}}$",
            )

    def test_no_discoverable_session_id_falls_back_to_the_shared_name(self) -> None:
        """Same degradation `session_markers.session_marker` documents: a host
        exposing no id gets the unsuffixed marker rather than a file keyed on
        the hash of a value no reader addresses."""
        with patch.dict(os.environ, no_session_env()):
            self.assertEqual(
                markers.CLOSE_CYCLE_ID.filename(), marker_names.CLOSE_CYCLE_ID
            )

    def test_scoping_is_the_session_marker_rule_itself(self) -> None:
        """Not "the same shape" — the same code. `session_markers.session_marker`
        builds on `session_scope.scoped_name`, so the hashing rule cannot drift
        between the heartbeat's marker and this one."""
        for session_id in ("sess-a", "", None, "  "):
            with self.subTest(session_id=session_id):
                self.assertEqual(
                    session_markers.session_marker(".m", session_id).name,
                    session_scope.scoped_name(".m", session_id),
                )

    def test_env_candidate_chain_has_one_home(self) -> None:
        """The appender's pre-write path cannot import `scripts/`, so the chain
        lives in `smm/session_scope.py` and hook_liveness reads it from there.
        Two copies would let a new host var be taught to the heartbeat while
        this marker silently degraded to the shared name."""
        self.assertIs(
            hook_liveness.SESSION_ID_ENV_CANDIDATES,
            session_scope.SESSION_ID_ENV_CANDIDATES,
        )


class TestSessionStartSweep(_HookTestCase):
    """A stale id must never outlive its session.

    An id left behind would tag later concerns with a dead close, and because
    the next close mints a DIFFERENT id the gate would then exclude them — a
    fresh fail-open worse than the inference this story removed.
    """

    def test_marker_is_in_the_stale_session_set(self) -> None:
        self.assertIn(markers.CLOSE_CYCLE_ID, session_markers._STALE_SESSION_MARKERS)

    def test_sweep_clears_this_sessions_marker(self) -> None:
        with patch.dict(os.environ, no_session_env(XP_SESSION_ID="sess-a")):
            markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ID, _CYCLE)
            session_markers.sweep_stale_session_markers(self.smm_dir)
            self.assertFalse(
                markers.marker_exists(self.smm_dir, markers.CLOSE_CYCLE_ID)
            )

    def test_sweep_clears_the_shared_no_id_marker(self) -> None:
        """The leg that actually leaks: with no discoverable session id both the
        old and the new session address the SAME file, so scoping cannot
        separate them and only the sweep can."""
        with patch.dict(os.environ, no_session_env()):
            markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ID, _CYCLE)
            session_markers.sweep_stale_session_markers(self.smm_dir)
            self.assertFalse(
                markers.marker_exists(self.smm_dir, markers.CLOSE_CYCLE_ID)
            )

    def test_sweep_leaves_another_sessions_marker_alone(self) -> None:
        """Unlike every other marker in that set, this one CAN belong to a live
        session: a teammate's close in another worktree against the shared SMM.
        Consuming it would untag that close's concerns mid-flight."""
        with patch.dict(os.environ, no_session_env(XP_SESSION_ID="sess-other")):
            markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ID, _OTHER_CYCLE)
            other = markers.marker_path(self.smm_dir, markers.CLOSE_CYCLE_ID)
        with patch.dict(os.environ, no_session_env(XP_SESSION_ID="sess-mine")):
            session_markers.sweep_stale_session_markers(self.smm_dir)
        self.assertTrue(other.is_file())


class TestMarkerCli(_HookTestCase):
    """The close pipeline's consume step drives the marker through this CLI."""

    def test_marker_is_cli_allowlisted(self) -> None:
        self.assertIn("CLOSE_CYCLE_ID", markers._CLI_ALLOWLIST)

    def test_cli_consume_removes_this_sessions_marker(self) -> None:
        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ID, _CYCLE)
        path = markers.marker_path(self.smm_dir, markers.CLOSE_CYCLE_ID)
        self.assertTrue(path.is_file())
        result = run_cli(_MARKERS_PY, ["consume", "CLOSE_CYCLE_ID"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(path.is_file())

    def test_cli_consume_of_an_absent_marker_is_quiet(self) -> None:
        """The consume runs on both the merge and the abort path, and may run
        twice — it must never turn a finished close into an error."""
        result = run_cli(_MARKERS_PY, ["consume", "CLOSE_CYCLE_ID"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)


class _AppendTestCase(_HookTestCase):
    """Drive the real appender CLI — the surface every non-hook concern uses.

    In-process assertions would prove nothing here: the whole point is that a
    concern is appended by a DIFFERENT process from the close that is running,
    and the id has to survive that gap.
    """

    def _append(self, *args: str, session_id: str | None = None) -> tuple[int, str]:
        extra_env = {"XP_SESSION_ID": session_id} if session_id else None
        result = run_cli(_APPEND_IMPL, list(args), self.smm_dir, extra_env=extra_env)
        return result.returncode, result.stderr

    def _append_concern(self, *args: str, session_id: str | None = None) -> dict:
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

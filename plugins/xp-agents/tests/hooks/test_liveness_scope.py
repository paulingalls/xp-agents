#!/usr/bin/env python3
"""What of the liveness machinery is load-bearing, measured rather than asserted.

The story this file belongs to deletes the VERDICT reader — `check_liveness`,
its `Liveness` result, its reason-building helpers and the `status` CLI — and
keeps the HEARTBEAT primitive. The split is not a preference: the reader had
exactly one consumer and story-020 measured that consumer inert, while the
primitive has the two below, and neither is.

**The proof of a keep is a CONSUMER's behaviour, never a name.** A test that
lists survivors passes trivially and reddens only on an import error — the
class story-017 exists to stop. So each survivor here is proved by breaking it
and watching a real consumer change its answer.

The consumers, and why each is reachable:

- `coordination._session_is_live`, reached from `has_active_teammates` — the
  Stop gates ask it whether another agent may still be writing. Its docstring
  forbids a second liveness implementation in so many words.
- `close_cycle_abandonment.owner_session_is_live` — whether a close cycle's
  owning session is still running, which is what replaced an age threshold that
  could not be both long enough for a slow live close and short enough for a
  dead one.

Both are the daily solo path, which is why the story's original AC3 ("no
liveness machinery runs on behalf of the daily solo path") was unsatisfiable
and had to be amended.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import close_cycle_abandonment
import hook_liveness
from conftest import _PLUGIN_ROOT, _HookTestCase

_OWNER = "owner-session-id"

# Where a shipped path could still read a verdict. `tests/` is excluded on
# purpose: a test may name the deleted symbol while describing its removal, and
# this asserts about what SHIPS.
_SHIPPED_DIRS = ("scripts", "skills", "smm", "hooks", "agents")

# The verdict API this story removes. Named here rather than inline so the two
# directions below — nothing shipped reads it, and the primitive survives — read
# off one list.
_DELETED_VERDICT_NAMES = ("check_liveness", "EXIT_NOT_LIVE", "UNDETERMINED_CODES")


class TestTheHeartbeatPrimitiveIsLoadBearing(_HookTestCase):
    """Break the writer; a real consumer must change its answer.

    This is the whole argument for keeping `write_heartbeat` and
    `heartbeat_marker` while the verdict machinery goes. If neither consumer
    moves when the writer stops writing, the primitive is dead too and the
    story's keep-list is wrong.
    """

    def test_close_cycle_abandonment_reads_a_live_owner(self):
        """The baseline the mutation below is measured against."""
        hook_liveness.write_heartbeat(self.smm_dir, session_id=_OWNER)
        self.assertIs(
            close_cycle_abandonment.owner_session_is_live(self.smm_dir, _OWNER),
            True,
        )

    def test_the_owner_is_unreadable_when_the_writer_never_ran(self):
        """The mutation: the same call, with the write withheld.

        Withheld by NOT MAKING IT — a `patch.object` on `write_heartbeat` would
        only stub the name this test calls itself, which is the same thing said
        less honestly. Nothing else in this method's path writes a heartbeat.

        With nothing written there is no marker to age, so the answer is None —
        "cannot tell" — not False. The distinction matters to the caller:
        `owner_session_is_live` returning None sends it to the age fallback,
        while False would record an abandonment against a live close.
        """
        self.assertIsNone(
            close_cycle_abandonment.owner_session_is_live(self.smm_dir, _OWNER),
            "the abandonment detector no longer depends on the heartbeat, so "
            "this story's keep-list has one entry too many",
        )

    def test_coordination_reads_a_live_session(self):
        """The second consumer, reached in production through
        `has_active_teammates`. Called directly here because the gate's own
        answer folds in entry age and own-session filtering, which would let a
        broken heartbeat read as a passing gate for an unrelated reason."""
        import coordination

        hook_liveness.write_heartbeat(self.smm_dir, session_id=_OWNER)
        self.assertIs(coordination._session_is_live(self.smm_dir, _OWNER), True)

    def test_coordination_is_undecided_when_the_writer_never_ran(self):
        """The same mutation against the second consumer — see above for why
        the write is withheld rather than stubbed."""
        import coordination

        self.assertIsNone(
            coordination._session_is_live(self.smm_dir, _OWNER),
            "the Stop-gate conflict check no longer depends on the heartbeat",
        )


class TestNoShippedPathReadsAVerdict(unittest.TestCase):
    """Red before the deletion, green after — the story's AC2 in one assertion.

    Scoped to shipped directories. A `tests/` hit is not a violation: a test
    may legitimately name a removed symbol while asserting it is gone.
    """

    def _shipped_files(self) -> list[Path]:
        out: list[Path] = []
        for sub in _SHIPPED_DIRS:
            for path in (_PLUGIN_ROOT / sub).rglob("*"):
                if path.is_file() and path.suffix in {".py", ".sh", ".md", ".json"}:
                    out.append(path)
        return out

    def test_the_verdict_api_has_no_shipped_reader(self):
        offenders: list[str] = []
        for path in self._shipped_files():
            text = path.read_text(encoding="utf-8", errors="replace")
            for name in _DELETED_VERDICT_NAMES:
                if name in text:
                    offenders.append(f"{path.relative_to(_PLUGIN_ROOT)}: {name}")
        self.assertEqual(
            sorted(offenders),
            [],
            "a shipped path still reads the liveness verdict API:\n"
            + "\n".join(sorted(offenders)),
        )

    def test_the_population_is_not_empty(self):
        """Story-017's rule: a scan of nothing reads as success. If the shipped
        tree stops being walked, the assertion above passes for the wrong
        reason."""
        self.assertGreater(len(self._shipped_files()), 100)


class TestThePrimitiveSurvives(unittest.TestCase):
    """The other direction. Deleting the reader must not take the writer with
    it, and the population check above cannot notice an over-deletion."""

    def test_the_kept_names_are_still_importable(self):
        for name in (
            "write_heartbeat",
            "heartbeat_marker",
            "resolve_session_id",
            "payload_session_id",
            "SESSION_ID_ENV_CANDIDATES",
            "STALE_AFTER_SECONDS",
            "FUTURE_SKEW_GRACE_SECONDS",
        ):
            with self.subTest(name=name):
                self.assertTrue(
                    hasattr(hook_liveness, name),
                    f"{name} is on the keep-list but no longer exists — a "
                    "consumer test above should have caught this first",
                )

    def test_the_marker_is_still_keyed_on_the_session_and_still_hashed(self):
        """The record is read by two modules this story does not touch, so its
        addressing is an interface, not an implementation detail.

        Two properties, both load-bearing. Distinct sessions must not collapse
        onto one file — that is what lets a detector in another window ask
        about a specific owner rather than about anyone. And the id must not
        appear verbatim: `session_markers.session_marker` HASHES it rather than
        sanitising it, because the id is untrusted input that ends up in a
        filename.
        """
        one = hook_liveness.heartbeat_marker("session-one").name
        two = hook_liveness.heartbeat_marker("session-two").name
        self.assertNotEqual(one, two)
        self.assertNotIn("session-one", one)
        self.assertNotEqual(one, hook_liveness.heartbeat_marker(None).name)


if __name__ == "__main__":
    unittest.main()

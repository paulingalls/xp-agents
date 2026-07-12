#!/usr/bin/env python3
"""Tests for the sprint CLI's `create` subcommand and the re-slice preserve.

Split out of test_sprint_cli_mutate.py (which sat at the 500-line cap) when
story-005 added the re-slice suite. TestCreateCommand moved here unchanged;
the routing-contract class stays there because it spans create + add-story +
edit-story as one cohesive contract.

The re-slice: `create` writes stdin verbatim, and the /xp-sprint-start payload
carries no branch_name at either level — so re-running create on the SAME
sprint (to rewrite a goal or drop a story, the only tool for either) used to
erase the sprint's branch_name and every story's. These tests pin the preserve
and, just as importantly, its key: sprint_id, not mere file existence.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import (
    _SMMTestCase,
    run_cli,
)
from conftest import (
    make_sprint_dict as _make_sprint,
)
from conftest import (
    make_story_dict as _make_story,
)

_CLI = Path(__file__).parent.parent.parent / "smm" / "sprint_cli.py"

_SPRINT_BRANCH = "paul/sprint-001-build-auth"
_STORY_1_BRANCH = "paul/story-001-user-registration"
_STORY_2_BRANCH = "paul/story-002-login"


class TestCreateCommand(_SMMTestCase):
    def test_create(self):
        sprint = _make_sprint(goal="New Sprint")
        result = run_cli(_CLI, ["create"], self.smm_dir, json.dumps(sprint))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.smm_dir / "sprint.json").exists())

    def test_create_invalid(self):
        result = run_cli(_CLI, ["create"], self.smm_dir, '{"bad": "data"}')
        self.assertNotEqual(result.returncode, 0)


class TestCreateReslicePreservesBranches(_SMMTestCase):
    """A same-id re-create is a re-slice: it must keep the branches it isn't
    being asked to change. A different id is the rollover: it must keep none."""

    def _recorded(self, sprint_id: str = "sprint-001") -> dict:
        """Seed sprint.json as an in-flight sprint: branch recorded at the
        sprint level and on each story (as create_*_branch records them)."""
        sprint = _make_sprint(
            sprint_id=sprint_id,
            goal="Build auth",
            branch_name=_SPRINT_BRANCH,
            stories=[
                _make_story(
                    id="story-001",
                    status="in-progress",
                    branch_name=_STORY_1_BRANCH,
                ),
                _make_story(
                    id="story-002",
                    status="in-progress",
                    branch_name=_STORY_2_BRANCH,
                    file_domain=["src/login.py — new module"],
                ),
            ],
        )
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        return sprint

    def _incoming(self, **overrides) -> dict:
        """The /xp-sprint-start payload: no branch_name at either level."""
        payload = {
            "sprint_id": "sprint-001",
            "goal": "Rewritten goal",
            "stories": [
                _make_story(id="story-001", status="ready"),
                _make_story(
                    id="story-002",
                    status="ready",
                    file_domain=["src/login.py — new module"],
                ),
            ],
        }
        payload.update(overrides)
        return _make_sprint(**payload)

    def _create(self, payload: dict):
        return run_cli(_CLI, ["create"], self.smm_dir, json.dumps(payload))

    def _loaded(self) -> dict:
        return json.loads((self.smm_dir / "sprint.json").read_text())

    def test_same_sprint_id_carries_every_branch_name(self):
        self._recorded()
        result = self._create(self._incoming())
        self.assertEqual(result.returncode, 0, result.stderr)

        loaded = self._loaded()
        self.assertEqual(loaded["goal"], "Rewritten goal", "re-slice must apply")
        self.assertEqual(loaded["branch_name"], _SPRINT_BRANCH)
        by_id = {s["id"]: s for s in loaded["stories"]}
        self.assertEqual(by_id["story-001"]["branch_name"], _STORY_1_BRANCH)
        self.assertEqual(by_id["story-002"]["branch_name"], _STORY_2_BRANCH)

    def test_reslice_is_reported_not_silent(self):
        self._recorded()
        result = self._create(self._incoming())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("sprint-001", result.stderr)
        self.assertIn(_SPRINT_BRANCH, result.stderr)
        self.assertIn(_STORY_1_BRANCH, result.stderr)

    def test_different_sprint_id_carries_nothing(self):
        """The rollover control. next_sprint_id increments over the CURRENT
        sprint.json in place, and /xp-sprint-start RENUMBERS the stories it
        carries forward — so a branch carried across ids would be a lie. A
        preserve keyed on mere file-existence would fail this test."""
        self._recorded()
        result = self._create(self._incoming(sprint_id="sprint-002"))
        self.assertEqual(result.returncode, 0, result.stderr)

        loaded = self._loaded()
        self.assertIsNone(loaded.get("branch_name"))
        for story in loaded["stories"]:
            self.assertIsNone(
                story.get("branch_name"),
                f"{story['id']} carried a branch across a sprint rollover",
            )

    def test_incoming_sprint_branch_name_wins(self):
        """Fill-when-absent, never clobber — else a deliberate rename is
        silently reverted to the recorded name."""
        self._recorded()
        result = self._create(self._incoming(branch_name="paul/sprint-001-renamed"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._loaded()["branch_name"], "paul/sprint-001-renamed")

    def test_incoming_story_branch_name_wins(self):
        self._recorded()
        payload = self._incoming()
        payload["stories"][0]["branch_name"] = "paul/story-001-renamed"
        result = self._create(payload)
        self.assertEqual(result.returncode, 0, result.stderr)

        by_id = {s["id"]: s for s in self._loaded()["stories"]}
        self.assertEqual(by_id["story-001"]["branch_name"], "paul/story-001-renamed")
        self.assertEqual(
            by_id["story-002"]["branch_name"],
            _STORY_2_BRANCH,
            "clobber-guard on one story must not suppress the carry on another",
        )

    def test_dropped_story_does_not_resurrect(self):
        """A story the re-slice drops loses its branch_name with it. Intended:
        the preserve carries branches for SURVIVING stories, it does not
        reinstate the old story list."""
        self._recorded()
        payload = self._incoming()
        payload["stories"] = [payload["stories"][0]]  # drop story-002
        result = self._create(payload)
        self.assertEqual(result.returncode, 0, result.stderr)

        loaded = self._loaded()
        self.assertEqual([s["id"] for s in loaded["stories"]], ["story-001"])
        self.assertEqual(loaded["stories"][0]["branch_name"], _STORY_1_BRANCH)

    def test_no_traceback_on_happy_path(self):
        self._recorded()
        result = self._create(self._incoming())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Traceback", result.stderr)


class TestCreateSurvivesUnreadableSprint(_SMMTestCase):
    """`create` is the repair path for a sprint.json that can no longer be
    loaded — it is the only subcommand that does not need to read the file
    first. One case per unusable-content cause load_sprint reports as
    SprintCorruptError (undecodable bytes, malformed JSON, schema-invalid), so
    an unguarded — or under-guarded — load in the preserve would turn the only
    repair tool into a traceback. Guarded: carry nothing, warn, still write."""

    def _fresh_payload(self) -> dict:
        return _make_sprint(sprint_id="sprint-001", goal="Recovered")

    def _assert_repaired(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        # Pin the actual warning, not just "stderr is non-empty" — otherwise an
        # unrelated line on stderr would let a silently-swallowed read pass.
        self.assertIn("could not be read", result.stderr)
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(loaded["goal"], "Recovered")
        self.assertIsNone(loaded.get("branch_name"))

    def test_malformed_json_sprint_still_creates(self):
        (self.smm_dir / "sprint.json").write_text('{"sprint_id": "sprint-001",')
        self._assert_repaired(
            run_cli(_CLI, ["create"], self.smm_dir, json.dumps(self._fresh_payload()))
        )

    def test_schema_stale_sprint_still_creates(self):
        """Parses fine, fails today's schema — e.g. a file written before a
        field was added. Distinct from malformed JSON: same raise, different
        cause, and this is the one a real repo actually hits."""
        (self.smm_dir / "sprint.json").write_text(
            json.dumps({"sprint_id": "sprint-001", "goal": "written by an old schema"})
        )
        self._assert_repaired(
            run_cli(_CLI, ["create"], self.smm_dir, json.dumps(self._fresh_payload()))
        )

    def test_byte_corrupt_sprint_still_creates(self):
        """The third unusable-content cause: bytes that are not even UTF-8 (a
        half-flushed or disk-mangled write). Neither the preserve's guard nor
        sprint_save's fail-open baseline can see it unless load_sprint reports
        it as corruption — a raw UnicodeDecodeError slips past BOTH `except`
        clauses and tracebacks the only tool that can overwrite the bad file."""
        (self.smm_dir / "sprint.json").write_bytes(
            b'{"sprint_id": "sprint-001", "goal": "\xff\xfe"}'
        )
        self._assert_repaired(
            run_cli(_CLI, ["create"], self.smm_dir, json.dumps(self._fresh_payload()))
        )


class TestUnreadableBaselineDoesNotWeakenCollisionGate(_SMMTestCase):
    """The load-bearing safety claim of failing the collision baseline open.

    Losing the baseline must make the file_domain gate STRICTER, never laxer:
    with nothing trustworthy on disk, every collision in the payload is
    attributed to this write. A fail-open that also excused collisions would
    turn `create` into a way to launder a colliding sprint past the gate by
    corrupting sprint.json first.
    """

    def _colliding_payload(self) -> dict:
        return _make_sprint(
            sprint_id="sprint-001",
            stories=[
                _make_story(id="story-001", file_domain=["src/shared.py — auth"]),
                _make_story(id="story-002", file_domain=["src/shared.py — login"]),
            ],
        )

    def test_colliding_payload_still_rejected_over_corrupt_baseline(self):
        corrupt = '{"sprint_id": "sprint-001",'
        (self.smm_dir / "sprint.json").write_text(corrupt)
        result = self._create_colliding()
        self.assertEqual(
            (self.smm_dir / "sprint.json").read_text(),
            corrupt,
            "a rejected create must not write",
        )
        self.assertNotEqual(result.returncode, 0, "collision must still block")
        self.assertIn("src/shared.py", result.stderr)

    def test_colliding_payload_still_rejected_with_no_baseline(self):
        """Control: same verdict when there is no sprint.json at all. Pins that
        the corrupt case degrades to exactly the first-create branch."""
        result = self._create_colliding()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("src/shared.py", result.stderr)
        self.assertFalse((self.smm_dir / "sprint.json").exists())

    def _create_colliding(self):
        return run_cli(
            _CLI, ["create"], self.smm_dir, json.dumps(self._colliding_payload())
        )


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Tests for sprint_save sister-test integration: layout resolution + run/save.

Extracted from tests/hooks/test_sprint_start.py in sprint-108 M1 (story-001),
and carved out of test_sprint_save.py to keep both files under the 500-line cap.

Split further (over the 500-line cap again) into:
- test_sprint_save_sisters_autoinclude.py (this file): _auto_include_sister_tests
  direct-argument behavior (no git project required) plus the collision-refusal
  tests for create/add-story that share its fixture style.
- test_sprint_save_sisters_layout.py: _resolve_layout + run()/save() integration,
  which DO need a real git project (_make_git_project).
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import sister_tests  # pyright: ignore[reportMissingImports]
import sprint_save
from conftest import _SMMTestCase


class TestAutoIncludeSisterTests(_SMMTestCase):
    """_auto_include_sister_tests appends discovered sister-test paths to
    each story's file_domain, dedups against existing entries, and skips
    entries already marked as sisters (prevents sister-of-sister)."""

    def setUp(self):
        super().setUp()

        self._tmp = Path(tempfile.mkdtemp(prefix="story-004-"))
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(self._tmp)]))
        self.mod = sprint_save
        self.sister_tests = sister_tests

    def _make_layout(self, convention: str = "python_pytest"):
        return self.sister_tests.BUILTIN_LAYOUTS[convention]

    def _write_file(self, rel: str, content: str = "") -> Path:
        p = self._tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return p

    def test_python_pytest_layout_appends_existing_sister(self):
        self._write_file("src/foo.py", "x = 1")
        self._write_file("tests/test_foo.py", "def test_x(): pass")
        data = {"stories": [{"id": "s1", "file_domain": ["src/foo.py — impl"]}]}
        self.mod._auto_include_sister_tests(data, self._make_layout(), self._tmp)
        self.assertIn(
            "tests/test_foo.py — sister test for src/foo.py",
            data["stories"][0]["file_domain"],
        )

    def test_no_sister_on_disk_is_noop(self):
        self._write_file("src/foo.py", "x = 1")
        data = {"stories": [{"id": "s1", "file_domain": ["src/foo.py — impl"]}]}
        before = list(data["stories"][0]["file_domain"])
        self.mod._auto_include_sister_tests(data, self._make_layout(), self._tmp)
        self.assertEqual(data["stories"][0]["file_domain"], before)

    def test_dedups_existing_manual_sister(self):
        self._write_file("src/foo.py", "x = 1")
        self._write_file("tests/test_foo.py", "def test_x(): pass")
        data = {
            "stories": [
                {
                    "id": "s1",
                    "file_domain": [
                        "src/foo.py — impl",
                        "tests/test_foo.py — manual",
                    ],
                }
            ]
        }
        self.mod._auto_include_sister_tests(data, self._make_layout(), self._tmp)
        paths = [e.split(" — ")[0] for e in data["stories"][0]["file_domain"]]
        self.assertEqual(paths.count("tests/test_foo.py"), 1)

    def test_skips_sister_marked_entries(self):
        """An entry whose note is 'sister test for X' must NOT be re-walked
        (sister-of-sister discovery would expand file_domain unboundedly)."""
        self._write_file("src/foo.py", "x = 1")
        self._write_file("tests/test_foo.py", "def test_x(): pass")
        self._write_file("tests/test_test_foo.py", "def test_meta(): pass")
        data = {
            "stories": [
                {
                    "id": "s1",
                    "file_domain": [
                        "src/foo.py — impl",
                        "tests/test_foo.py — sister test for src/foo.py",
                    ],
                }
            ]
        }
        self.mod._auto_include_sister_tests(data, self._make_layout(), self._tmp)
        for entry in data["stories"][0]["file_domain"]:
            self.assertNotIn(
                "test_test_foo.py",
                entry,
                f"sister-of-sister leaked: {entry}",
            )


class TestAutoIncludeRespectsOtherStoriesClaims(_SMMTestCase):
    """The sister globber must never hand story A a file story B declared.

    Its dedup set used to reset per story, so any prefix-y naming scheme
    (foo.py / foo_tools.py, each with its own sister) let a stem match pull
    another story's test into this story's domain — silently.
    """

    def setUp(self):
        super().setUp()
        self._tmp = Path(tempfile.mkdtemp(prefix="story-002-"))
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(self._tmp)]))
        self.mod = sprint_save

    def _layout(self):
        return sister_tests.BUILTIN_LAYOUTS["python_pytest"]

    def _write(self, rel: str) -> None:
        p = self._tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x = 1")

    def _domains(self, data: dict) -> list[list[str]]:
        return [s["file_domain"] for s in data["stories"]]

    def test_sister_not_injected_when_another_story_authored_it(self):
        """The divineruin sprint-040 repro: `test_foo*` matches the sibling
        source's sister, which another story explicitly authored."""
        self._write("src/foo.py")
        self._write("src/foo_tools.py")
        self._write("tests/test_foo.py")
        self._write("tests/test_foo_tools.py")
        data = {
            "stories": [
                {
                    "id": "story-A",
                    "file_domain": [
                        "src/foo.py — impl",
                        "tests/test_foo.py — its test",
                    ],
                },
                {
                    "id": "story-B",
                    "file_domain": [
                        "src/foo_tools.py — tools",
                        "tests/test_foo_tools.py — its test",
                    ],
                },
            ]
        }
        self.mod._auto_include_sister_tests(data, self._layout(), self._tmp)
        a_domain, b_domain = self._domains(data)
        self.assertNotIn(
            "tests/test_foo_tools.py",
            " ".join(a_domain),
            f"story-B's authored test leaked into story-A: {a_domain}",
        )
        self.assertNotIn("tests/test_foo.py", " ".join(b_domain))

    def test_contested_sister_no_story_authored_goes_to_both(self):
        """When NO story authored the sister but a stem match resolves it for
        two stories, it must land in BOTH — not be silently awarded to the
        first in list order. Picking a single winner can deny the sister to the
        story whose source actually covers it (finding 2: story-B commits its
        own test and trips out-of-domain drift). Injecting into both lets the
        collision gate surface it as the tool error it is, which is the remedy
        the gate's message prints.
        """
        self._write("src/foo.py")
        self._write("src/foo_tools.py")
        self._write("tests/test_foo_tools.py")
        data = {
            "stories": [
                {"id": "story-A", "file_domain": ["src/foo.py — impl"]},
                {"id": "story-B", "file_domain": ["src/foo_tools.py — tools"]},
            ]
        }
        self.mod._auto_include_sister_tests(data, self._layout(), self._tmp)
        a_domain, b_domain = self._domains(data)
        claimed_by_a = any("tests/test_foo_tools.py" in e for e in a_domain)
        claimed_by_b = any("tests/test_foo_tools.py" in e for e in b_domain)
        self.assertTrue(
            claimed_by_a and claimed_by_b,
            "an unauthored contested sister must reach both claiming stories "
            f"so the collision gate can catch it; got A={a_domain} B={b_domain}",
        )

    def test_idempotent_across_reruns_on_expanded_data(self):
        """Sister entries persist to sprint.json and re-feed run() on the next
        add-story. A second pass over already-expanded data must be a no-op —
        seeding `claimed` from authored paths only must not re-append a sister
        already present in the story's own domain."""
        self._write("src/foo.py")
        self._write("tests/test_foo.py")
        data = {"stories": [{"id": "story-A", "file_domain": ["src/foo.py — impl"]}]}
        self.mod._auto_include_sister_tests(data, self._layout(), self._tmp)
        after_first = list(data["stories"][0]["file_domain"])
        self.mod._auto_include_sister_tests(data, self._layout(), self._tmp)
        self.assertEqual(
            data["stories"][0]["file_domain"],
            after_first,
            "second pass on expanded data must not duplicate the sister entry",
        )

    def test_single_story_discovery_still_appends_its_sister(self):
        """Guard against 'fixing' the leak by disabling auto-include."""
        self._write("src/foo.py")
        self._write("tests/test_foo.py")
        data = {"stories": [{"id": "story-A", "file_domain": ["src/foo.py — impl"]}]}
        self.mod._auto_include_sister_tests(data, self._layout(), self._tmp)
        self.assertIn(
            "tests/test_foo.py — sister test for src/foo.py",
            data["stories"][0]["file_domain"],
        )


class TestCreateRefusesCollidingSprintE2E(_SMMTestCase):
    """AC5: drive the real CLI as a subprocess. _cmd_create already maps
    ValueError to rc 1, so raising from run() covers create and add-story
    without touching sprint_cli_mutate.py."""

    _CLI = Path(__file__).parent.parent.parent / "smm" / "sprint_cli.py"

    def _sprint(self, dependencies):
        from conftest import _s

        a = _s("story-001", "a", "ready")
        a["file_domain"] = ["src/shared.py — mine"]
        b = _s("story-002", "b", "ready")
        b["file_domain"] = ["src/shared.py — also mine"]
        b["dependencies"] = dependencies
        return {
            "sprint_id": "sprint-001",
            "goal": "t",
            "started": "2026-04-01",
            "milestone": "",
            "stories": [a, b],
        }

    def test_create_exits_nonzero_and_leaves_sprint_json_unwritten(self):
        from conftest import run_cli

        result = run_cli(
            self._CLI, ["create"], self.smm_dir, json.dumps(self._sprint([]))
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("src/shared.py", result.stderr)
        self.assertIn("story-001", result.stderr)
        self.assertIn("story-002", result.stderr)
        self.assertFalse((self.smm_dir / "sprint.json").exists())

    def test_create_accepts_the_same_sprint_when_the_stories_are_dependent(self):
        from conftest import run_cli

        result = run_cli(
            self._CLI,
            ["create"],
            self.smm_dir,
            json.dumps(self._sprint(["story-001"])),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.smm_dir / "sprint.json").exists())


class TestAddStoryNotBlockedByPreexistingCollision(_SMMTestCase):
    """Finding 3: a collision already on disk between two OTHER stories
    (persisted via an edit-story flip that bypasses run()) must not refuse a
    later add-story of a disjoint, unique-id story — the 'a clean new story
    can always be added' guarantee. run() blocks only collisions it introduces.
    """

    def _colliding_sprint(self):
        from conftest import _s

        a = _s("story-001", "a", "ready")
        a["file_domain"] = ["src/shared.py — mine"]
        b = _s("story-002", "b", "ready")
        b["file_domain"] = ["src/shared.py — also mine"]
        return {
            "sprint_id": "sprint-001",
            "goal": "t",
            "started": "2026-04-01",
            "milestone": "",
            "stories": [a, b],
        }

    def test_disjoint_add_story_succeeds_despite_prior_collision(self):
        import sprint_store
        from conftest import _s

        # Persist the colliding sprint directly — the edit-story bypass that
        # side-steps run()'s gate (store.save_sprint has no collision check).
        data = self._colliding_sprint()
        sprint_store.save_sprint(self.smm_dir, data)

        c = _s("story-003", "c", "ready")
        c["file_domain"] = ["src/other.py — separate"]
        data["stories"].append(c)
        # Must NOT raise: the 001/002 collision is not this write's fault.
        sprint_save.run(data, self.smm_dir)

        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertIn("story-003", [s["id"] for s in loaded["stories"]])

    def test_add_story_that_itself_collides_is_still_refused(self):
        import sprint_store
        from conftest import _s

        data = self._colliding_sprint()
        sprint_store.save_sprint(self.smm_dir, data)

        c = _s("story-003", "c", "ready")
        c["file_domain"] = ["src/shared.py — new claimant"]
        data["stories"].append(c)
        with self.assertRaises(ValueError) as ctx:
            sprint_save.run(data, self.smm_dir)
        self.assertIn("story-003", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Tests for sprint_cli.py: CLI wrapper for sprint operations."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _branching_fixtures import GIT_ENV, init_repo
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


class TestExistsCommand(_SMMTestCase):
    def test_exists(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = run_cli(_CLI, ["exists"], self.smm_dir)
        self.assertEqual(result.returncode, 0)

    def test_not_exists(self):
        result = run_cli(_CLI, ["exists"], self.smm_dir)
        self.assertEqual(result.returncode, 1)


class TestHasActiveCommand(_SMMTestCase):
    def test_active_when_ready(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = run_cli(_CLI, ["has-active"], self.smm_dir)
        self.assertEqual(result.returncode, 0)

    def test_no_active_when_done(self):
        sprint = _make_sprint(stories=[_make_story(status="done")])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(_CLI, ["has-active"], self.smm_dir)
        self.assertEqual(result.returncode, 1)


class TestIsCompleteCommand(_SMMTestCase):
    def test_complete_when_all_done(self):
        sprint = _make_sprint(stories=[_make_story(status="done")])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(_CLI, ["is-complete"], self.smm_dir)
        self.assertEqual(result.returncode, 0)

    def test_not_complete_with_ready(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = run_cli(_CLI, ["is-complete"], self.smm_dir)
        self.assertEqual(result.returncode, 1)


class TestCountCommand(_SMMTestCase):
    def test_count_output(self):
        sprint = _make_sprint(
            stories=[
                _make_story(id="s1", status="ready"),
                _make_story(id="s2", status="done"),
            ]
        )
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(_CLI, ["count"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("ready=1", result.stdout)
        self.assertIn("done=1", result.stdout)


class TestCreateCommand(_SMMTestCase):
    def test_create(self):
        sprint = _make_sprint(goal="New Sprint")
        result = run_cli(_CLI, ["create"], self.smm_dir, json.dumps(sprint))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.smm_dir / "sprint.json").exists())

    def test_create_invalid(self):
        result = run_cli(_CLI, ["create"], self.smm_dir, '{"bad": "data"}')
        self.assertNotEqual(result.returncode, 0)


class TestNextScheduledCommand(_SMMTestCase):
    def test_returns_first_scheduled_id(self):
        sprint = _make_sprint(
            stories=[
                _make_story(id="story-001", status="done"),
                _make_story(id="story-002", status="scheduled"),
            ]
        )
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(_CLI, ["next-scheduled"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "story-002")

    def test_no_scheduled_exits_nonzero(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = run_cli(_CLI, ["next-scheduled"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)

    def test_treat_as_done_satisfies_dep(self):
        # Mirrors xp-story-close Step 8: the just-closed story's
        # status is `closing` (not yet `done`), so a dep-gated next
        # story would be invisible without the override.
        sprint = _make_sprint(
            stories=[
                _make_story(id="story-001", status="closing"),
                _make_story(
                    id="story-002", status="scheduled", dependencies=["story-001"]
                ),
            ]
        )
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        # Without the flag: dep is `closing`, not `done` — exit 1.
        result = run_cli(_CLI, ["next-scheduled"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)
        # With the flag: dep treated as satisfied; story-002 surfaces.
        result = run_cli(
            _CLI,
            ["next-scheduled", "--treat-as-done", "story-001"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "story-002")

    def test_treat_as_done_accepts_multiple_ids(self):
        sprint = _make_sprint(
            stories=[
                _make_story(id="story-001", status="closing"),
                _make_story(id="story-002", status="closing"),
                _make_story(
                    id="story-003",
                    status="scheduled",
                    dependencies=["story-001", "story-002"],
                ),
            ]
        )
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(
            _CLI,
            [
                "next-scheduled",
                "--treat-as-done",
                "story-001",
                "--treat-as-done",
                "story-002",
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "story-003")


class TestScheduledOverlapCommand(_SMMTestCase):
    def test_overlap_exit0_when_shared_file(self):
        sprint = _make_sprint(
            stories=[
                _make_story(
                    id="story-001",
                    status="scheduled",
                    file_domain=["src/a.py — owner", "src/b.py — shared"],
                ),
                _make_story(
                    id="story-002",
                    status="scheduled",
                    file_domain=["src/b.py — caller", "src/c.py — owner"],
                ),
            ]
        )
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(_CLI, ["scheduled-overlap"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_overlap_exit1_when_disjoint(self):
        sprint = _make_sprint(
            stories=[
                _make_story(id="s1", status="scheduled", file_domain=["a.py"]),
                _make_story(id="s2", status="scheduled", file_domain=["b.py"]),
            ]
        )
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(_CLI, ["scheduled-overlap"], self.smm_dir)
        self.assertEqual(result.returncode, 1)


class TestUpdateStoryAcceptsScheduled(_SMMTestCase):
    def test_update_story_to_scheduled(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = run_cli(_CLI, ["update-story", "story-001", "scheduled"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(loaded["stories"][0]["status"], "scheduled")


class TestCountStatusAcceptsScheduled(_SMMTestCase):
    def test_count_scheduled(self):
        sprint = _make_sprint(stories=[_make_story(status="scheduled")])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(_CLI, ["count-status", "scheduled"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "1")


class TestGetStoryCommand(_SMMTestCase):
    def test_get_story_returns_json(self):
        sprint = _make_sprint(
            stories=[_make_story(id="story-042", title="Demo", status="ready")]
        )
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(_CLI, ["get-story", "story-042"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        story = json.loads(result.stdout)
        self.assertEqual(story["id"], "story-042")
        self.assertEqual(story["title"], "Demo")
        self.assertEqual(story["status"], "ready")

    def test_get_story_missing_id_exits_nonzero(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = run_cli(_CLI, ["get-story", "story-999"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)

    def test_get_story_no_sprint_file_exits_nonzero(self):
        result = run_cli(_CLI, ["get-story", "story-001"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)


class TestUpdateStoryCommand(_SMMTestCase):
    def test_update_status(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = run_cli(
            _CLI,
            ["update-story", "story-001", "in-progress"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(loaded["stories"][0]["status"], "in-progress")

    def test_invalid_story_id(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = run_cli(_CLI, ["update-story", "story-999", "done"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)


class TestUpdateStoryIfCommand(_SMMTestCase):
    """CLI exposure of the CAS helper. Production xp-accept Step 1.5
    uses this to guard the singleton reviewing→closing transition."""

    def _seed(self, status: str) -> None:
        sprint = _make_sprint(stories=[_make_story(id="story-001", status=status)])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))

    def test_succeeds_when_status_matches_expected(self):
        self._seed("reviewing")
        result = run_cli(
            _CLI,
            [
                "update-story-if",
                "story-001",
                "--expected",
                "reviewing",
                "--new",
                "closing",
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(loaded["stories"][0]["status"], "closing")

    def test_cas_mismatch_exits_rc1(self):
        # A prior caller already advanced the story past `reviewing`;
        # the CAS subcommand must report failure (no demotion). Pins
        # rc=1 specifically — the xp-accept skill instructs the
        # orchestrator to skip-this-story on rc=1 vs halt on rc=2,
        # so the 1↔2 distinction is contract, not implementation detail.
        self._seed("closing")
        result = run_cli(
            _CLI,
            [
                "update-story-if",
                "story-001",
                "--expected",
                "reviewing",
                "--new",
                "closing",
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(loaded["stories"][0]["status"], "closing")

    def test_invalid_new_status_exits_rc2(self):
        # Validation error (argparse choices=) — distinct from the
        # benign rc=1 race-loss; orchestrator must halt, not skip.
        self._seed("reviewing")
        result = run_cli(
            _CLI,
            [
                "update-story-if",
                "story-001",
                "--expected",
                "reviewing",
                "--new",
                "bogus",
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 2)

    def test_unknown_story_id_exits_rc2(self):
        # Helper's ValueError → rc=2. Same orchestrator semantics as
        # the bogus-status case: halt, surface stderr, do not skip.
        self._seed("reviewing")
        result = run_cli(
            _CLI,
            [
                "update-story-if",
                "story-999",
                "--expected",
                "reviewing",
                "--new",
                "closing",
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 2)


class TestRenderCommand(_SMMTestCase):
    def test_render(self):
        (self.smm_dir / "sprint.json").write_text(
            json.dumps(_make_sprint(goal="My Sprint"))
        )
        result = run_cli(_CLI, ["render"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("# Sprint: My Sprint", result.stdout)

    def test_render_missing(self):
        result = run_cli(_CLI, ["render"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)


class TestRenderStoriesCommand(_SMMTestCase):
    def test_render_specific(self):
        sprint = _make_sprint(
            stories=[
                _make_story(id="story-001", title="First"),
                _make_story(id="story-002", title="Second"),
            ]
        )
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(_CLI, ["render-stories", "story-001"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("First", result.stdout)
        self.assertNotIn("Second", result.stdout)


class TestVelocityCommand(_SMMTestCase):
    def test_velocity(self):
        sprint = _make_sprint(
            stories=[
                _make_story(id="s1", status="done"),
                _make_story(id="s2", status="deferred"),
            ]
        )
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(_CLI, ["velocity"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("delivered=1", result.stdout)
        self.assertIn("carried=1", result.stdout)


class TestAddStoryCommand(_SMMTestCase):
    def test_add_story(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        new_story = _make_story(id="story-002", title="Login")
        result = run_cli(
            _CLI,
            ["add-story"],
            self.smm_dir,
            json.dumps(new_story),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(len(loaded["stories"]), 2)


class TestAddStoryDupId(_SMMTestCase):
    """add-story rejects payloads whose id collides with an existing
    story (story-003). Non-dict / id-less payloads fall through to the
    existing schema validator so their error messages stay stable."""

    def test_dup_id_rejects_nonzero(self):
        sprint = _make_sprint(stories=[_make_story(id="story-001")])
        sprint_path = self.smm_dir / "sprint.json"
        sprint_path.write_text(json.dumps(sprint))
        before = sprint_path.read_bytes()
        dup_payload = _make_story(id="story-001", title="Collision")
        result = run_cli(
            _CLI,
            ["add-story"],
            self.smm_dir,
            json.dumps(dup_payload),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Duplicate story id", result.stderr)
        self.assertIn("story-001", result.stderr)
        self.assertEqual(sprint_path.read_bytes(), before)

    def test_new_id_succeeds(self):
        sprint = _make_sprint(stories=[_make_story(id="story-001")])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(
            _CLI,
            ["add-story"],
            self.smm_dir,
            json.dumps(_make_story(id="story-099", title="Fresh")),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        ids = [s["id"] for s in loaded["stories"]]
        self.assertIn("story-099", ids)

    def test_dup_check_preserves_jsondecodeerror_path(self):
        # Pre-check must not swallow the existing parse-error branch.
        sprint = _make_sprint(stories=[_make_story(id="story-001")])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(_CLI, ["add-story"], self.smm_dir, "{not json")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Invalid JSON", result.stderr)
        self.assertNotIn("Duplicate story id", result.stderr)

    def test_missing_id_falls_through_to_validator(self):
        # An id-less dict isn't a dup candidate; the schema validator
        # owns the rejection so its message stays the source of truth.
        sprint = _make_sprint(stories=[_make_story(id="story-001")])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(
            _CLI,
            ["add-story"],
            self.smm_dir,
            json.dumps({"title": "no-id"}),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Validation error", result.stderr)
        self.assertNotIn("Duplicate story id", result.stderr)

    def test_non_dict_payload_falls_through_to_validator(self):
        # Same contract for non-dict JSON shapes (list, string, ...).
        sprint = _make_sprint(stories=[_make_story(id="story-001")])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(_CLI, ["add-story"], self.smm_dir, "[]")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Validation error", result.stderr)
        self.assertNotIn("Duplicate story id", result.stderr)


class TestSprintCliHelp(_SMMTestCase):
    def test_help_contains_examples(self):
        result = run_cli(_CLI, ["--help"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Examples:", result.stdout)


class TestEditStoryCommand(_SMMTestCase):
    """edit-story updates arbitrary story fields via stdin JSON."""

    def test_updates_context_field(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = run_cli(
            _CLI,
            ["edit-story", "story-001"],
            self.smm_dir,
            json.dumps({"context": "Updated context."}),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(loaded["stories"][0]["context"], "Updated context.")

    def test_unknown_story_id_fails(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = run_cli(
            _CLI,
            ["edit-story", "story-999"],
            self.smm_dir,
            json.dumps({"context": "new"}),
        )
        self.assertNotEqual(result.returncode, 0)

    def test_validates_schema(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = run_cli(
            _CLI,
            ["edit-story", "story-001"],
            self.smm_dir,
            json.dumps({"context": "x" * 601}),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("budget", result.stderr.lower())

    def test_no_sprint_fails(self):
        result = run_cli(
            _CLI,
            ["edit-story", "story-001"],
            self.smm_dir,
            json.dumps({"context": "new"}),
        )
        self.assertNotEqual(result.returncode, 0)

    def test_rejects_id_override(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = run_cli(
            _CLI,
            ["edit-story", "story-001"],
            self.smm_dir,
            json.dumps({"id": "story-999"}),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("immutable", result.stderr.lower())

    def test_rejects_non_object_input(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = run_cli(
            _CLI,
            ["edit-story", "story-001"],
            self.smm_dir,
            json.dumps(["not", "a", "dict"]),
        )
        self.assertNotEqual(result.returncode, 0)


class TestUpdateStoryBranch(_SMMTestCase):
    def test_sets_branch_name(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = run_cli(
            _CLI,
            ["update-story-branch", "story-001", "paul/story-001-foo"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(loaded["stories"][0]["branch_name"], "paul/story-001-foo")

    def test_invalid_story_fails(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = run_cli(
            _CLI,
            ["update-story-branch", "story-999", "paul/story-999-foo"],
            self.smm_dir,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("error", result.stderr.lower())

    def test_no_sprint_fails(self):
        result = run_cli(
            _CLI,
            ["update-story-branch", "story-001", "paul/story-001-foo"],
            self.smm_dir,
        )
        self.assertNotEqual(result.returncode, 0)


class TestValidateDomainCommand(_SMMTestCase):
    """validate-domain diffs git-changed files (since base) vs declared file_domain.

    Surfaces file_domain drift at story-close commit time instead of
    waiting for the close-reviewer or post-sprint retro (concern
    69fb3b79ca3e).
    """

    def _seed(self, file_domain, story_id="story-001"):
        story = _make_story(id=story_id, file_domain=file_domain)
        sprint = _make_sprint(stories=[story])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))

    def _make_branch_with_changes(self, repo: Path, files):
        """Init repo and add `files` on a feature branch off main."""
        init_repo(str(repo))
        subprocess.run(
            ["git", "checkout", "-b", "story"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        for fn in files:
            target = repo / fn
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("x\n")
            subprocess.run(
                ["git", "add", fn], cwd=repo, capture_output=True, check=True
            )
            subprocess.run(
                ["git", "commit", "-m", f"add {fn}"],
                cwd=repo,
                capture_output=True,
                check=True,
                env=GIT_ENV,
            )

    def test_clean_match_exits_zero(self):
        self._seed(file_domain=["src/a.py — owner", "src/b.py — owner"])
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            self._make_branch_with_changes(repo, ["src/a.py", "src/b.py"])
            result = run_cli(
                _CLI,
                [
                    "validate-domain",
                    "story-001",
                    "--base",
                    "main",
                    "--cwd",
                    str(repo),
                ],
                self.smm_dir,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("clean", result.stdout.lower())

    def test_single_drift_at_K0_exits_nonzero_and_names_file(self):
        self._seed(file_domain=["src/a.py — owner"])
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            self._make_branch_with_changes(repo, ["src/a.py", "src/drift.py"])
            result = run_cli(
                _CLI,
                [
                    "validate-domain",
                    "story-001",
                    "--base",
                    "main",
                    "--cwd",
                    str(repo),
                ],
                self.smm_dir,
                extra_env={"XP_FILE_DOMAIN_DRIFT_TOLERANCE": "0"},
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("src/drift.py", result.stderr)
            self.assertNotIn("src/a.py", result.stderr)

    def test_single_drift_at_default_K1_exits_zero(self):
        self._seed(file_domain=["src/a.py — owner"])
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            self._make_branch_with_changes(repo, ["src/a.py", "src/drift.py"])
            result = run_cli(
                _CLI,
                [
                    "validate-domain",
                    "story-001",
                    "--base",
                    "main",
                    "--cwd",
                    str(repo),
                ],
                self.smm_dir,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            # Absorbed-drift signal is emitted on stderr so retros and
            # quality-review can see what slipped past the K-budget.
            self.assertIn("drift (within K=1)", result.stderr)
            self.assertIn("src/drift.py", result.stderr)
            # Stdout must NOT claim "clean" when drift was absorbed —
            # would lie to callers parsing stdout for the clean signal.
            self.assertNotIn("clean", result.stdout)
            self.assertIn("absorbed", result.stdout)

    def test_zero_drift_emits_no_absorbed_signal(self):
        # Clean cases must stay quiet — the absorbed-drift line only
        # fires when 1 <= len(drift) <= tolerance.
        self._seed(file_domain=["src/a.py — owner"])
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            self._make_branch_with_changes(repo, ["src/a.py"])
            result = run_cli(
                _CLI,
                [
                    "validate-domain",
                    "story-001",
                    "--base",
                    "main",
                    "--cwd",
                    str(repo),
                ],
                self.smm_dir,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("drift", result.stderr)

    def test_env_read_per_invocation_not_module_global(self):
        # Two back-to-back invocations with different tolerance values
        # against the same story+diff. If XP_FILE_DOMAIN_DRIFT_TOLERANCE
        # were cached at module-import time, the second invocation would
        # inherit the first's tolerance and fail. Subprocess re-import
        # would mask a stale module global, so this test pins the
        # per-invocation contract for any future caller that imports
        # sprint_cli as a library and holds the module across env
        # mutations.
        self._seed(file_domain=["src/a.py — owner"])
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            self._make_branch_with_changes(repo, ["src/a.py", "src/drift.py"])
            argv = [
                "validate-domain",
                "story-001",
                "--base",
                "main",
                "--cwd",
                str(repo),
            ]
            strict = run_cli(
                _CLI,
                argv,
                self.smm_dir,
                extra_env={"XP_FILE_DOMAIN_DRIFT_TOLERANCE": "0"},
            )
            self.assertNotEqual(strict.returncode, 0)
            self.assertIn("src/drift.py", strict.stderr)

            permissive = run_cli(
                _CLI,
                argv,
                self.smm_dir,
                extra_env={"XP_FILE_DOMAIN_DRIFT_TOLERANCE": "2"},
            )
            self.assertEqual(permissive.returncode, 0, permissive.stderr)
            self.assertIn("drift (within K=2)", permissive.stderr)

    def test_two_drift_at_default_K1_exits_nonzero_and_names_both(self):
        self._seed(file_domain=["src/a.py — owner"])
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            self._make_branch_with_changes(
                repo, ["src/a.py", "src/drift1.py", "src/drift2.py"]
            )
            result = run_cli(
                _CLI,
                [
                    "validate-domain",
                    "story-001",
                    "--base",
                    "main",
                    "--cwd",
                    str(repo),
                ],
                self.smm_dir,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("src/drift1.py", result.stderr)
            self.assertIn("src/drift2.py", result.stderr)
            self.assertNotIn("src/a.py", result.stderr)

    def test_e2e_two_stories_one_sprint_only_over_budget_fails(self):
        # AC4: same sprint.json, two stories. Same git diff seen through
        # each story's file_domain — within-K story passes, over-K fails.
        # Story-001 owns {a, b, drift_x}: changed - declared = {drift_y}
        # = 1 file → within K=1 → exit 0.
        # Story-002 owns {drift_y}: changed - declared = {a, b, drift_x}
        # = 3 files → over K=1 → exit non-zero.
        story_within = _make_story(
            id="story-001",
            file_domain=[
                "src/a.py — owner",
                "src/b.py — owner",
                "src/drift_x.py — owner",
            ],
        )
        story_over = _make_story(id="story-002", file_domain=["src/drift_y.py — owner"])
        sprint = _make_sprint(stories=[story_within, story_over])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            self._make_branch_with_changes(
                repo, ["src/a.py", "src/b.py", "src/drift_x.py", "src/drift_y.py"]
            )
            within_result = run_cli(
                _CLI,
                ["validate-domain", "story-001", "--base", "main", "--cwd", str(repo)],
                self.smm_dir,
            )
            over_result = run_cli(
                _CLI,
                ["validate-domain", "story-002", "--base", "main", "--cwd", str(repo)],
                self.smm_dir,
            )
            self.assertEqual(within_result.returncode, 0, within_result.stderr)
            self.assertNotEqual(over_result.returncode, 0)
            self.assertIn("src/a.py", over_result.stderr)
            self.assertIn("src/b.py", over_result.stderr)
            self.assertIn("src/drift_x.py", over_result.stderr)

    def test_no_commits_on_branch_exits_zero(self):
        self._seed(file_domain=["src/a.py — owner"])
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            init_repo(str(repo))
            # No additional commits — HEAD is still main's initial commit.
            result = run_cli(
                _CLI,
                [
                    "validate-domain",
                    "story-001",
                    "--base",
                    "main",
                    "--cwd",
                    str(repo),
                ],
                self.smm_dir,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_e2e_third_commit_drift_at_K0_in_stderr(self):
        """E2E: 2-file declared domain + 3rd commit out-of-domain → drift at K=0."""
        self._seed(file_domain=["src/a.py — owner", "src/b.py — owner"])
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            self._make_branch_with_changes(repo, ["src/a.py", "src/b.py", "src/c.py"])
            result = run_cli(
                _CLI,
                [
                    "validate-domain",
                    "story-001",
                    "--base",
                    "main",
                    "--cwd",
                    str(repo),
                ],
                self.smm_dir,
                extra_env={"XP_FILE_DOMAIN_DRIFT_TOLERANCE": "0"},
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("src/c.py", result.stderr)


class TestGetStoryBranchCommand(_SMMTestCase):
    """get-story-branch prints a story's recorded branch_name. Replaces
    the inline `python3 -c` JSON-poking that /xp-story-close was using
    in Step 8 to gate JIT-create on solo vs teammate (parallel) mode.
    """

    def test_returns_recorded_branch_name(self):
        sprint = _make_sprint(
            stories=[
                _make_story(id="story-001", branch_name="paul/story-001-foo"),
            ]
        )
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(_CLI, ["get-story-branch", "story-001"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "paul/story-001-foo")

    def test_returns_empty_when_unset(self):
        sprint = _make_sprint(stories=[_make_story(id="story-001")])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(_CLI, ["get-story-branch", "story-001"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_returns_empty_when_story_missing(self):
        sprint = _make_sprint(stories=[_make_story(id="story-001")])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(_CLI, ["get-story-branch", "story-999"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_returns_empty_when_no_sprint(self):
        result = run_cli(_CLI, ["get-story-branch", "story-001"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")


class TestBuildCapstoneCommand(_SMMTestCase):
    def _run(self, extra):
        return run_cli(_CLI, ["build-capstone", *extra], self.smm_dir)

    def test_prints_ready_capstone_json(self):
        result = self._run(
            [
                "--milestone",
                "Milestone 3: surface-coverage",
                "--surfaces",
                "cli,sdk",
                "--depends-on",
                "story-001,story-002",
                "--story-id",
                "story-006",
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        story = json.loads(result.stdout)
        self.assertEqual(story["id"], "story-006")
        self.assertEqual(story["status"], "ready")
        self.assertTrue(story["title"].startswith("Capstone:"))
        self.assertEqual(story["dependencies"], ["story-001", "story-002"])
        surfaces = {
            a["surface"] for a in story["acceptance_criteria"] if isinstance(a, dict)
        }
        self.assertEqual(surfaces, {"cli", "sdk"})

    def test_output_pipes_into_add_story(self):
        (self.smm_dir / "sprint.json").write_text(
            json.dumps(_make_sprint(stories=[_make_story(id="story-001")]))
        )
        built = self._run(
            [
                "--milestone",
                "Milestone 3",
                "--surfaces",
                "cli",
                "--depends-on",
                "story-001",
                "--story-id",
                "story-006",
            ]
        )
        self.assertEqual(built.returncode, 0, built.stderr)
        added = run_cli(_CLI, ["add-story"], self.smm_dir, stdin_data=built.stdout)
        self.assertEqual(added.returncode, 0, added.stderr)


class TestReadyFrontierCommand(_SMMTestCase):
    """ready-frontier emits JSON {"frontier": [...], "parallelizable": bool}
    for the /xp-schedule preload to consume. Exit 0 always — an empty
    frontier is a valid state, not an error."""

    def _run(self, stories, extra_args=None):
        sprint = _make_sprint(stories=stories)
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(_CLI, ["ready-frontier", *(extra_args or [])], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_single_story_frontier_not_parallelizable(self):
        out = self._run(
            [
                _make_story(
                    id="story-001",
                    status="scheduled",
                    dependencies=[],
                    file_domain=["a.py — x"],
                ),
                _make_story(
                    id="story-002",
                    status="scheduled",
                    dependencies=["story-001"],
                    file_domain=["b.py — y"],
                ),
            ]
        )
        self.assertEqual(out["frontier"], ["story-001"])
        self.assertFalse(out["parallelizable"])

    def test_disjoint_multi_frontier_is_parallelizable(self):
        out = self._run(
            [
                _make_story(
                    id="story-001",
                    status="scheduled",
                    dependencies=[],
                    file_domain=["a.py — x"],
                ),
                _make_story(
                    id="story-002",
                    status="scheduled",
                    dependencies=[],
                    file_domain=["b.py — y"],
                ),
            ]
        )
        self.assertEqual(out["frontier"], ["story-001", "story-002"])
        self.assertTrue(out["parallelizable"])

    def test_overlapping_multi_frontier_not_parallelizable(self):
        out = self._run(
            [
                _make_story(
                    id="story-001",
                    status="scheduled",
                    dependencies=[],
                    file_domain=["shared.py — x"],
                ),
                _make_story(
                    id="story-002",
                    status="scheduled",
                    dependencies=[],
                    file_domain=["shared.py — y"],
                ),
            ]
        )
        self.assertEqual(out["frontier"], ["story-001", "story-002"])
        self.assertFalse(out["parallelizable"])

    def test_empty_frontier(self):
        out = self._run([_make_story(id="story-001", status="done", dependencies=[])])
        self.assertEqual(out["frontier"], [])
        self.assertFalse(out["parallelizable"])

    def test_no_sprint_is_empty(self):
        result = run_cli(_CLI, ["ready-frontier"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout), {"frontier": [], "parallelizable": False}
        )

    def test_treat_as_done_unblocks_frontier(self):
        out = self._run(
            [
                _make_story(id="story-001", status="closing", dependencies=[]),
                _make_story(
                    id="story-002", status="scheduled", dependencies=["story-001"]
                ),
            ],
            extra_args=["--treat-as-done", "story-001"],
        )
        self.assertEqual(out["frontier"], ["story-002"])


class TestStructuralSubcommandsRouteThroughRun(_SMMTestCase):
    """Story-004: _cmd_create + _cmd_add_story route through save_sprint.run()
    (structural mutations — full pipeline). _cmd_edit_story routes through
    save_sprint.save() (status flips — side-effect-free). Lock-in tests.

    Observable side-effect of run() used here: the soft-warn marker for
    sister-test layout (Q1(b)) — touched only by run(), never by save().
    """

    _MARKER = ".sister-test-layout-warn"

    def _sample_sprint(self):
        return _make_sprint(stories=[_make_story(id="story-001", status="ready")])

    def test_create_fires_run_pipeline(self):
        sprint = self._sample_sprint()
        result = run_cli(_CLI, ["create"], self.smm_dir, json.dumps(sprint))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(
            (self.smm_dir / self._MARKER).exists(),
            "expected sister-test soft-warn marker after _cmd_create — proves "
            "_cmd_create routes through save_sprint.run()",
        )

    def test_add_story_fires_run_pipeline(self):
        sprint = self._sample_sprint()
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        new_story = _make_story(id="story-099", status="ready")
        result = run_cli(_CLI, ["add-story"], self.smm_dir, json.dumps(new_story))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(
            (self.smm_dir / self._MARKER).exists(),
            "expected sister-test soft-warn marker after _cmd_add_story",
        )

    def test_add_story_dup_id_stays_above_run(self):
        """story-003's locked contract: dup-id guard runs BEFORE save_sprint.run.
        A duplicate-id payload must NOT fire run()'s side effects (no marker,
        no transition concerns)."""
        sprint = self._sample_sprint()
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        dup = _make_story(id="story-001", status="ready", title="dup")
        result = run_cli(_CLI, ["add-story"], self.smm_dir, json.dumps(dup))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Duplicate story id", result.stderr)
        self.assertFalse(
            (self.smm_dir / self._MARKER).exists(),
            "dup-id rejection MUST short-circuit before save_sprint.run — "
            "marker should NOT exist (locks story-003 contract)",
        )

    def test_edit_story_uses_save_not_run(self):
        """Status flips via edit-story must NOT trigger sister discovery or
        soft-warn (impact-zone constraint per plan-review e7b72bd57c84)."""
        sprint = self._sample_sprint()
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(
            _CLI,
            ["edit-story", "story-001"],
            self.smm_dir,
            json.dumps({"status": "in-progress"}),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(
            (self.smm_dir / self._MARKER).exists(),
            "edit-story MUST route through save() not run() — sister-test "
            "soft-warn marker should NOT exist (locks the architectural split)",
        )
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(loaded["stories"][0]["status"], "in-progress")


if __name__ == "__main__":
    unittest.main()

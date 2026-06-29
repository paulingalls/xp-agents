#!/usr/bin/env python3
"""Tests for sprint_save sister-test integration: layout resolution + run/save.

Extracted from tests/hooks/test_sprint_start.py in sprint-108 M1 (story-001),
and carved out of test_sprint_save.py to keep both files under the 500-line cap.

Three cohesive groups:
- TestAutoIncludeSisterTests: _auto_include_sister_tests takes project_root as a
  direct argument and never calls _resolve_project_root (folds concern
  2097e2759873 — the prior _make_git_project setup was dead). No git required.
- TestResolveLayout: _resolve_layout reads system_context.test_layout.
- TestRunIntegratesSisterTestsAndSoftWarn: run()/save() discovery + soft-warn;
  these DO need a real git project (_make_git_project).
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import sister_tests  # pyright: ignore[reportMissingImports]
import sprint_save
from conftest import _SMMTestCase, triage
from event_schema import EVENT_TYPE_CONCERN


def _make_git_project(tmpdir: Path) -> Path:
    """_resolve_project_root delegates to worktree.resolve_git_root, which
    shells `git rev-parse --show-toplevel` — a bare `.git/` directory won't
    satisfy it (no HEAD, no refs, no objects), so a real init is required.
    Only the run()-driven tests below need it; TestAutoIncludeSisterTests
    passes project_root directly."""
    subprocess.run(["git", "init", "-q", str(tmpdir)], check=True)
    return tmpdir


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


class TestResolveLayout(_SMMTestCase):
    """_resolve_layout reads system_context.test_layout and constructs a
    TestLayout instance. Returns None when absent, when convention is
    'unknown', or when system_context is missing/unreadable."""

    def setUp(self):
        super().setUp()
        self.mod = sprint_save
        self.sister_tests = sister_tests

    def _write_sc(self, test_layout=None):
        from _system_context_fixtures import valid_doc, write_doc

        kwargs = {}
        if test_layout is not None:
            kwargs["test_layout"] = test_layout
        write_doc(self.smm_dir, valid_doc(**kwargs))

    def test_returns_none_when_system_context_absent(self):
        self.assertIsNone(self.mod._resolve_layout(self.smm_dir))

    def test_returns_none_when_test_layout_absent(self):
        self._write_sc(test_layout=None)
        self.assertIsNone(self.mod._resolve_layout(self.smm_dir))

    def test_returns_none_when_convention_unknown(self):
        self._write_sc({"convention": "unknown", "overrides": []})
        self.assertIsNone(self.mod._resolve_layout(self.smm_dir))

    def test_returns_builtin_layout_for_python_pytest(self):
        self._write_sc({"convention": "python_pytest", "overrides": []})
        layout = self._assert_not_none(self.mod._resolve_layout(self.smm_dir))
        self.assertEqual(layout.convention, "python_pytest")
        self.assertEqual(
            layout.rules,
            self.sister_tests.BUILTIN_LAYOUTS["python_pytest"].rules,
        )

    def test_custom_convention_has_empty_rules_only_overrides(self):
        self._write_sc(
            {
                "convention": "custom",
                "overrides": [
                    {
                        "source_pattern": "**/*.toml",
                        "stem_extractor": "basename_no_ext",
                        "test_glob": "tests/test_{stem}.py",
                    }
                ],
            }
        )
        layout = self._assert_not_none(self.mod._resolve_layout(self.smm_dir))
        self.assertEqual(layout.convention, "custom")
        self.assertEqual(layout.rules, ())
        self.assertEqual(len(layout.overrides), 1)
        self.assertEqual(layout.overrides[0].source_pattern, "**/*.toml")

    def test_overrides_coerce_list_to_tuple_for_skip_fields(self):
        self._write_sc(
            {
                "convention": "python_pytest",
                "overrides": [
                    {
                        "source_pattern": "src/*.py",
                        "stem_extractor": "basename_no_ext",
                        "test_glob": "tests/{stem}.py",
                        "skip_basenames": ["__init__.py", "conftest.py"],
                        "skip_suffixes": ["_test.py"],
                        "source_excludes": ["obj/**"],
                    }
                ],
            }
        )
        layout = self._assert_not_none(self.mod._resolve_layout(self.smm_dir))
        rule = layout.overrides[0]
        self.assertIsInstance(rule.skip_basenames, tuple)
        self.assertEqual(rule.skip_basenames, ("__init__.py", "conftest.py"))
        self.assertEqual(rule.skip_suffixes, ("_test.py",))
        self.assertEqual(rule.source_excludes, ("obj/**",))


class TestRunIntegratesSisterTestsAndSoftWarn(_SMMTestCase):
    """run() invokes _auto_include_sister_tests when layout resolves; calls
    _warn_sister_skip_once otherwise. Soft-warn is marker-based so it
    survives the subprocess-per-CLI-call model the production CLI uses."""

    def setUp(self):
        super().setUp()
        self.mod = sprint_save
        self._tmp = Path(tempfile.mkdtemp(prefix="story-004-run-"))
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(self._tmp)]))
        _make_git_project(self._tmp)
        # Stage the sister-tests fixture inside the git project
        (self._tmp / "src").mkdir()
        (self._tmp / "tests").mkdir()
        (self._tmp / "src/foo.py").write_text("x = 1")
        (self._tmp / "tests/test_foo.py").write_text("def test_x(): pass")
        self._orig_cwd = Path.cwd()
        os.chdir(self._tmp)
        self.addCleanup(lambda: os.chdir(self._orig_cwd))

    def _write_sc(self, test_layout=None):
        from _system_context_fixtures import valid_doc, write_doc

        kwargs = {}
        if test_layout is not None:
            kwargs["test_layout"] = test_layout
        write_doc(self.smm_dir, valid_doc(**kwargs))

    def _sample_sprint(self, file_domain=None):
        from conftest import _s

        story = _s("story-001", "x", "ready")
        story["file_domain"] = file_domain or ["src/foo.py — impl"]
        return {
            "sprint_id": "sprint-001",
            "goal": "t",
            "started": "2026-04-01",
            "milestone": "",
            "stories": [story],
        }

    def test_run_auto_includes_sister_when_layout_resolves(self):
        self._write_sc({"convention": "python_pytest", "overrides": []})
        data = self._sample_sprint()
        self.mod.run(data, self.smm_dir)
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        domains = loaded["stories"][0]["file_domain"]
        self.assertTrue(
            any("tests/test_foo.py" in e for e in domains),
            f"sister not appended; got {domains}",
        )

    def test_run_warns_once_when_layout_unknown_marker_blocks_second(self):
        """Marker-based: first run records concern + touches marker; second
        run sees marker and is silent. This is the cross-process semantics
        story-004 explicitly aims for."""
        from event_helpers import events_of_type

        self._write_sc({"convention": "unknown", "overrides": []})
        data = self._sample_sprint()
        self.mod.run(data, self.smm_dir)
        self.mod.run(data, self.smm_dir)
        events = [
            json.loads(line)
            for line in (self.smm_dir / "events.jsonl").read_text().splitlines()
            if line.strip()
        ]
        sister_concerns = [
            e
            for e in events_of_type(events, EVENT_TYPE_CONCERN)
            if "test_layout" in e.get("content", "")
        ]
        self.assertEqual(
            len(sister_concerns),
            1,
            f"expected exactly one sister-test concern; got {len(sister_concerns)}",
        )

    def test_run_warns_once_when_project_root_missing(self):
        """If layout resolves but cwd has no .git/ ancestor, the warn
        path must fire — the prior shape attached the else to
        `if layout`, silently skipping discovery AND the warn when both
        legs were short-circuited. (concern code-review #3)"""
        from event_helpers import events_of_type

        # Move out of the git project so _resolve_project_root() returns None
        non_git = Path(tempfile.mkdtemp(prefix="story-004-no-git-"))
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(non_git)]))
        os.chdir(non_git)
        self._write_sc({"convention": "python_pytest", "overrides": []})
        data = self._sample_sprint()
        self.mod.run(data, self.smm_dir)
        events = [
            json.loads(line)
            for line in (self.smm_dir / "events.jsonl").read_text().splitlines()
            if line.strip()
        ]
        sister_concerns = [
            e
            for e in events_of_type(events, EVENT_TYPE_CONCERN)
            if "Sister-test auto-inclusion" in e.get("content", "")
        ]
        self.assertEqual(
            len(sister_concerns),
            1,
            f"expected one project-root-missing concern; got {sister_concerns}",
        )
        self.assertIn(
            "no project root",
            sister_concerns[0]["content"],
            f"reason should name project-root cause; got {sister_concerns[0]}",
        )

    def test_run_warns_once_when_custom_layout_has_no_overrides(self):
        """convention='custom' with empty overrides resolves to no rules
        and no overrides — a degenerate layout that would silently
        no-op on every save. Must surface through the warn path.
        (concern code-review #4)"""
        from event_helpers import events_of_type

        self._write_sc({"convention": "custom", "overrides": []})
        data = self._sample_sprint()
        self.mod.run(data, self.smm_dir)
        events = [
            json.loads(line)
            for line in (self.smm_dir / "events.jsonl").read_text().splitlines()
            if line.strip()
        ]
        sister_concerns = [
            e
            for e in events_of_type(events, EVENT_TYPE_CONCERN)
            if "Sister-test auto-inclusion" in e.get("content", "")
        ]
        self.assertEqual(
            len(sister_concerns),
            1,
            f"degenerate-custom must warn once; got {sister_concerns}",
        )

    def test_run_dedups_ascii_dash_sister_entries(self):
        """file_domain entries using ASCII ' -- ' for description must
        dedup correctly against sister discovery — the prior
        _extract_path split only on em-dash and leaked ASCII-dash
        entries past dedup, causing duplicates to accumulate on every
        save. (concern code-review #2)"""
        (self._tmp / "src/bar.py").write_text("x = 1")
        (self._tmp / "tests/test_bar.py").write_text("def test_x(): pass")
        self._write_sc({"convention": "python_pytest", "overrides": []})
        data = self._sample_sprint(
            file_domain=[
                "src/bar.py -- impl (ASCII dash)",
                "tests/test_bar.py -- manual (ASCII dash)",
            ]
        )
        self.mod.run(data, self.smm_dir)
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        domains = loaded["stories"][0]["file_domain"]
        # tests/test_bar.py must appear exactly once — not duplicated as
        # a sister entry just because the original used ASCII dash.
        bar_paths = [triage.entry_to_paths(e) for e in domains]
        flattened = [p for paths in bar_paths for p in paths]
        self.assertEqual(
            flattened.count("tests/test_bar.py"),
            1,
            f"ASCII-dash entry leaked dedup; got domains={domains}",
        )

    def test_save_skips_discovery_and_soft_warn(self):
        """save() is the side-effect-free path. Status flips via
        _cmd_edit_story will call save(), not run() — so milestone
        transition / discovery / soft-warn do NOT fire on those edits.
        Locks the architectural decision (plan-review e7b72bd57c84)."""
        from event_helpers import events_of_type

        self._write_sc({"convention": "unknown", "overrides": []})
        data = self._sample_sprint()
        self.mod.save(data, self.smm_dir)
        events_path = self.smm_dir / "events.jsonl"
        events = (
            [
                json.loads(line)
                for line in events_path.read_text().splitlines()
                if line.strip()
            ]
            if events_path.exists()
            else []
        )
        sister_concerns = [
            e
            for e in events_of_type(events, EVENT_TYPE_CONCERN)
            if "test_layout" in e.get("content", "")
        ]
        self.assertEqual(sister_concerns, [])
        # Marker NOT touched either
        marker = self.smm_dir / ".sister-test-layout-warn"
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()

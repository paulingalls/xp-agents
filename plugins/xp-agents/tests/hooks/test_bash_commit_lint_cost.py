#!/usr/bin/env python3
"""Cost bound for post-commit lint resolution: an N-file commit whose files
share one (linter, config) group must spawn exactly one linter subprocess,
not one per file.

Counts real spawn attempts at `lint_runners.subprocess.run` — the actual
process-spawn seam both `run_linter` and `run_linter_batch` share — so a
passing test is a claim about PROCESSES, not about which helper got called.
"""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import lint_resolution
import worktree
from conftest import _HookTestCase, _mock_ruff_result, compute_resolutions, make_event
from event_schema import EVENT_TYPE_CONCERN


class _LintCostTestCase(_HookTestCase):
    """A real (but git-init'd) tmp repo with a `ruff.toml`, so file paths
    normalize the same project-relative way they do in production — needed
    for the flag-shaped-path test below, where the leading '-' must survive
    normalization."""

    def setUp(self):
        super().setUp()
        self.repo = Path(tempfile.mkdtemp())
        subprocess.run(
            ["git", "init", "-q"], cwd=str(self.repo), check=True, capture_output=True
        )
        (self.repo / "ruff.toml").touch()
        self._git_root_patch = patch(
            "worktree.resolve_git_root", return_value=str(self.repo)
        )
        self._git_root_patch.start()

    def tearDown(self):
        self._git_root_patch.stop()
        shutil.rmtree(self.repo, ignore_errors=True)
        super().tearDown()

    def _seed(self, *files: str) -> None:
        for f in files:
            p = self.repo / f
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x = 1\n")

    def _seed_concern(self, rel_path: str) -> dict:
        norm = worktree.normalize_path(rel_path, str(self.repo))
        return make_event(
            EVENT_TYPE_CONCERN,
            content=f"Lint errors in {norm}:\nE302 expected 2 blank lines",
            severity="medium",
        )

    def _resolved_ids(self, events: list[dict]) -> list[str]:
        ids: list[str] = []
        for e in events:
            ids.extend(e.get("metadata", {}).get("resolves", []))
        return ids

    def _fake_spawn(self, returncode=0, stdout="", stderr=""):
        calls: list[list[str]] = []

        def _run(argv, **_kwargs):
            calls.append(argv)
            return _mock_ruff_result(
                returncode=returncode, stdout=stdout, stderr=stderr
            )

        _run.calls = calls
        return _run

    def _resolve_on_commit(self, files, *, returncode=0, stdout="", stderr=""):
        fake = self._fake_spawn(returncode=returncode, stdout=stdout, stderr=stderr)
        events = self._read_events()
        resolutions = compute_resolutions(events)
        with (
            patch("lint_runners.shutil.which", return_value="/usr/bin/tool"),
            patch("lint_runners.subprocess.run", side_effect=fake),
        ):
            lint_resolution.resolve_lint_on_commit(
                self.smm_dir,
                str(self.repo),
                "main",
                files,
                events=events,
                resolutions=resolutions,
            )
        return fake.calls

    def _sweep(self, committed_files, *, returncode=0, stdout="", stderr=""):
        fake = self._fake_spawn(returncode=returncode, stdout=stdout, stderr=stderr)
        events = self._read_events()
        resolutions = compute_resolutions(events)
        with (
            patch("lint_runners.shutil.which", return_value="/usr/bin/tool"),
            patch("lint_runners.subprocess.run", side_effect=fake),
        ):
            lint_resolution.sweep_orphan_lint_concerns(
                self.smm_dir,
                str(self.repo),
                "main",
                committed_files,
                events=events,
                resolutions=resolutions,
            )
        return fake.calls


class TestResolveLintOnCommitCost(_LintCostTestCase):
    def test_one_process_for_a_single_group(self):
        """5 .py files, one shared ruff.toml -> exactly one linter process,
        and every concern the per-file loop would have resolved is resolved.

        RED before lint_resolution.py batches: the existing per-file loop
        spawns 5 processes here, failing 5 != 1 — a real process-count
        failure, not an import or collection error.
        """
        files = [f"{c}.py" for c in "abcde"]
        self._seed(*files)
        seeded = [self._seed_concern(f) for f in files]
        self._write_events(seeded)

        calls = self._resolve_on_commit(files)

        self.assertEqual(len(calls), 1)
        resolved = self._resolved_ids(self._read_events())
        for c in seeded:
            self.assertIn(c["id"], resolved)

    def test_one_process_per_group_not_one_overall(self):
        """3 .py + 3 .ts in a repo carrying both ruff.toml and
        eslint.config.mjs -> exactly 2 processes. The positive control that
        stops 'batch everything into one call' from passing the test above.
        """
        py_files = [f"{c}.py" for c in "abc"]
        ts_files = [f"{c}.ts" for c in "def"]
        self._seed("eslint.config.mjs", *py_files, *ts_files)
        seeded = [self._seed_concern(f) for f in py_files + ts_files]
        self._write_events(seeded)

        calls = self._resolve_on_commit(py_files + ts_files)

        self.assertEqual(len(calls), 2)
        resolved = self._resolved_ids(self._read_events())
        for c in seeded:
            self.assertIn(c["id"], resolved)

    def test_unverified_group_resolves_nothing(self):
        """A non-zero exit with no output classifies as unverified — a bad
        read is not a pass, so nothing in the group resolves."""
        files = [f"{c}.py" for c in "abcde"]
        self._seed(*files)
        seeded = [self._seed_concern(f) for f in files]
        self._write_events(seeded)

        calls = self._resolve_on_commit(files, returncode=1, stdout="", stderr="")

        self.assertEqual(len(calls), 1)
        self.assertEqual(self._resolved_ids(self._read_events()), [])

    def test_no_open_concern_spawns_nothing(self):
        """Same 5 files, but no lint concern was ever raised for any of them
        -> nothing to resolve, so nothing is spawned. The honest statement
        of the common commit."""
        files = [f"{c}.py" for c in "abcde"]
        self._seed(*files)

        calls = self._resolve_on_commit(files)

        self.assertEqual(len(calls), 0)

    def test_flag_shaped_path_does_not_block_its_siblings(self):
        """A sixth path, `-x.py`, sits alongside the 5. Without dropping it
        before grouping, `run_linter_batch`'s arg-injection guard refuses
        the WHOLE batch and none of the 5 resolve. Filtered, the 5 resolve
        and `-x.py`'s own concern is left open — the fail-closed property
        preserved on the one path it is a fact about."""
        files = [f"{c}.py" for c in "abcde"]
        self._seed(*files, "-x.py")
        seeded = [self._seed_concern(f) for f in files]
        flagged = self._seed_concern("-x.py")
        self._write_events([*seeded, flagged])

        calls = self._resolve_on_commit([*files, "-x.py"])

        self.assertEqual(len(calls), 1)
        resolved = self._resolved_ids(self._read_events())
        for c in seeded:
            self.assertIn(c["id"], resolved)
        self.assertNotIn(flagged["id"], resolved)


class TestSweepOrphanLintConcernsCost(_LintCostTestCase):
    def test_one_process_for_a_single_group(self):
        """The orphan sweep gets the same count assertion: 5 orphaned files
        sharing one ruff.toml -> one process, all 5 concerns resolved."""
        files = [f"{c}.py" for c in "abcde"]
        self._seed(*files)
        seeded = [self._seed_concern(f) for f in files]
        self._write_events(seeded)

        calls = self._sweep(committed_files=[])

        self.assertEqual(len(calls), 1)
        resolved = self._resolved_ids(self._read_events())
        for c in seeded:
            self.assertIn(c["id"], resolved)


if __name__ == "__main__":
    unittest.main()

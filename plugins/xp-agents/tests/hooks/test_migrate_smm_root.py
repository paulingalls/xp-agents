#!/usr/bin/env python3
"""Tests for migrate_smm_root.py — the manual escape hatch.

The tool exists for the one case automation must not decide: a worktree
directory that looks live but belongs to a story abandoned long ago. Its
contract is therefore mostly about what it REFUSES to do, so that is what most
of these pin.

It drives init.sh rather than reimplementing relocation, so these tests exercise
the real script end to end against a temp HOME rather than mocking the move.
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
from conftest import _TempRepoTestCase

_SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "migrate_smm_root.py"


class _ToolCase(_TempRepoTestCase):
    def _home(self, name: str) -> Path:
        home = self.tmpdir / f"home-{name}"
        home.mkdir(parents=True, exist_ok=True)
        return home

    def _project_id(self) -> str:
        probe = self.tmpdir / "probe"
        result = self._run_init(extra_env={"XP_AGENTS_DATA": str(probe)})
        self.assertEqual(result.returncode, 0, result.stderr)
        return Path(result.stdout.strip()).parent.name

    def _seed_legacy(self, home: Path) -> Path:
        smm = (
            home
            / ".claude"
            / "plugins"
            / "data"
            / "xp-agents-xp-agents"
            / self._project_id()
            / "smm"
        )
        (smm / "retrospectives").mkdir(parents=True)
        (smm / "events.jsonl").write_text('{"e":1}\n')
        (smm / "retrospectives" / "r1.json").write_text('{"keep":[]}')
        return smm

    def _new_smm(self, home: Path) -> Path:
        return home / ".xp-agents" / "data" / self._project_id() / "smm"

    def _tool(self, home: Path, *args: str, **env_extra: str):
        """Run the real script against a temp HOME, in the class temp repo.

        The data-root pin from setUpClass is dropped unless a case sets it, so
        the tool exercises the same discovery path a real upgrade takes.
        """
        env = self._test_env.copy()
        env["HOME"] = str(home)
        for name in ("XP_AGENTS_DATA", "CLAUDE_PLUGIN_DATA", "SMM_DIR"):
            if name not in env_extra:
                env.pop(name, None)
        env.update(env_extra)
        return subprocess.run(
            [sys.executable, str(_SCRIPT), *args],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(self.tmpdir),
            env=env,
        )


class TestDryRunChangesNothing(_ToolCase):
    def test_default_run_reports_without_relocating(self):
        home = self._home("dry")
        legacy = self._seed_legacy(home)
        result = self._tool(home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(legacy), result.stdout)
        self.assertIn("at risk:     YES", result.stdout)
        self.assertIn("Dry run", result.stdout)
        self.assertFalse(self._new_smm(home).exists())

    def test_report_names_the_destination_and_the_contents(self):
        home = self._home("report")
        self._seed_legacy(home)
        result = self._tool(home)
        self.assertIn(str(self._new_smm(home)), result.stdout)
        # Exact counts are not pinned: resolution seeds any missing defaults,
        # so the number tracks the seed set rather than this fixture.
        self.assertRegex(result.stdout, r"contents:\s+[1-9]\d* files, [\d.]+ \w+")

    def test_safe_root_reports_nothing_to_do(self):
        home = self._home("safe")
        safe_root = self.tmpdir / "chosen-root"
        result = self._tool(home, XP_AGENTS_DATA=str(safe_root))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("at risk:     no", result.stdout)
        self.assertIn("Nothing to do", result.stdout)

    def test_a_safe_root_does_not_claim_signals_hold_relocation_back(self):
        """Nothing is holding back a relocation that is not wanted.

        A safe root with a leftover worktree directory used to print "N
        live-teammate signal(s), which hold relocation back", advise clearing
        them so "the next session relocates on its own", and then finish with
        "Nothing to do." — three lines that contradict each other and send the
        user to delete a directory for no reason.
        """
        home = self._home("safe-signals")
        safe_root = self.tmpdir / "chosen-root-signals"
        first = self._tool(home, XP_AGENTS_DATA=str(safe_root))
        self.assertEqual(first.returncode, 0, first.stderr)
        current = Path(
            next(
                line.split("current:")[1].strip()
                for line in first.stdout.splitlines()
                if "current:" in line
            )
        )
        (current.parent / "worktrees" / "worktree-story-001").mkdir(parents=True)

        result = self._tool(home, XP_AGENTS_DATA=str(safe_root))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("at risk:     no", result.stdout)
        self.assertIn("Nothing to do", result.stdout)
        self.assertNotIn("hold relocation back", result.stdout)
        self.assertNotIn("relocates on its own", result.stdout)


class TestRefusals(_ToolCase):
    def test_refuses_to_relocate_while_a_worktree_exists(self):
        home = self._home("blocked")
        legacy = self._seed_legacy(home)
        (legacy.parent / "worktrees" / "worktree-story-001").mkdir(parents=True)
        result = self._tool(home, "--confirm")
        self.assertEqual(result.returncode, 1)
        self.assertIn("worktrees/worktree-story-001", result.stdout)
        self.assertIn("Refusing to relocate", result.stderr)
        self.assertFalse(self._new_smm(home).exists())

    def test_refuses_while_an_in_place_marker_exists(self):
        home = self._home("blocked-marker")
        legacy = self._seed_legacy(home)
        (legacy / ".in-place-active-worktree-story-002").write_text("live")
        result = self._tool(home, "--confirm")
        self.assertEqual(result.returncode, 1)
        self.assertIn(".in-place-active-worktree-story-002", result.stdout)
        # Assert the TOOL refused, not merely that nothing moved: init.sh's own
        # gate also blocks here and also exits 1, so a weaker assertion passes
        # even with this refusal deleted.
        self.assertIn("Refusing to relocate", result.stderr)
        self.assertFalse(self._new_smm(home).exists())

    def test_refuses_when_smm_dir_is_pinned(self):
        """A pinned handle short-circuits resolution, so anything this tool
        reported would describe a different SMM than the one in use."""
        home = self._home("pinned")
        self._seed_legacy(home)
        result = self._tool(home, SMM_DIR=str(self.tmpdir / "elsewhere"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("SMM_DIR is set", result.stderr)


class TestRelocation(_ToolCase):
    def test_confirm_relocates_and_verifies(self):
        home = self._home("go")
        legacy = self._seed_legacy(home)
        result = self._tool(home, "--confirm")
        self.assertEqual(result.returncode, 0, result.stderr)
        new = self._new_smm(home)
        self.assertIn(f"Relocated to {new}", result.stdout)
        self.assertIn("Verified:", result.stdout)
        self.assertEqual((new / "events.jsonl").read_text(), '{"e":1}\n')
        # Source survives, and the tool says so rather than leaving the user
        # to guess whether it is safe to delete.
        self.assertTrue(legacy.exists())
        self.assertIn(f"The old copy is still at {legacy}", result.stdout)

    def test_confirm_relocates_past_a_crashed_runs_dead_lock(self):
        """A dead lock costs a SESSION a relocation, never this command.

        No resolver removes a lock any more: breaking one is a read then a
        delete, and no shell primitive makes that pair indivisible, so init.sh
        now leaves a dead lock alone and answers legacy every time. Clearing it
        is this command's own job — supervised, one invocation, and it refuses on
        a live holder. The clear itself is pinned in
        tests/smm/test_migration_lock_never_broken.py; this is the CLI path.
        """
        home = self._home("deadlock")
        legacy = self._seed_legacy(home)
        lock = self._new_smm(home).parent / ".migrate.lock"
        lock.parent.mkdir(parents=True)
        lock.symlink_to("999999")

        result = self._tool(home, "--confirm")
        self.assertEqual(result.returncode, 0, result.stderr)
        new = self._new_smm(home)
        self.assertIn(f"Relocated to {new}", result.stdout)
        self.assertEqual((new / "events.jsonl").read_text(), '{"e":1}\n')
        self.assertTrue(legacy.exists())
        self.assertFalse(lock.is_symlink(), "the dead lock must not survive")

    def test_force_relocates_past_a_stale_worktree(self):
        home = self._home("forced")
        legacy = self._seed_legacy(home)
        (legacy.parent / "worktrees" / "worktree-story-001").mkdir(parents=True)
        result = self._tool(home, "--force")
        self.assertEqual(result.returncode, 0, result.stderr)
        new = self._new_smm(home)
        self.assertEqual((new / "events.jsonl").read_text(), '{"e":1}\n')
        self.assertTrue(legacy.exists())
        # The report must not claim relocation is blocked and then relocate.
        self.assertNotIn("Relocation is blocked", result.stdout)
        self.assertIn(
            "--force: relocating despite 1 live-teammate signal", result.stdout
        )

    def test_force_names_the_worktrees_it_strands(self):
        """Only `smm/` moves; the sibling worktrees stay put, and
        `worktree.worktree_path()` derives placement from the SMM's parent — so
        after a forced move the tooling looks for them under the new root and
        cleanup fails. Silent is the one thing that must not happen."""
        home = self._home("stranded")
        legacy = self._seed_legacy(home)
        stale = legacy.parent / "worktrees" / "worktree-story-001"
        stale.mkdir(parents=True)
        result = self._tool(home, "--force")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("did NOT move", result.stderr)
        self.assertIn(str(stale), result.stderr)
        self.assertTrue(stale.is_dir())

    def test_clean_relocation_warns_about_no_worktrees(self):
        """The stranded-worktree warning is conditional on there being any —
        a normal relocation must not emit a scary paragraph about nothing."""
        home = self._home("clean")
        self._seed_legacy(home)
        result = self._tool(home, "--confirm")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("did NOT move", result.stderr)

    def test_second_run_after_relocation_is_a_no_op(self):
        home = self._home("twice")
        self._seed_legacy(home)
        self.assertEqual(self._tool(home, "--confirm").returncode, 0)
        again = self._tool(home)
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertIn("at risk:     no", again.stdout)
        self.assertIn("Nothing to do", again.stdout)


if __name__ == "__main__":
    unittest.main()

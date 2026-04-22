#!/usr/bin/env python3
"""Tests for SMM initialization.

Covers TestInit, TestInitHonorsSmmDirEnv, TestSeedSMM.
Event validation tests live in test_event_validation.py.
"""

import subprocess
import sys
import unittest
from pathlib import Path

# Path setup -- allow importing production modules and conftest
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
from conftest import _TempRepoTestCase


class TestInit(_TempRepoTestCase):
    """Tests for smm/init.sh."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.smm_dir = cls._get_smm_dir()

    def setUp(self) -> None:
        # Reset events.jsonl before each test
        (self.smm_dir / "events.jsonl").write_text("")

    def test_init_succeeds(self):
        result = self._run_init(extra_env={"SMM_DIR": ""})
        self.assertEqual(result.returncode, 0)
        smm_dir = result.stdout.strip()
        self.assertTrue(Path(smm_dir).is_dir())

    def test_init_idempotent(self):
        r1 = self._run_init(extra_env={"SMM_DIR": ""})
        r2 = self._run_init(extra_env={"SMM_DIR": ""})
        self.assertEqual(r1.returncode, 0)
        self.assertEqual(r2.returncode, 0)
        self.assertEqual(r1.stdout.strip(), r2.stdout.strip())

    def test_init_creates_structure(self):
        smm_dir = self._get_smm_dir()
        self.assertTrue((smm_dir / "events.jsonl").exists())
        self.assertTrue((smm_dir / "events.lock").exists())
        self.assertTrue((smm_dir / "retrospectives").is_dir())

    def test_init_events_file_permissions(self):
        smm_dir = self._get_smm_dir()
        events_file = smm_dir / "events.jsonl"
        mode = events_file.stat().st_mode & 0o777
        self.assertEqual(mode, 0o600, f"events.jsonl mode is {oct(mode)}")

    def test_init_lock_file_permissions(self):
        smm_dir = self._get_smm_dir()
        lock_file = smm_dir / "events.lock"
        mode = lock_file.stat().st_mode & 0o777
        self.assertEqual(mode, 0o600, f"events.lock mode is {oct(mode)}")

    def test_init_smm_dir_permissions(self):
        smm_dir = self._get_smm_dir()
        mode = smm_dir.stat().st_mode & 0o777
        self.assertEqual(mode, 0o700, f"SMM dir mode is {oct(mode)}")

    def test_init_retrospectives_dir_permissions(self):
        smm_dir = self._get_smm_dir()
        retro_dir = smm_dir / "retrospectives"
        mode = retro_dir.stat().st_mode & 0o777
        self.assertEqual(
            mode,
            0o700,
            f"retrospectives dir mode is {oct(mode)}",
        )

    def test_init_does_not_truncate_existing(self):
        smm_dir = self._get_smm_dir()
        events_file = smm_dir / "events.jsonl"
        events_file.write_text("existing content\n")

        self._run_init()

        self.assertEqual(events_file.read_text(), "existing content\n")


class TestInitHonorsSmmDirEnv(_TempRepoTestCase):
    """When SMM_DIR env var is set, init.sh uses that path."""

    def _run_init_with_smm(self, smm_dir: str | Path) -> subprocess.CompletedProcess:
        return self._run_init(extra_env={"SMM_DIR": str(smm_dir)})

    def test_echoes_smm_dir_when_set(self):
        target = self.tmpdir / "custom-smm"
        result = self._run_init_with_smm(target)
        self.assertEqual(
            result.returncode,
            0,
            f"init.sh failed: {result.stderr}",
        )
        self.assertEqual(result.stdout.strip(), str(target))

    def test_creates_structure_at_smm_dir(self):
        target = self.tmpdir / "custom-smm-structure"
        result = self._run_init_with_smm(target)
        self.assertEqual(
            result.returncode,
            0,
            f"init.sh failed: {result.stderr}",
        )
        self.assertTrue(target.is_dir(), "target dir should exist")
        self.assertTrue((target / "events.jsonl").exists())
        self.assertTrue((target / "events.lock").exists())
        self.assertTrue((target / "retrospectives").is_dir())

    def test_creates_nested_nonexistent_path(self):
        target = self.tmpdir / "deep" / "nested" / "path" / "smm"
        result = self._run_init_with_smm(target)
        self.assertEqual(
            result.returncode,
            0,
            f"init.sh failed: {result.stderr}",
        )
        self.assertTrue(target.is_dir())

    def test_idempotent_on_rerun(self):
        target = self.tmpdir / "idempotent-smm"
        r1 = self._run_init_with_smm(target)
        (target / "events.jsonl").write_text("existing\n")
        r2 = self._run_init_with_smm(target)
        self.assertEqual(r1.returncode, 0)
        self.assertEqual(r2.returncode, 0)
        self.assertEqual(r1.stdout.strip(), r2.stdout.strip())
        self.assertEqual((target / "events.jsonl").read_text(), "existing\n")

    def test_empty_smm_dir_falls_through_to_derivation(self):
        """Empty string should derive normally."""
        result = self._run_init_with_smm("")
        self.assertEqual(result.returncode, 0)
        derived = Path(result.stdout.strip())
        self.assertTrue(
            str(derived).startswith(str(self._plugin_data_dir)),
            f"expected derived path under {self._plugin_data_dir}, got {derived}",
        )

    def test_inherited_base_dir_is_not_chmodded(self):
        """When SMM_DIR is set, BASE_DIR must NOT be chmodded."""
        target = self.tmpdir / "custom-smm-no-basedir-leak"
        stray = self.tmpdir / "stray-base-dir"
        stray.mkdir(mode=0o755)
        original_mode = stray.stat().st_mode & 0o777
        self.assertEqual(original_mode, 0o755)

        result = self._run_init(
            extra_env={
                "SMM_DIR": str(target),
                "BASE_DIR": str(stray),
            }
        )
        self.assertEqual(
            result.returncode,
            0,
            f"init.sh failed: {result.stderr}",
        )
        self.assertEqual(
            stray.stat().st_mode & 0o777,
            0o755,
            "init.sh leaked chmod to an inherited BASE_DIR",
        )


class TestSeedSMM(_TempRepoTestCase):
    """Tests for seed_smm.py -- default SMM created by init.sh."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.smm_dir = cls._get_smm_dir()

    def _load_smm(self) -> dict:
        import json

        path = self.smm_dir / "shared_mental_model.json"
        return json.loads(path.read_text())

    def test_seed_creates_smm_file(self):
        smm_file = self.smm_dir / "shared_mental_model.json"
        self.assertTrue(
            smm_file.exists(),
            "init.sh should seed shared_mental_model.json",
        )

    def test_seed_has_four_pillars(self):
        smm = self._load_smm()
        for pillar in ("intent", "constraints", "risks", "wisdom"):
            self.assertIn(pillar, smm)
            self.assertIsInstance(smm[pillar], list)

    def test_seed_has_xp_constraints(self):
        smm = self._load_smm()
        contents = [e["content"] for e in smm["constraints"]]
        joined = " ".join(contents)
        self.assertIn("TDD", joined)
        self.assertIn("Small commits", joined)

    def test_seed_detects_missing_linter(self):
        """Fresh git repo has no linter -- should be flagged."""
        smm = self._load_smm()
        contents = [e["content"] for e in smm["risks"]]
        joined = " ".join(contents)
        self.assertIn("No linter configured", joined)

    def test_seed_detects_missing_hooks(self):
        """Fresh git repo has no hooks -- should be flagged."""
        smm = self._load_smm()
        contents = [e["content"] for e in smm["risks"]]
        joined = " ".join(contents)
        self.assertIn("No git commit hooks", joined)

    def test_seed_idempotent(self):
        """Running init.sh again does not overwrite existing SMM."""
        smm_file = self.smm_dir / "shared_mental_model.json"
        smm_file.write_text('{"custom": true}')
        self._run_init()
        self.assertEqual(smm_file.read_text(), '{"custom": true}')

    def test_seed_fires_when_only_old_md_exists(self):
        """Old .md present but no JSON -> seed fires."""
        json_file = self.smm_dir / "shared_mental_model.json"
        md_file = self.smm_dir / "SHARED_MENTAL_MODEL.md"
        json_file.unlink(missing_ok=True)
        md_file.write_text("# Old markdown SMM\n")
        self._run_init()
        self.assertTrue(json_file.exists())
        self.assertTrue(md_file.exists())
        self.assertEqual(md_file.read_text(), "# Old markdown SMM\n")


if __name__ == "__main__":
    unittest.main()

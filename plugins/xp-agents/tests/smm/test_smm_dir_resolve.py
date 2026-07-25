#!/usr/bin/env python3
"""Tests for smm_dir_resolve — the in-process half of SMM path resolution.

This module is the single resolver behind every hook, append and CLI that does
NOT go through session_start's own guarded call. That makes its failure
handling load-bearing in a way a normal helper's is not: anything it raises
crashes the hook that called it, and init.sh — the shell half, on the same
inputs — degrades gracefully instead. The two halves must fail the same way.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))


class _ResolveCase(unittest.TestCase):
    def setUp(self):
        import smm_dir_resolve

        self.mod = smm_dir_resolve
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.smm = self.tmp / "smm"
        self.smm.mkdir()


class TestFollowMigrationPointer(_ResolveCase):
    def test_a_pointer_to_a_real_dir_is_followed(self):
        target = self.tmp / "new-smm"
        target.mkdir()
        (self.smm / self.mod.MIGRATION_POINTER).write_text(f"{target}\n")
        self.assertEqual(self.mod.follow_migration_pointer(self.smm), target)

    def test_no_pointer_returns_the_input(self):
        self.assertEqual(self.mod.follow_migration_pointer(self.smm), self.smm)

    def test_a_pointer_that_is_not_utf8_degrades_to_the_input(self):
        """init.sh's `cat` does not care what bytes are in this file, and its
        `[[ -d ]]` test rejects the garbage; the Python half used to raise
        UnicodeDecodeError straight out of resolve_smm_dir and crash EVERY hook
        on the same input. A resolver whose two halves disagree about what is
        fatal is worse than either behavior.
        """
        (self.smm / self.mod.MIGRATION_POINTER).write_bytes(b"\xff\xfe/not/utf8")
        self.assertEqual(self.mod.follow_migration_pointer(self.smm), self.smm)

    def test_a_pointer_to_a_missing_dir_degrades_to_the_input(self):
        (self.smm / self.mod.MIGRATION_POINTER).write_text(str(self.tmp / "gone"))
        self.assertEqual(self.mod.follow_migration_pointer(self.smm), self.smm)


class TestPublicPointerName(_ResolveCase):
    """It has a consumer in another package (``identity``) and a public shell
    twin (``follow_migration_pointer`` in init.sh). A name two modules reach
    across is not a private one, and the underscore made the shell/Python pair
    read as different things."""

    def test_the_private_alias_is_gone(self):
        self.assertFalse(hasattr(self.mod, "_follow_migration_pointer"))

    def test_identitys_pinned_handle_follows_a_relocation(self):
        """The behavior the cross-module import exists for.

        A teammate's SMM_DIR is pinned to an absolute path at spawn. If the
        tree relocates under it, this reader has to land on the same tree every
        other reader and writer uses, or the teammate reads as the lead.
        """
        import identity
        import marker_names

        moved = self.tmp / "relocated-smm"
        moved.mkdir()
        name = "worktree-story-001"
        (moved / marker_names.IN_PLACE_ACTIVE.format(name=name)).write_text("{}")
        (self.smm / self.mod.MIGRATION_POINTER).write_text(str(moved))

        with patch.dict(
            "os.environ", {"XP_TEAMMATE_NAME": name, "SMM_DIR": str(self.smm)}
        ):
            self.assertEqual(identity.in_place_teammate_name(), name)


class TestDeriveTimeout(_ResolveCase):
    """init.sh's worst case is no longer a path lookup.

    It can copy the WHOLE SMM twice and wait out a lock, so an unbounded
    subprocess call here hangs whichever hook made it — indefinitely, if the
    script wedges. session_start has its own guarded call with a budget; every
    OTHER in-process resolver arrives through this one and had none.
    """

    def test_it_passes_a_timeout(self):
        with patch.object(self.mod.subprocess, "check_output") as run:
            run.return_value = f"{self.smm}\n"
            self.mod._derive_smm_dir()
        self.assertIsNotNone(
            run.call_args.kwargs.get("timeout"), "init.sh must be run with a timeout"
        )

    def test_an_expired_timeout_resolves_to_none(self):
        with patch.object(
            self.mod.subprocess,
            "check_output",
            side_effect=subprocess.TimeoutExpired(cmd="init.sh", timeout=1),
        ):
            self.assertIsNone(self.mod._derive_smm_dir())


if __name__ == "__main__":
    unittest.main()

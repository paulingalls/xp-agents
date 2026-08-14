#!/usr/bin/env python3
"""Tests for skill_preload_map.py — the skill-to-preload-invocation resolver.

Story context: the per-skill `!`...`` preload line in SKILL.md is the only
existing record of which command each skill's preload is. A later story
deletes those lines; this resolver is what replaces the record they carried,
so both a shell-preload harness and a locator-only harness can run the same
invocation from one source.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import skill_preload_map
from conftest import _PLUGIN_ROOT

_SKILLS_DIR = _PLUGIN_ROOT / "skills"

# Same non-vacuity guard as test_preload_wiring.py: a scan of nothing must not
# read as green.
_EXPECTED_PRELOADS = 17

# The two skills that ship no scripts/*.sh at all — absence, not failure.
_NO_PRELOAD_SKILLS = ("xp-scaffold-acceptance", "xp-stage-migration")


def _all_preload_skill_names() -> list[str]:
    return sorted(
        script.parent.parent.name for script in _SKILLS_DIR.glob("*/scripts/*.sh")
    )


class TestCommonDefaultResolution(unittest.TestCase):
    """15 of 17 preload-bearing skills resolve to `scripts/preload.sh` with
    no extra arguments — the common default."""

    def test_the_scan_finds_every_preload(self):
        self.assertEqual(
            len(_all_preload_skill_names()),
            _EXPECTED_PRELOADS,
            "the preload glob drifted — a scan of nothing reads as green",
        )

    def test_common_default_resolves_to_preload_sh(self):
        invocation = skill_preload_map.resolve_preload("xp-accept")
        assert invocation is not None
        self.assertEqual(Path(invocation.argv[0]).name, "preload.sh")
        self.assertEqual(invocation.argv[1:], [])

    def test_argv0_is_absolute(self):
        invocation = skill_preload_map.resolve_preload("xp-accept")
        assert invocation is not None
        self.assertTrue(Path(invocation.argv[0]).is_absolute())

    def test_argv0_file_exists(self):
        invocation = skill_preload_map.resolve_preload("xp-accept")
        assert invocation is not None
        self.assertTrue(Path(invocation.argv[0]).is_file())

    def test_every_common_default_skill_resolves(self):
        outliers = {"xp-assign", "xp-kickoff"}
        for name in _all_preload_skill_names():
            if name in outliers:
                continue
            with self.subTest(skill=name):
                invocation = skill_preload_map.resolve_preload(name)
                assert invocation is not None
                self.assertEqual(Path(invocation.argv[0]).name, "preload.sh")
                self.assertEqual(invocation.argv[1:], [])

    def test_two_sh_files_in_one_scripts_dir_raises(self):
        """The glob's one-script-per-skill assumption is guarded loudly,
        not silently resolved by picking one."""
        real_glob = Path.glob

        def fake_glob(self, pattern):
            results = list(real_glob(self, pattern))
            if self == _SKILLS_DIR and pattern == "*/scripts/*.sh":
                extra = _SKILLS_DIR / "xp-accept" / "scripts" / "extra_preload.sh"
                results.append(extra)
            return results

        with patch.object(Path, "glob", fake_glob), self.assertRaises(ValueError):
            skill_preload_map.resolve_preload("xp-accept")


class TestOutliers(unittest.TestCase):
    """The two skills that do NOT use the common default. No name list
    substitutes the default for either — a hardcoded default would be right
    on 15 skills and wrong on these two."""

    def test_xp_kickoff_resolves_to_its_own_script_name(self):
        """xp-kickoff ships check_session_needs.sh, not preload.sh — the
        glob finds it with no name list involved."""
        invocation = skill_preload_map.resolve_preload("xp-kickoff")
        assert invocation is not None
        self.assertEqual(Path(invocation.argv[0]).name, "check_session_needs.sh")
        self.assertEqual(invocation.argv[1:], [])

    def test_xp_assign_carries_consume_gate(self):
        invocation = skill_preload_map.resolve_preload("xp-assign")
        assert invocation is not None
        self.assertEqual(Path(invocation.argv[0]).name, "preload.sh")
        self.assertEqual(invocation.argv[1:], ["--consume-gate"])

    def test_extra_args_table_is_subset_of_discovered_skills(self):
        """Superset guard: every _EXTRA_ARGS key must name a skill the glob
        actually discovered. A renamed or deleted skill leaves a loud dead
        entry here rather than a silently ignored one."""
        discovered = set(_all_preload_skill_names())
        extra_args_keys = set(skill_preload_map._EXTRA_ARGS.keys())
        self.assertTrue(
            extra_args_keys <= discovered,
            f"_EXTRA_ARGS names skills the glob no longer finds: "
            f"{extra_args_keys - discovered}",
        )


class TestEnvironmentContract(unittest.TestCase):
    """`env` names the variables a consumer must forward, resolved where an
    ambient value exists. Not a copy of the ambient environment — a
    sanitized-env consumer (a hook process) is exactly who needs this."""

    def test_invocation_names_claude_plugin_data(self):
        invocation = skill_preload_map.resolve_preload("xp-accept")
        assert invocation is not None
        self.assertIn("CLAUDE_PLUGIN_DATA", invocation.env)

    def test_resolves_ambient_value_when_set(self):
        with patch.dict(os.environ, {"CLAUDE_PLUGIN_DATA": "/some/data/root"}):
            invocation = skill_preload_map.resolve_preload("xp-accept")
        assert invocation is not None
        self.assertEqual(invocation.env["CLAUDE_PLUGIN_DATA"], "/some/data/root")

    def test_tolerates_empty_claude_plugin_data(self):
        """Empty is a SUPPORTED state — legacy SMM discovery skips it and
        falls back to a candidate list; it must not raise."""
        env = dict(os.environ)
        env.pop("CLAUDE_PLUGIN_DATA", None)
        with patch.dict(os.environ, env, clear=True):
            invocation = skill_preload_map.resolve_preload("xp-accept")
        assert invocation is not None
        self.assertEqual(invocation.env["CLAUDE_PLUGIN_DATA"], "")


if __name__ == "__main__":
    unittest.main()

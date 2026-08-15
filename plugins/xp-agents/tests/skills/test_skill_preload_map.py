#!/usr/bin/env python3
"""Tests for skill_preload_map.py — the skill-to-preload-invocation resolver.

Story context: the per-skill `!`...`` preload line in SKILL.md is the only
existing record of which command each skill's preload is. A later story
deletes those lines; this resolver is what replaces the record they carried,
so both a shell-preload harness and a locator-only harness can run the same
invocation from one source.
"""

import os
import re
import shlex
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

# The only skills that still carry an instruction-time `!`...`` line, and so the
# only ones the conformance pin below still has an oracle for. They are the
# forked ones: injection reaches the parent and stops at the fork boundary, so
# these three cannot be delivered by it until they are converted to spawn their
# own subagent. Spelled literally rather than discovered by scanning for the
# line — derived, this set would silently follow whatever the tree happens to
# say, and the pin would report green on a tree where someone had deleted a
# line that was still load-bearing.
_LINE_BEARING_SKILLS = frozenset(
    {"xp-review-plan", "xp-sprint-review", "xp-system-context"}
)


def _all_preload_skill_names() -> list[str]:
    return sorted(
        script.parent.parent.name for script in _SKILLS_DIR.glob("*/scripts/*.sh")
    )


# The oracle for the conformance pin below: the `!`...`` invocation line
# itself, matching the same shape test_preload_wiring.py keys off. This
# regex is the ONLY line-shaped assumption this module makes — it is a test
# fixture for reading the plugin's OWN shipped declaration, not language
# parsing of any user-project code.
_INVOCATION_LINE_RE = re.compile(r"^!`(.+)`$")
_ENV_ASSIGNMENT_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=")


def _parse_skill_md_invocation(skill_name: str) -> tuple[list[str], list[str]]:
    """Parse `skill_name`'s `!`...`` line into (required env names, argv
    tail), where argv tail is [script_filename, *args] — everything the
    resolver is responsible for reproducing.

    Whole-line parse, not a script-path needle: a needle is blind to
    exactly the two facts this story exists to get right (a dropped
    argument, a dropped env name).
    """
    skill_md = _SKILLS_DIR / skill_name / "SKILL.md"
    for line in skill_md.read_text(encoding="utf-8").splitlines():
        m = _INVOCATION_LINE_RE.match(line)
        if not m:
            continue
        tokens = shlex.split(m.group(1))
        env_names = []
        i = 0
        while i < len(tokens):
            env_match = _ENV_ASSIGNMENT_RE.match(tokens[i])
            if not env_match:
                break
            env_names.append(env_match.group(1))
            i += 1
        argv_tail = tokens[i:]
        if not argv_tail:
            continue
        script_name = Path(argv_tail[0]).name
        return env_names, [script_name, *argv_tail[1:]]
    raise AssertionError(f"{skill_name} has no `!`...`` invocation line")


def _assert_conforms(skill_name: str) -> None:
    env_names, argv_tail = _parse_skill_md_invocation(skill_name)
    invocation = skill_preload_map.resolve_preload(skill_name)
    assert invocation is not None
    resolved_argv_tail = [Path(invocation.argv[0]).name, *invocation.argv[1:]]
    if resolved_argv_tail != argv_tail:
        raise AssertionError(
            f"{skill_name}: resolver argv {resolved_argv_tail!r} != "
            f"SKILL.md line {argv_tail!r}"
        )
    if set(invocation.env.keys()) != set(env_names):
        raise AssertionError(
            f"{skill_name}: resolver env {sorted(invocation.env)!r} != "
            f"SKILL.md line {sorted(env_names)!r}"
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


class TestAbsenceVsFailure(unittest.TestCase):
    """Three distinct cases: no preload (None), no preload but required
    (raises), and no such skill at all (raises from resolve_preload
    itself — collapsing this into None would erase the distinction between
    "this skill has no preload" and "there is no such skill")."""

    def test_no_preload_skills_are_in_the_shipped_tree(self):
        for name in _NO_PRELOAD_SKILLS:
            with self.subTest(skill=name):
                self.assertTrue((_SKILLS_DIR / name).is_dir())

    def test_skill_with_no_preload_returns_none(self):
        for name in _NO_PRELOAD_SKILLS:
            with self.subTest(skill=name):
                self.assertIsNone(skill_preload_map.resolve_preload(name))

    def test_required_raises_when_no_preload(self):
        for name in _NO_PRELOAD_SKILLS:
            with self.subTest(skill=name), self.assertRaises(ValueError):
                skill_preload_map.resolve_preload_required(name)

    def test_unknown_skill_name_raises_from_resolve_preload(self):
        with self.assertRaises(ValueError):
            skill_preload_map.resolve_preload("xp-does-not-exist")

    def test_path_shaped_name_raises_rather_than_reading_as_no_preload(self):
        """Only a bare directory name can key the glob's results. An empty
        name, `.`, `..`, a nested path and an absolute path all pass an
        `is_dir()` check under `skills/` while matching no key — without a
        shape check each returns None, telling a caller "this skill ships no
        preload" about a name that names no skill. The empty one is the
        reachable case: a consumer reading the skill name out of hook input
        gets `""` when the field is missing."""
        for name in ("", ".", "..", "xp-accept/scripts", "/tmp"):
            with self.subTest(skill=name), self.assertRaises(ValueError):
                skill_preload_map.resolve_preload(name)


class TestConformancePin(unittest.TestCase):
    """The resolver must reproduce every REMAINING `!`...`` line exactly —
    argv AND env, not just "some script ran".

    **Retired down, deliberately, when the lines were deleted.** This module's
    docstring said the day would come and named the obligation: retire or
    repoint, never leave the pin in place quietly checking nothing. Fourteen
    inline skills now get their state by injection and have no line to conform
    to; the three forked ones still carry theirs, because injection was measured
    not to cross the fork boundary. So the oracle still exists — for three
    skills instead of seventeen — and the pin follows it down rather than
    pretending to a coverage it lost.

    The pin retires completely when those three are converted. Whoever does that
    should delete this class and `_parse_skill_md_invocation` with it, rather
    than leave a scan of an empty set reporting green.
    """

    def test_every_remaining_line_conforms_to_the_resolver(self):
        for name in sorted(_LINE_BEARING_SKILLS):
            with self.subTest(skill=name):
                _assert_conforms(name)

    def test_the_line_bearing_set_is_not_empty(self):
        """Non-vacuity, and it is not hypothetical here: the set shrank from
        seventeen to three in one commit and goes to zero in another. At zero,
        every assertion above passes by iterating nothing."""
        self.assertTrue(
            _LINE_BEARING_SKILLS,
            "no skill carries an instruction-time line — retire this class "
            "rather than let it scan an empty set",
        )

    def test_pin_catches_a_dropped_env_name(self):
        """Mutation proof: dropping the required env name must turn the pin
        red — a script-name-only check would miss this.

        Matched on the env-mismatch message, not on bare AssertionError:
        `_assert_conforms`'s own `assert invocation is not None` raises that
        type too, so an unmatched assertRaises would go green on a resolver
        that had stopped resolving anything at all."""
        subject = sorted(_LINE_BEARING_SKILLS)[0]
        with (
            patch.object(skill_preload_map, "_REQUIRED_ENV", ()),
            self.assertRaisesRegex(AssertionError, "resolver env"),
        ):
            _assert_conforms(subject)
        # Reverted: the table is unpatched again here, proven by conformance.
        _assert_conforms(subject)

    # The argv mutation proof is GONE, not moved, and the reason is worth
    # stating: it dropped `--consume-gate` from the table and watched the pin
    # go red, and the only skill taking an extra argument is `xp-assign`, which
    # is inline and no longer has a line to conform to. Against the three that
    # remain — all plain `preload.sh` with no arguments — emptying `_EXTRA_ARGS`
    # changes nothing, so the same test would have passed while proving
    # nothing. `TestOutliers.test_xp_assign_carries_consume_gate` still pins the
    # value directly, and the gate's own suite pins that the resolver is what
    # carries it.


if __name__ == "__main__":
    unittest.main()

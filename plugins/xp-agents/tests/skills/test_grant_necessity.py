#!/usr/bin/env python3
"""A skill may pre-approve a script path only if something still runs it.

`allowed-tools` widens what the MODEL may run from a skill body. Sprint-007
deleted every instruction-time `!` line, and `preload_injection.py` now runs
each preload with `subprocess.run` from inside the hook — which never consults
`allowed-tools` at all. So `Bash(*/skills/*/scripts/*)` stopped being
load-bearing for the thing it was added for, and survived in 16 skills.

Dead pre-approval is not inert: it widens each skill's permission surface for
no benefit, and a reader auditing what a skill may do gets a wrong answer.

**Necessity is decided by what the glob matches at runtime, never by one
spelling.** Three legs, and the audit that preceded this file got each of them
wrong in turn — which is why they are computed here rather than listed:

1. **Both path spellings.** `skills/<name>/scripts/...` and
   `${CLAUDE_SKILL_DIR}/scripts/...` reach the same files. `xp-end-session`
   uses only the second, so a scan for the first reads it as dead and would
   have removed a grant it needs.
2. **Shared prose a preload injects.** `scripts/_close_pipeline_shared.md` runs
   `skills/xp-work-selection/scripts/*.py`, and four close preloads `cat` it
   into their output. Those commands reach the model from a file that is not
   the skill's own `SKILL.md`, so a file-only scan cannot see them.
3. **Bare `Bash` subsumes a pattern grant.** Six skills declare a bare `Bash`
   entry, which already permits every command; alongside it a `Bash(pattern)`
   entry grants nothing. All four close skills from leg 2 are in this set, so
   legs 2 and 3 point opposite ways and only both together give the answer.

The count that falls out is 2 needed / 14 dead. An earlier audit reported 10
dead by getting leg 3 wrong, and the concern's original 14 was right.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import _PLUGIN_ROOT

_SKILLS_DIR = _PLUGIN_ROOT / "skills"
_SCRIPTS_DIR = _PLUGIN_ROOT / "scripts"

# The grant under audit. Written once: a test that spells its subject twice can
# drift from the thing it audits.
_GRANT = "Bash(*/skills/*/scripts/*)"

# What the grant matches when the model runs it. Both spellings resolve to a
# file under some skill's `scripts/`, which is the whole point of leg 1.
_MATCHES_GRANT = re.compile(
    r"(?:\$\{CLAUDE_SKILL_DIR\}|skills/[a-z0-9-]+)/scripts/[A-Za-z0-9_.-]+"
)

# A bare `Bash` entry in an allowed-tools list — no parenthesised pattern.
_BARE_BASH = re.compile(r"^\s*-\s*Bash\s*$", re.MULTILINE)

# Shared prose injected by a preload, e.g. `_close_pipeline_shared.md`.
_SHARED_PROSE = re.compile(r"_[a-z_]+\.md")


def _skill_dirs() -> list[Path]:
    return sorted(p for p in _SKILLS_DIR.iterdir() if (p / "SKILL.md").is_file())


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Frontmatter and body. A skill with no frontmatter yields ("", text)."""
    if not text.startswith("---\n"):
        return "", text
    _, _, rest = text.partition("---\n")
    front, sep, body = rest.partition("\n---")
    return (front, body) if sep else ("", text)


def _grants_the_pattern(front: str) -> bool:
    return _GRANT in front


def _declares_bare_bash(front: str) -> bool:
    return bool(_BARE_BASH.search(front))


def _body_runs_a_matching_path(body: str) -> bool:
    return bool(_MATCHES_GRANT.search(body))


def _injected_prose_runs_a_matching_path(skill: Path) -> bool:
    """Leg 2: does anything this skill's preload injects run a matching path?"""
    for script in sorted((skill / "scripts").glob("*.sh")):
        script_text = script.read_text(encoding="utf-8")
        for name in set(_SHARED_PROSE.findall(script_text)):
            shared = _SCRIPTS_DIR / name
            if shared.is_file() and _MATCHES_GRANT.search(
                shared.read_text(encoding="utf-8")
            ):
                return True
    return False


def _needs_the_grant(skill: Path) -> bool:
    """True when removing `_GRANT` would refuse a command the model still runs.

    Leg 3 comes FIRST and short-circuits: a bare `Bash` already permits
    everything, so the pattern entry cannot be load-bearing no matter what legs
    1 and 2 find. Ordering it last would have kept the four close skills.
    """
    front, body = _split_frontmatter(skill.joinpath("SKILL.md").read_text("utf-8"))
    if _declares_bare_bash(front):
        return False
    return _body_runs_a_matching_path(body) or _injected_prose_runs_a_matching_path(
        skill
    )


class TestNoSkillPreApprovesAPathNothingRuns(unittest.TestCase):
    def test_the_grant_is_held_by_exactly_the_skills_that_need_it(self):
        """One equality, deliberately, so it is red in BOTH directions.

        Two separate assertions ("no unnecessary grant survives", "no necessary
        grant was removed") would each pass while the other failed, and the
        first alone is what a sweep can satisfy by doing nothing. Set equality
        cannot be satisfied by either mistake.
        """
        skills = _skill_dirs()
        holds = {s.name for s in skills if _grants_the_pattern(_front(s))}
        needs = {s.name for s in skills if _needs_the_grant(s)}
        self.assertEqual(
            holds,
            needs,
            "allowed-tools disagrees with what the glob matches at runtime.\n"
            f"  dead pre-approval (remove): {sorted(holds - needs)}\n"
            f"  removed but still used (restore): {sorted(needs - holds)}",
        )

    def test_the_population_is_not_empty(self):
        """A guard whose subject set is empty reads as success — story-017's
        lesson, and the reason this file exists at all."""
        self.assertGreater(len(_skill_dirs()), 10)
        self.assertTrue(
            any(_needs_the_grant(s) for s in _skill_dirs()),
            "no skill needs the grant, so the equality above would be "
            "satisfied by deleting every one of them",
        )

    def test_both_path_spellings_are_recognised(self):
        """Leg 1, pinned on the specimen that exposed it: `xp-end-session`
        reaches its own script only as `${CLAUDE_SKILL_DIR}/scripts/...`, so a
        scan keyed on the literal `skills/<name>/scripts/` spelling calls it
        dead and removes a grant it needs."""
        self.assertTrue(_MATCHES_GRANT.search("${CLAUDE_SKILL_DIR}/scripts/x.py"))
        self.assertTrue(_MATCHES_GRANT.search("skills/xp-work-selection/scripts/x.py"))
        end_session = _SKILLS_DIR / "xp-end-session"
        self.assertTrue(
            _body_runs_a_matching_path(_split_frontmatter(_text(end_session))[1]),
            "xp-end-session no longer runs its own script — if that is "
            "deliberate, this leg's specimen must move to whichever skill does",
        )

    def test_injected_shared_prose_counts_as_a_use(self):
        """Leg 2, pinned on the four close skills. They are excluded by leg 3
        today, so this asserts the LEG rather than the outcome — otherwise the
        only thing keeping the answer right would be an accident of ordering.
        """
        for name in (
            "xp-free-close",
            "xp-plan-close",
            "xp-sprint-close",
            "xp-story-close",
        ):
            with self.subTest(skill=name):
                self.assertTrue(
                    _injected_prose_runs_a_matching_path(_SKILLS_DIR / name),
                    f"{name}'s preload no longer injects prose running a "
                    "matching path; leg 2 has lost its specimen",
                )

    def test_bare_bash_subsumes_the_pattern(self):
        """Leg 3. The finding that corrected the audit from 10 dead to 14."""
        subsumed = [
            s.name
            for s in _skill_dirs()
            if _declares_bare_bash(_front(s)) and _grants_the_pattern(_front(s))
        ]
        self.assertEqual(
            subsumed,
            [],
            "these skills declare a bare `Bash` AND the narrower pattern, so "
            f"the pattern grants nothing: {subsumed}",
        )


def _text(skill: Path) -> str:
    return (skill / "SKILL.md").read_text(encoding="utf-8")


def _front(skill: Path) -> str:
    return _split_frontmatter(_text(skill))[0]


if __name__ == "__main__":
    unittest.main()

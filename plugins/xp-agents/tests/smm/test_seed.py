"""Tests for seed_smm.py — default SMM generation.

Feature detection lives in `seed_detect.py` and is tested against that module
directly in `test_seed_detect.py`.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import seed_smm
import smm_schema

# PROCESS_GUIDE.md documents the Wisdom pillar's 5-10 cap; nothing in
# smm_schema enforces it, so the seeded list is checked here.
_WISDOM_CAP = (5, 10)

# A distinctive substring of every wisdom item seeded before the
# prose-hygiene one. Presence of all of them proves a new item was ADDED
# rather than traded against an existing one.
_WISDOM_SEEDED_BEFORE = (
    "Run /xp-kickoff at every session start",
    "Commit after every green test run",
    "Review cadence (commit | story)",
    "After exiting plan mode",
    "Keep files small with single responsibility",
    "Fail fast, fail loud",
    "Name things well",
    "Test at boundaries",
)


def wisdom_cap_violations(contents: list[str]) -> list[str]:
    """Shortfalls when a seeded wisdom list falls outside the documented cap."""
    low, high = _WISDOM_CAP
    if low <= len(contents) <= high:
        return []
    return [f"seeded wisdom has {len(contents)} items, outside the {low}-{high} cap"]


def missing_wisdom(contents: list[str], expected: tuple[str, ...]) -> list[str]:
    """Every *expected* substring that no entry in *contents* carries."""
    return [want for want in expected if not any(want in got for got in contents)]


class TestGenerateSMM(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmpdir)

    def test_returns_dict(self):
        smm = seed_smm.generate_smm(self.tmpdir)
        self.assertIsInstance(smm, dict)

    def test_has_four_pillars(self):
        smm = seed_smm.generate_smm(self.tmpdir)
        for pillar in smm_schema.PILLARS:
            self.assertIn(pillar, smm)
            self.assertIsInstance(smm[pillar], list)

    def test_validates_against_schema(self):
        smm = seed_smm.generate_smm(self.tmpdir)
        errors = smm_schema.validate_smm(smm)
        self.assertEqual(errors, [], f"Schema errors: {errors}")

    def test_entries_have_source_seed(self):
        smm = seed_smm.generate_smm(self.tmpdir)
        for pillar in smm_schema.PILLARS:
            for entry in smm[pillar]:
                self.assertEqual(
                    entry["source"],
                    "seed",
                    f"{pillar} entry missing source='seed'",
                )

    def test_entries_have_uuid_ids(self):
        smm = seed_smm.generate_smm(self.tmpdir)
        seen = set()
        for pillar in smm_schema.PILLARS:
            for entry in smm[pillar]:
                self.assertIn("id", entry)
                self.assertNotIn(entry["id"], seen, "duplicate id")
                seen.add(entry["id"])

    def test_review_cycle_wisdom_is_cadence_aware(self):
        """story-006: the review-cycle wisdom names both cadences, not an
        absolute per-commit rule."""
        smm = seed_smm.generate_smm(self.tmpdir)
        entry = next(
            (e for e in smm["wisdom"] if "cadence" in e["content"].lower()),
            None,
        )
        self.assertIsNotNone(entry, "no cadence-aware review-cycle wisdom")
        assert entry is not None  # narrow for the type-checker
        text = entry["content"].lower()
        self.assertIn("commit", text)
        self.assertIn("story", text)
        self.assertIn("/xp-story-close", entry["content"])
        # Security review is Step 4 (Step 4.5 is the close-reviewer/quality
        # stream) — keep this surface in agreement with PROCESS_GUIDE.md and
        # scripts/_close_pipeline_shared.md.
        self.assertIn("Step 4.", entry["content"])
        self.assertNotIn("Step 4.5", entry["content"])

    def test_empty_project_has_all_risks(self):
        smm = seed_smm.generate_smm(self.tmpdir)
        contents = [e["content"] for e in smm["risks"]]
        joined = " ".join(contents)
        self.assertIn("No linter configured", joined)
        self.assertIn("No test files detected", joined)
        self.assertIn("No git commit hooks", joined)
        self.assertIn("No CI/CD configured", joined)

    def test_project_with_everything_has_no_risks(self):
        (self.tmpdir / "ruff.toml").touch()
        (self.tmpdir / "tests").mkdir()
        (self.tmpdir / "lefthook.yml").touch()
        (self.tmpdir / ".github" / "workflows").mkdir(parents=True)
        smm = seed_smm.generate_smm(self.tmpdir)
        self.assertEqual(smm["risks"], [])

    def test_has_xp_constraints(self):
        smm = seed_smm.generate_smm(self.tmpdir)
        contents = [e["content"] for e in smm["constraints"]]
        joined = " ".join(contents)
        self.assertIn("TDD", joined)
        self.assertIn("red, green, commit", joined)
        self.assertIn("Small commits", joined)
        self.assertIn("strict linting", joined)

    def test_has_wisdom(self):
        smm = seed_smm.generate_smm(self.tmpdir)
        contents = [e["content"] for e in smm["wisdom"]]
        joined = " ".join(contents)
        self.assertIn("xp-kickoff", joined)

    def test_seeded_wisdom_routes_claims_by_checkability(self):
        """story-003: the seeded wisdom carries the prose-hygiene rule, so an
        adopting project inherits the lesson and not only the reviewers."""
        smm = seed_smm.generate_smm(self.tmpdir)
        entry = next(
            (e for e in smm["wisdom"] if "rot loudly" in e["content"]),
            None,
        )
        self.assertIsNotNone(entry, "no prose-hygiene routing wisdom seeded")
        assert entry is not None  # narrow for the type-checker
        text = entry["content"]
        self.assertIn("tests", text, "no test destination for a checkable claim")
        self.assertIn("git", text, "no git destination for history")
        self.assertIn(
            "cannot express", text, "comments not confined to the why/constraint"
        )

    def test_seeded_wisdom_stays_within_the_documented_cap(self):
        smm = seed_smm.generate_smm(self.tmpdir)
        contents = [e["content"] for e in smm["wisdom"]]
        self.assertEqual(wisdom_cap_violations(contents), [])

    def test_the_cap_check_rejects_a_list_outside_the_band(self):
        """Non-vacuity proof: 8 seeded items already satisfy a 5-10 cap, so the
        assertion above passes on arrival. Prove the check can fail."""
        low, high = _WISDOM_CAP
        self.assertTrue(wisdom_cap_violations(["x"] * (high + 1)))
        self.assertTrue(wisdom_cap_violations(["x"] * (low - 1)))

    def test_seeded_wisdom_adds_without_displacing(self):
        smm = seed_smm.generate_smm(self.tmpdir)
        contents = [e["content"] for e in smm["wisdom"]]
        self.assertEqual(missing_wisdom(contents, _WISDOM_SEEDED_BEFORE), [])

    def test_the_displacement_check_catches_a_dropped_item(self):
        """Non-vacuity proof for the assertion above."""
        smm = seed_smm.generate_smm(self.tmpdir)
        contents = [e["content"] for e in smm["wisdom"]]
        traded = [c for c in contents if _WISDOM_SEEDED_BEFORE[0] not in c]
        self.assertEqual(
            missing_wisdom(traded, _WISDOM_SEEDED_BEFORE),
            [_WISDOM_SEEDED_BEFORE[0]],
        )

    def test_has_commit_after_green_wisdom(self):
        smm = seed_smm.generate_smm(self.tmpdir)
        contents = [e["content"] for e in smm["wisdom"]]
        joined = " ".join(contents)
        self.assertIn("Commit after every green", joined)

    def test_commit_after_green_wisdom_names_only_quality_review(self):
        """story-011: only /xp-quality-review runs per commit; pairing
        /code-review in this per-commit wisdom entry implied it does too."""
        smm = seed_smm.generate_smm(self.tmpdir)
        entry = next(
            e for e in smm["wisdom"] if "Commit after every green" in e["content"]
        )
        self.assertIn("/xp-quality-review", entry["content"])
        self.assertNotIn("/code-review", entry["content"])

    def test_review_cadence_wisdom_names_workflow_tool_not_percommit(self):
        """story-011: the cadence entry claimed /code-review runs 'before
        each commit' in commit cadence — contradicts the per-commit cadence
        (xp-quality-review only; /code-review once at sprint/plan/free-close).
        It must instead name the Workflow tool for /code-review's real cadence."""
        smm = seed_smm.generate_smm(self.tmpdir)
        entry = next(
            (e for e in smm["wisdom"] if "cadence" in e["content"].lower()),
            None,
        )
        self.assertIsNotNone(entry, "no cadence-aware review-cycle wisdom")
        assert entry is not None  # narrow for the type-checker
        text = entry["content"]
        self.assertNotIn("(/code-review, /xp-quality-review)", text)
        self.assertNotIn("/code-review → /xp-quality-review before each commit", text)
        self.assertIn("Workflow tool", text)

    def test_deterministic_ids(self):
        """Seeded ids are stable across calls (uuid5 from content)."""
        smm1 = seed_smm.generate_smm(self.tmpdir)
        smm2 = seed_smm.generate_smm(self.tmpdir)
        ids1 = {e["id"] for p in smm_schema.PILLARS for e in smm1[p]}
        ids2 = {e["id"] for p in smm_schema.PILLARS for e in smm2[p]}
        self.assertEqual(ids1, ids2)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Pins for probe_skill_surface.py — story-005's authored proof.

Throwaway spike code; deleted at sprint close with the rest of the rig.

What these pins are FOR, stated because the trap here is subtle. story-005 asks
whether Codex rejects, warns at, or silently ignores SKILL.md frontmatter keys it
does not define. The app-server loader answers that with an `errors` array, and the
observed answer is `errors: []` — no rejection.

`errors: []` is worthless on its own. It reads identically whether the loader
examined our keys and forgave them, or whether the array is simply never populated.
So the instrument carries TWO controls and both are pinned here:

  * ARMING control (positive): a genuinely malformed skill MUST produce a non-empty
    `errors`. Without this, "no rejection" is an unfalsifiable claim.
  * DISCRIMINATION control (negative): a skill carrying an invented key must load
    exactly like our real ones. This is what makes "silently ignored" a measurement
    rather than a restatement of the arming control.

An instrument that cannot report `unknown` must not be allowed to conclude `ignored`.
"""

import unittest

import probe_skill_surface as probe


class TestKeyClassification(unittest.TestCase):
    """Pure classification: which frontmatter keys does Codex define?"""

    def test_documented_keys_classified_as_defined(self):
        documented = (
            "name",
            "description",
            "allowed-tools",
            "context",
            "agent",
            "model",
        )
        for key in documented:
            self.assertEqual(
                probe.classify_key(key),
                probe.DEFINED,
                f"{key} is in Codex's own embedded frontmatter docs",
            )

    def test_effort_is_the_only_undocumented_key_we_ship(self):
        self.assertEqual(probe.classify_key("effort"), probe.UNDOCUMENTED)

    def test_invented_key_is_undocumented(self):
        self.assertEqual(
            probe.classify_key("xp-spike-nonsense-key"), probe.UNDOCUMENTED
        )

    def test_bundled_validator_allowlist_is_narrower_than_the_docs(self):
        """Codex's own quick_validate.py contradicts Codex's own guidance."""
        rejected = probe.bundled_validator_rejects()
        self.assertIn("effort", rejected)
        self.assertIn("context", rejected)
        self.assertIn("agent", rejected)
        self.assertNotIn("allowed-tools", rejected)
        self.assertNotIn("name", rejected)


class TestShippedFrontmatter(unittest.TestCase):
    """The keys we actually ship, read off the filesystem — never a literal count."""

    def test_shipped_key_census_is_read_from_disk(self):
        census = probe.shipped_key_census(probe.repo_skills_dir())
        self.assertGreater(
            len(census),
            0,
            "no shipped skills found - refuse, do not report an empty census",
        )
        self.assertIn("allowed-tools", census)
        self.assertIn("effort", census)

    def test_census_counts_match_the_files_on_disk(self):
        """A dropped row must not read as 'checked and fine'."""
        skills_dir = probe.repo_skills_dir()
        on_disk = sorted(p.parent.name for p in skills_dir.glob("*/SKILL.md"))
        self.assertEqual(probe.shipped_skill_names(skills_dir), on_disk)


class TestRefusesRatherThanLies(unittest.TestCase):
    """tabulate_fields.py discipline: empty result and broken probe look alike."""

    def test_empty_skill_list_raises_rather_than_reporting_no_errors(self):
        with self.assertRaises(probe.ProbeRefusal):
            probe.summarise_load([])

    def test_missing_plugin_skills_raises(self):
        """Skills present, but none of ours: the plugin did not install."""
        foreign = [{"name": "other:thing", "enabled": True, "errors": []}]
        with self.assertRaises(probe.ProbeRefusal):
            probe.summarise_load(foreign)


class TestControlsArmTheInstrument(unittest.TestCase):
    """The two controls, which are the whole reason the AC-1 verdict is not vacuous."""

    def test_arming_control_requires_a_nonempty_errors_array(self):
        """A malformed skill MUST error, or `errors: []` proves nothing."""
        with self.assertRaises(probe.ProbeNotArmed):
            probe.assert_armed(malformed_errors=[])

    def test_arming_control_passes_when_the_loader_reports_the_malformed_skill(self):
        probe.assert_armed(
            malformed_errors=[{"path": "/x/SKILL.md", "message": "not closed"}]
        )

    def test_discrimination_control_must_load_clean(self):
        """The invented-key control must load like our real skills."""
        verdict = probe.classify_load_outcome(entry={"enabled": True}, errors=[])
        self.assertEqual(verdict, probe.LOADED_CLEAN)

    def test_a_rejected_skill_is_not_reported_as_clean(self):
        verdict = probe.classify_load_outcome(
            entry=None, errors=[{"path": "/x/SKILL.md", "message": "boom"}]
        )
        self.assertEqual(verdict, probe.REJECTED)


class TestLoaderCannotSeeFrontmatter(unittest.TestCase):
    """Phase 0's finding, pinned so a Codex upgrade that changes it fails loudly.

    Asserting a hand-typed field set against a hand-typed key list would be a
    tautology. So the detector is proven to discriminate first (it MUST fire on a
    field set that does contain a frontmatter key), and only then is it pointed at
    the field names the loader really returned.
    """

    def test_detector_fires_when_a_frontmatter_key_is_present(self):
        leaked = {"name", "description", "effort"}
        self.assertEqual(probe.frontmatter_keys_in(leaked), {"effort"})

    def test_detector_is_silent_on_a_field_set_with_none(self):
        clean = {"name", "description", "path", "scope", "enabled"}
        self.assertEqual(probe.frontmatter_keys_in(clean), set())

    def test_live_loader_surfaces_no_frontmatter_key(self):
        """The measurement itself, against fields the loader actually returned."""
        fields = probe.observed_loader_fields()
        self.assertGreater(len(fields), 0, "no fields captured - refuse, do not pass")
        self.assertEqual(
            probe.frontmatter_keys_in(fields),
            set(),
            "loader now surfaces frontmatter; warn-vs-ignore can move back to it",
        )

    def test_warn_verdict_is_unavailable_from_the_loader_channel(self):
        self.assertEqual(probe.loader_can_answer("rejects"), True)
        self.assertEqual(probe.loader_can_answer("warns"), False)
        self.assertEqual(probe.loader_can_answer("honoured"), False)


if __name__ == "__main__":
    unittest.main()

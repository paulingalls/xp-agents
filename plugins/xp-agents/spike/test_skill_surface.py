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
    `errors`. Without this, "no rejection" is an unfalsifiable claim. Pinned here AND
    called by `main` on the live payload — pinning it here alone would leave the
    measurement free to skip the precondition these pins describe.
  * DISCRIMINATION control (negative): a skill carrying an invented key must load
    exactly like our real ones. This is what makes "silently ignored" a measurement
    rather than a restatement of the arming control.

An instrument that cannot report `unknown` must not be allowed to conclude `ignored`.
"""

import tempfile
import unittest
from pathlib import Path

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
        """The doc's headline claim, checked against disk rather than restated.

        Asserting only `classify_key("effort") == UNDOCUMENTED` would leave the word
        "only" unpinned — and it is the whole finding, since it is what falsifies
        gap #25's premise for the other three keys.
        """
        self.assertEqual(probe.classify_key("effort"), probe.UNDOCUMENTED)
        shipped = probe.shipped_frontmatter_keys()
        self.assertEqual(shipped - probe.CODEX_DOCUMENTED_KEYS, {"effort"})

    def test_invented_key_is_undocumented(self):
        self.assertEqual(
            probe.classify_key("xp-spike-nonsense-key"), probe.UNDOCUMENTED
        )

    def test_bundled_validator_allowlist_is_narrower_than_the_docs(self):
        """Codex's own quick_validate.py contradicts Codex's own guidance.

        The rejected set is derived from the keys on DISK, so this is a claim about
        our tree and not a subtraction of one hand-typed literal from another: a key
        listed here that we stopped shipping fails instead of padding the table.
        """
        rejected = probe.bundled_validator_rejects()
        self.assertEqual(rejected, {"effort", "context", "agent"})
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
        """A dropped row must not read as 'checked and fine'.

        Cross-checks the two independent walks — one counts skill directories, the
        other counts keys — rather than re-running the same glob and comparing it to
        itself. Every skill declares exactly one `name`, so a row the key walk skips
        (or double-counts) breaks the equality.
        """
        skills_dir = probe.repo_skills_dir()
        names = probe.shipped_skill_names(skills_dir)
        census = probe.shipped_key_census(skills_dir)
        self.assertEqual(census["name"], len(names))
        over = {k: c for k, c in census.items() if c > len(names)}
        self.assertEqual(over, {}, "a key counted more often than there are skills")

    def test_an_unclosed_frontmatter_block_refuses(self):
        """Otherwise the parser walks into the body and invents census rows."""
        with tempfile.TemporaryDirectory() as td:
            skill = Path(td) / "xp-broken" / "SKILL.md"
            skill.parent.mkdir()
            skill.write_text("---\nname: xp-broken\n\n## Step 1: Read\n", "utf-8")
            with self.assertRaises(probe.ProbeRefusal):
                probe.shipped_key_census(Path(td))


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
            probe.assert_armed([])

    def test_arming_control_passes_when_the_loader_reports_the_malformed_skill(self):
        probe.assert_armed([{"path": "/x/SKILL.md", "message": "not closed"}])

    def test_an_error_on_the_control_is_not_attributed_to_one_of_ours(self):
        """`errors` is per-SCAN, so the control's own error sits beside our skills.

        Read unfiltered it would report every shipped skill as rejected in exactly
        the run that arms the channel — the arming control marking its own run void.
        """
        errors = [
            {"path": "/cache/skills/xp-spike-malformed/SKILL.md", "message": "boom"}
        ]
        self.assertEqual(probe.errors_naming(errors, "xp-plan"), [])
        self.assertEqual(len(probe.errors_naming(errors, "xp-spike-malformed")), 1)

    def test_an_error_naming_a_shipped_skill_is_attributed(self):
        errors = [{"path": "/cache/skills/xp-plan/SKILL.md", "message": "boom"}]
        self.assertEqual(len(probe.errors_naming(errors, "xp-plan")), 1)
        self.assertEqual(
            probe.classify_load_outcome(
                entry={"enabled": True}, errors=probe.errors_naming(errors, "xp-plan")
            ),
            probe.REJECTED,
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


class TestAppServerCallPrimitive(unittest.TestCase):
    """Behaviour test for the primitive extracted so `model/list` can reuse it.

    The 19 pins around it exercise `app_server_skills`, which only ever asks for
    `skills/list` — so none of them reach the arbitrary-method path or the
    error-response branch this extraction added. Per the refactor rule, a new
    primitive gets its own test rather than riding its caller's.
    """

    def test_arbitrary_method_reaches_the_server(self):
        """The whole point of the extraction: a method other than skills/list."""
        payload = probe.app_server_call("model/list", {"limit": 1})
        self.assertIn("result", payload)
        self.assertIn("data", payload["result"])

    def test_unknown_method_refuses_rather_than_returning_empty(self):
        """A JSON-RPC error must not read as 'the server said nothing useful'.

        The message is asserted, not just the exception type: the no-response path
        raises the same `ProbeRefusal`, so a bare `assertRaises` passes whether or
        not the new error branch is ever reached.
        """
        with self.assertRaises(probe.ProbeRefusal) as caught:
            probe.app_server_call("xp-spike/definitely-not-a-method", {})
        self.assertIn("returned an error", str(caught.exception))


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

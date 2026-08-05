#!/usr/bin/env python3
"""Pins for probe_model_tiers.py — story-006's authored proof.

Throwaway spike code; deleted at sprint close with the rest of the rig.

These pins deliberately assert **instrument properties, not catalog content**. An
earlier draft proposed pinning "exactly the non-5.6 models lack `max`" and "the
default model advertises at least four efforts"; both encode today's entitlements,
so a plan change or a Codex release would red the suite for a non-defect while
adding no power to falsify the one claim that matters — that the matrix came from
`model/list` rather than from someone's memory.

Four properties are pinned instead:

  provenance      a row that did not come from a catalog record cannot enter the
                  matrix, so a hand-written table fails instead of shipping
  discrimination  the requested-vs-effective reader tells a match from a
                  substitution, proven in BOTH directions
  refusal         an empty catalog, or one with no default model, raises rather
                  than printing an empty matrix
  arming          the effective values must be READABLE on the live path

That last one is deliberately NOT "the harness refused an unsupported pair". Arming
is a property of the instrument; whether Codex refuses or silently clamps is the
FINDING, and a clamp must still emit the matrix — annotated — because per the
story's own interface contract a clamp is the more valuable result. Arming on the
harness's verdict would let an adverse-but-valid measurement block story-007.
"""

import unittest

import probe_model_tiers as probe


class TestCatalogRefusal(unittest.TestCase):
    """An empty answer and a broken probe must not look alike."""

    def test_empty_catalog_raises(self):
        with self.assertRaises(probe.ProbeRefusal):
            probe.assert_catalog_usable([])

    def test_catalog_with_no_default_model_raises(self):
        """Every Codex catalog has a default; its absence means we misread the shape."""
        no_default = [
            {
                "id": "m1",
                "isDefault": False,
                "hidden": False,
                "defaultReasoningEffort": "low",
                "supportedReasoningEfforts": [{"reasoningEffort": "low"}],
            },
        ]
        with self.assertRaises(probe.ProbeRefusal):
            probe.assert_catalog_usable(no_default)

    def test_usable_catalog_passes(self):
        ok = [
            {
                "id": "m1",
                "isDefault": True,
                "hidden": False,
                "defaultReasoningEffort": "low",
                "supportedReasoningEfforts": [{"reasoningEffort": "low"}],
            },
        ]
        probe.assert_catalog_usable(ok)


class TestProvenance(unittest.TestCase):
    """A row must trace to a model/list record. A literal table cannot enter."""

    def test_hand_written_row_is_rejected(self):
        """The failure mode: typing the table from the doc instead of reading it."""
        invented = [{"id": "gpt-5.6-sol", "efforts": ["low", "ultra"]}]
        with self.assertRaises(probe.ProbeRefusal):
            probe.effort_matrix(invented)

    def test_record_missing_supported_efforts_is_rejected(self):
        partial = [
            {
                "id": "m1",
                "defaultReasoningEffort": "low",
                "isDefault": True,
                "hidden": False,
            },
        ]
        with self.assertRaises(probe.ProbeRefusal):
            probe.effort_matrix(partial)

    def test_catalog_record_yields_its_advertised_efforts(self):
        rec = [
            {
                "id": "m1",
                "isDefault": True,
                "hidden": False,
                "defaultReasoningEffort": "medium",
                "supportedReasoningEfforts": [
                    {"reasoningEffort": "low", "description": "x"},
                    {"reasoningEffort": "medium", "description": "y"},
                ],
            }
        ]
        self.assertEqual(probe.effort_matrix(rec), {"m1": ["low", "medium"]})

    def test_model_with_empty_advertised_efforts_is_rejected(self):
        """`supportedReasoningEfforts` is a required non-empty field in the schema."""
        empty = [
            {
                "id": "m1",
                "isDefault": True,
                "hidden": False,
                "defaultReasoningEffort": "low",
                "supportedReasoningEfforts": [],
            }
        ]
        with self.assertRaises(probe.ProbeRefusal):
            probe.effort_matrix(empty)


class TestRequestedVsEffective(unittest.TestCase):
    """The discrimination the clamped column depends on, both directions."""

    def test_equal_values_read_as_accepted(self):
        verdict = probe.compare_requested(
            requested={"model": "m1", "effort": "high"},
            effective={"model": "m1", "effort": "high"},
        )
        self.assertEqual(verdict, probe.ACCEPTED)

    def test_substituted_effort_reads_as_clamped(self):
        verdict = probe.compare_requested(
            requested={"model": "m1", "effort": "ultra"},
            effective={"model": "m1", "effort": "xhigh"},
        )
        self.assertEqual(verdict, probe.CLAMPED)

    def test_substituted_model_reads_as_clamped(self):
        verdict = probe.compare_requested(
            requested={"model": "m2", "effort": "high"},
            effective={"model": "m1", "effort": "high"},
        )
        self.assertEqual(verdict, probe.CLAMPED)

    def test_unreadable_effective_is_not_silently_accepted(self):
        """Absent evidence must never resolve to the happy answer."""
        with self.assertRaises(probe.ProbeNotArmed):
            probe.compare_requested(
                requested={"model": "m1", "effort": "high"},
                effective={"model": None, "effort": None},
            )


class TestArming(unittest.TestCase):
    """Arming is 'the effective values are readable', not 'the harness refused'."""

    def test_unreadable_effective_fails_arming(self):
        with self.assertRaises(probe.ProbeNotArmed):
            probe.assert_effective_readable({"model": None, "effort": None})

    def test_partially_readable_effective_fails_arming(self):
        with self.assertRaises(probe.ProbeNotArmed):
            probe.assert_effective_readable({"model": "m1", "effort": None})

    def test_readable_effective_passes_arming(self):
        probe.assert_effective_readable({"model": "m1", "effort": "high"})

    def test_a_clamp_still_yields_a_matrix(self):
        """The deadlock this design exists to avoid: a clamp must not suppress data."""
        rows = probe.annotate_matrix(
            matrix={"m1": ["low", "high"]},
            verdicts={("m1", "high"): probe.CLAMPED},
        )
        self.assertIn("m1", rows)
        self.assertEqual(rows["m1"]["enforced"], False)
        self.assertEqual(rows["m1"]["note"], probe.ADVERTISED_NOT_ENFORCED)

    def test_all_accepted_reads_as_enforced(self):
        rows = probe.annotate_matrix(
            matrix={"m1": ["low", "high"]},
            verdicts={("m1", "high"): probe.ACCEPTED, ("m1", "low"): probe.ACCEPTED},
        )
        self.assertEqual(rows["m1"]["enforced"], True)
        self.assertIsNone(rows["m1"]["note"])


class TestRolloutReader(unittest.TestCase):
    """The channel: a rollout log carries the EFFECTIVE model and effort."""

    def test_reader_extracts_model_and_effort(self):
        lines = [
            '{"payload": {"cwd": "/x"}}',
            '{"payload": {"model": "gpt-5.6-sol", "effort": "high"}}',
        ]
        self.assertEqual(
            probe.effective_from_lines(lines),
            {"model": "gpt-5.6-sol", "effort": "high"},
        )

    def test_reader_reports_none_rather_than_guessing(self):
        """A rollout without the fields yields None, which arming then rejects."""
        self.assertEqual(
            probe.effective_from_lines(['{"payload": {"cwd": "/x"}}']),
            {"model": None, "effort": None},
        )

    def test_reader_survives_a_malformed_line(self):
        lines = ["not json", '{"payload": {"model": "m1", "effort": "low"}}']
        self.assertEqual(
            probe.effective_from_lines(lines), {"model": "m1", "effort": "low"}
        )


class TestExecCommand(unittest.TestCase):
    """Command construction, kept pure so it is testable without spending runs.

    An earlier draft passed `--ignore-user-config` to stop the operator's global
    `model_reasoning_effort` reading as a harness clamp. The arming control refused
    on its first live run and showed why that was wrong: the flag also discards
    `model_provider` and auth, so every request 401'd. The confound never needed it —
    explicit `-m` and `-c model_reasoning_effort=` already beat `config.toml`, so the
    operator's defaults can only reach a run that OMITS the flags.
    """

    def test_measured_run_does_not_discard_operator_auth(self):
        """--ignore-user-config also drops model_provider and auth; measured 401s."""
        cmd = probe.build_exec_command("m1", "high", prompt="ok")
        self.assertNotIn("--ignore-user-config", cmd)

    def test_both_values_are_pinned_explicitly_so_config_cannot_win(self):
        """Isolation is achieved by overriding, not by discarding the whole config."""
        cmd = probe.build_exec_command("m1", "high", prompt="ok")
        self.assertIn("-m", cmd)
        self.assertIn("model_reasoning_effort=high", cmd)

    def test_control_run_omits_the_effort_flag_to_expose_the_override(self):
        """The one run that measures config.toml's override must not pin effort."""
        cmd = probe.build_exec_command("m1", None, prompt="ok")
        self.assertFalse(
            [a for a in cmd if str(a).startswith("model_reasoning_effort=")],
            "a control run must leave effort unset so the operator default shows",
        )

    def test_model_and_effort_travel_on_their_documented_flags(self):
        """No -e shorthand exists; effort goes through -c model_reasoning_effort."""
        cmd = probe.build_exec_command("m1", "ultra", prompt="ok")
        self.assertIn("-m", cmd)
        self.assertIn("m1", cmd)
        self.assertIn("model_reasoning_effort=ultra", cmd)
        self.assertNotIn("-e", cmd)


class TestLiveArmingIsReachable(unittest.TestCase):
    """The story-005 defect, pinned so it cannot recur silently in this instrument.

    story-005 added an arming control and never called it on the live path, so the
    probe would have printed a full verdict table with the control uninstalled.
    Convention `instrument-arms-on-live-path` came out of that. This asserts the
    live entry point actually reaches the arming, rather than trusting that it does.
    """

    def test_main_reaches_the_arming_control(self):
        import inspect

        source = inspect.getsource(probe.main)
        self.assertIn(
            "arm_channel",
            source,
            "main() must arm the requested-vs-effective channel before emitting "
            "verdicts - an unreached arming control is theatre",
        )

    def test_arm_channel_calls_the_arming_assertion(self):
        import inspect

        source = inspect.getsource(probe.arm_channel)
        self.assertIn("assert_effective_readable", source)


class TestLiveCatalog(unittest.TestCase):
    """The measurement itself, against what model/list actually returned."""

    def test_live_catalog_is_usable_and_yields_a_matrix(self):
        models = probe.model_catalog()
        probe.assert_catalog_usable(models)
        matrix = probe.effort_matrix(models)
        self.assertGreater(len(matrix), 0, "no models - refuse, do not pass")
        for model_id, efforts in matrix.items():
            self.assertGreater(len(efforts), 0, f"{model_id}: no advertised efforts")


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Tests for tier_wire.py — the single source for teammate tier-picker wires.

Scoped to the module's own constants: model vocabulary, config tokens, the
token->config map, recommended-model values, and the SMM wire strings. Prose
binding (that SKILL.md / agent.md name every model) lives in each consumer's
existing prose-pin file, not here.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import tier_wire


class TestTierWire(unittest.TestCase):
    def test_teammate_models_are_the_canonical_tiers(self):
        """fable is the top tier: in-agent < haiku < sonnet < opus < fable."""
        self.assertEqual(
            tier_wire.TEAMMATE_MODELS, frozenset({"haiku", "sonnet", "opus", "fable"})
        )

    def test_config_tokens_are_models_plus_off_and_inherit(self):
        self.assertEqual(
            tier_wire.TEAMMATE_CONFIG_TOKENS,
            frozenset({"off", "inherit"}) | tier_wire.TEAMMATE_MODELS,
        )

    def test_token_to_config_maps_every_token(self):
        self.assertEqual(
            set(tier_wire.TOKEN_TO_CONFIG), set(tier_wire.TEAMMATE_CONFIG_TOKENS)
        )
        self.assertEqual(
            tier_wire.TOKEN_TO_CONFIG["off"],
            {"enabled": False, "default_model": None},
        )
        self.assertEqual(
            tier_wire.TOKEN_TO_CONFIG["inherit"],
            {"enabled": True, "default_model": None},
        )
        for m in tier_wire.TEAMMATE_MODELS:
            self.assertEqual(
                tier_wire.TOKEN_TO_CONFIG[m],
                {"enabled": True, "default_model": m},
                f"token {m!r} must map to its own default_model",
            )

    def test_recommended_models_are_in_agent_plus_the_tiers(self):
        """recommended_model adds 'in-agent' (no spawn) to the model tiers."""
        self.assertEqual(
            tier_wire.RECOMMENDED_MODELS,
            frozenset({"in-agent"}) | tier_wire.TEAMMATE_MODELS,
        )

    def test_wire_strings(self):
        self.assertEqual(
            tier_wire.TIER_RECOMMENDATION_TOPIC_PREFIX, "tier-recommendation-"
        )
        self.assertEqual(tier_wire.TIER_OVERRIDE_ACTION, "tier_override")

    def test_teammate_efforts_ordered_ascending(self):
        """Effort levels from low to max; ordering is semantically meaningful."""
        self.assertEqual(
            tier_wire.TEAMMATE_EFFORTS, ("low", "medium", "high", "xhigh", "max")
        )

    def test_haiku_has_no_effort_support(self):
        """Haiku does not support the effort param."""
        for effort in tier_wire.TEAMMATE_EFFORTS:
            self.assertFalse(
                tier_wire.effort_supported("haiku", effort),
                f"haiku must not support {effort!r}",
            )

    def test_sonnet_opus_fable_support_all_efforts(self):
        """Sonnet, Opus, and Fable support the full range of effort levels."""
        for model in {"sonnet", "opus", "fable"}:
            for effort in tier_wire.TEAMMATE_EFFORTS:
                self.assertTrue(
                    tier_wire.effort_supported(model, effort),
                    f"{model} must support {effort!r}",
                )

    def test_effort_supported_rejects_unknown_model(self):
        """Unknown models return False for any effort level."""
        self.assertFalse(tier_wire.effort_supported("unknown", "low"))
        self.assertFalse(tier_wire.effort_supported("gpt-4", "medium"))

    def test_effort_supported_rejects_unknown_effort(self):
        """Unknown effort strings return False for any model."""
        self.assertFalse(tier_wire.effort_supported("sonnet", "invalid"))
        self.assertFalse(tier_wire.effort_supported("opus", "unknown"))

    def test_effort_support_parity_with_teammate_models(self):
        """EFFORT_SUPPORT keys are exactly TEAMMATE_MODELS."""
        self.assertEqual(
            set(tier_wire.EFFORT_SUPPORT.keys()), set(tier_wire.TEAMMATE_MODELS)
        )


if __name__ == "__main__":
    unittest.main()

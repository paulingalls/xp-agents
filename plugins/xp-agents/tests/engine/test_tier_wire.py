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


if __name__ == "__main__":
    unittest.main()

"""Shared tier-wire constants for the teammate tier-picker subsystem.

The teammate model vocabulary and the tier-recommendation / tier-override wire
strings were duplicated across scripts/ and smm/ modules and shipped prose,
drifting over time. This is the single source: code readers import it, and
shipped prose (SKILL.md / agent.md) plus the preload.sh embedded literal are
pinned to it by binding tests (prose cannot import). Lives in smm/ with no
imports so both scripts/ (via the sys.path shim) and smm/ siblings can
reference it — mirrors marker_names.py.
"""

# Canonical teammate/executor model tiers. Cheapest -> most capable:
#   in-agent < haiku < sonnet < opus < fable
# fable is the most powerful and most expensive tier.
TEAMMATE_MODELS = frozenset({"haiku", "sonnet", "opus", "fable"})

# Session config tokens accepted by teammate_config_cli / offered at kickoff:
# every model tier plus the two non-model tokens.
TEAMMATE_CONFIG_TOKENS = frozenset({"off", "inherit"}) | TEAMMATE_MODELS

# Token -> teammate-config dict. "off" disables teammates; "inherit" spawns them
# on the lead's model; a model token pins that model as the default.
TOKEN_TO_CONFIG: dict[str, dict] = {
    "off": {"enabled": False, "default_model": None},
    "inherit": {"enabled": True, "default_model": None},
    **{m: {"enabled": True, "default_model": m} for m in TEAMMATE_MODELS},
}

# Values the plan-reviewer may emit as metadata.recommended_model. "in-agent"
# means "no spawn — continue in the existing checkout"; it is not a model tier.
RECOMMENDED_MODELS = frozenset({"in-agent"}) | TEAMMATE_MODELS

# SMM event wire strings. The plan-reviewer writes a decision on
# f"{TIER_RECOMMENDATION_TOPIC_PREFIX}{story_id}"; the xp-assign hand-off writes
# a status event with metadata.action == TIER_OVERRIDE_ACTION.
TIER_RECOMMENDATION_TOPIC_PREFIX = "tier-recommendation-"
TIER_OVERRIDE_ACTION = "tier_override"

# Teammate effort levels: a Claude-Code reasoning_effort knob. Ordered ascending
# from least to most intensive. Only sonnet, opus, and fable support effort;
# haiku errors on any effort param.
TEAMMATE_EFFORTS: tuple[str, ...] = ("low", "medium", "high", "xhigh", "max")

# Per-tier effort support: haiku unsupported, sonnet/opus/fable support all levels.
# Built from TEAMMATE_EFFORTS so no hand-duplication drift.
EFFORT_SUPPORT: dict[str, frozenset[str]] = {
    "haiku": frozenset(),
    **{m: frozenset(TEAMMATE_EFFORTS) for m in TEAMMATE_MODELS - {"haiku"}},
}


def effort_supported(model: str, effort: str) -> bool:
    """Return True if the model supports the given effort level."""
    return effort in EFFORT_SUPPORT.get(model, frozenset())

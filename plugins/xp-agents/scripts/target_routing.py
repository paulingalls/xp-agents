#!/usr/bin/env python3
"""Shared name-routing helpers for PostToolUse:Skill|Agent hooks.

Three hooks (`review_cycle_done`, `subagent_stop`, `accept_terminal`)
all need to look up an incoming skill/agent name in their own allowlist
and treat third-party plugin namespaces as non-matches. The shape was
re-implemented inline in each hook; this module centralizes the
namespace strip so future hooks don't drift on the rules.
"""

_OUR_NAMESPACE = "xp-agents"

# The close-reviewer's bare (namespace-stripped) agent type. Shared so the
# emit site (subagent_stop) and the read site (close_cycle_stop_gate) of the
# reviewer-completion evidence handshake cannot drift on a rename.
CLOSE_REVIEWER_BARE = "xp-close-reviewer"


def strip_our_namespace(name: str) -> str | None:
    """Return the bare form when `name` is unqualified or in our plugin's
    namespace; return None for third-party plugin qualified forms.

    Examples:
        strip_our_namespace("xp-assign")              -> "xp-assign"
        strip_our_namespace("xp-agents:xp-assign")    -> "xp-assign"
        strip_our_namespace("otherplugin:xp-assign")  -> None
        strip_our_namespace("")                       -> None
    """
    if not name:
        return None
    if ":" not in name:
        return name
    plugin, _, bare = name.partition(":")
    if plugin == _OUR_NAMESPACE:
        return bare
    return None

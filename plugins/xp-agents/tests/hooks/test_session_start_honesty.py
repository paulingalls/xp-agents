#!/usr/bin/env python3
"""The two SessionStart channels must not disagree about enforcement.

`hook_io.hook_output` sends `additionalContext` to the AGENT and `systemMessage`
to the USER — its own docstring says so. When SMM validation failed, `run`
returned "SMM init failed — xp-agents disabled." as context while
`_system_message` opened unconditionally with "XP agents (vN) active." and, on a
fresh start, invited `/xp-kickoff`. So the agent was told the gates were off and
the user was told they were on and sent into an unenforced session (concerns
`e32c04a46599` and `7c688f1295d6`, both measured live).

The rows here assert the PROPERTY rather than one string: whatever the two
channels say, they agree about whether enforcement is on. A per-string
assertion would pass a future edit that changed one channel's wording and left
the other behind, which is the defect itself.

Driven through `main`, never `_system_message` in isolation — the bug lived in
how `main` composed the two, so a unit call on the helper cannot see it.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase

# The two claims the user-facing line must not make while the gates are absent.
# "active" is the false statement; the kickoff invitation is the harmful one,
# because every gate that skill relies on is missing.
_ACTIVE_CLAIM = "active"
_KICKOFF_INVITE = "/xp-kickoff"


def _says_enforcement_is_on(message: str) -> bool:
    """Does this user-facing line claim the gates are running?"""
    return _ACTIVE_CLAIM in message


def _context_says_enforcement_is_off(context: str) -> bool:
    """Does this agent-facing context report the runtime disabled?"""
    return "SMM init failed" in context


def _enforcing_banner() -> str:
    """The whole active banner, spelled out for the byte-identity rows.

    A literal, not a call back into the code under test, or the comparison is a
    tautology. Spelled once and shared by the lead and teammate legs so the two
    pins cannot drift apart. Version read at assert time, never at import: the
    plugin root is env-derived and other suites repoint it.
    """
    import plugin_loader

    return f"XP agents (v{plugin_loader.plugin_version()}) active. Run /xp-kickoff."


class _BannerTestCase(_HookTestCase):
    """Drives `main` with the init.sh resolution stubbed, like the core suite.

    `_assert_not_none` comes free: `_HookTestCase` -> `_SMMTestCase` already
    mixes it in. Adding `_AssertNotNoneMixin` here as a second base looked
    harmless and was not — it put `TestCase` ahead of its own subclass and
    pyright refused the method ordering.
    """

    def _emit(
        self, resolved, *, teammate: bool = False, source: str = "startup"
    ) -> tuple[str, str]:
        """Run main() and return the (context, systemMessage) it emitted.

        Mirrors test_session_start_core's `_main_with_resolution` rather than
        inventing a second driver: the argument positions of `hook_output` are
        the contract under test, and two spellings of that would drift.

        Both returns are narrowed via `_assert_not_none` rather than handed back
        as `str | None`. A missing banner is a real failure of this story — the
        whole point is that the user-facing channel says something true — so it
        belongs here as an assertion, not pushed onto every caller as a type
        check pyright would otherwise (correctly) reject.
        """
        import session_start

        with (
            patch.object(session_start, "_resolve_via_init_sh", return_value=resolved),
            patch.object(
                session_start._common,
                "read_hook_input",
                return_value={"session_id": "t", "source": source},
            ),
            patch.object(
                session_start.identity,
                "is_worktree_teammate",
                return_value=teammate,
            ),
            patch.object(session_start._common, "hook_output") as hook_output,
        ):
            session_start.main()
        hook_output.assert_called_once()
        # Positional args are (event_name, context, system_message). Indexed off
        # `call_args` directly, the way test_session_start_core does it: binding
        # the tuple to a local first narrows it to empty for pyright.
        self.assertGreater(
            len(hook_output.call_args.args),
            2,
            "SessionStart emitted no user-facing message at all",
        )
        return (
            self._assert_not_none(hook_output.call_args.args[1], "no context"),
            self._assert_not_none(hook_output.call_args.args[2], "no message"),
        )


class TestTheDisabledBannerTellsTheTruth(_BannerTestCase):
    """The lead path, with SMM validation failing."""

    def test_the_user_is_not_told_enforcement_is_active(self):
        """The measured contradiction. The agent is told "disabled"; the user
        was told "active" in the same emission."""
        context, message = self._emit(None)
        self.assertTrue(
            _context_says_enforcement_is_off(context),
            f"precondition: expected the disabled context, got {context!r}",
        )
        self.assertFalse(
            _says_enforcement_is_on(message),
            f"user was told enforcement is active while it is off: {message!r}",
        )

    def test_the_user_is_not_invited_into_an_unenforced_session(self):
        """Worse than inaccurate. Every gate that skill drives is absent, so the
        invitation sends the user into exactly the session it cannot police."""
        _, message = self._emit(None)
        self.assertNotIn(_KICKOFF_INVITE, message)

    def test_the_disabled_banner_names_a_cause(self):
        """A refusal that reports no cause cannot be acted on. Generic across
        harnesses — this must not name one host's install path."""
        _, message = self._emit(None)
        self.assertTrue(message and message.strip(), "no user-facing line at all")
        self.assertGreater(len(message.split()), 3, f"too terse to act on: {message!r}")


class TestTheChannelsAgree(_BannerTestCase):
    """The invariant, over both outcomes — not one wording.

    Without the success row, "never say active" would satisfy the failure rows
    while silently deleting the working banner.
    """

    def test_they_agree_when_validation_fails(self):
        context, message = self._emit(None)
        self.assertEqual(
            _context_says_enforcement_is_off(context),
            not _says_enforcement_is_on(message),
            f"channels disagree: context={context!r} message={message!r}",
        )

    def test_they_agree_when_validation_succeeds(self):
        context, message = self._emit(self.smm_dir)
        self.assertEqual(
            _context_says_enforcement_is_off(context),
            not _says_enforcement_is_on(message),
            f"channels disagree: context={context!r} message={message!r}",
        )

    def test_the_working_banner_is_unchanged(self):
        """Over-arming control, pinned byte-for-byte. The active path keeps its
        claim AND its nudge; without this, suppressing the banner entirely would
        pass every row above. Whole-line rather than two substrings, because the
        claim being made is that the enforcing banner is unchanged, and a
        substring pair passes a reworded line that still contains both."""
        _, message = self._emit(self.smm_dir)
        self.assertEqual(message, _enforcing_banner())


class TestATeammateIsNotToldTheGatesAreOff(_BannerTestCase):
    """The leg nothing pinned before.

    `main` passes no SMM dir for a teammate on purpose — handing one over would
    inject the whole SMM render into every teammate's context. So a verdict
    derived from that absent dir reads "disabled" for a session whose
    enforcement is on. The disabled banner must be reachable only where the
    lead path actually validated something.
    """

    def test_a_teammate_banner_never_claims_enforcement_is_off(self):
        _, message = self._emit(None, teammate=True)
        self.assertIn(
            _ACTIVE_CLAIM,
            message,
            f"teammate told the gates are off while they are on: {message!r}",
        )

    def test_the_teammate_banner_is_byte_identical_to_today(self):
        """Unchanged means unchanged: the WHOLE line, not one substring.

        A teammate's banner does carry "Run /xp-kickoff" — measured, against a
        plausible-sounding argument that it would not (kickoff is lead-owned and
        the privilege gate refuses a teammate). That invitation is arguably its
        own small honesty wart, but pinning it as-is is what keeps a later fix to
        it deliberate rather than a side effect of some other change.
        """
        _, message = self._emit(None, teammate=True)
        self.assertEqual(message, _enforcing_banner())


if __name__ == "__main__":
    unittest.main()

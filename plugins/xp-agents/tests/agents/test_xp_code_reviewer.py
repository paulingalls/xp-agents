#!/usr/bin/env python3
"""xp-code-reviewer.md prose pins for sprint-113 story-001.

The three additions:
  Section 1  — state/lifecycle/concurrency angle bullet
  Section 1b — bounded self-verify with category-based spare-clause
  Section 1c — self-triage: the reviewer assesses the diff's own risk from
               the change plus the injected Constraints pillar, elevates the
               relevant angles itself, and down-rates diffs that match a
               documented convention. Replaces the classifier-fed
               ## Review Focus handshake table (removed in story-002).

Section 1's removed-behavior angle also carries the story-007 widening: when a
hunk deletes a name, search the project's tests for it, including in files the
diff never touched.

Tests are prose pins: the agent is an LLM, so the deterministic guard is the
prompt prose itself. Sprint-103 attempted similar work and was abandoned at
close — the cross-language vocabulary guard (test 2 and the §1c anti-leak
guard) is the load-bearing sprint-104/sprint-113 lesson (CLAUDE.md two-layer
project-agnostic guardrail).

WHAT THESE PINS DO NOT PROVE. story-007's criteria are about what the reviewer
DOES when it meets a removal diff — that it finds the orphaned tests, and stays
quiet when there are none. No prose pin can observe that; only a live review
can. What is proved here is narrower and worth stating plainly: the instruction
is present, both of its halves are legible, it is distinguishable from the
sibling angle it extends, and it names no language. A pin that claimed the
behavior itself would be a green check certifying something untrue — the same
error as a test that outlives the thing it tests.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _md_helpers import (
    PROJECT_AGNOSTIC_FORBIDDEN_VOCAB,
    _split_frontmatter_body,
    assert_project_agnostic,
)
from conftest import _PLUGIN_ROOT

_AGENT_PROMPT = _PLUGIN_ROOT / "agents" / "xp-code-reviewer.md"

# Members of PROJECT_AGNOSTIC_FORBIDDEN_VOCAB whose casing is load-bearing, used
# by both the helper's contract pin and the §1 mutation proof. See
# TestProjectAgnosticAssertHelper for why the pair, and not either one alone.
_MIXED_CASE_VOCAB_MEMBERS = ("ACCEPT_IN_FLIGHT", " LOC")


def _section_slice(body: str, start_heading: str, end_heading: str) -> str:
    """Return the body slice between two headings (start inclusive, end exclusive).

    Both headings must appear; raises a clear AssertionError otherwise so
    the section-anchored assertions fail loud rather than silently shrink.
    """
    s = body.find(start_heading)
    e = body.find(end_heading, s + 1 if s != -1 else 0)
    if s == -1 or e == -1:
        raise AssertionError(
            f"Could not locate section bounds: start={start_heading!r} "
            f"found={s != -1}, end={end_heading!r} found={e != -1}"
        )
    return body[s:e]


class TestXpCodeReviewerProse(unittest.TestCase):
    """Pin the prose additions in xp-code-reviewer.md."""

    @classmethod
    def setUpClass(cls):
        text = _AGENT_PROMPT.read_text(encoding="utf-8")
        _, cls.body = _split_frontmatter_body(text)
        cls.lower = cls.body.lower()

    def test_section_1_lists_state_lifecycle_angle(self):
        """Section 1 (Correctness) includes a state/lifecycle/concurrency angle."""
        section_1 = _section_slice(self.body, "## 1.", "## 2.").lower()
        # The angle name itself must appear in Section 1.
        self.assertTrue(
            "state/lifecycle" in section_1 or "state / lifecycle" in section_1,
            "Section 1 must name a 'state/lifecycle' review angle",
        )
        # Concrete signal vocabulary covering the failure shapes the two
        # known regressions exhibited (latch-no-clear, marker-no-drain,
        # paired-lifecycle, async ordering).
        for keyword in ("latch", "marker", "lifecycle", "async"):
            self.assertIn(
                keyword,
                section_1,
                f"Section 1 state/lifecycle angle must mention {keyword!r}",
            )

    def test_state_lifecycle_angle_is_cross_language(self):
        """Anti-leak guard: the new angle uses generic CS vocabulary only.

        Sprint-103 leaked xp-agents internals into shipped prose three times.
        The plugin ships to any-language projects; Python-specific examples
        or xp-agents internal surface names break the cross-language
        guarantee (constraint plugin-cross-language-coverage; CLAUDE.md
        project-agnostic guardrail vocabulary layer).
        """
        section_1 = _section_slice(self.body, "## 1.", "## 2.")
        assert_project_agnostic(self, section_1, "Section 1")
        # Singling out the language by name stays at the call site — only this
        # file's two sites assert it (rationale: the helper's docstring).
        self.assertNotIn(
            "python",
            section_1.lower(),
            "Section 1 must not single out Python — agent reviews any language",
        )

    def _removed_behavior_angle(self) -> str:
        """The removed-behavior angle alone, sliced out of §1's angle list.

        Asserting against the whole of §1 would let the sibling angles satisfy
        a pin about this one — the vacuous-pass shape story-006's Half-B pins
        were corrected for. The slice ends at the next angle, `cross-file`.
        """
        return _section_slice(self.body, "removed-behavior", "cross-file")

    def test_removed_behavior_angle_searches_beyond_the_changed_files(self):
        """AC-1: a deleted name's tests are hunted OUTSIDE the diff's own files.

        The reviewer's pre-existing angle reads the diff's own hunks. The gap
        this pins is what survives elsewhere: the tests of a deleted symbol
        routinely live in files the diff never opened, where the file-domain
        collision gate is equally blind.
        """
        angle = self._removed_behavior_angle().lower()
        # The trigger: a hunk deleting a name, not just a deleted guard.
        self.assertRegex(
            angle,
            r"delete[sd]?\b[^.;)]{0,40}\bname\b",
            "the removed-behavior angle must trigger on a hunk that DELETES A "
            "NAME, not only on a deleted guard/validation/test",
        )
        # The action: go looking, in the project's tests.
        self.assertRegex(
            angle,
            r"\bsearch\b[^.;)]{0,60}\btests\b",
            "the angle must instruct SEARCHING the project's tests for that "
            "name — the near half (reading the diff's own hunks) is already "
            "covered by the pre-existing clause",
        )
        # The half that is not already implied: coverage outside the diff.
        self.assertRegex(
            angle,
            r"(never touched|not touched|untouched|outside|elsewhere)",
            "the angle must widen the search BEYOND the changed files — "
            "without this half the clause is indistinguishable from the "
            "removed-behavior sentence that was already there",
        )

    def test_removed_behavior_angle_states_the_quiet_case(self):
        """AC-2: nothing is raised when the removal took its tests with it.

        Half a rule invites a reviewer to report every deletion. The clause
        must make the negative case as legible as the positive one.
        """
        angle = self._removed_behavior_angle().lower()
        # The alternation lists the ways prose says "the tests went along with
        # the removal". It must stay wide enough that the rewording this
        # failure message itself suggests would pass — a pin whose message
        # names a phrasing it then rejects sends the next author in a circle.
        self.assertRegex(
            angle,
            r"\bnothing\b[^.;)]{0,60}(with it|took them|went with|its tests)",
            "the angle must say to raise NOTHING when the removal deleted its "
            "tests too — otherwise the instruction reads as 'report every "
            "deletion'",
        )

    def test_new_clause_lies_inside_the_vocab_scan(self):
        """AC-3, by mutation rather than by claim.

        `test_state_lifecycle_angle_is_cross_language` scans all of §1, so it
        should already cover the new clause — but "should" is what a vacuous
        guard also says. Injecting a forbidden term into the clause itself and
        watching the scan go red is the difference between the two.

        Both mixed-case members are injected for the reason documented at
        `_MIXED_CASE_VOCAB_MEMBERS`: a lowercase probe like `.py` would pass
        through a degraded scan and prove nothing.
        """
        section_1 = _section_slice(self.body, "## 1.", "## 2.")
        angle = self._removed_behavior_angle()
        self.assertIn(angle, section_1, "the angle must lie within §1")
        for term in _MIXED_CASE_VOCAB_MEMBERS:
            with self.subTest(term=term):
                mutated = section_1.replace(angle, f"{angle.rstrip()} {term} ")
                self.assertNotEqual(mutated, section_1, "the injection landed")
                with self.assertRaisesRegex(
                    AssertionError, re.escape(f"token: {term!r}")
                ):
                    assert_project_agnostic(self, mutated, "Section 1 (mutated)")

    def test_section_1b_bounded_self_verify_exists(self):
        """Section 1b stands up the bounded self-verify pass."""
        self.assertIn(
            "## 1b",
            self.body,
            "xp-code-reviewer.md must have a Section 1b heading",
        )
        section_1b = _section_slice(self.body, "## 1b", "## 1c").lower()
        self.assertIn(
            "self-verify",
            section_1b,
            "Section 1b must name the self-verify pass",
        )
        # Bound: one pass, not iterative — the cost-faithful shape.
        self.assertTrue(
            "one " in section_1b or "bounded" in section_1b,
            "Section 1b must describe the pass as bounded (one pass)",
        )

    def test_self_verify_spares_state_lifecycle_by_default(self):
        """Section 1b uses a CATEGORY-based spare-clause, not uncertainty-bias.

        Sprint-103 lesson (design doc §What was actually good): spare
        sparse state-findings by category, refute style nitpicks. Do NOT
        adopt an uncertainty-based 'default-refuted' bias — uncertainty
        alone doesn't earn deletion of a state/lifecycle finding.
        """
        section_1b = _section_slice(self.body, "## 1b", "## 1c")
        section_1b_lower = section_1b.lower()
        # The category-based spare clause: state/lifecycle findings spared by default.
        self.assertRegex(
            section_1b_lower,
            r"spare[^.]{0,120}state/?\s?lifecycle",
            "Section 1b must explicitly spare state/lifecycle findings by default",
        )
        # The disclaimer of the wrong shape (uncertainty-bias / default-refuted).
        # Same-sentence proximity: `not` followed within 80 chars by the rejected term.
        self.assertRegex(
            section_1b_lower,
            r"\bnot\b[^.]{0,80}(uncertainty|default[-\s]?refuted)",
            "Section 1b must explicitly disclaim an uncertainty-bias / "
            "default-refuted framing",
        )

    def test_section_1c_self_triages_not_classifier_handshake(self):
        """Section 1c is a self-triage instruction, not the classifier handshake.

        The reviewer self-assesses the diff's risk from the change itself AND
        the injected Constraints pillar, elevates the relevant angles / hunts
        them first (defaulting to state/lifecycle/concurrency), and down-rates
        (does not flag) a diff that matches a documented Constraints-pillar
        convention. The old classifier-fed ## Review Focus heading is gone —
        story-002 deletes the classifier that produced it.
        """
        self.assertIn(
            "## 1c",
            self.body,
            "xp-code-reviewer.md must have a Section 1c heading",
        )
        section_1c = _section_slice(self.body, "## 1c", "## 2.")
        section_1c_lower = section_1c.lower()

        # The classifier handshake heading must be gone.
        self.assertNotIn(
            "## Review Focus",
            section_1c,
            "Section 1c must no longer reference the classifier-fed "
            "## Review Focus block — it now self-triages",
        )

        # Self-triage: assess risk from the diff + injected Constraints pillar.
        self.assertIn(
            "self-triage",
            section_1c_lower,
            "Section 1c must describe self-triage of risk",
        )
        self.assertIn(
            "constraints pillar",
            section_1c_lower,
            "Section 1c must ground self-triage in the injected Constraints "
            "pillar (the reviewer's actual injected context; sprint-113 "
            "retired the orphaned 'Design Context' vocabulary)",
        )

        # Elevation behavior: elevate / hunt first / priority — at least one.
        verbs = ("elevate", "hunt first", "priority")
        self.assertTrue(
            any(verb in section_1c_lower for verb in verbs),
            "Section 1c must describe how the agent elevates angles "
            "(elevate / hunt first / priority)",
        )

        # Default elevated angle when nothing more specific stands out.
        self.assertRegex(
            section_1c_lower,
            r"state/?\s?lifecycle/?\s?concurrency",
            "Section 1c must default the elevated angle to state/lifecycle/concurrency",
        )

        # Down-rate (not flag) diffs matching a documented convention.
        self.assertIn(
            "down-rate",
            section_1c_lower,
            "Section 1c must instruct down-rating diffs matching a "
            "documented Constraints-pillar convention",
        )

        # Project-agnostic gate: no baked-in plugin size cap as the rule.
        self.assertNotRegex(
            section_1c,
            r"\b500\b",
            "§1c must not bake in the plugin's 500-line cap — defer to the host "
            "project's standards",
        )

    def test_section_1c_is_cross_language(self):
        """Anti-leak guard: §1c uses generic CS vocabulary only.

        Mirrors test_state_lifecycle_angle_is_cross_language — the
        self-triage prose must not leak xp-agents-internal surface names or
        single out a language, since the reviewer runs on any-language diffs
        (CLAUDE.md project-agnostic guardrail vocabulary layer).
        """
        section_1c = _section_slice(self.body, "## 1c", "## 2.")
        assert_project_agnostic(self, section_1c, "Section 1c")
        self.assertNotIn(
            "python",
            section_1c.lower(),
            "Section 1c must not single out Python — agent reviews any language",
        )


class TestProjectAgnosticAssertHelper(unittest.TestCase):
    """Pin the shared vocab-scan helper's own contract: scan RAW.

    Four prose suites across two agents route their forbidden-vocabulary scan
    through `assert_project_agnostic`. Centralizing the loop is the point of
    the extraction, but it also concentrates the blast radius: a helper that
    lowercased its input would degrade all four guards at once, silently. So
    the "scan RAW, never lowercase" contract is pinned here, at the helper,
    rather than restated as a comment at each call site.
    """

    # Merely asserting "it raises" would leave `ACCEPT_IN_FLIGHT` inert: the
    # tuple lists that name in BOTH casings, so a lowercasing helper still
    # raises — on the lowercase twin. The assertion therefore pins WHICH member
    # the failure names, in its raw casing, so a lowercasing helper goes red on
    # both members rather than only on ` LOC` (the one member with no twin to
    # cover for it). That the message names the offending token at all is part
    # of the helper's contract too — a scan that fails without saying what
    # leaked sends the reader back to the tuple.

    def test_mixed_case_members_still_fail_through_the_helper(self):
        for member in _MIXED_CASE_VOCAB_MEMBERS:
            with self.subTest(member=member):
                self.assertIn(member, PROJECT_AGNOSTIC_FORBIDDEN_VOCAB)
                with self.assertRaisesRegex(
                    AssertionError, re.escape(f"token: {member!r}")
                ):
                    assert_project_agnostic(
                        self,
                        f"a prose section mentioning{member} verbatim",
                        "fixture section",
                    )

    def test_helper_passes_clean_prose(self):
        """A guard that fails on everything is as useless as one that fails on
        nothing — pin the negative case too."""
        assert_project_agnostic(
            self,
            "a prose section using only generic terms: state field, marker, gate.",
            "fixture section",
        )


if __name__ == "__main__":
    unittest.main()

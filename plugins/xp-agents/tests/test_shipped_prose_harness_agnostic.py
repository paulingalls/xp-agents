#!/usr/bin/env python3
"""Shipped prose must not name one harness as though it were the only one.

Milestone 8 asks for prose audited for harness leaks the way it is already
audited for language leaks, and the sibling
`test_shipped_prose_language_agnostic.py` establishes that way: an AT-SITE
`<!-- lang-ok: reason -->` marker, chosen because "an allowlist in another file
drifts away from" the thing it excuses. This pin mirrors it with its own keyword,
`harness-ok`, so the two guardrails cannot silence each other.

At-site is what makes a stale excuse impossible rather than policed. A marker
lives on the line it excuses, so deleting the sentence deletes the marker with
it. A separate registry keyed on a line number would instead red-light any commit
that merely inserted a paragraph above a site — and a guardrail that fires on
unrelated edits gets blanket-updated, which is the same as deleted.

These fixture rows come first because the scanner's exclusions are the whole
design: 216 of ~230 harness mentions in shipped prose are excluded structurally,
so an exclusion even slightly too greedy produces a green pin over a leaky tree.
The positive controls exist to make that failure loud.

LIMITS — READ THIS BEFORE TRUSTING THE GREEN CHECK. A guardrail that overclaims
is itself a green check certifying something untrue. What this pin does NOT see:

* Anything inside a backtick span, including a harness's binary name used as a
  noun rather than as a command to type — `skills/xp-assign/SKILL.md` says a
  headless `claude -p` session, and that stays invisible here. Accurate today
  (the spawn script runs exactly one harness); it becomes a leak the day the
  spawn is neutral, and this pin will not be what catches it.
* Shell prose bound to a variable instead of echoed. A shell file may assign a
  whole user-facing sentence to a variable and echo the variable later; the
  model reads the echo, not the sentence. Scanning every string literal in
  every shell file would reach it, at the cost of judging command arguments as
  English.
* A documentation URL, which `_PATHY` blanks along with real dotfile paths.
  Both harnesses' readers get pointed at one harness's docs, and neither name
  can be rewritten without naming nothing.
* SHIPPED PYTHON, ENTIRELY — the largest gap, and the one this list previously
  omitted while reading exhaustive. `shipped_prose_files` walks `.md` and `.sh`
  only, so every user-facing string in `scripts/` and `smm/` is unjudged. That
  is not theoretical: `session_start_banner.py` shipped a banner naming one
  harness's uninstall command, injected on BOTH harnesses, and it was found by
  a human reading the diff rather than by this pin. A Python prose model would
  have to tell a user-facing string from a subprocess argument, which is the
  same judgement the shell model makes and no harder — it is unbuilt, not
  impossible.
"""

import sys
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import _harness_leak_scan as scan
from _paths import _PLUGIN_ROOT


class TestProseIsFound(unittest.TestCase):
    """Positive controls. Without these, over-broad exclusions read as clean."""

    def test_a_plain_markdown_prose_mention_is_reported(self):
        found = scan.find_harness_mentions("Run this under Claude Code.\n", ".md")
        self.assertEqual(found, [(1, "claude")])

    def test_a_shell_echo_body_is_prose(self):
        """The measured leak's own shape: advice inside an echoed string."""
        text = 'echo "Run the test command (look in CLAUDE.md)"\n'
        self.assertEqual(scan.find_harness_mentions(text, ".sh"), [(1, "claude")])

    def test_a_printf_payload_is_prose_not_just_its_format_string(self):
        """`printf '%s\\n' "<payload>"` is the tree's dominant printf shape.

        A rule reading only the first quoted run scans the format string and
        never the sentence beside it — the same class of miss as the leak this
        pin was built from, hidden in the emitter the preload helpers use most.
        """
        text = """printf '%s\\n' "Look in CLAUDE.md for the test command"\n"""
        self.assertEqual(scan.find_harness_mentions(text, ".sh"), [(1, "claude")])

    def test_a_shell_comment_body_is_prose(self):
        self.assertEqual(
            scan.find_harness_mentions("# Codex reads a different file\n", ".sh"),
            [(1, "codex")],
        )

    def test_the_other_harness_is_caught_too(self):
        """The pin is not one-sided: naming only the second harness is the same
        leak, and a rule that watched one name would pass the mirror image."""
        found = scan.find_harness_mentions("This only works on Codex.\n", ".md")
        self.assertEqual(found, [(1, "codex")])


class TestIdentifiersAreExcluded(unittest.TestCase):
    """Each exclusion class, PAIRED with a prose mention on the same line.

    The pairing is the point. Excluding the identifier must not amnesty its whole
    line, or `${CLAUDE_PLUGIN_ROOT}` becomes a licence to say anything after it.
    """

    def test_the_plugin_root_variable_is_not_a_mention(self):
        text = "Resolve via `${CLAUDE_PLUGIN_ROOT}/smm/init.sh`.\n"
        self.assertEqual(scan.find_harness_mentions(text, ".md"), [])

    def test_but_prose_beside_that_variable_is_still_caught(self):
        text = "Set ${CLAUDE_PLUGIN_ROOT}, which only Claude Code defines.\n"
        self.assertEqual(scan.find_harness_mentions(text, ".md"), [(1, "claude")])

    def test_a_dot_path_is_not_a_mention(self):
        text = "Do not browse `.claude/` or the transcripts.\n"
        self.assertEqual(scan.find_harness_mentions(text, ".md"), [])

    def test_but_prose_beside_a_path_is_still_caught(self):
        text = "Files land in ~/.claude/plugins, because Claude puts them there.\n"
        self.assertEqual(scan.find_harness_mentions(text, ".md"), [(1, "claude")])

    def test_a_fenced_command_block_is_not_prose(self):
        text = "Install it:\n\n```bash\ncodex plugin add xp-agents@xp-agents\n```\n"
        self.assertEqual(scan.find_harness_mentions(text, ".md"), [])

    def test_but_prose_after_a_fence_closes_is_still_caught(self):
        text = "```bash\ncodex plugin add x\n```\n\nCodex is the only harness.\n"
        self.assertEqual(scan.find_harness_mentions(text, ".md"), [(5, "codex")])

    def test_a_multi_line_fence_does_not_leak_its_middle(self):
        """A fence opening and closing many lines apart must stay closed
        throughout — line-by-line blanking would read its body as prose."""
        text = "```bash\ncodex a\ncodex b\ncodex c\n```\n"
        self.assertEqual(scan.find_harness_mentions(text, ".md"), [])

    def test_a_nested_fence_does_not_blank_the_rest_of_the_file(self):
        """The failure that reads as CLEAN, which is why it gets its own row.

        A four-backtick block quoting an inner three-backtick one is how this
        tree shows a fenced example inside a fenced example. Toggling on every
        fence line reads the inner opener as the outer's close and the inner
        close as a new opening, so every later line scans as fenced — the pin
        then reports zero offenders over prose it never read, and the per-suffix
        file-count floor cannot see it because the file still counts as scanned.
        """
        text = (
            "````markdown\n"
            "```bash\n"
            "codex plugin add x\n"
            "```\n"
            "````\n"
            "\n"
            "Codex is the only harness.\n"
        )
        self.assertEqual(scan.find_harness_mentions(text, ".md"), [(7, "codex")])

    def test_an_unterminated_fence_is_reported_rather_than_swallowed(self):
        """A stray opener makes the rest of the file invisible to every rule
        here. Nothing can tell that apart from a genuinely code-only tail, so
        the imbalance itself is the finding."""
        text = "Fine prose.\n\n```bash\ncodex plugin add x\n"
        self.assertEqual(scan.unterminated_fence(text), 3)

    def test_a_balanced_file_reports_no_open_fence(self):
        text = "Fine prose.\n\n```bash\ncodex plugin add x\n```\n\nMore prose.\n"
        self.assertIsNone(scan.unterminated_fence(text))


class TestTheHatch(unittest.TestCase):
    """A marker excuses its line; an empty one excuses nothing."""

    def test_a_markdown_hatch_with_a_reason_excuses_the_line(self):
        text = "A Claude Code setting. <!-- harness-ok: only there -->\n"
        self.assertEqual(scan.find_harness_mentions(text, ".md"), [])

    def test_a_hatch_on_the_line_above_excuses_it(self):
        text = "<!-- harness-ok: that knob exists only there -->\nA Claude setting.\n"
        self.assertEqual(scan.find_harness_mentions(text, ".md"), [])

    def test_an_empty_reason_is_not_a_hatch(self):
        """An excuse that says nothing is not an excuse — the sibling pin treats
        a blank marker as absent, and a silencer is what this would become."""
        text = "A Claude Code setting. <!-- harness-ok: -->\n"
        self.assertEqual(scan.find_harness_mentions(text, ".md"), [(1, "claude")])

    def test_a_shell_hatch_uses_the_comment_form(self):
        text = '# harness-ok: that flag is only on that CLI\necho "Claude only"\n'
        self.assertEqual(scan.find_harness_mentions(text, ".sh"), [])

    def test_a_reason_that_opens_with_a_cli_flag_is_a_hatch(self):
        """The reason a leak most often HAS is the flag it names, and the shipped
        install prose names `--disable unified_exec` and
        `--dangerously-bypass-hook-trust`. A reason stopping at the first hyphen
        captured nothing, reported the line as unexcused while a reason sat
        visibly beside it, and made deleting accurate prose the obvious repair.
        """
        text = "A Claude Code flag. <!-- harness-ok: --disable is that CLI's -->\n"
        self.assertEqual(scan.find_harness_mentions(text, ".md"), [])

    def test_such_a_reason_is_visible_to_the_staleness_check_too(self):
        """Both readers share `_HATCH_RE`, so a reason invisible to one is
        invisible to the other: the line escapes the leak report AND the stale-
        marker report, which is the state no row can see."""
        text = "<!-- harness-ok: --disable is that CLI's -->\nNo harness named.\n"
        self.assertEqual(scan.hatches_without_mentions(text, ".md"), [1])


class TestAHatchCannotOutliveItsProse(unittest.TestCase):
    """The property that made at-site the right choice.

    A registry keyed on a line number needs machinery to notice that the prose it
    excused was reworded away. Here the marker sits on the line, so the residue
    is visible directly — and the pin reports it rather than letting a stale
    excuse accumulate.
    """

    def test_a_hatch_with_no_mention_beside_it_is_reported(self):
        text = "<!-- harness-ok: stale reason -->\nThis text no longer names one.\n"
        self.assertEqual(scan.hatches_without_mentions(text, ".md"), [1])

    def test_a_hatch_doing_real_work_is_not_reported(self):
        text = "<!-- harness-ok: a live reason -->\nA Claude Code setting.\n"
        self.assertEqual(scan.hatches_without_mentions(text, ".md"), [])


# The scan must actually cover the tree. A glob that matched nothing would
# report zero leaks and read as clean, which is the failure this whole file is
# built to make loud. Floored PER SUFFIX, as the sibling pin floors per glob
# group: the two suffixes are two different prose models over two different
# surfaces, and a tree-wide total cannot see one of them empty out. Every skill
# preload could vanish and a total of 40 would still clear. Floors from the tree
# as it stands (31 `.md`, 25 `.sh`).
_MIN_FILES_BY_SUFFIX = {".md": 28, ".sh": 22}


class TestTheShippedTreeIsClean(unittest.TestCase):
    """No shipped prose names a harness without an at-site reason.

    This row was run RED against the unfixed preload before the wording change
    landed — it reported `skills/_preload_base.sh:286`, which is the behaviour
    proof for this story's only production edit.
    """

    def setUp(self):
        self.files = scan.shipped_prose_files(_PLUGIN_ROOT)

    def test_the_scan_actually_covers_the_tree(self):
        """Non-vacuity: an empty scan reports zero leaks and looks green."""
        counts = Counter(path.suffix for path in self.files)
        self.assertEqual(
            set(counts),
            set(_MIN_FILES_BY_SUFFIX),
            "a prose model was added or dropped without a floor",
        )
        for suffix, floor in sorted(_MIN_FILES_BY_SUFFIX.items()):
            with self.subTest(suffix=suffix):
                self.assertGreaterEqual(
                    counts[suffix],
                    floor,
                    f"the {suffix} surface scans {counts[suffix]} files, below "
                    f"its floor of {floor} — a glob stopped matching, and a "
                    "surface that matches nothing reports no leaks",
                )

    def test_no_unmarked_harness_mention_survives(self):
        offenders = []
        for path in self.files:
            text = path.read_text(encoding="utf-8")
            for line, name in scan.find_harness_mentions(text, path.suffix):
                offenders.append(f"{path.relative_to(_PLUGIN_ROOT)}:{line} [{name}]")
        self.assertEqual(
            offenders,
            [],
            "shipped prose names a harness with no `harness-ok:` reason at the "
            "site:\n  " + "\n  ".join(offenders),
        )

    def test_no_shipped_markdown_leaves_a_fence_open(self):
        """Non-vacuity, per file: an open fence hides every line after it.

        The floor above counts files, not lines, so a file scanned down to a
        stray opener and skipped from there still counts as covered.
        """
        open_fences = []
        for path in self.files:
            if path.suffix != ".md":
                continue
            line = scan.unterminated_fence(path.read_text(encoding="utf-8"))
            if line is not None:
                open_fences.append(f"{path.relative_to(_PLUGIN_ROOT)}:{line}")
        self.assertEqual(
            open_fences,
            [],
            "a fenced block is never closed, so everything after it is invisible "
            "to this pin:\n  " + "\n  ".join(open_fences),
        )

    def test_no_marker_has_outlived_its_prose(self):
        """AC#3 — the residue an at-site marker can still leave behind."""
        stale = []
        for path in self.files:
            text = path.read_text(encoding="utf-8")
            for line in scan.hatches_without_mentions(text, path.suffix):
                stale.append(f"{path.relative_to(_PLUGIN_ROOT)}:{line}")
        self.assertEqual(
            stale,
            [],
            "a `harness-ok:` marker excuses nothing:\n  " + "\n  ".join(stale),
        )


class TestTheGuidesAndPreloadNeedNoExcuse(unittest.TestCase):
    """AC#4 — the guides and the shared preload are clean, not excused.

    Stated as its own claim rather than left to follow from the tree-wide row:
    those three files being green *without a marker* is what the story owes, and
    a tree-wide pass would also be satisfied by marking them.
    """

    def test_they_carry_no_harness_marker(self):
        targets = [
            _PLUGIN_ROOT / "PROCESS_GUIDE.md",
            _PLUGIN_ROOT / "TEAMMATE_GUIDE.md",
            _PLUGIN_ROOT / "skills" / "_preload_base.sh",
        ]
        marked = [
            str(p.relative_to(_PLUGIN_ROOT))
            for p in targets
            if "harness-ok:" in p.read_text(encoding="utf-8")
        ]
        self.assertEqual(
            marked,
            [],
            f"these should need no excuse, but carry one: {marked}",
        )

    def test_and_they_report_no_leak(self):
        names = ("PROCESS_GUIDE.md", "TEAMMATE_GUIDE.md", "skills/_preload_base.sh")
        for name in names:
            path = _PLUGIN_ROOT / name
            with self.subTest(file=name):
                found = scan.find_harness_mentions(
                    path.read_text(encoding="utf-8"), path.suffix
                )
                self.assertEqual(found, [])


# Every file carrying a `DEFERRED AS DEBT` marker, and nothing else. Pinned by
# FILE, not by line, so inserting a paragraph does not red-light the commit —
# but adding or dropping a deferral has to be a deliberate edit here, which is
# what makes the roster an assertion rather than a printout.
#
# No debt id is pinned, and none appears in the markers: shipped agent prose is
# separately pinned to carry no 12-hex ids. The marker says it is a deferral in
# words; the debt event carries the file, which is the join key.
_DEBT_DEFERRED_FILES = {"agents/xp-system-analyzer.md"}


class TestDeferredLeaksStayReported(unittest.TestCase):
    """AC#5 — a leak deferred as debt is declared, not silenced.

    A marker reading DEFERRED AS DEBT is an admission, not an excuse: it keeps
    the pin green so the suite stays usable, and a debt event is the actual
    record. A roster that has to be edited is what keeps the two honest — a
    printed list nobody asserts on grows a deferral silently.
    """

    def test_the_deferred_roster_is_exactly_what_is_declared(self):
        deferred = {
            str(path.relative_to(_PLUGIN_ROOT))
            for path in scan.shipped_prose_files(_PLUGIN_ROOT)
            for line in path.read_text(encoding="utf-8").splitlines()
            if "harness-ok:" in line and "DEFERRED AS DEBT" in line
        }
        self.assertEqual(
            deferred,
            _DEBT_DEFERRED_FILES,
            "the set of harness leaks deferred as debt changed. Adding one is "
            "allowed — record the debt event, then add the file here so the "
            "deferral is declared rather than accumulated",
        )

    def test_a_deferral_marker_still_excuses_a_real_mention(self):
        """A deferral that stopped covering a leak is a marker excusing nothing,
        and would otherwise sit in the roster looking like live cover."""
        for name in sorted(_DEBT_DEFERRED_FILES):
            path = _PLUGIN_ROOT / name
            with self.subTest(file=name):
                text = path.read_text(encoding="utf-8")
                self.assertEqual(scan.hatches_without_mentions(text, path.suffix), [])


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Doctrinal pin: shipped PROSE may not name one language's tool as the remedy.

The prose half of the doctrine `hooks/test_no_language_leak.py` enforces over
code. That sibling stops a shipped module branching on a file's extension; this
one stops a shipped *instruction* assuming the reader's project is Python. Both
exist because the plugin ships to projects in any language, and until these pins
the invariant was enforced only by prose plus reviewer vigilance — which
sprint-103 leaked past three times before being abandoned.

The leak this pin was built from: `TEAMMATE_GUIDE.md` told every teammate, in
every project, to run ``ruff format`` before staging, and the close pipeline's
`lint` remedy said ``ruff format && ruff check --fix``. Both reach the reader
verbatim. Neither is actionable in a project that ships no Python, and the
plugin already carries a table of eighteen linters it detects instead.

TWO LEGS, and the second is the stronger one.

1. **Prose.** A shipped text surface may name no tool from the vocabulary below.
   Not "no more than one", and not a one-vs-many heuristic: the surfaces that
   look like counter-examples (`skills/xp-sprint-start/SKILL.md`'s runner list,
   `agents/xp-plan-reviewer.md`'s positional-runner list,
   `agents/xp-system-analyzer.md`'s detection tables) name ZERO entries of this
   vocabulary — their pytest/playwright/cargo/bats mentions are test *runners*,
   not linters or formatters. An exemption for "names several" would therefore
   protect nothing in this tree while adding a heuristic that can be argued with.

2. **Tool grants.** Every `Bash(...)` entry in a shipped skill or agent's
   `allowed-tools` must name a plugin-owned path or a host VCS command — never a
   language's test runner or linter. This needs no vocabulary at all: it reads
   machine-readable frontmatter and cannot false-positive on English. It was
   added after `Bash(python3 -m unittest *)` was found in
   `skills/xp-quality-review/SKILL.md` — a grant that is inert for every
   non-Python project (it can never match `cargo test`) yet implies to all of
   them that their tests are Python's.

THE ESCAPE HATCH is `<!-- lang-ok: <reason> -->` on the offending line or the one
above it, mirroring the shipped `# lang-ok:` convention of the code-side pin. The
justification lives AT THE SITE; an allowlist in another file drifts away from
what it excuses. The reason must be non-empty.

LIMITS — READ THIS BEFORE TRUSTING THE GREEN CHECK. A guardrail that overclaims
is itself a green check certifying something untrue, which is the failure these
pins exist to kill. So, precisely:

* The vocabulary is `linter_tables.LINTER_COMMANDS` — which holds **check**
  linters — plus `_FORMATTERS` below, because that table has no format/fix
  column. Anything in neither list is invisible here: a new formatter, a type
  checker (`mypy`, `tsc`), a build tool. The durable fix is a format/fix column
  in `linter_tables` so this pin can read one list; see `_FORMATTERS`.
* It reads literal tool names only. "Run the Python formatter" or "run black"
  written as prose without the backticked token may still slip past, and an
  instruction that is language-specific in meaning but names no tool
  ("re-run the type checker on the changed .py files") is out of reach entirely.
* Leg 2 sees only `Bash(...)` entries in shipped frontmatter. A language
  assumption expressed in a skill's *body* is leg 1's problem, and one expressed
  in hook registration or a script is neither pin's.
* Tests are not scanned, by either leg. They never ship, so they are free to be
  Python-specific — the same carve-out the code-side pin makes.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from _pin_helpers import rel as _rel_impl
from _pin_helpers import shipped_prose_to_scan
from linter_tables import LINTER_COMMANDS

PLUGIN_ROOT = Path(__file__).parent.parent  # plugins/xp-agents/
REPO_ROOT = PLUGIN_ROOT.parent.parent  # repo root, for stable rel paths

# Formatters and fixers, which `LINTER_COMMANDS` does NOT carry: every entry
# there is a CHECK invocation (`ruff` -> `ruff check --output-format=concise`),
# and the only `--fix` in the whole table belongs to `php-cs-fixer`. The leak
# that motivated this pin was a FORMAT instruction, so a pin reading the table
# alone would have been blind to the very recurrence it guards — `gofmt` would
# have sailed past it.
#
# This list lives here, in a test, rather than in `linter_tables`, because
# nothing in the shipped plugin invokes a formatter yet: adding a shipped table
# with no shipped caller would be inventing machinery to satisfy a test. When a
# format/fix column earns its place in `linter_tables` (the recorded follow-up),
# this constant should be deleted and read from there instead.
_FORMATTERS = frozenset(
    {
        "black",
        "autopep8",
        "isort",
        "yapf",
        "gofmt",
        "goimports",
        "rustfmt",
        "cargo fmt",
        "standardrb",
        "ktlint",
        "google-java-format",
        "shfmt",
    }
)

TOOL_VOCABULARY = frozenset(LINTER_COMMANDS) | _FORMATTERS

# `<!-- lang-ok: reason -->`, reason non-empty.
_HATCH_RE = re.compile(r"<!--\s*lang-ok:\s*(?P<reason>[^>]*?)\s*-->")

# A `Bash(...)` entry in an `allowed-tools` block.
_GRANT_RE = re.compile(r"^\s*-\s*Bash\((?P<body>[^)]*)\)\s*$")

# What a grant is ALLOWED to name. A permit-list, so an unrecognised grant fails
# closed rather than being silently tolerated.
#
# THE DISCRIMINATOR, found by running this leg over the real tree: `python3` is
# not the signal — the plugin is itself Python and requires `python3` on PATH, so
# it legitimately grants both `python3 */smm/sprint_cli.py *` (its own script) and
# `python3 -c *datetime*` (its own inline code). What separates those from
# `python3 -m unittest *` is `-m`: it resolves a module from the ENVIRONMENT,
# which is the user's project, not the plugin. Plugin path or `-c` = our code;
# `-m` = their toolchain. That is why `-m` appears in no permitted form below.
_PLUGIN_OWNED = (
    "*/scripts/",
    "*/smm/",
    "*/skills/",
    "*/append.sh",
    "*/init.sh",
)
# The plugin running its own inline code under its own declared runtime.
_PLUGIN_INLINE = ("python3 -c",)
# Host utilities every project has whatever its language: the VCS, the forge CLI,
# and POSIX text builtins. None carries language semantics.
_HOST_COMMANDS = ("git ", "gh ", "printf ", "echo ")

# Floors per glob group, from the tree as it stands. A group that empties out is
# a dropped surface, and a tree-wide total would not see it: `scripts prose`
# matches exactly ONE file, so a rename there would leave the total healthy.
_GROUP_FLOORS = {
    "root guides": 3,
    "agents": 6,
    "skills": 15,
    "scripts prose": 1,
}


def _rel(path: Path) -> str:
    return _rel_impl(path, REPO_ROOT)


def _hatched(lines: list[str], index: int) -> bool:
    """True when the line, or the one above it, carries a non-empty hatch."""
    for candidate in (lines[index], lines[index - 1] if index else ""):
        match = _HATCH_RE.search(candidate)
        if match and match.group("reason").strip():
            return True
    return False


def find_prose_tool_names(
    text: str, vocabulary: frozenset[str] = TOOL_VOCABULARY
) -> list[tuple[int, str]]:
    """Every (1-based line, tool) where shipped prose names a vocabulary tool.

    Word-boundary matched so `ruff` does not fire inside a longer word, and
    multi-word entries (`cargo fmt`) are matched whole. Hatched lines are
    skipped, not reported.
    """
    lines = text.splitlines()
    hits: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        for tool in sorted(vocabulary):
            if not re.search(rf"(?<![\w-]){re.escape(tool)}(?![\w-])", line):
                continue
            if _hatched(lines, index):
                continue
            hits.append((index + 1, tool))
    return hits


def find_offending_grants(text: str) -> list[tuple[int, str]]:
    """Every (1-based line, grant body) that names neither plugin nor host."""
    offenders: list[tuple[int, str]] = []
    for index, line in enumerate(text.splitlines()):
        match = _GRANT_RE.match(line)
        if not match:
            continue
        body = match.group("body").strip()
        if any(owned in body for owned in _PLUGIN_OWNED):
            continue
        if body.startswith(_PLUGIN_INLINE) or body.startswith(_HOST_COMMANDS):
            continue
        offenders.append((index + 1, body))
    return offenders


def _scan_prose() -> dict[str, list[tuple[int, str]]]:
    found: dict[str, list[tuple[int, str]]] = {}
    for paths in shipped_prose_to_scan(PLUGIN_ROOT).values():
        for path in paths:
            hits = find_prose_tool_names(path.read_text(encoding="utf-8"))
            if hits:
                found[_rel(path)] = hits
    return found


def _scan_grants() -> dict[str, list[tuple[int, str]]]:
    found: dict[str, list[tuple[int, str]]] = {}
    groups = shipped_prose_to_scan(PLUGIN_ROOT)
    for group in ("agents", "skills"):
        for path in groups[group]:
            offenders = find_offending_grants(path.read_text(encoding="utf-8"))
            if offenders:
                found[_rel(path)] = offenders
    return found


class TestShippedProseNamesNoSingleLanguageTool(unittest.TestCase):
    """Leg 1: no shipped text surface names a linter or formatter."""

    def test_no_shipped_prose_names_a_tool(self) -> None:
        offenders = _scan_prose()
        self.assertEqual(
            offenders,
            {},
            "shipped prose names a single language's tool as the remedy — point "
            "the reader at the project's own formatter/linter, or justify it "
            "inline with `<!-- lang-ok: <reason> -->`:\n"
            + "\n".join(
                f"  {path}:{line} names `{tool}`"
                for path, hits in sorted(offenders.items())
                for line, tool in hits
            ),
        )


class TestShippedGrantsNameNoUserRunner(unittest.TestCase):
    """Leg 2: every Bash grant names a plugin path or the host's VCS."""

    def test_no_grant_names_a_user_project_runner(self) -> None:
        offenders = _scan_grants()
        self.assertEqual(
            offenders,
            {},
            "a shipped Bash(...) grant names something other than a "
            "plugin-owned path or a host VCS command. A grant naming the "
            "project's test runner or linter assumes its language, and is "
            "inert for every other one:\n"
            + "\n".join(
                f"  {path}:{line} grants `{body}`"
                for path, offending in sorted(offenders.items())
                for line, body in offending
            ),
        )


class TestScanIsNotVacuous(unittest.TestCase):
    """A pin that silently matches nothing passes forever.

    Floored PER GROUP: `scripts prose` is a single file, so a rename would drop
    that entire surface while a tree-wide count still cleared its floor.
    """

    def test_every_group_meets_its_floor(self) -> None:
        groups = shipped_prose_to_scan(PLUGIN_ROOT)
        self.assertEqual(
            set(groups),
            set(_GROUP_FLOORS),
            "a glob group was added or renamed without a floor",
        )
        for name, floor in sorted(_GROUP_FLOORS.items()):
            with self.subTest(group=name):
                self.assertGreaterEqual(
                    len(groups[name]),
                    floor,
                    f"the {name!r} surface scans {len(groups[name])} files, "
                    f"below its floor of {floor} — a glob stopped matching",
                )

    def test_vocabulary_is_not_empty(self) -> None:
        self.assertGreaterEqual(len(TOOL_VOCABULARY), 25)
        self.assertIn("ruff", TOOL_VOCABULARY)

    def test_vocabulary_covers_formatters_the_table_omits(self) -> None:
        """The blind spot this pin was corrected for: the table is check-only."""
        self.assertNotIn("gofmt", LINTER_COMMANDS)
        self.assertIn("gofmt", TOOL_VOCABULARY)

    def test_grant_scan_reads_a_real_grant_surface(self) -> None:
        """Leg 2's own non-vacuity: frontmatter is actually being parsed."""
        groups = shipped_prose_to_scan(PLUGIN_ROOT)
        grants = [
            body
            for group in ("agents", "skills")
            for path in groups[group]
            for _, body in _all_grants(path.read_text(encoding="utf-8"))
        ]
        self.assertGreaterEqual(
            len(grants),
            20,
            "no Bash grants found — the frontmatter shape changed and leg 2 "
            "is scanning nothing",
        )


def _all_grants(text: str) -> list[tuple[int, str]]:
    """Every Bash grant, offending or not — for leg 2's vacuity check."""
    return [
        (index + 1, match.group("body").strip())
        for index, line in enumerate(text.splitlines())
        if (match := _GRANT_RE.match(line))
    ]


class TestDetectionActuallyWorks(unittest.TestCase):
    """Mutation proof, in-suite. Four vacuous pins were found in one sprint;
    a pin asserting a property nothing exercises is how that keeps happening.
    Both legs are green over the real tree once the fix lands, so a synthetic
    offender is the only thing that can prove the matchers fire at all."""

    def test_a_single_tool_instruction_is_flagged(self) -> None:
        hits = find_prose_tool_names("- `ruff format` before staging\n")
        self.assertEqual(hits, [(1, "ruff")])

    def test_a_multi_word_tool_is_matched_whole(self) -> None:
        self.assertEqual(
            find_prose_tool_names("run `cargo fmt` first\n"), [(1, "cargo fmt")]
        )

    def test_a_tool_inside_a_longer_word_is_not_flagged(self) -> None:
        """`ruff` must not fire on `scruffy`, or the pin gets disabled."""
        self.assertEqual(find_prose_tool_names("a scruffy diff, blackened\n"), [])

    def test_agnostic_prose_is_not_flagged(self) -> None:
        self.assertEqual(
            find_prose_tool_names("- Run the project's formatter before staging\n"),
            [],
        )

    def test_the_hatch_exempts_a_named_tool(self) -> None:
        text = "listing linters <!-- lang-ok: documents the detection table -->\n"
        self.assertEqual(find_prose_tool_names(text), [])

    def test_the_hatch_on_the_line_above_exempts(self) -> None:
        text = "<!-- lang-ok: table of every detected linter -->\n| `ruff` | .py |\n"
        self.assertEqual(find_prose_tool_names(text), [])

    def test_an_empty_hatch_reason_does_not_exempt(self) -> None:
        """A bare marker is a shrug, not a justification."""
        self.assertEqual(
            find_prose_tool_names("`ruff` <!-- lang-ok: -->\n"), [(1, "ruff")]
        )

    def test_a_user_runner_grant_is_flagged(self) -> None:
        self.assertEqual(
            find_offending_grants("  - Bash(python3 -m unittest *)\n"),
            [(1, "python3 -m unittest *")],
        )

    def test_plugin_owned_and_host_grants_are_exempt(self) -> None:
        text = (
            "  - Bash(python3 */smm/sprint_cli.py *)\n"
            "  - Bash(*/append.sh *)\n"
            "  - Bash(*/init.sh)\n"
            "  - Bash(*/skills/*/scripts/*)\n"
            "  - Bash(git push *)\n"
            "  - Bash(gh pr *)\n"
            "  - Bash(printf *)\n"
        )
        self.assertEqual(find_offending_grants(text), [])

    def test_the_plugins_own_inline_runtime_is_exempt_but_dash_m_is_not(self) -> None:
        """`python3` is not the signal — `-m` is. `-c` runs the plugin's own code;
        `-m` resolves a module from the environment, which is the user's project.
        Both were live in the tree, and conflating them would have forced a real
        grant to be deleted or a real leak to be tolerated."""
        self.assertEqual(find_offending_grants("  - Bash(python3 -c *datetime*)\n"), [])
        self.assertEqual(
            find_offending_grants("  - Bash(python3 -m pytest *)\n"),
            [(1, "python3 -m pytest *")],
        )


if __name__ == "__main__":
    unittest.main()

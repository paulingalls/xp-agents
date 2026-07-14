#!/usr/bin/env python3
"""Unit tests for the language-leak walker (`tests/_lang_leak_scan.py`).

Split from `test_no_language_leak.py`, which is the pin — it points the walker
at the real shipped tree and fails on an unjustified extension predicate. This
file tests the walker itself: what it detects, and what it must never detect.

Every case writes a temp file and runs the production `scan_file` over it — the
same `read_text -> ast.parse -> walk` pipeline the pin uses. An in-memory AST
node would bypass file I/O and parse, hiding a regression in either layer.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _lang_leak_scan import Site, scan_file


class TestWalkerDetection(unittest.TestCase):
    """The walker, exercised end-to-end on real files.

    Every case writes a temp file and runs the production scanner over it —
    the same `read_text -> ast.parse -> walk` pipeline the pin uses. An
    in-memory AST node would bypass file I/O and parse, hiding a regression in
    either layer.
    """

    def _scan(self, src: str) -> list[Site]:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "shipped_module.py"
            tmp.write_text(src)
            return scan_file(tmp)

    def test_planted_leak_is_caught(self) -> None:
        """AC1: the canonical leak — a `.py` predicate on a user's path."""
        sites = self._scan(
            "from pathlib import Path\n"
            "\n"
            "def check(file_path):\n"
            '    if Path(file_path).suffix != ".py":\n'
            "        return None\n"
            "    return file_path\n"
        )
        self.assertEqual(sites, [(4, "suffix-compare", None)])

    def test_planted_leak_on_bare_attribute_is_caught(self) -> None:
        """`path.suffix != ".py"` — the exact shape CLAUDE.md names — has no
        `Path(...)` call to anchor on. The rule must not require one."""
        sites = self._scan('def check(path):\n    return path.suffix == ".py"\n')
        self.assertEqual(sites, [(2, "suffix-compare", None)])

    def test_planted_endswith_leak_is_caught(self) -> None:
        sites = self._scan(
            "def staged(paths):\n    return [p for p in paths if p.endswith('.py')]\n"
        )
        self.assertEqual(sites, [(2, "endswith-extension", None)])

    def test_hoisted_suffix_is_caught_one_hop_away(self) -> None:
        """TRAP: `suffix = Path(p).suffix` then `if suffix in SET` is the same
        predicate one statement apart. Firing on the inline form only would
        mean a leak could be hidden by hoisting it to a local."""
        sites = self._scan(
            "from pathlib import Path\n"
            "\n"
            "def classify(path):\n"
            "    suffix = Path(path).suffix.lower()\n"
            '    return suffix in {".py", ".ts"}\n'
        )
        self.assertEqual(sites, [(5, "suffix-compare", None)])

    def test_conditional_hoisted_suffix_is_caught(self) -> None:
        """`file_suffix = Path(fp).suffix if fp else None` — the hoist hides
        inside an IfExp in shipped code."""
        sites = self._scan(
            "from pathlib import Path\n"
            "\n"
            "def detect(file_path, allowed):\n"
            "    file_suffix = Path(file_path).suffix if file_path else None\n"
            "    return file_suffix not in allowed\n"
        )
        self.assertEqual(sites, [(5, "suffix-compare", None)])

    def test_tuple_of_extensions_is_caught(self) -> None:
        sites = self._scan(
            'def is_ts(name):\n    return name.endswith((".ts", ".tsx"))\n'
        )
        self.assertEqual(sites, [(2, "endswith-extension", None)])

    def test_walrus_hoisted_suffix_is_caught(self) -> None:
        """TRAP: `if (s := Path(p).suffix) == ".py"` hoists the suffix into the
        comparison itself. The Compare's left is a NamedExpr, not an Attribute —
        a rule that only unwraps attributes lets the walrus form through."""
        sites = self._scan(
            "from pathlib import Path\n"
            "\n"
            "def check(file_path):\n"
            '    if (ext := Path(file_path).suffix) == ".py":\n'
            "        return ext\n"
            "    return None\n"
        )
        self.assertEqual(sites, [(4, "suffix-compare", None)])

    def test_match_case_on_a_suffix_is_caught(self) -> None:
        """TRAP: this project's own coding standard mandates `match/case` for
        routing, so routing on an extension is the shape a future author here is
        most likely to reach for — and it is not a Compare at all."""
        sites = self._scan(
            "from pathlib import Path\n"
            "\n"
            "def linter_for(file_path):\n"
            "    match Path(file_path).suffix:\n"
            '        case ".py":\n'
            '            return "ruff"\n'
            "        case _:\n"
            "            return None\n"
        )
        self.assertEqual(sites, [(4, "suffix-match", None)])

    def test_match_case_on_a_hoisted_suffix_is_caught(self) -> None:
        """The same routing one hop away: `suffix = Path(p).suffix` then
        `match suffix:`."""
        sites = self._scan(
            "from pathlib import Path\n"
            "\n"
            "def linter_for(file_path):\n"
            "    suffix = Path(file_path).suffix\n"
            "    match suffix:\n"
            '        case ".ts" | ".tsx":\n'
            '            return "eslint"\n'
            "        case _:\n"
            "            return None\n"
        )
        self.assertEqual(sites, [(5, "suffix-match", None)])

    def test_own_source_mention_does_not_exempt_a_user_path(self) -> None:
        """TRAP, and the sharpest hole in the `__file__` exemption: the operand
        here is the USER's path — it is merely *measured against* the plugin's
        own root. Exempting on "an own-source name appears somewhere in the
        subtree" hands a real leak a silent pass; only the path the suffix is
        actually taken FROM may earn the exemption."""
        sites = self._scan(
            "from pathlib import Path\n"
            "\n"
            "def check(user_path):\n"
            "    here = Path(__file__).parent\n"
            '    return Path(user_path).relative_to(here).suffix == ".py"\n'
        )
        self.assertEqual(sites, [(5, "suffix-compare", None)])

    def test_own_source_mention_does_not_exempt_an_endswith(self) -> None:
        """Same hole on the `endswith` leg."""
        sites = self._scan(
            "from pathlib import Path\n"
            "\n"
            "def check(user_path):\n"
            "    root = Path(__file__).parent\n"
            '    return str(Path(user_path).relative_to(root)).endswith(".py")\n'
        )
        self.assertEqual(sites, [(5, "endswith-extension", None)])

    def test_marked_site_passes(self) -> None:
        """AC3: an inline marker with a reason satisfies the pin."""
        sites = self._scan(
            "def ruff_targets(staged):\n"
            "    # lang-ok: per-linter dispatch; returns [] in a Rust project\n"
            '    return [p for p in staged if p.endswith(".py")]\n'
        )
        self.assertEqual(
            sites,
            [
                (
                    3,
                    "endswith-extension",
                    "per-linter dispatch; returns [] in a Rust project",
                )
            ],
        )

    def test_marker_on_the_statement_itself_passes(self) -> None:
        sites = self._scan(
            "def ruff_targets(staged):\n"
            '    return [p for p in staged if p.endswith(".py")]  # lang-ok: dispatch\n'
        )
        self.assertEqual(sites, [(2, "endswith-extension", "dispatch")])

    def test_empty_marker_reason_is_reported(self) -> None:
        """AC3: the marker without a reason must not silence the pin."""
        sites = self._scan(
            "def ruff_targets(staged):\n"
            "    # lang-ok:\n"
            '    return [p for p in staged if p.endswith(".py")]\n'
        )
        self.assertEqual(sites, [(3, "endswith-extension", "")])

    def test_function_scope_marker_covers_every_predicate_inside(self) -> None:
        """A dispatch built from many per-ecosystem predicates is justified
        once, at the function, not once per branch."""
        sites = self._scan(
            "from pathlib import Path\n"
            "\n"
            "def is_test_file(path):\n"
            '    """Detect tests across ecosystems.\n'
            "\n"
            "    lang-ok: enumerates 13 ecosystems; Python is one peer.\n"
            '    """\n'
            "    p = Path(path)\n"
            '    if p.name.endswith("_test.go"):\n'
            "        return True\n"
            '    return p.suffix == ".py"\n'
        )
        reasons = {r for _, _, r in sites}
        self.assertEqual(len(sites), 2)
        self.assertEqual(reasons, {"enumerates 13 ecosystems; Python is one peer."})

    def test_marker_spanning_a_multiline_statement_is_found(self) -> None:
        """AST discards comments, so the marker is matched on raw lines. A
        multi-line set literal puts the marker several lines from the
        statement's first line."""
        sites = self._scan(
            "from pathlib import Path\n"
            "\n"
            "def classify(path):\n"
            "    return Path(path).suffix in {\n"
            '        ".py",  # lang-ok: deny-list, everything else is code\n'
            '        ".rs",\n'
            "    }\n"
        )
        self.assertEqual(
            sites,
            [(4, "suffix-compare", "deny-list, everything else is code")],
        )


class TestWalkerFalsePositives(unittest.TestCase):
    """Zero false positives on today's tree (AC2).

    Each case is a real shape from shipped code, none of them in this story's
    file domain. A noisy guardrail gets disabled, which is worse than none —
    and "fixing" the noise by editing out-of-domain files, or by loosening the
    marker convention under pressure, is how a pin rots.
    """

    def _scan(self, src: str) -> list[Site]:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "shipped_module.py"
            tmp.write_text(src)
            return scan_file(tmp)

    def test_trailing_slash_check_is_not_an_extension(self) -> None:
        """verify_paths.py: `path.endswith("/")` — a directory test."""
        sites = self._scan(
            "def normalize(path, normalized):\n"
            '    return normalized + "/" if path.endswith("/") else normalized\n'
        )
        self.assertEqual(sites, [])

    def test_field_name_suffix_check_is_not_an_extension(self) -> None:
        """resolution.py: `key.endswith("_ids")` — a JSON field-name test."""
        sites = self._scan("def is_id_list(key):\n    return key.endswith('_ids')\n")
        self.assertEqual(sites, [])

    def test_computed_path_suffix_is_not_an_extension(self) -> None:
        """concerns.py / story_metrics.py: `p.endswith("/" + rel)` — a BinOp,
        not a literal. Matching it would demand markers on path arithmetic."""
        sites = self._scan(
            "def owns(path_part, rel_path):\n"
            '    return path_part == rel_path or path_part.endswith("/" + rel_path)\n'
        )
        self.assertEqual(sites, [])

    def test_dynamic_suffix_from_a_rule_table_is_not_flagged(self) -> None:
        """sister_tests.py: `source_path.endswith(s) for s in rule.skip_suffixes`
        — the per-language suffixes live in a data table, so the call site is
        agnostic by construction. Flagging it would punish the right design."""
        sites = self._scan(
            "def skipped(source_path, rule):\n"
            "    return any(source_path.endswith(s) for s in rule.skip_suffixes)\n"
        )
        self.assertEqual(sites, [])

    def test_docstring_mentioning_a_py_file_is_not_flagged(self) -> None:
        """TRAP: seven shipped modules put `python3 <script>.py` in their
        docstring, and dozens name `foo.py` in prose. Docstrings parse as bare
        Constants; no rule here matches one."""
        sites = self._scan(
            '"""Spawn a teammate.\n'
            "\n"
            "Usage: python3 spawn_teammate.py --story story-001\n"
            "\n"
            "Mirrors cleanup_teammate.py; see hooks.json.\n"
            '"""\n'
            "\n"
            "def spawn(story):\n"
            "    return story\n"
        )
        self.assertEqual(sites, [])

    def test_shebang_and_comments_are_not_flagged(self) -> None:
        """~140 shipped modules open with `#!/usr/bin/env python3`. They are
        comments: the AST never sees them. This is why the pin is not a grep."""
        sites = self._scan(
            "#!/usr/bin/env python3\n"
            "# Rewrites of foo.py and bar.py belong in baz.py\n"
            "def noop():\n"
            "    return None\n"
        )
        self.assertEqual(sites, [])

    def test_none_guard_on_a_suffix_is_not_a_predicate(self) -> None:
        """lint_check.py: `file_suffix = Path(fp).suffix if fp else None` then
        `if file_suffix is not None:`. Asking whether a suffix exists says
        nothing about any language; only the comparison against a set of
        extensions does."""
        sites = self._scan(
            "from pathlib import Path\n"
            "\n"
            "def detect(file_path):\n"
            "    file_suffix = Path(file_path).suffix if file_path else None\n"
            "    return file_suffix is not None\n"
        )
        self.assertEqual(sites, [])

    def test_own_source_path_is_not_flagged(self) -> None:
        """AC4: the plugin reasoning about its OWN module path is not a leak —
        that path IS Python, unconditionally."""
        sites = self._scan(
            "from pathlib import Path\n"
            "\n"
            "def own():\n"
            '    return Path(__file__).suffix == ".py"\n'
        )
        self.assertEqual(sites, [])

    def test_own_source_path_via_a_local_is_not_flagged(self) -> None:
        """AC4, one hop: `here = Path(__file__)` then `here.suffix == ".py"`."""
        sites = self._scan(
            "from pathlib import Path\n"
            "\n"
            "def own():\n"
            "    here = Path(__file__)\n"
            '    return here.suffix == ".py"\n'
        )
        self.assertEqual(sites, [])

    def test_own_source_through_a_path_join_is_not_flagged(self) -> None:
        """AC4 stays generous where it should: a sibling of the plugin's own
        module is still the plugin's own source, however many hops of `/` and
        `.parent` it takes to name it."""
        sites = self._scan(
            "from pathlib import Path\n"
            "\n"
            "def sibling(name):\n"
            '    return (Path(__file__).parent / name).suffix == ".py"\n'
        )
        self.assertEqual(sites, [])

    def test_own_source_binding_does_not_leak_across_functions(self) -> None:
        """The `__file__` exemption is scoped to the function that establishes
        it. A sibling function's `p` is a user path and stays flagged —
        otherwise one own-source local anywhere in a module would blanket-exempt
        every predicate in it."""
        sites = self._scan(
            "from pathlib import Path\n"
            "\n"
            "def own():\n"
            "    p = Path(__file__)\n"
            '    return p.suffix == ".py"\n'
            "\n"
            "def user(p):\n"
            '    return p.suffix == ".py"\n'
        )
        self.assertEqual(sites, [(8, "suffix-compare", None)])


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Tests for smm/triage.py — shared triage helpers.

Covers: find_unresolved, find_overlapping_commits, extract_file_domain_paths.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import triage
from conftest import make_event

# Explicit `from event_schema import EVENT_TYPE_*` so a future constant rename
# fails at test collection (NameError) instead of silently changing behavior.
from event_schema import EVENT_TYPE_COMMIT, EVENT_TYPE_CONCERN, EVENT_TYPE_DEBT


class TestFindUnresolved(unittest.TestCase):
    """find_unresolved returns unresolved events of a given type, newest first."""

    def test_returns_unresolved_concerns_newest_first(self):
        c1 = make_event(EVENT_TYPE_CONCERN, content="First")
        c1["ts"] = "2026-01-01T00:00:00Z"
        c2 = make_event(EVENT_TYPE_CONCERN, content="Second")
        c2["ts"] = "2026-01-02T00:00:00Z"
        result = triage.find_unresolved([c1, c2], "concern", set())
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["content"], "Second")

    def test_excludes_resolved(self):
        c1 = make_event(EVENT_TYPE_CONCERN, content="Resolved one")
        c2 = make_event(EVENT_TYPE_CONCERN, content="Still open")
        result = triage.find_unresolved([c1, c2], "concern", {c1["id"]})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["content"], "Still open")

    def test_filters_by_type(self):
        c = make_event(EVENT_TYPE_CONCERN, content="A concern")
        d = make_event(EVENT_TYPE_DEBT, content="Some debt")
        result = triage.find_unresolved([c, d], "concern", set())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["type"], EVENT_TYPE_CONCERN)

    def test_empty_events(self):
        result = triage.find_unresolved([], "concern", set())
        self.assertEqual(result, [])


class TestFindOverlappingCommits(unittest.TestCase):
    """find_overlapping_commits finds commits whose files overlap a concern."""

    def test_finds_overlapping_commit(self):
        concern = make_event(EVENT_TYPE_CONCERN, content="Issue", files=["src/app.ts"])
        commit = make_event(EVENT_TYPE_COMMIT, content="fix app", files=["src/app.ts"])
        commit["ts"] = "2099-01-01T00:00:00Z"
        result = triage.find_overlapping_commits(concern, [commit])
        self.assertEqual(len(result), 1)

    def test_ignores_commits_before_concern(self):
        concern = make_event(EVENT_TYPE_CONCERN, content="Issue", files=["src/app.ts"])
        concern["ts"] = "2099-01-01T00:00:00Z"
        commit = make_event(EVENT_TYPE_COMMIT, content="old fix", files=["src/app.ts"])
        commit["ts"] = "2000-01-01T00:00:00Z"
        result = triage.find_overlapping_commits(concern, [commit])
        self.assertEqual(len(result), 0)

    def test_no_overlap_different_files(self):
        concern = make_event(EVENT_TYPE_CONCERN, content="Issue", files=["src/app.ts"])
        commit = make_event(
            EVENT_TYPE_COMMIT, content="fix other", files=["src/other.ts"]
        )
        commit["ts"] = "2099-01-01T00:00:00Z"
        result = triage.find_overlapping_commits(concern, [commit])
        self.assertEqual(len(result), 0)

    def test_same_timestamp_excluded(self):
        """Commit at exact same timestamp as concern is excluded."""
        concern = make_event(EVENT_TYPE_CONCERN, content="Issue", files=["src/app.ts"])
        concern["ts"] = "2026-06-01T00:00:00Z"
        commit = make_event(EVENT_TYPE_COMMIT, content="fix", files=["src/app.ts"])
        commit["ts"] = "2026-06-01T00:00:00Z"
        result = triage.find_overlapping_commits(concern, [commit])
        self.assertEqual(len(result), 0)

    def test_concern_without_files_returns_empty(self):
        concern = make_event(EVENT_TYPE_CONCERN, content="No files")
        commit = make_event(EVENT_TYPE_COMMIT, content="fix", files=["src/app.ts"])
        commit["ts"] = "2099-01-01T00:00:00Z"
        result = triage.find_overlapping_commits(concern, [commit])
        self.assertEqual(len(result), 0)


class TestExtractFileDomainPaths(unittest.TestCase):
    """extract_file_domain_paths splits "path — desc" entries and expands globs.

    Glob expansion uses fnmatch-style matching against an optional
    `candidate_files` iterable (the cascade-analysis case where commit files
    may no longer exist on disk). When no candidates are passed, falls back
    to pathlib.Path(".").glob for current on-disk files.
    """

    def test_literal_path_with_em_dash(self):
        result = triage.extract_file_domain_paths(["scripts/auth.py — add login"])
        self.assertEqual(result, {"scripts/auth.py"})

    def test_literal_path_no_dash(self):
        result = triage.extract_file_domain_paths(["scripts/foo.py"])
        self.assertEqual(result, {"scripts/foo.py"})

    def test_empty_list(self):
        self.assertEqual(triage.extract_file_domain_paths([]), set())

    def test_blank_entry_skipped(self):
        self.assertEqual(triage.extract_file_domain_paths(["   "]), set())

    def test_literal_unaffected_by_candidate_files_kwarg(self):
        """AC2: literal entries pass through unchanged when candidates are given."""
        result = triage.extract_file_domain_paths(
            ["scripts/foo.py — modify foo"],
            candidate_files=["scripts/foo.py", "scripts/bar.py"],
        )
        self.assertEqual(result, {"scripts/foo.py"})

    def test_glob_expanded_against_candidates(self):
        """AC1: 'tests/hooks/**/*.py' expands to matching candidate paths."""
        candidates = [
            "tests/hooks/test_a.py",
            "tests/hooks/test_b.py",
            "tests/hooks/sub/test_c.py",
            "scripts/foo.py",
        ]
        result = triage.extract_file_domain_paths(
            ["tests/hooks/**/*.py — migrated tests"],
            candidate_files=candidates,
        )
        self.assertEqual(
            result,
            {
                "tests/hooks/test_a.py",
                "tests/hooks/test_b.py",
                "tests/hooks/sub/test_c.py",
            },
        )

    def test_glob_drops_non_matching_candidates(self):
        candidates = ["scripts/foo.py", "tests/hooks/test_a.py"]
        result = triage.extract_file_domain_paths(
            ["tests/hooks/*.py"],
            candidate_files=candidates,
        )
        self.assertEqual(result, {"tests/hooks/test_a.py"})

    def test_glob_single_star_does_not_cross_slash(self):
        """A bare '*' segment is one path segment — doesn't match nested dirs."""
        candidates = ["tests/foo.py", "tests/sub/bar.py"]
        result = triage.extract_file_domain_paths(
            ["tests/*.py"], candidate_files=candidates
        )
        self.assertEqual(result, {"tests/foo.py"})

    def test_question_mark_glob(self):
        candidates = ["tests/test_a.py", "tests/test_ab.py", "tests/test_b.py"]
        result = triage.extract_file_domain_paths(
            ["tests/test_?.py"], candidate_files=candidates
        )
        self.assertEqual(result, {"tests/test_a.py", "tests/test_b.py"})

    def test_bracket_class_glob(self):
        candidates = ["test_a.py", "test_b.py", "test_c.py", "test_d.py"]
        result = triage.extract_file_domain_paths(
            ["test_[ab].py"], candidate_files=candidates
        )
        self.assertEqual(result, {"test_a.py", "test_b.py"})

    def test_glob_with_no_candidates_and_no_cwd_raises(self):
        """Glob entry without candidate_files OR cwd raises ValueError.

        Eliminates the prior implicit-cwd foot-gun (concern edf2fc993f52).
        Callers MUST declare a glob root explicitly — either via
        candidate_files (cascade-analysis) or cwd= (disk expansion).
        """
        with self.assertRaises(ValueError) as ctx:
            triage.extract_file_domain_paths(["tests/hooks/*.py"])
        self.assertIn("tests/hooks/*.py", str(ctx.exception))
        self.assertIn("candidate_files=", str(ctx.exception))
        self.assertIn("cwd=", str(ctx.exception))

    def test_glob_recursive_with_cwd_expands_via_disk(self):
        """** glob expands recursively via Path(cwd).glob when cwd is supplied."""
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            (tdp / "tests" / "hooks" / "sub").mkdir(parents=True)
            (tdp / "tests" / "hooks" / "test_a.py").touch()
            (tdp / "tests" / "hooks" / "sub" / "test_b.py").touch()

            result = triage.extract_file_domain_paths(["tests/hooks/**/*.py"], cwd=td)
            self.assertIn("tests/hooks/test_a.py", result)
            self.assertIn("tests/hooks/sub/test_b.py", result)

    def test_glob_no_matching_candidates_yields_nothing(self):
        """When a glob matches no candidates, the entry contributes no paths."""
        result = triage.extract_file_domain_paths(
            ["tests/hooks/**/*.py"],
            candidate_files=["scripts/foo.py"],
        )
        self.assertEqual(result, set())

    def test_mixed_literal_and_glob_entries(self):
        candidates = ["tests/hooks/test_a.py", "scripts/foo.py"]
        result = triage.extract_file_domain_paths(
            [
                "tests/hooks/**/*.py — migrated tests",
                "scripts/explicit.py — direct",
            ],
            candidate_files=candidates,
        )
        self.assertEqual(result, {"tests/hooks/test_a.py", "scripts/explicit.py"})

    # --- cwd kwarg (story-005 / concern edf2fc993f52) ---------------------

    def test_glob_with_cwd_kwarg_uses_provided_dir(self):
        """AC2/AC3: cwd= names the glob root — does NOT consult os.getcwd()."""
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            (tdp / "tests" / "hooks").mkdir(parents=True)
            (tdp / "tests" / "hooks" / "test_a.py").touch()
            (tdp / "tests" / "hooks" / "test_b.py").touch()

            # Stay in a DIFFERENT cwd to prove the kwarg, not the process
            # cwd, drives expansion. If the implementation regresses to
            # `Path(".").glob` the result will be empty under any tmpdir
            # that doesn't itself contain `tests/hooks/*.py`.
            with tempfile.TemporaryDirectory() as other_cwd:
                origin = os.getcwd()
                os.chdir(other_cwd)
                try:
                    result = triage.extract_file_domain_paths(
                        ["tests/hooks/*.py"], cwd=td
                    )
                finally:
                    os.chdir(origin)

            self.assertEqual(
                result,
                {"tests/hooks/test_a.py", "tests/hooks/test_b.py"},
                "cwd= should drive glob expansion, not the process cwd",
            )

    def test_literal_paths_work_without_cwd(self):
        """Literal file_domain paths (no glob) work without cwd or candidates.

        file_domain overlap checks ride this path — sprint stories
        declare literal paths in file_domain and the overlap logic does
        set-overlap on declared strings, no disk lookup needed.
        """
        result = triage.extract_file_domain_paths(
            ["tests/hooks/test_a.py", "scripts/foo.py"]
        )
        self.assertEqual(result, {"tests/hooks/test_a.py", "scripts/foo.py"})

    def test_cwd_ignored_when_candidate_files_provided(self):
        """AC2: candidate_files takes precedence — cwd= is irrelevant.

        Cascade-analysis call-sites (story_metrics._attribute_commits) pass
        candidate_files with historical commit paths that may not exist on
        disk. cwd= must NOT silently switch them to disk-glob.
        """
        candidates = ["tests/hooks/test_a.py"]
        with tempfile.TemporaryDirectory() as td:
            # The tmpdir has no matching files — if cwd= leaked through,
            # the result would be empty. The candidate_files path must win.
            result = triage.extract_file_domain_paths(
                ["tests/hooks/*.py"],
                candidate_files=candidates,
                cwd=td,
            )
        self.assertEqual(result, {"tests/hooks/test_a.py"})


class TestMalformedGlobRobustness(unittest.TestCase):
    """A malformed glob in a file_domain path must never crash a hook.

    A path that is itself an invalid glob — an empty bracket class
    `items[]` is an unterminated character set — produces invalid regex.
    This once crashed the SessionStart retrospective hook (re.PatternError)
    via every caller of extract_file_domain_paths. Such an entry must
    degrade gracefully: it matches nothing real rather than raising.
    """

    # The path portion (`src/items[].py`) is a malformed glob: a bare `[]`
    # is an unterminated character set. Uses the em-dash convention so the
    # bad glob lives in the path, not a leaked description.
    BAD_GLOB_ENTRY = "src/items[].py — empty bracket class is invalid regex"

    def test_compile_glob_does_not_raise_on_unterminated_set(self):
        """_compile_glob returns a usable pattern instead of raising re.error."""
        pattern = triage._compile_glob("items[].py")
        # Falls back to a literal match — the malformed glob matches only
        # its own literal text, never a real file path.
        self.assertIsNone(pattern.fullmatch("items.py"))
        self.assertIsNotNone(pattern.fullmatch("items[].py"))

    def test_candidate_branch_does_not_raise(self):
        """The cascade-analysis (candidate_files) path must not crash."""
        result = triage.extract_file_domain_paths(
            [self.BAD_GLOB_ENTRY],
            candidate_files=["src/items.py", "src/other.py"],
        )
        # Malformed glob matches no real candidate -> contributes nothing.
        self.assertEqual(result, set())

    def test_disk_branch_does_not_raise(self):
        """The disk-glob (cwd=) path must not crash on a malformed entry."""
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "src").mkdir()
            (Path(td) / "src" / "items.py").touch()
            result = triage.extract_file_domain_paths([self.BAD_GLOB_ENTRY], cwd=td)
        self.assertEqual(result, set())

    def test_wellformed_entries_alongside_bad_one_still_resolve(self):
        """A bad entry doesn't poison sibling well-formed entries."""
        result = triage.extract_file_domain_paths(
            [self.BAD_GLOB_ENTRY, "scripts/auth.py — add login"],
            candidate_files=["scripts/auth.py", "src/items.py"],
        )
        self.assertEqual(result, {"scripts/auth.py"})


class TestLenientFileDomainParsing(unittest.TestCase):
    """extract_file_domain_paths tolerates common authoring deviations.

    The documented convention is "path — description" (em-dash), but the
    ASCII ' -- ' deviation is common and several paths may be comma-joined
    in one entry. Both forms resolve to the real declared path(s) rather
    than leaking the description into the glob (which once crashed a hook).
    """

    def test_ascii_double_dash_separator_strips_description(self):
        result = triage.extract_file_domain_paths(
            ["content/items.json -- strip legacy stuff"],
            candidate_files=["content/items.json"],
        )
        self.assertEqual(result, {"content/items.json"})

    def test_crash_entry_now_extracts_the_real_path(self):
        """The exact entry that crashed the hook now yields its real path."""
        entry = (
            "content/items.json -- strip legacy "
            "effects[].damage/ac_bonus copies (34 items)"
        )
        result = triage.extract_file_domain_paths(
            [entry], candidate_files=["content/items.json", "apps/server/x.ts"]
        )
        self.assertEqual(result, {"content/items.json"})

    def test_comma_joined_paths_split(self):
        result = triage.extract_file_domain_paths(
            ["apps/a.ts, apps/b.ts -- route through helper"],
            candidate_files=["apps/a.ts", "apps/b.ts", "apps/c.ts"],
        )
        self.assertEqual(result, {"apps/a.ts", "apps/b.ts"})

    def test_ascii_double_dash_preserves_glob(self):
        """A glob path before an ASCII ' -- ' still expands."""
        result = triage.extract_file_domain_paths(
            ["tests/hooks/*.py -- migrated tests"],
            candidate_files=["tests/hooks/test_a.py", "scripts/foo.py"],
        )
        self.assertEqual(result, {"tests/hooks/test_a.py"})

    def test_em_dash_with_comma_joined_paths(self):
        result = triage.extract_file_domain_paths(
            ["a.py, b.py — shared refactor"],
            candidate_files=["a.py", "b.py", "c.py"],
        )
        self.assertEqual(result, {"a.py", "b.py"})

    def test_comma_in_description_not_treated_as_path(self):
        """A comma inside the description must not spawn phantom paths."""
        result = triage.extract_file_domain_paths(
            ["scripts/auth.py — refactor, simplify, and test"],
            candidate_files=["scripts/auth.py"],
        )
        self.assertEqual(result, {"scripts/auth.py"})

    def test_single_ascii_hyphen_separator_strips_description(self):
        """' - ' is the third authoring deviation, and it used to fail SILENTLY.

        An unrecognized separator does not error — it makes the WHOLE entry the
        path, so the declared file matches nothing and `validate-domain` reports
        drift on a file that is plainly declared. That is worse than a crash: it
        reads as a real finding. Hit twice in one session hand-writing two
        stories' domains (concern dd9ddb62ec3f).
        """
        result = triage.extract_file_domain_paths(
            ["scripts/auth.py - refactor the token path"],
            candidate_files=["scripts/auth.py"],
        )
        self.assertEqual(result, {"scripts/auth.py"})

    def test_single_hyphen_with_comma_joined_paths(self):
        result = triage.extract_file_domain_paths(
            ["a.py, b.py - shared refactor"],
            candidate_files=["a.py", "b.py", "c.py"],
        )
        self.assertEqual(result, {"a.py", "b.py"})

    def test_single_hyphen_preserves_glob(self):
        result = triage.extract_file_domain_paths(
            ["tests/hooks/*.py - migrated tests"],
            candidate_files=["tests/hooks/test_a.py", "scripts/foo.py"],
        )
        self.assertEqual(result, {"tests/hooks/test_a.py"})

    def test_hyphen_inside_a_path_is_not_a_separator(self):
        """The separator is space-hyphen-space. A hyphen in a filename carries
        no surrounding spaces, so hyphenated paths — which are everywhere in
        this repo — must survive untouched."""
        for entry, expected in (
            ("scripts/pre-commit-hook.py", "scripts/pre-commit-hook.py"),
            ("scripts/pre-commit-hook.py - install it", "scripts/pre-commit-hook.py"),
            ("some-dir/some-file.py — desc", "some-dir/some-file.py"),
        ):
            with self.subTest(entry=entry):
                result = triage.extract_file_domain_paths(
                    [entry], candidate_files=[expected]
                )
                self.assertEqual(result, {expected})

    def test_earliest_separator_still_wins_across_all_three_forms(self):
        """Adding a third separator must not let a later one win. A description
        that itself contains ' -- ' or an em dash after a ' - ' would otherwise
        drag prose into the path."""
        result = triage.extract_file_domain_paths(
            ["scripts/auth.py - rework -- see notes — really"],
            candidate_files=["scripts/auth.py"],
        )
        self.assertEqual(result, {"scripts/auth.py"})
        result = triage.extract_file_domain_paths(
            ["scripts/auth.py -- rework - see notes"],
            candidate_files=["scripts/auth.py"],
        )
        self.assertEqual(result, {"scripts/auth.py"})

    def test_a_trailing_hyphen_with_no_description_yields_the_path(self):
        """`path -` (nothing after) must not yield an empty path set."""
        result = triage.extract_file_domain_paths(
            ["scripts/auth.py -"], candidate_files=["scripts/auth.py"]
        )
        self.assertEqual(result, {"scripts/auth.py"})


if __name__ == "__main__":
    unittest.main()

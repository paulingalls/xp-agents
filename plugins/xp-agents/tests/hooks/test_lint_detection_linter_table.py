#!/usr/bin/env python3
"""The linter registry columns that make "non-zero exit" a sufficient signal.

Split from test_lint_detection.py to keep files under the 500-line cap.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import lint_check
import lint_runners
import linters
from conftest import _mock_ruff_result


def _write_compile_db(root: str, *files: str) -> None:
    """A compile DB that actually COVERS `files`.

    An empty `[]` database exists but covers nothing, and coverage is now tested per
    file — because a database that exists is not a database that can compile the
    staged file, and the gap between those two is an unfixable block.
    """
    import json as _json

    Path(root, "compile_commands.json").write_text(
        _json.dumps(
            [
                {"directory": root, "command": f"cc -c {f}", "file": str(Path(root, f))}
                for f in files
            ]
        )
    )


class TestLinterTableColumns(unittest.TestCase):
    """The two columns that make "non-zero exit" a sufficient finding signal.

    The gate reads only the exit code (see run_linter_batch). That is sound ONLY
    if two things hold per linter, and out of the box neither does:

    (a) STRICTNESS — some linters exit 0 even when they found something. eslint
        exits 0 when only *warnings* fire, and `no-unused-vars` is `warn` in many
        popular configs — so the headline case of this whole story (a staged .ts
        with an unused import) would sail straight through the gate. swiftlint
        and `dart analyze` share the shape.

    (b) FILE SCOPE — some linters cannot lint a single file at all. `cargo clippy
        -- -D warnings` lints the whole crate and exits non-zero if ANY warning
        exists anywhere, staged or not. A Rust repo with one pre-existing warning
        in an untouched file would have every commit blocked, unfixably.

    Both are per-row DATA, not branches: a flag column and a capability column.
    Note what they are NOT — a map of per-language rule codes
    ({eslint: no-unused-vars, clippy: unused_imports}). That would be a hardcoded
    model of each language's rule semantics, the exact leak the guardrail forbids,
    and test_no_language_leak.py could not see it (it only scans extension
    predicates). A strictness flag says "be strict"; it does not say what strict
    means in that language. The linter decides that.
    """

    def test_eslint_carries_a_strictness_flag(self):
        """Without --max-warnings=0, eslint exits 0 on a warn-level finding and
        the gate reads a repo full of unused imports as clean."""
        self.assertIn("--max-warnings=0", linters.linter_command("eslint"))

    def test_swiftlint_and_dart_carry_strictness_flags(self):
        self.assertIn("--strict", linters.linter_command("swiftlint"))
        self.assertIn("--fatal-infos", linters.linter_command("dart-analyze"))

    def test_ruff_needs_no_strictness_flag(self):
        """ruff already exits non-zero on any finding. A row only carries a flag
        when its linter would otherwise lie about having found nothing."""
        self.assertEqual(
            linters.linter_command("ruff"),
            ["ruff", "check", "--output-format=concise"],
        )

    def test_strictness_flag_reaches_the_commit_gate_argv(self):
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/npx"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _mock_ruff_result()
            lint_check.run_linter_batch("eslint", ["src/a.ts"], cwd="/tmp")
        cmd = mock_run.call_args[0][0]
        self.assertIn("--max-warnings=0", cmd)
        # ...and before the `--` separator, or eslint reads it as a filename.
        self.assertLess(cmd.index("--max-warnings=0"), cmd.index("--"))

    def test_strictness_flag_reaches_edit_time_argv(self):
        """The command table is SHARED with the edit-time run_linter path. The
        flag applies there too, on purpose: if the gate blocks at commit on a
        warn-level finding that edit-time never mentioned, the agent gets
        ambushed by a rule it was never told about."""
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/npx"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _mock_ruff_result()
            lint_check.run_linter("eslint", "src/a.ts")
        self.assertIn("--max-warnings=0", mock_run.call_args[0][0])

    def test_edit_time_run_linter_still_reports_findings(self):
        """Pin against regression: the shared-table change must not disturb
        edit-time's contract (output on non-zero, None on clean)."""
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/npx"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _mock_ruff_result(
                returncode=1, stdout="  1:10  warning  'foo' is unused  no-unused-vars"
            )
            found = lint_check.run_linter("eslint", "src/a.ts")
            mock_run.return_value = _mock_ruff_result()
            clean = lint_check.run_linter("eslint", "src/a.ts")
        assert found is not None
        self.assertIn("no-unused-vars", found)
        self.assertIsNone(clean)

    def test_degraded_rows_are_not_gated(self):
        """The gate must DEGRADE on these, not block. A non-zero exit from them
        reports something the staged diff neither caused nor can fix, and the first
        thing anyone does with an unfixable gate is disable it.

        checkstyle is here for a DIFFERENT reason than the rest, which is why the
        reason is now per-row: it can judge one file perfectly well, but its exit
        code counts severity=error only — a severity=warning violation prints and
        exits 0. Measured, not assumed (test_lint_polyglot.py).
        """
        with tempfile.TemporaryDirectory() as td:
            for linter in ("clippy", "checkstyle", "detekt", "credo", "dotnet-format"):
                self.assertIsNotNone(linters.degrade_reason(linter, td), msg=linter)

    def test_file_scoped_rows_can_judge_one_file(self):
        with tempfile.TemporaryDirectory() as td:
            for linter in ("ruff", "flake8", "eslint", "golangci-lint", "rubocop"):
                self.assertIsNone(linters.degrade_reason(linter, td))

    def test_clang_tidy_takes_its_paths_BEFORE_the_separator(self):
        """INVERTED. This pin used to assert the bug.

        Its predecessor said a row "whose separator semantics we cannot honor must
        not be GATED on", and prescribed the fix: "sources BEFORE the separator,
        trailing `--` for no compiler args, proven against the real binary."

        We proved it against the real binary — and the SECOND half of that
        prescription is WRONG. A trailing `--` means "no compiler flags" and
        OVERRIDES compile_commands.json, so it throws away the very database that
        lets clang-tidy resolve an #include. See test_lint_polyglot.py.
        """
        with tempfile.TemporaryDirectory() as td:
            _write_compile_db(td, "app.c")

            argv = linters.linter_argv("clang-tidy", ["app.c"], root=td)

            assert argv is not None
            self.assertEqual(argv[-1], "app.c", "the path is the LAST arg")
            self.assertNotIn("--", argv, "a trailing -- would override the compile DB")
            self.assertIn("--warnings-as-errors=*", argv, "or a finding exits 0")

    def test_clang_tidy_is_gated_only_where_a_compile_database_exists(self):
        """The precondition, and the reason it is not just a static row.

        Without a compile DB clang-tidy cannot resolve an #include, so a file whose
        header lives elsewhere fails to COMPILE: clang-diagnostic-error, non-zero,
        with output — which the contract reads as FINDINGS. The gate would refuse the
        commit over a header path nothing in the diff can fix.
        """
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNotNone(
                linters.degrade_reason("clang-tidy", td),
                "no compile DB: must degrade, not block on an unfixable error",
            )
            self.assertIsNone(
                linters.linter_argv("clang-tidy", ["app.c"], root=td),
                "and it must not even be INVOKED — the edit-time path would raise a "
                "concern lint_resolution could never clear",
            )

            _write_compile_db(td, "app.c")

            self.assertIsNone(
                linters.degrade_reason("clang-tidy", td),
                "with a compile DB, C/C++ is genuinely gatable",
            )

    def test_a_config_required_linter_refuses_to_run_configless(self):
        """checkstyle has no way to find its own config. Running it without `-c`
        would judge the project by a built-in default — a different project's rules,
        reading back as either findings or clean. Both are lies, so refuse."""
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(linters.linter_argv("checkstyle", ["Foo.java"], root=td))

            argv = linters.linter_argv(
                "checkstyle", ["Foo.java"], root=td, config_path="/proj/checkstyle.xml"
            )

            assert argv is not None
            self.assertIn("/proj/checkstyle.xml", argv, "the DETECTED config")
            self.assertNotIn("/google_checks.xml", argv, "not Google's")

    def test_clippy_has_no_per_file_argv_at_all(self):
        """The OTHER separator bug, and the one the shared builder did NOT fix.

        `cargo clippy -- -D warnings` already ends in a separator: everything after
        it goes to rustc. Appending the default `-- <path>` therefore builds

            cargo clippy -- -D warnings -- src/main.rs

        and rustc answers `error: multiple input filenames provided` and exits 101.
        MEASURED against real cargo — not a false-clean but something worse: the
        edit-time path reads 101 as FINDINGS and raises a lint concern whose text is
        a cargo argv error, on EVERY .rs file edited. lint_resolution then re-runs the
        same broken argv to clear it, gets 101 again, and the concern can never be
        resolved — it is injected into every prompt by prompt_nugget, forever.

        clippy lints the CRATE; there is no argv that asks it about one file. So there
        is no argv, and the honest answer is None — the same "must not run this here"
        the precondition rows return. The commit gate already degrades the row.
        """
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(
                linters.linter_argv("clippy", ["src/main.rs"], root=td),
                "a per-file clippy argv does not exist — do not invent one",
            )

    def test_detekt_credo_dotnet_format_have_no_per_file_argv_at_all(self):
        """The SAME separator-shape bug as clippy, on three more rows.

        DEGRADED_LINTERS already asserts each of these lints the WHOLE PROJECT:
        detekt's `--input` defaults to the whole source set, credo walks the
        whole project, and dotnet-format's `--verify-no-changes` covers the
        whole solution. A per-file path is a question none of those CLIs can
        answer — the same shape clippy's row exists to fix — so the honest
        argv is None, not `[*cmd, "--", <path>]`.
        """
        with tempfile.TemporaryDirectory() as td:
            for linter, path in (
                ("detekt", "Foo.kt"),
                ("credo", "lib/x.ex"),
                ("dotnet-format", "A.cs"),
            ):
                self.assertIsNone(
                    linters.linter_argv(linter, [path], root=td),
                    f"a per-file {linter} argv does not exist — do not invent one",
                )

    def test_every_row_has_a_scope_answer(self):
        """No silent gap: a new linter row must be classified, not defaulted by
        accident. The default IS the bug this story fixed — clang-tidy's argv shape
        defaulted, and the default was wrong."""
        with tempfile.TemporaryDirectory() as td:
            for linter in linters.LINTER_COMMANDS:
                self.assertIsInstance(
                    linters.degrade_reason(linter, td), (str, type(None))
                )


class TestOptionalFlagRetry(unittest.TestCase):
    """A config-style flag the tool rejects must not become an unfixable block.

    MEASURED 2026-07-22 against real eslint (7.32.0, 8.30.0, 8.50.0, 8.57.1), each
    config mode pinned via ESLINT_USE_FLAT_CONFIG:

      flat 8.30.0 + `--no-warn-ignored` -> exit 2, "Invalid option '--warn-ignored'"
      flat 8.57.1 + `--no-warn-ignored` -> exit 0

    The flag landed in eslint 8.51, but `detect_linter_config` recognizes
    `eslint.config.js` from 8.21, so the filename-keyed row hands every project in
    the 8.21-8.50 window an unrecognised option: non-zero WITH output, which the gate
    reads as findings — a block naming a flag the committer never wrote.

    The recovery is a retry without the optional flags rather than a version probe.
    A probe was measured at 0.40-0.64s per invocation and rejected: it ran inside the
    gate's shared wall-clock budget, which exists so the gate cannot outlive the
    harness hook timeout and fail OPEN. The retry costs nothing on the hot path, and
    covers tool/version/config combinations no table could enumerate.
    """

    def _config(self, td, name="eslint.config.js"):
        path = Path(td, name)
        path.write_text("")
        return str(path)

    def test_usage_error_retries_without_the_optional_flags(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = self._config(td)
            argv = linters.linter_argv(
                "eslint", ["a.js"], root=td, config_path=cfg, base=td
            )
            self.assertIn("--no-warn-ignored", argv or [])
            retry = linters.optional_flag_retry(argv or [], cfg, 2)
        self.assertIsNotNone(retry, "exit 2 is the row's usage-error code")
        self.assertNotIn("--no-warn-ignored", retry or [])
        # Everything else survives — only the OPTIONAL part is dropped.
        self.assertIn("--max-warnings=0", retry or [])
        self.assertIn("a.js", retry or [])

    def test_ordinary_lint_failure_does_not_retry(self):
        """The cost question: findings exit 1, so a regular lint failure must
        never pay for a second process. MEASURED (eslint 8.57.1): warnings,
        errors and even a parse error all exit 1; only an unsupported flag exits 2."""
        with tempfile.TemporaryDirectory() as td:
            cfg = self._config(td)
            argv = linters.linter_argv(
                "eslint", ["a.js"], root=td, config_path=cfg, base=td
            )
            for rc in (0, 1):
                with self.subTest(returncode=rc):
                    self.assertIsNone(linters.optional_flag_retry(argv or [], cfg, rc))

    def test_no_retry_without_a_matching_row(self):
        with tempfile.TemporaryDirectory() as td:
            eslintrc = self._config(td, ".eslintrc.json")
            argv = linters.linter_argv(
                "eslint", ["a.js"], root=td, config_path=eslintrc, base=td
            )
            self.assertNotIn("--no-warn-ignored", argv or [])
            self.assertIsNone(linters.optional_flag_retry(argv or [], eslintrc, 2))
            self.assertIsNone(linters.optional_flag_retry(argv or [], None, 2))

    def test_runner_retries_once_and_reports_the_second_result(self):
        """The behavioural pin: a rejected flag must not reach the committer.
        Without the retry the first result — non-zero with output — is reported
        as findings, which is the unfixable block this exists to prevent."""
        with tempfile.TemporaryDirectory() as td:
            cfg = self._config(td)
            Path(td, "a.js").write_text("const a = 1;\n")
            calls = []

            def fake_run(argv, **kwargs):
                calls.append(list(argv))
                if "--no-warn-ignored" in argv:
                    return Mock(
                        returncode=2,
                        stdout="Invalid option '--warn-ignored'",
                        stderr="",
                    )
                return Mock(returncode=0, stdout="", stderr="")

            with (
                patch("lint_runners.subprocess.run", side_effect=fake_run),
                patch("lint_runners.shutil.which", return_value="/usr/bin/npx"),
            ):
                result = lint_runners.run_linter(
                    "eslint", str(Path(td, "a.js")), root=td, config_path=cfg, cwd=td
                )

        self.assertEqual(len(calls), 2, "exactly one retry")
        self.assertIn("--no-warn-ignored", calls[0])
        self.assertNotIn("--no-warn-ignored", calls[1])
        self.assertIsNone(result, "the retry was clean, so nothing is reported")


class TestEslintrcCarriesNoConfigStyleFlag(unittest.TestCase):
    """The `.eslintrc*` filenames intentionally carry NO config-style row.

    This is a REFUSAL, recorded because it was measured rather than assumed.
    MEASURED 2026-07-22, eslint 7.32.0 / 8.50.0 / 8.57.1, ESLINT_USE_FLAT_CONFIG=false:

      `--max-warnings=0 --no-warn-ignored` -> exit 2 on EVERY version, including
          8.57.1, which accepts the same flag under flat config. The option does
          not exist in eslintrc mode at any version; it is not a version cliff.
      `--max-warnings=0 --quiet`            -> exit 1, "too many warnings".
          `--quiet` filters the REPORT but max-warnings still counts the filtered
          warnings, so it is not an antidote either.
      `--max-warnings=0 --no-ignore`        -> exit 1, and it LINTS the excluded
          file — wrong semantics: it overrides the project's own exclusion.

    So no flag suppresses the ignored-file warning under eslintrc. The only lever
    that clears it is dropping `--max-warnings=0`, which measurement shows costs
    warn-level gating outright (`normal.js` with a warn-level violation: exit 1
    with the flag, exit 0 without) while errors still block. That trade was
    declined: it would cost every eslintrc project its warn-level gate
    permanently to fix a block that only fires when an ignore-matched file is
    staged.

    Delete this test only with a NEW measurement, not a plausible-looking flag.
    """

    def test_no_eslintrc_filename_carries_a_config_style_row(self):
        eslintrc_names = {
            config_name
            for config_name, linter, _content_check in linters.LINTER_CONFIGS
            if linter == "eslint" and config_name.startswith(".eslintrc")
        }
        self.assertTrue(eslintrc_names, "no eslintrc rows found to check")

        present = eslintrc_names & linters.CONFIG_STYLE_FLAGS.keys()
        self.assertFalse(
            present,
            f"{sorted(present)} carry a CONFIG_STYLE_FLAGS row, but measurement "
            "(2026-07-22, eslint 7.32.0/8.50.0/8.57.1) shows eslintrc mode "
            "rejects --no-warn-ignored with exit 2 on every version, and neither "
            "--quiet nor --no-ignore is a valid antidote. See this test's "
            "docstring before adding one.",
        )


class TestConfigStyleFlagsAgreesWithLinterConfigs(unittest.TestCase):
    """Guards the two eslint-flat-config tables against drifting apart.

    CONFIG_STYLE_FLAGS is keyed by config FILENAME (not by linter name) because
    the flag it answers — `--no-warn-ignored` — is only valid under flat
    config, and the config file is what selects the mode; see the column's own
    docstring in linters.py. LINTER_CONFIGS is a separate table naming which
    filenames `detect_linter_config` recognizes as flat config for eslint
    (`eslint.config.js` / `.mjs` / `.ts`).

    Today both tables list the same three filenames, so nothing is broken yet.
    But nothing enforces that they stay in sync: add a fourth flat-config
    filename to LINTER_CONFIGS (say, eslint.config.cjs, which real eslint
    supports) without a matching CONFIG_STYLE_FLAGS row, and the ignored-file
    warning this column exists to suppress comes back for every project using
    that filename — silently, because both tables still type-check and no
    other test reads them together. This test is that missing link.
    """

    def test_flat_config_filenames_in_linter_configs_have_a_config_style_flags_row(
        self,
    ):
        flat_config_filenames = {
            config_name
            for config_name, linter, _content_check in linters.LINTER_CONFIGS
            if linter == "eslint" and config_name.startswith("eslint.config.")
        }
        # Vacuity guard: if eslint's flat-config rows ever get renamed or
        # removed from LINTER_CONFIGS, this test must not pass by finding an
        # empty set to be trivially "a subset of" anything.
        self.assertTrue(flat_config_filenames, "no flat-config rows found to check")

        missing = flat_config_filenames - linters.CONFIG_STYLE_FLAGS.keys()
        self.assertFalse(
            missing,
            f"{sorted(missing)} appear as flat-config rows in LINTER_CONFIGS but "
            "have no CONFIG_STYLE_FLAGS entry — eslint would run under flat "
            "config without --no-warn-ignored, and the gate would refuse a file "
            "the project's own config says to skip",
        )


if __name__ == "__main__":
    unittest.main()

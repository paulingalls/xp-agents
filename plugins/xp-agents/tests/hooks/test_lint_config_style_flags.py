#!/usr/bin/env python3
"""The config-style flag column: an option valid only under ONE config mode.

Split from test_lint_detection_linter_table.py, which was approaching the
500-line cap — these classes are one feature (the CONFIG_STYLE_FLAGS column and
the retry that recovers when a tool rejects one of its flags), not one more
registry column, so they get their own file rather than a bigger one.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import lint_budget
import lint_runners
import linters


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

    def test_the_stdin_path_retries_in_binary_mode_and_resends_the_blob(self):
        """The divergent-index path is the one that runs in BINARY mode, and the
        retry has to survive that: the second process gets the staged bytes again
        (it is a fresh pipe — a retry that forgot them would lint an empty file
        and report it clean) and its output is decoded, not read as str."""
        with tempfile.TemporaryDirectory() as td:
            cfg = self._config(td)
            calls = []

            def fake_run(argv, **kwargs):
                calls.append((list(argv), kwargs.get("input")))
                if "--no-warn-ignored" in argv:
                    return Mock(
                        returncode=2,
                        stdout=b"Invalid option '--warn-ignored'",
                        stderr=b"",
                    )
                return Mock(returncode=1, stdout=b"app.ts:1:1 \xff oops\n", stderr=b"")

            with (
                patch("lint_runners.subprocess.run", side_effect=fake_run),
                patch("lint_runners.shutil.which", return_value="/usr/bin/npx"),
            ):
                run = lint_runners.run_linter_stdin(
                    "eslint",
                    "app.ts",
                    b"const a = 1;\n",
                    cwd=td,
                    root=td,
                    config_path=cfg,
                )

        self.assertEqual(len(calls), 2, "exactly one retry")
        self.assertNotIn("--no-warn-ignored", calls[1][0])
        self.assertEqual(
            calls[1][1], b"const a = 1;\n", "the retry re-sends the staged bytes"
        )
        self.assertEqual(run.status, "findings", "the SECOND run is what is reported")
        self.assertIn("oops", run.output, "and its bytes decode leniently")
        self.assertNotIn("Invalid option", run.output)


class TestBatchTimeoutCutShortVsHang(unittest.TestCase):
    """story-009: a spent shared lint budget must not read as a hung linter.

    The fake raises TimeoutExpired with the timeout it was ACTUALLY handed
    (`kwargs["timeout"]`), not an invented number — otherwise the test would
    only prove the except-branch is reachable, not that the printed numbers
    are the ones production computed.
    """

    @staticmethod
    def _fake_immediate_timeout(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    def test_budget_well_below_ceiling_reads_as_cut_short_not_hang(self):
        with (
            patch("lint_runners.shutil.which", return_value="/usr/bin/ruff"),
            patch(
                "lint_runners.subprocess.run",
                side_effect=self._fake_immediate_timeout,
            ),
        ):
            result = lint_runners.run_linter_batch("ruff", ["a.py"], budget_s=5.0)

        self.assertEqual(result.status, "unverified")
        # "ran 5s", not a bare "5s" — "30.25s" contains "5s", so the loose form
        # would pass off the ceiling alone and pin nothing about the slice.
        self.assertIn("ran 5s", result.output, "the slice it actually got")
        self.assertIn("its own 30.25s ceiling", result.output, "own ceiling, N=1")
        self.assertIn(
            "may have been cut short rather than hung",
            result.output,
        )
        self.assertNotIn("timed out after", result.output, "not the hang wording")
        self.assertNotIn("earlier linters", result.output, "asserts nothing about WHO")


class TestBatchTimeoutMarginIsNotABareLessThan(unittest.TestCase):
    """N >= 40 saturates own_ceiling to the CAP, so on a real first batch
    `budget_s` is necessarily a hair under it — staged_lint sets its deadline
    BEFORE the git read in `_divergent_from_index` and grouping, and that
    alone must not misread as cut short.

    Both fixtures are derived from `_MATERIALLY_SHORT_S` itself, not a
    hand-picked number, so this pair fails if the margin is ever weakened to
    a bare `<`: at half the margin it must still read as a hang (a bare `<`
    would already call this cut short, since budget_s < ceiling); at five
    times the margin it must read as cut short.
    """

    _N = 40

    def _fixture_ceiling(self):
        ceiling = min(
            lint_runners.BATCH_TIMEOUT_CAP_S,
            lint_runners.BATCH_TIMEOUT_BASE_S
            + lint_runners.BATCH_TIMEOUT_PER_PATH_S * self._N,
        )
        self.assertEqual(
            ceiling,
            lint_runners.BATCH_TIMEOUT_CAP_S,
            f"N={self._N} must saturate the cap for this test to prove anything",
        )
        return ceiling

    @staticmethod
    def _fake_immediate_timeout(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    def _run(self, budget_s):
        paths = [f"f{i}.py" for i in range(self._N)]
        with (
            patch("lint_runners.shutil.which", return_value="/usr/bin/ruff"),
            patch(
                "lint_runners.subprocess.run",
                side_effect=self._fake_immediate_timeout,
            ),
        ):
            return lint_runners.run_linter_batch("ruff", paths, budget_s=budget_s)

    def test_just_inside_the_margin_still_reads_as_a_hang(self):
        budget_s = self._fixture_ceiling() - lint_budget._MATERIALLY_SHORT_S / 2
        result = self._run(budget_s)
        self.assertEqual(result.status, "unverified")
        self.assertIn("timed out after", result.output)
        self.assertNotIn("cut short", result.output)
        self.assertNotIn("earlier linters", result.output)

    def test_well_outside_the_margin_reads_as_cut_short(self):
        budget_s = self._fixture_ceiling() - lint_budget._MATERIALLY_SHORT_S * 5
        result = self._run(budget_s)
        self.assertEqual(result.status, "unverified")
        self.assertIn("may have been cut short rather than hung", result.output)
        self.assertNotIn("timed out after", result.output)


class TestStdinTimeoutCutShortIncludesRemedy(unittest.TestCase):
    """The stdin path's cut-short message keeps its actionable `git add`
    remedy — run_linter_stdin costs a process of its own only because the
    staged bytes diverge from the working tree, and that is fixable, unlike
    a generic budget message naming nothing the committer can act on.
    """

    @staticmethod
    def _fake_immediate_timeout(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    def test_cut_short_stdin_run_names_the_git_add_remedy(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td, "eslint.config.js")
            cfg.write_text("")
            with (
                patch("lint_runners.shutil.which", return_value="/usr/bin/npx"),
                patch(
                    "lint_runners.subprocess.run",
                    side_effect=self._fake_immediate_timeout,
                ),
            ):
                result = lint_runners.run_linter_stdin(
                    "eslint",
                    "app.ts",
                    b"const a = 1;\n",
                    cwd=td,
                    root=td,
                    config_path=str(cfg),
                    budget_s=5.0,
                )
        self.assertEqual(result.status, "unverified")
        self.assertIn("ran 5s", result.output, "the slice it actually got")
        self.assertIn("its own 30.25s ceiling", result.output, "its own ceiling")
        self.assertIn("may have been cut short rather than hung", result.output)
        self.assertIn("git add app.ts", result.output)


class TestBatchRetryTimeoutNamesSecondAttempt(unittest.TestCase):
    """A rejected flag's retry can itself genuinely hang. It must still read
    as a hang — not cut short — and the verdict must be driven by what the two
    attempts consumed TOGETHER, since they share one slice: the retry is handed
    exactly what the first attempt left, so their total is the nominal timeout.

    Reporting the retry's remainder alone inverts the verdict on the very path
    this class covers — a first attempt that burned most of the slice leaves a
    small remainder that reads as "cut short" though the run spent its whole
    ceiling.
    """

    def test_retry_that_hangs_reads_as_hang_with_its_own_slice(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td, "eslint.config.js")
            cfg.write_text("")
            js_path = Path(td, "a.js")
            js_path.write_text("const a = 1;\n")

            def fake_run(argv, **kwargs):
                if "--no-warn-ignored" in argv:
                    return Mock(returncode=2, stdout="Invalid option", stderr="")
                raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

            with (
                patch("lint_runners.shutil.which", return_value="/usr/bin/npx"),
                patch("lint_runners.subprocess.run", side_effect=fake_run),
            ):
                result = lint_runners.run_linter_batch(
                    "eslint",
                    [str(js_path)],
                    root=td,
                    config_path=str(cfg),
                    cwd=td,
                )

        self.assertEqual(result.status, "unverified")
        self.assertIn("timed out after", result.output, "genuine hang, not cut short")
        self.assertNotIn("cut short", result.output)
        self.assertIn("second attempt", result.output)
        self.assertIn("rejected for an unsupported flag", result.output)
        self.assertNotIn(
            "30.25s of the 30.25s",
            result.output,
            "a tail that reconciles a number against itself is noise",
        )

    def test_slow_first_attempt_then_hang_still_reads_as_a_hang(self):
        """The inverted-verdict case: `npx eslint` cold-starts ~20s and exits 2
        on an unsupported flag, so the retry gets only the 10.25s left — and
        hangs in it. The run consumed its entire 30.25s ceiling, so it must NOT
        read as cut short, and the number printed must be the total the two
        attempts spent, not the remainder the second one was handed.
        """
        message = lint_budget.timeout_message(
            "eslint",
            subprocess.TimeoutExpired(["npx"], 10.25),
            timeout=30.25,
            own_ceiling=30.25,
            budget_s=None,
        )
        self.assertIn("second attempt", message)
        self.assertIn("timed out after 30.25s", message)
        self.assertNotIn("cut short", message)

    def test_retry_under_a_squeezed_budget_still_reads_as_cut_short(self):
        """The other direction: when the SHARED budget narrowed the slice, the
        two attempts together still only got that narrowed slice, so the verdict
        stays "cut short" — the total is what decides, not the retry alone.
        """
        message = lint_budget.timeout_message(
            "eslint",
            subprocess.TimeoutExpired(["npx"], 2.0),
            timeout=5.0,
            own_ceiling=30.25,
            budget_s=5.0,
            remedy="git add app.ts",
        )
        self.assertIn("second attempt", message)
        self.assertIn("ran 5s against its own 30.25s ceiling", message)
        self.assertIn("may have been cut short rather than hung", message)
        self.assertIn("git add app.ts", message)

    def test_message_never_reconciles_a_number_against_itself(self):
        """A tail quoting two near-identical durations ("30.2481s of the 30.25s")
        reconciles nothing and reads as a contradiction. The message reports ONE
        duration — the total — so there is no pair to contradict.
        """
        message = lint_budget.timeout_message(
            "eslint",
            subprocess.TimeoutExpired(["npx"], 30.2481),
            timeout=30.25,
            own_ceiling=30.25,
            budget_s=None,
        )
        self.assertNotIn("this run was granted", message)
        self.assertNotIn("30.2481", message)


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

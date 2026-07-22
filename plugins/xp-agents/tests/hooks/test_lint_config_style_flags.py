#!/usr/bin/env python3
"""The config-style flag column: an option valid only under ONE config mode.

Split from test_lint_detection_linter_table.py, which was approaching the
500-line cap — these classes are one feature (the CONFIG_STYLE_FLAGS column and
the retry that recovers when a tool rejects one of its flags), not one more
registry column, so they get their own file rather than a bigger one.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

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

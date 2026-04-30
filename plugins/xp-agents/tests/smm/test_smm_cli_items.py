#!/usr/bin/env python3
"""Tests for smm_cli item-CRUD subcommands: add-item / update-item / remove-item.

Split from test_smm_cli.py to keep both files under the 500-line target.
The render / extract-pillar / save / complete-curation / promote-event
tests stay in the parent file; this module owns the item lifecycle group.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import smm_cli
from conftest import _HookTestCase


def _make_cli_args(smm_dir, command="add-item", **kwargs):
    """Build a namespace mimicking argparse output."""
    import argparse

    ns = argparse.Namespace(smm_dir=smm_dir, command=command)
    for k, v in kwargs.items():
        setattr(ns, k, v)
    return ns


# ---------------------------------------------------------------------------
# add-item CLI
# ---------------------------------------------------------------------------


class TestAddItemCommand(_HookTestCase):
    def test_creates_entry(self):
        import io
        from unittest.mock import patch

        with patch("sys.stdin", io.StringIO("TDD always")):
            result = smm_cli._cmd_add_item(
                _make_cli_args(
                    self.smm_dir,
                    pillar="wisdom",
                    type=None,
                    topic=None,
                    severity=None,
                    source="curated",
                    source_event_id=None,
                )
            )
        self.assertEqual(result, 0)
        import smm_store

        smm = smm_store.load_smm(self.smm_dir)
        self.assertEqual(len(smm["wisdom"]), 1)
        self.assertEqual(smm["wisdom"][0]["content"], "TDD always")

    def test_prints_id(self):
        import io
        from unittest.mock import patch

        with (
            patch("sys.stdin", io.StringIO("TDD always")),
            patch("sys.stdout", new_callable=io.StringIO) as mock_out,
        ):
            smm_cli._cmd_add_item(
                _make_cli_args(
                    self.smm_dir,
                    pillar="wisdom",
                    type=None,
                    topic=None,
                    severity=None,
                    source="curated",
                    source_event_id=None,
                )
            )
        output = mock_out.getvalue().strip()
        self.assertRegex(output, r"^[0-9a-f]{12}$")

    def test_error_on_invalid_type(self):
        import io
        from unittest.mock import patch

        with (
            patch("sys.stdin", io.StringIO("Bad")),
            patch("sys.stderr", new_callable=io.StringIO),
        ):
            result = smm_cli._cmd_add_item(
                _make_cli_args(
                    self.smm_dir,
                    pillar="intent",
                    type="concern",
                    topic=None,
                    severity=None,
                    source="curated",
                    source_event_id=None,
                )
            )
        self.assertEqual(result, 1)


# ---------------------------------------------------------------------------
# update-item CLI
# ---------------------------------------------------------------------------


class TestUpdateItemCommand(_HookTestCase):
    def setUp(self):
        super().setUp()
        import smm_store

        self.uid = smm_store.add_item(
            self.smm_dir,
            "constraints",
            "Use REST",
            type="decision",
            topic="api-style",
        )

    def test_changes_content(self):
        import io
        from unittest.mock import patch

        with patch("sys.stdin", io.StringIO("Use GraphQL")):
            result = smm_cli._cmd_update_item(
                _make_cli_args(
                    self.smm_dir,
                    command="update-item",
                    item_id=self.uid,
                    type=None,
                    topic=None,
                    severity=None,
                )
            )
        self.assertEqual(result, 0)
        import smm_store

        smm = smm_store.load_smm(self.smm_dir)
        self.assertEqual(smm["constraints"][0]["content"], "Use GraphQL")

    def test_error_on_missing_id(self):
        import io
        from unittest.mock import patch

        with (
            patch("sys.stdin", io.StringIO("")),
            patch("sys.stderr", new_callable=io.StringIO),
        ):
            result = smm_cli._cmd_update_item(
                _make_cli_args(
                    self.smm_dir,
                    command="update-item",
                    item_id="00000000-0000-4000-8000-000000000000",
                    type=None,
                    topic=None,
                    severity=None,
                )
            )
        self.assertEqual(result, 1)


# ---------------------------------------------------------------------------
# remove-item CLI
# ---------------------------------------------------------------------------


class TestRemoveItemCommand(_HookTestCase):
    def test_removes_entry(self):
        import smm_store

        uid = smm_store.add_item(self.smm_dir, "wisdom", "TDD always")
        result = smm_cli._cmd_remove_item(
            _make_cli_args(
                self.smm_dir,
                command="remove-item",
                item_id=uid,
            )
        )
        self.assertEqual(result, 0)
        smm = smm_store.load_smm(self.smm_dir)
        self.assertEqual(len(smm["wisdom"]), 0)

    def test_error_on_missing_id(self):
        import io
        from unittest.mock import patch

        with patch("sys.stderr", new_callable=io.StringIO):
            result = smm_cli._cmd_remove_item(
                _make_cli_args(
                    self.smm_dir,
                    command="remove-item",
                    item_id="00000000-0000-4000-8000-000000000000",
                )
            )
        self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()

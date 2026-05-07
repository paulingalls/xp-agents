#!/usr/bin/env python3
"""Shared worktree-test fixtures.

`_NormalizePathIdentityMixin` stubs `worktree.normalize_path` to identity
in setUp — for tests where canonical path form is incidental and only
set equality on raw paths matters. Tests that assert against the
canonical-form contract itself (e.g. TestFileOverlapNormalization) must
keep their inline patches.

Promoted from an inline copy in `tests/hooks/test_retro_metrics.py` plus
hand-rolled patcher.start()/addCleanup pairs across multiple test files.
The retro flagged 8+ pre-existing copies of the identity stub; this
module is the canonical home for the setUp-mixin variant.

Pinned by `tests/integration/test_conftest_consolidation_pin.py
::test_single_normalize_path_identity_mixin_definition`.
"""

from unittest.mock import patch

from _test_typing import _MixinBase


class _NormalizePathIdentityMixin(_MixinBase):
    """Stub `worktree.normalize_path` to identity in setUp."""

    def setUp(self):
        super().setUp()
        patcher = patch("worktree.normalize_path", side_effect=lambda p, _cwd: p)
        patcher.start()
        self.addCleanup(patcher.stop)


__all__ = ["_NormalizePathIdentityMixin"]

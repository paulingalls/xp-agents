#!/usr/bin/env python3
"""Static-only `_MixinBase` for pyright-friendly mixin classes.

A mixin that wants to call `self.assertEqual` / `self.assertIn` / other
TestCase machinery has a typing problem: pyright can't see those names
unless the base advertises them, but inheriting `unittest.TestCase`
makes pytest collect the mixin's test methods in isolation (with no
real fixtures wired up — every test errors).

The pattern: at TYPE_CHECKING `_MixinBase = unittest.TestCase` so pyright
type-checks `self.assert*` against TestCase; at runtime `_MixinBase = object`
so pytest sees a plain mixin and only collects the concrete subclass that
inherits both this mixin and `_HookTestCase` / `_IntegrationTestCase` /
`unittest.TestCase`.

Single source of truth — promoted from 3 inline copies (`_close_fixtures.py`,
`integration/test_preload_markers.py`, `hooks/test_auto_resolve.py`) so a
future fourth mixin doesn't paste a fourth copy. Pinned by
`tests/integration/test_conftest_consolidation_pin.py
::test_single_mixin_base_definition`.
"""

import unittest
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    _MixinBase = unittest.TestCase
else:
    _MixinBase = object

__all__ = ["_MixinBase"]

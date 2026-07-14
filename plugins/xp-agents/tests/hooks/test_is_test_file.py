#!/usr/bin/env python3
"""Tests for pre_tool_write.is_test_file — the cross-language test-file heuristic.

Split from test_pre_tool_write.py, which was 508 lines (over the project's 500
cap) before this class left. is_test_file enumerates 13 ecosystems' test-naming
conventions, so its suite grows with every language added; the hook's own
behavior tests (conflict detection, TDD order, cost invariants) stay behind.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import pre_tool_write


class TestIsTestFile(unittest.TestCase):
    def test_python_test_prefix(self):
        self.assertTrue(pre_tool_write.is_test_file("test_foo.py"))

    def test_python_test_suffix(self):
        self.assertTrue(pre_tool_write.is_test_file("foo_test.py"))

    def test_js_test(self):
        self.assertTrue(pre_tool_write.is_test_file("app.test.js"))

    def test_ts_spec(self):
        self.assertTrue(pre_tool_write.is_test_file("app.spec.ts"))

    def test_ts_underscore_test(self):
        self.assertTrue(pre_tool_write.is_test_file("foo_test.ts"))

    def test_tsx_underscore_test(self):
        self.assertTrue(pre_tool_write.is_test_file("Button_test.tsx"))

    def test_js_underscore_test(self):
        self.assertTrue(pre_tool_write.is_test_file("util_test.js"))

    def test_jsx_underscore_test(self):
        self.assertTrue(pre_tool_write.is_test_file("Card_test.jsx"))

    def test_mts_underscore_test(self):
        self.assertTrue(pre_tool_write.is_test_file("api_test.mts"))

    def test_cts_underscore_test(self):
        self.assertTrue(pre_tool_write.is_test_file("legacy_test.cts"))

    def test_ts_impl_with_underscore_not_test(self):
        # Underscore in the middle (not preceding "_test.") shouldn't fire.
        self.assertFalse(pre_tool_write.is_test_file("user_service.ts"))

    def test_go_test(self):
        self.assertTrue(pre_tool_write.is_test_file("handler_test.go"))

    def test_java_test(self):
        self.assertTrue(pre_tool_write.is_test_file("UserTest.java"))

    def test_ruby_spec(self):
        self.assertTrue(pre_tool_write.is_test_file("user_spec.rb"))

    def test_tests_directory(self):
        self.assertTrue(pre_tool_write.is_test_file("tests/conftest.py"))

    def test_dunder_tests_directory(self):
        self.assertTrue(pre_tool_write.is_test_file("__tests__/Button.tsx"))

    def test_impl_file(self):
        self.assertFalse(pre_tool_write.is_test_file("src/app.ts"))

    def test_python_impl(self):
        self.assertFalse(pre_tool_write.is_test_file("models.py"))

    def test_swift_tests_suffix(self):
        self.assertTrue(pre_tool_write.is_test_file("JaroWinklerTests.swift"))

    def test_xcode_tests_directory(self):
        self.assertTrue(
            pre_tool_write.is_test_file("ContactForgeTests/JaroWinklerTests.swift")
        )

    def test_swift_impl(self):
        self.assertFalse(pre_tool_write.is_test_file("ContactForge/JaroWinkler.swift"))

    def test_rust_test_suffix(self):
        self.assertTrue(pre_tool_write.is_test_file("handler_test.rs"))

    def test_rust_impl(self):
        self.assertFalse(pre_tool_write.is_test_file("src/handler.rs"))

    def test_kotlin_test(self):
        self.assertTrue(pre_tool_write.is_test_file("UserTest.kt"))

    def test_kotlin_tests(self):
        self.assertTrue(pre_tool_write.is_test_file("UserTests.kt"))

    def test_csharp_test(self):
        self.assertTrue(pre_tool_write.is_test_file("UserTest.cs"))

    def test_cpp_test(self):
        self.assertTrue(pre_tool_write.is_test_file("test_handler.cpp"))
        self.assertTrue(pre_tool_write.is_test_file("handler_test.cc"))

    def test_cpp_impl(self):
        self.assertFalse(pre_tool_write.is_test_file("handler.cpp"))

    def test_php_test(self):
        self.assertTrue(pre_tool_write.is_test_file("UserTest.php"))

    def test_dart_test(self):
        self.assertTrue(pre_tool_write.is_test_file("widget_test.dart"))

    def test_elixir_test(self):
        self.assertTrue(pre_tool_write.is_test_file("user_test.exs"))

    def test_maven_test_dir(self):
        self.assertTrue(pre_tool_write.is_test_file("src/test/java/UserTest.java"))

    def test_spec_dir(self):
        self.assertTrue(pre_tool_write.is_test_file("spec/user_spec.rb"))

    def test_scala_test(self):
        self.assertTrue(pre_tool_write.is_test_file("UserTest.scala"))


if __name__ == "__main__":
    unittest.main()

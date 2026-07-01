#!/usr/bin/env python3
"""Per-language BUILTIN_LAYOUTS discovery suites for sister_tests.

Split out of tests/hooks/test_sister_tests.py: that file keeps the compiler /
discovery mechanics; this file holds the per-language layout suites. The shared
base and ``_touch`` helper are imported from the co-located sister_test_base so
exactly one definition exists.
"""

import sys
import unittest
from pathlib import Path

# sister_tests lives in smm/ — not on sys.path under the `python3 -m unittest`
# fallback (no conftest auto-load). Insert smm/ so it resolves. Also insert this
# engine dir so the bare `import sister_test_base` (a top-level sibling) resolves
# under unittest discover regardless of collection order.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sister_test_base import (  # pyright: ignore[reportMissingImports]
    _DiscoveryTestCase,
    _touch,
)
from sister_tests import (  # pyright: ignore[reportMissingImports]
    BUILTIN_LAYOUTS,
    discover_sister_tests,
)


class TestBuiltinLayoutsScaffold(unittest.TestCase):
    """The BUILTIN_LAYOUTS dict exists; per-language entries land in later commits."""

    def test_builtin_layouts_is_a_dict(self):
        self.assertIsInstance(BUILTIN_LAYOUTS, dict)


class TestPythonPytest(_DiscoveryTestCase):
    """python_pytest: top-level tests/ tree AND co-located {dir}/tests/."""

    def setUp(self):
        super().setUp()
        self.layout = BUILTIN_LAYOUTS["python_pytest"]

    def test_top_level_tests_dir_r1(self):
        _touch(self.root, "tests/test_foo.py")
        self.assertEqual(
            discover_sister_tests("pkg/foo.py", self.layout, self.root),
            ["tests/test_foo.py"],
        )

    def test_nested_top_level_tests_dir_r1(self):
        # tests/**/test_<stem>*.py — nested OK
        _touch(self.root, "tests/sub/test_foo.py")
        self.assertEqual(
            discover_sister_tests("pkg/foo.py", self.layout, self.root),
            ["tests/sub/test_foo.py"],
        )

    def test_colocated_tests_dir_r2(self):
        _touch(self.root, "pkg/tests/test_foo.py")
        out = discover_sister_tests("pkg/foo.py", self.layout, self.root)
        self.assertIn("pkg/tests/test_foo.py", out)

    def test_suffix_wildcard_matches_extra_test_files(self):
        # test_<stem>*.py matches test_foo_edge.py as well as test_foo.py.
        _touch(self.root, "tests/test_foo_edge.py")
        _touch(self.root, "tests/test_foo.py")
        out = discover_sister_tests("pkg/foo.py", self.layout, self.root)
        self.assertEqual(
            out,
            ["tests/test_foo.py", "tests/test_foo_edge.py"],
        )

    def test_skip_basenames_init_and_conftest(self):
        # Source files named __init__.py / conftest.py must not produce results.
        _touch(self.root, "tests/test___init__.py")
        _touch(self.root, "tests/test_conftest.py")
        self.assertEqual(
            discover_sister_tests("pkg/__init__.py", self.layout, self.root), []
        )
        self.assertEqual(
            discover_sister_tests("pkg/conftest.py", self.layout, self.root), []
        )

    def test_no_test_file_on_disk_returns_empty(self):
        # Negative: rule matches, no file -> [].
        self.assertEqual(
            discover_sister_tests("pkg/bar.py", self.layout, self.root), []
        )


class TestPhpPhpunit(_DiscoveryTestCase):
    """php_phpunit: src/Foo.php -> tests/FooTest.php (flat or mirror)."""

    def setUp(self):
        super().setUp()
        self.layout = BUILTIN_LAYOUTS["php_phpunit"]

    def test_flat_tests_dir_r1(self):
        _touch(self.root, "tests/FooTest.php")
        out = discover_sister_tests("src/Foo.php", self.layout, self.root)
        self.assertIn("tests/FooTest.php", out)

    def test_mirror_layout_r2(self):
        _touch(self.root, "tests/Bar/BazTest.php")
        out = discover_sister_tests("src/Bar/Baz.php", self.layout, self.root)
        self.assertIn("tests/Bar/BazTest.php", out)

    def test_test_file_as_source_is_skipped(self):
        _touch(self.root, "tests/FooTestTest.php")
        self.assertEqual(
            discover_sister_tests("src/FooTest.php", self.layout, self.root), []
        )

    def test_no_test_file_on_disk_returns_empty(self):
        self.assertEqual(
            discover_sister_tests("src/Bar.php", self.layout, self.root), []
        )


class TestSwiftXCTest(_DiscoveryTestCase):
    """swift_xctest: Sources/<mod>/Foo.swift -> Tests/<any>/FooTests.swift."""

    def setUp(self):
        super().setUp()
        self.layout = BUILTIN_LAYOUTS["swift_xctest"]

    def test_finds_test_in_any_module_tests_dir(self):
        # SwiftPM convention: Tests/<ModuleNameTests>/FooTests.swift. We use
        # the simpler glob Tests/**/FooTests.swift since the plan defers exact
        # module-name derivation.
        _touch(self.root, "Tests/MyLibTests/FooTests.swift")
        self.assertEqual(
            discover_sister_tests("Sources/MyLib/Foo.swift", self.layout, self.root),
            ["Tests/MyLibTests/FooTests.swift"],
        )

    def test_test_file_as_source_is_skipped(self):
        _touch(self.root, "Tests/MyLibTests/FooTestsTests.swift")
        self.assertEqual(
            discover_sister_tests(
                "Sources/MyLib/FooTests.swift", self.layout, self.root
            ),
            [],
        )

    def test_no_test_file_on_disk_returns_empty(self):
        self.assertEqual(
            discover_sister_tests("Sources/MyLib/Bar.swift", self.layout, self.root),
            [],
        )


class TestElixirExunit(_DiscoveryTestCase):
    """elixir_exunit: lib/foo/bar.ex -> test/foo/bar_test.exs (mirror)."""

    def setUp(self):
        super().setUp()
        self.layout = BUILTIN_LAYOUTS["elixir_exunit"]

    def test_mirror_layout(self):
        _touch(self.root, "test/foo/bar_test.exs")
        self.assertEqual(
            discover_sister_tests("lib/foo/bar.ex", self.layout, self.root),
            ["test/foo/bar_test.exs"],
        )

    def test_source_directly_under_lib(self):
        _touch(self.root, "test/bar_test.exs")
        self.assertEqual(
            discover_sister_tests("lib/bar.ex", self.layout, self.root),
            ["test/bar_test.exs"],
        )

    def test_test_file_as_source_is_skipped(self):
        _touch(self.root, "test/bar_test_test.exs")
        self.assertEqual(
            discover_sister_tests("lib/bar_test.exs", self.layout, self.root),
            [],
        )

    def test_no_test_file_on_disk_returns_empty(self):
        self.assertEqual(
            discover_sister_tests("lib/foo/bar.ex", self.layout, self.root), []
        )


class TestCsharpXunit(_DiscoveryTestCase):
    """csharp_xunit: Foo.cs -> FooTests.cs (sibling or sibling Tests dir).

    Sources under obj/ and bin/ are excluded (generated build artifacts).
    """

    def setUp(self):
        super().setUp()
        self.layout = BUILTIN_LAYOUTS["csharp_xunit"]

    def test_sibling_tests_cs(self):
        _touch(self.root, "src/Project/FooTests.cs")
        self.assertIn(
            "src/Project/FooTests.cs",
            discover_sister_tests("src/Project/Foo.cs", self.layout, self.root),
        )

    def test_separate_tests_project(self):
        # {dir}/../Tests/{stem}Tests.cs — common .NET layout with a sibling
        # Tests project at src/Project.Tests/.
        _touch(self.root, "src/Tests/FooTests.cs")
        out = discover_sister_tests("src/Project/Foo.cs", self.layout, self.root)
        self.assertIn("src/Tests/FooTests.cs", out)

    def test_obj_dir_source_excluded(self):
        # Generated code under obj/ must not produce sister-test lookups.
        _touch(self.root, "obj/FooTests.cs")
        self.assertEqual(
            discover_sister_tests("obj/Foo.cs", self.layout, self.root), []
        )

    def test_bin_dir_source_excluded(self):
        _touch(self.root, "bin/FooTests.cs")
        self.assertEqual(
            discover_sister_tests("bin/Foo.cs", self.layout, self.root), []
        )

    def test_test_file_as_source_is_skipped(self):
        _touch(self.root, "src/Project/FooTestsTests.cs")
        self.assertEqual(
            discover_sister_tests("src/Project/FooTests.cs", self.layout, self.root),
            [],
        )

    def test_no_test_file_on_disk_returns_empty(self):
        self.assertEqual(
            discover_sister_tests("src/Project/Bar.cs", self.layout, self.root), []
        )


class TestJavaJunit(_DiscoveryTestCase):
    """java_junit: src/main/java/<pkg>/Foo.java -> src/test/java/<pkg>/FooTest.java."""

    def setUp(self):
        super().setUp()
        self.layout = BUILTIN_LAYOUTS["java_junit"]

    def test_test_suffix(self):
        _touch(self.root, "src/test/java/com/acme/FooTest.java")
        self.assertEqual(
            discover_sister_tests(
                "src/main/java/com/acme/Foo.java", self.layout, self.root
            ),
            ["src/test/java/com/acme/FooTest.java"],
        )

    def test_tests_suffix(self):
        _touch(self.root, "src/test/java/com/acme/FooTests.java")
        self.assertIn(
            "src/test/java/com/acme/FooTests.java",
            discover_sister_tests(
                "src/main/java/com/acme/Foo.java", self.layout, self.root
            ),
        )

    def test_it_suffix_integration(self):
        _touch(self.root, "src/test/java/com/acme/FooIT.java")
        self.assertIn(
            "src/test/java/com/acme/FooIT.java",
            discover_sister_tests(
                "src/main/java/com/acme/Foo.java", self.layout, self.root
            ),
        )

    def test_test_file_as_source_is_skipped(self):
        # FooTest.java IS a test — must not re-resolve.
        _touch(self.root, "src/test/java/com/acme/FooTestTest.java")
        self.assertEqual(
            discover_sister_tests(
                "src/test/java/com/acme/FooTest.java", self.layout, self.root
            ),
            [],
        )

    def test_no_test_file_on_disk_returns_empty(self):
        self.assertEqual(
            discover_sister_tests(
                "src/main/java/com/acme/Bar.java", self.layout, self.root
            ),
            [],
        )


class TestRubyRspec(_DiscoveryTestCase):
    """ruby_rspec: lib/foo/bar.rb -> spec/foo/bar_spec.rb (mirror layout)."""

    def setUp(self):
        super().setUp()
        self.layout = BUILTIN_LAYOUTS["ruby_rspec"]

    def test_top_level_spec(self):
        # R1: spec/{stem}_spec.rb regardless of nesting under lib/.
        _touch(self.root, "spec/bar_spec.rb")
        out = discover_sister_tests("lib/foo/bar.rb", self.layout, self.root)
        self.assertIn("spec/bar_spec.rb", out)

    def test_mirror_layout(self):
        # R2: spec/{mirror}/{stem}_spec.rb — strip the 'lib/' prefix.
        _touch(self.root, "spec/foo/bar_spec.rb")
        out = discover_sister_tests("lib/foo/bar.rb", self.layout, self.root)
        self.assertIn("spec/foo/bar_spec.rb", out)

    def test_source_directly_under_lib(self):
        # lib/bar.rb -> spec/bar_spec.rb via both R1 and the collapsed mirror R2.
        _touch(self.root, "spec/bar_spec.rb")
        out = discover_sister_tests("lib/bar.rb", self.layout, self.root)
        self.assertEqual(out, ["spec/bar_spec.rb"])

    def test_spec_file_as_source_is_skipped(self):
        # bar_spec.rb IS a spec — don't re-resolve.
        _touch(self.root, "spec/bar_spec_spec.rb")
        self.assertEqual(
            discover_sister_tests("lib/bar_spec.rb", self.layout, self.root),
            [],
        )

    def test_no_spec_file_on_disk_returns_empty(self):
        self.assertEqual(
            discover_sister_tests("lib/foo/bar.rb", self.layout, self.root), []
        )


class TestRustCargo(_DiscoveryTestCase):
    """rust_cargo: src/bin/foo.rs -> tests/foo.rs (integration tests only)."""

    def setUp(self):
        super().setUp()
        self.layout = BUILTIN_LAYOUTS["rust_cargo"]

    def test_bin_source_finds_integration_test(self):
        _touch(self.root, "tests/foo.rs")
        self.assertEqual(
            discover_sister_tests("src/bin/foo.rs", self.layout, self.root),
            ["tests/foo.rs"],
        )

    def test_lib_source_returns_empty(self):
        # src/lib.rs and src/foo.rs don't follow the integration-test pattern.
        _touch(self.root, "tests/lib.rs")
        self.assertEqual(
            discover_sister_tests("src/lib.rs", self.layout, self.root), []
        )

    def test_test_file_in_tests_dir_skipped_as_source(self):
        # A file under tests/ that gets passed as source shouldn't re-resolve.
        _touch(self.root, "tests/foo_test.rs")
        self.assertEqual(
            discover_sister_tests("tests/foo_test.rs", self.layout, self.root),
            [],
        )

    def test_no_integration_test_on_disk_returns_empty(self):
        self.assertEqual(
            discover_sister_tests("src/bin/foo.rs", self.layout, self.root), []
        )


class TestJsUnit(_DiscoveryTestCase):
    """js_unit: .test.{ext}, .spec.{ext}, and __tests__/{stem}.test.{ext}."""

    def setUp(self):
        super().setUp()
        self.layout = BUILTIN_LAYOUTS["js_unit"]

    def test_dot_test_sibling_ts(self):
        _touch(self.root, "src/foo.test.ts")
        self.assertEqual(
            discover_sister_tests("src/foo.ts", self.layout, self.root),
            ["src/foo.test.ts"],
        )

    def test_dot_spec_sibling_js(self):
        _touch(self.root, "src/bar.spec.js")
        self.assertEqual(
            discover_sister_tests("src/bar.js", self.layout, self.root),
            ["src/bar.spec.js"],
        )

    def test_underscore_tests_subdir(self):
        # __tests__/{stem}.test.{ext}
        _touch(self.root, "src/__tests__/baz.test.tsx")
        self.assertEqual(
            discover_sister_tests("src/baz.tsx", self.layout, self.root),
            ["src/__tests__/baz.test.tsx"],
        )

    def test_d_ts_source_is_skipped(self):
        # foo.d.ts is a declaration file, not a real source.
        _touch(self.root, "src/foo.test.ts")
        self.assertEqual(
            discover_sister_tests("src/foo.d.ts", self.layout, self.root),
            [],
        )

    def test_test_file_as_source_is_skipped(self):
        # foo.test.ts IS a test — skip when given as source.
        _touch(self.root, "src/foo.test.test.ts")  # would match if not skipped
        self.assertEqual(
            discover_sister_tests("src/foo.test.ts", self.layout, self.root),
            [],
        )

    def test_no_test_file_on_disk_returns_empty(self):
        self.assertEqual(
            discover_sister_tests("src/bar.ts", self.layout, self.root), []
        )


class TestGoNative(_DiscoveryTestCase):
    """go_native: foo.go -> foo_test.go in the same dir."""

    def setUp(self):
        super().setUp()
        self.layout = BUILTIN_LAYOUTS["go_native"]

    def test_finds_colocated_test(self):
        _touch(self.root, "pkg/foo_test.go")
        self.assertEqual(
            discover_sister_tests("pkg/foo.go", self.layout, self.root),
            ["pkg/foo_test.go"],
        )

    def test_test_file_as_source_is_skipped(self):
        # foo_test.go IS the test — don't re-resolve it via the _test suffix.
        _touch(self.root, "pkg/foo_test_test.go")  # would match if not skipped
        self.assertEqual(
            discover_sister_tests("pkg/foo_test.go", self.layout, self.root),
            [],
        )

    def test_no_test_file_on_disk_returns_empty(self):
        self.assertEqual(
            discover_sister_tests("pkg/bar.go", self.layout, self.root), []
        )


if __name__ == "__main__":
    unittest.main()

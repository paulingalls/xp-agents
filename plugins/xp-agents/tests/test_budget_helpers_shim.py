"""Smoke test pinning the public extraction surface for _budget_helpers.

Write the shim-import test BEFORE extracting from a >500-line file so
cascade breakage is caught at collection time, not in 80 downstream
test failures.
"""


def test_shim_imports_from_conftest():
    from conftest import (
        _HISTORICAL_ID_RE,
        _LEAKY_GIT_ENV,
        _bootstrap_seeded_smm,
        _run_emitter,
        _run_preload,
        assert_budgets_match,
        assert_emitter_under_budgets,
        assert_md_budgets_match,
        assert_md_under_budgets,
        assert_no_12hex_ids_in_md,
        assert_preload_under_budgets,
        discover_emitter_scripts,
        discover_preload_scripts,
    )

    assert all(
        [
            _HISTORICAL_ID_RE,
            _LEAKY_GIT_ENV,
            _bootstrap_seeded_smm,
            _run_emitter,
            _run_preload,
            assert_emitter_under_budgets,
            assert_preload_under_budgets,
            assert_md_under_budgets,
            assert_md_budgets_match,
            assert_budgets_match,
            assert_no_12hex_ids_in_md,
            discover_emitter_scripts,
            discover_preload_scripts,
        ]
    )


def test_direct_imports_from_module():
    """Extraction is real, not a flat-namespace alias."""
    from _budget_helpers import (
        _bootstrap_seeded_smm,
        _run_emitter,
        _run_preload,
        assert_emitter_under_budgets,
    )

    assert all(
        [
            _run_emitter,
            _run_preload,
            assert_emitter_under_budgets,
            _bootstrap_seeded_smm,
        ]
    )

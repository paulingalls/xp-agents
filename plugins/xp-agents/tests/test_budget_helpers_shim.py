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


def test_measured_len_normalizes_the_real_worktree_layout():
    """The location guard must match where worktrees ACTUALLY live.

    `_WORKTREE_SEGMENT_RE` was written for `/.claude/worktrees/<dir>`. Worktrees
    have lived under `${XP_AGENTS_DATA:-~/.xp-agents/data}/{project-id}/worktrees/`
    since the v5.0.0 SMM root move, so the guard matched nothing and every
    emitter budget measured longer inside a teammate worktree than in the main
    checkout — purely from path length. Two teammates in one session each
    misdiagnosed that drift as real growth (one bypassed the gate, one banked a
    permanent budget bump), which is what a guard that silently matches nothing
    costs.
    """
    from _budget_helpers import _measured_len

    root = "/Users/x/.xp-agents/data/abc123"
    plain = f"SMM_DIR={root}/smm\n".encode()
    inside_worktree = f"SMM_DIR={root}/worktrees/worktree-story-004/smm\n".encode()

    assert _measured_len(inside_worktree) == _measured_len(plain), (
        "the worktrees segment under the data root must be stripped — it was "
        "only ever matched under .claude/, which is not where worktrees live"
    )


def test_emitter_budgets_normalize_checkout_paths():
    """`assert_emitter_under_budgets` must pass `normalize_paths`, as its
    preload sibling does. Without it the base checkout path length leaks into
    every emitter measurement, so the same code scores differently depending on
    where the checkout lives.
    """
    import inspect

    from conftest import assert_emitter_under_budgets

    source = inspect.getsource(assert_emitter_under_budgets)
    assert "normalize_paths" in source, (
        "emitter budgets must normalize checkout-variable paths before "
        "measuring — the preload helper already does"
    )

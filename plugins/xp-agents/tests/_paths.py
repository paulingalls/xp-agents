#!/usr/bin/env python3
"""Tree paths every suite resolves against. The LEAF of the tests/ import graph.

It imports nothing from the suite, which is the point: `_bases` and `_repo_bases`
both need `_PLUGIN_ROOT`, and whichever of them owned it would have to be imported
by the other — a cycle the moment the owner also re-exports the other's names for
back-compat. A leaf breaks that: `_paths` <- `_repo_bases` <- `_bases` <- conftest,
every arrow pointing DOWN.

`_bases` re-exports all of these BY IDENTITY, so `from _bases import _PLUGIN_ROOT`
(and the conftest spelling) keep working unchanged — which is what makes the many
suites that reach for them evidence that this split is correct rather than files
to edit.
"""

from pathlib import Path

_PLUGIN_ROOT = Path(__file__).parent.parent
_SCRIPTS_DIR = _PLUGIN_ROOT / "scripts"
_SMM_DIR = _PLUGIN_ROOT / "smm"
_MARKERS_PY = _SCRIPTS_DIR / "markers.py"
_CADENCE_CLI_PY = _SCRIPTS_DIR / "cadence_cli.py"
_TEAMMATE_CONFIG_CLI_PY = _SCRIPTS_DIR / "teammate_config_cli.py"

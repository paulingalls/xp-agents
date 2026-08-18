.PHONY: setup manifests

# Regenerates the two DERIVED packaging manifests from their hand-edited
# sources: hooks/hooks.codex.json from hooks/hooks.json, and
# .codex-plugin/plugin.json from .claude-plugin/plugin.json. Neither derived
# file is ever hand-edited, so running this is always safe and idempotent.
#
# It exists because nothing invoked the emitters. Their own docstrings were the
# only instruction, so a version bump or a hooks edit desynchronized the derived
# half until the full suite ran at push — which happened twice in one day and
# cost two repair commits. The commit gate now calls this target (lefthook's
# `derived-manifests`), and the regeneration pins in tests/test_manifest_pins.py
# and tests/test_hooks_variants.py remain the backstop.
manifests:
	python3 plugins/xp-agents/scripts/hooks_emit.py
	python3 plugins/xp-agents/scripts/manifest_emit.py

# Wires up the gates: verifies pytest -n auto actually works (the CAPABILITY
# that matters, however it got installed — pipx is only the recommended
# route, not a requirement), verifies `node --test` runs, installs the
# lefthook hooks, and sets an SSH keepalive for this clone.
#
# The node probe is here for the same reason the pytest one is: the JS suite
# covering the shipped Workflow script is DRIVEN from pytest, so a missing
# node fails the whole suite rather than skipping the file. Finding that out
# at `make setup` is a one-line message; finding it out at push is a red gate
# on a change that touched no JavaScript.
#
# The keepalive is not optional housekeeping. The full suite runs on
# PRE-PUSH, and git opens the connection to the remote BEFORE running that
# hook — so a multi-minute suite leaves the connection idle until the server
# closes it. The suite passes and the push dies anyway, reporting only
# "Connection to github.com closed by remote host" with none of the hook's
# output. Measured here: a 320s hook landed, a 510s hook died with SIGPIPE,
# two ~360s pushes died with exit 243.
#
# It lives here because core.sshCommand is per-clone git config — it cannot
# be committed, and this is the target every clone already runs.
#
# Idempotent: test_dev_setup.py's failure message points developers here,
# and some will run it twice.
setup:
	@probe=$$(pytest -n auto --collect-only -q 2>&1); \
	if [ $$? -ne 0 ]; then \
		echo "$$probe" >&2; \
		echo "" >&2; \
		echo "'pytest -n auto --collect-only' failed (output above), so the commit gate was NOT installed." >&2; \
		echo "A collection error means pytest works and a module doesn't — fix that, not this." >&2; \
		echo "If pytest itself is missing, install it and re-run 'make setup':" >&2; \
		echo "  brew install pipx                    # if not already installed" >&2; \
		echo "  pipx install pytest" >&2; \
		echo "  pipx inject pytest pytest-xdist      # parallel test execution" >&2; \
		exit 1; \
	fi
	@if ! node --test --help >/dev/null 2>&1; then \
		echo "'node --test' isn't available, so the JavaScript suite covering" >&2; \
		echo "plugins/xp-agents/workflows/ cannot run — and it is driven from" >&2; \
		echo "pytest, so its absence fails the suite rather than skipping it." >&2; \
		echo "Install Node (v22 or newer) and re-run 'make setup':" >&2; \
		echo "  brew install node" >&2; \
		exit 1; \
	fi
	@if ! command -v lefthook >/dev/null 2>&1; then \
		echo "lefthook isn't on PATH. Install it, then re-run 'make setup':" >&2; \
		echo "  brew install lefthook" >&2; \
		exit 1; \
	fi
	lefthook install
	git config core.sshCommand "ssh -o ServerAliveInterval=60 -o ServerAliveCountMax=10"
	@echo "Gates installed — lint/format/types plus your staged tests on commit;"
	@echo "the full suite on push, with an SSH keepalive so it survives the wait."

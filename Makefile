.PHONY: setup

# Wires up the commit gate: verifies pytest -n auto actually works (the
# CAPABILITY that matters, however it got installed — pipx is only the
# recommended route, not a requirement), then installs the lefthook hook.
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
	@if ! command -v lefthook >/dev/null 2>&1; then \
		echo "lefthook isn't on PATH. Install it, then re-run 'make setup':" >&2; \
		echo "  brew install lefthook" >&2; \
		exit 1; \
	fi
	lefthook install
	@echo "Commit gate installed — pytest -n auto now runs on every commit."

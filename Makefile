.PHONY: setup

# Wires up the gates: verifies pytest -n auto actually works (the CAPABILITY
# that matters, however it got installed — pipx is only the recommended
# route, not a requirement), installs the lefthook hooks, and sets an SSH
# keepalive for this clone.
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
	@if ! command -v lefthook >/dev/null 2>&1; then \
		echo "lefthook isn't on PATH. Install it, then re-run 'make setup':" >&2; \
		echo "  brew install lefthook" >&2; \
		exit 1; \
	fi
	lefthook install
	git config core.sshCommand "ssh -o ServerAliveInterval=60 -o ServerAliveCountMax=10"
	@echo "Gates installed — lint/format/types plus your staged tests on commit;"
	@echo "the full suite on push, with an SSH keepalive so it survives the wait."

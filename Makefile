.PHONY: test test-unit test-integration test-all

# Fast unit tests (~0.2s + ~8s) — run on every change
test-unit:
	python3 -m unittest plugins/xp-agents/scripts/test_hooks.py plugins/xp-agents/smm/test_smm.py plugins/xp-agents/smm/test_engine.py

# Integration tests (~5s) — run before pushing
test-integration:
	python3 -m unittest plugins/xp-agents/scripts/test_integration.py

# Everything (~14s) — full confidence
test-all:
	python3 -m unittest plugins/xp-agents/scripts/test_hooks.py plugins/xp-agents/smm/test_smm.py plugins/xp-agents/smm/test_engine.py plugins/xp-agents/scripts/test_integration.py

# Default: unit tests (what pre-commit runs)
test: test-unit

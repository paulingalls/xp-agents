---
name: xp-security-triage
description: >-
  Triage staged changes for security relevance before committing. Reads
  git diff --cached, classifies changes as trivial (docs, tests, renames,
  config) or security-relevant (auth, crypto, input handling, permissions,
  network, secrets). Trivial changes get auto-cleared; security-relevant
  changes require /security-review first.
effort: high
allowed-tools:
  - Bash(*/skills/*/scripts/*)
  - Skill(security-review)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload_diff.sh`

The triage marker has been written and the commit gate is cleared. Classify the staged changes above:

**Trivial:** renames, documentation, tests, config formatting, comments, imports, type annotations, CI/CD metadata — changes that cannot introduce security vulnerabilities. No further action needed.

**Security-relevant:** any change touching authentication, authorization, cryptography, input validation/sanitization, file I/O with user-controlled paths, network requests, secret/credential handling, permission checks, SQL/command construction, cookie/session management, CORS/CSP headers, or dependency version changes. Run `/security-review` for a full review. This is a **built-in Claude Code command** — invoke it as `/security-review`, NOT as `xp-agents:security-review`.

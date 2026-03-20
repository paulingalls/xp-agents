---
name: xp-security-triage
description: >-
  Triage staged changes for security relevance before committing. Reads
  git diff --cached, classifies changes as trivial (docs, tests, renames,
  config) or security-relevant (auth, crypto, input handling, permissions,
  network, secrets). Trivial changes get auto-cleared; security-relevant
  changes require /security-review first.
allowed-tools:
  - Bash(git diff --cached*)
  - Bash(*/skills/*/scripts/*)
---

Review the staged changes (`git diff --cached`) and classify them:

**Trivial (auto-clear):** renames, documentation, tests, config formatting, comments, imports, type annotations, CI/CD metadata — changes that cannot introduce security vulnerabilities.

**Security-relevant (require review):** any change touching authentication, authorization, cryptography, input validation/sanitization, file I/O with user-controlled paths, network requests, secret/credential handling, permission checks, SQL/command construction, cookie/session management, CORS/CSP headers, or dependency version changes.

## If trivial

Write the triage marker:

!`python3 ${CLAUDE_SKILL_DIR}/scripts/mark_triaged.py`

Changes triaged as non-security-relevant. Commit gate cleared.

## If security-relevant

Do NOT write the marker. Instead, run `/security-review` which will perform a full security review and write the marker upon completion.

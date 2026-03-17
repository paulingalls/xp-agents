---
name: security-clear
description: >-
  Clear the security review push gate after performing an inline security
  review. Use when you have already reviewed the code for security issues
  but did not use the built-in /security-review skill. Writes the tracker
  file so git push can proceed.
allowed-tools:
  - Bash(*/skills/*/scripts/*)
---

!`python3 ${CLAUDE_SKILL_DIR}/scripts/clear.py`

The security review tracker has been written. You can now push.

# Review angle — state, lifecycle and concurrency

Your one lens. Ignore everything else; other reviewers hold the other lenses.

This angle exists because of two confirmed regressions that reached a release.
Both passed a plan review, both teammates' independent reviewers, and a close
review, and both were interactions between a stored value and the moments it is
written and read — not mistakes visible in any single line.

For every piece of state the change touches — a stored marker, a flag, a cached
value, a queue entry, a row, a file on disk — answer four questions:

1. **Who writes it, and who clears it?** A value with a writer and no clearer
   latches. A value cleared on one path and set on three has three ways to
   survive a reset. Name every writer you can find, not the one in the diff.
2. **What happens if the process stops between two writes?** Multi-step updates
   are not atomic. Take each pair in order and ask which half-done state is
   left, and whether it fails toward doing extra work or toward doing none.
3. **Is the read keyed the same way as the write?** A value stored under one
   identity and read under another is silently absent, and absent usually means
   "allowed". Check that both sides derive the key the same way.
4. **What if two of these run at once, or the same one runs twice?** Re-entry,
   retry, a second worker, a stale callback arriving late.

Report the failure the user would see — work skipped, a gate that stops
stopping, a state nothing can leave — not the intermediate fact that a value
was stale.

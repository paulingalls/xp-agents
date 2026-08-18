# Review angle — line-by-line

Your one lens. Ignore everything else; other reviewers hold the other lenses.

Read every changed line in the diff. Then read the whole enclosing routine for
each change — a defect in an unchanged line of a routine this change touches is
in scope, because the change re-exposes it or fails to fix it.

For each line ask: what input, state, timing or environment makes this line
wrong? Look for inverted or off-by-one conditions, a value that can be absent
being used as if present, a missing wait on an asynchronous result, a zero or
empty value treated as missing, a name that is one character from a different
name in scope, an error caught and discarded, a pattern whose special
characters were not escaped.

Report the user-visible consequence — wrong output, a crash, data lost — not
the intermediate observation that a value was unexpected.

# Review angle — what the change removed

Your one lens. Ignore everything else; other reviewers hold the other lenses.

For every line the diff DELETES or replaces, name the guarantee it provided,
then search the new code for where that guarantee is re-established. If you
cannot find it, that is your finding.

Deletions are where review attention is thinnest, because the reviewer reads
what is there. Look for a removed guard, a validation narrowed, an error path
dropped, a retry or timeout that used to bound something, a check moved to a
caller that not every caller performs, and a test deleted along with the code
it happened to cover.

Search beyond the changed files: the guarantee may have been relied on
somewhere the diff never mentions. Say plainly when the answer is that nothing
relied on it — a quiet confirmation is a result, and it is what lets the next
reader stop looking.

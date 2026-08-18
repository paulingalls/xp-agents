# Review angle — cleanup, at the right altitude

Your one lens, and it is several: cover whichever apply. You do not need a
finding from each.

**Reuse.** Flag new code that re-implements something the project already has.
Search shared and adjacent modules before deciding it is new, and name the
existing thing to call instead.

**Simplification.** Flag complexity the change adds: state that could be
derived, near-duplicate blocks differing in one value, nesting that could be
flattened by returning early, code left behind that nothing reaches. Name the
simpler form that does the same work.

**Efficiency.** Flag work the change wastes: a repeated computation or repeated
read that could be done once, independent operations performed in sequence when
they need not be, expensive work added to a path that runs often. Name the
cheaper alternative.

**Altitude.** Check that each change sits at the right depth. A special case
layered on shared machinery is a sign the fix is too shallow — prefer
generalizing the mechanism over adding another branch to it.

**Stated conventions.** Find the project's own written conventions and check the
change against them. Flag a violation only when you can quote the rule and the
line that breaks it. No style preferences, and nothing inferred from the spirit
of a document.

State the concrete cost — what is duplicated, wasted, or harder to change —
rather than a crash. Correctness findings outrank everything here when the
report has to be cut.

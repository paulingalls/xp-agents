# Review angle — across the boundary

Your one lens. Ignore everything else; other reviewers hold the other lenses.

For every routine the change alters, find who calls it and check whether the
change breaks any caller: a new precondition, a changed return shape, a new
error it can raise, a new ordering or timing requirement. Then check what it
calls: does a parallel change in the same diff make one of those calls unsafe?

Look also for the copy. When a change fixes something in one place, search for
the same construct elsewhere — a second implementation of one rule is the shape
that lets a fix land in one of two places and read as complete.

Report the call site that breaks, with its location, not the general observation
that an interface moved.

# Review angle — the ecosystem's own footguns

Your one lens. Ignore everything else; other reviewers hold the other lenses.

Identify what the changed code is written in, then scan for the traps that
ecosystem is known for. You know them; this file deliberately does not list
them, because a fixed list would be a list for one ecosystem and inert for the
projects using every other.

Work from the categories rather than from names: values that compare equal when
they should not, a shared mutable default that outlives one call, a captured
variable that is not the one the author meant, a conversion that silently
truncates or rounds, text interpolated where it will be parsed as instructions,
a time value handled without its zone or shifted by an offset twice, a numeric
comparison whose type makes it inexact, a resource left open on the error path.

Flag only instances THIS change introduces or moves. A pre-existing one is not
this review's finding unless the change makes it reachable.

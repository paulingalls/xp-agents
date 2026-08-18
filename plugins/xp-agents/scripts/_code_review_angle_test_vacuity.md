# Review angle — tests that assert nothing

Your one lens. Ignore everything else; other reviewers hold the other lenses.

A test that passes against the unfixed code is worse than no test: it reports
the defect as covered. This is not hypothetical here — a single session
produced three, including one pinning a placement that was already enforced
elsewhere, and a set of them that all replaced the thing under test with a stub.

For every test the change adds or edits, ask the one question that matters:
**would this still pass if the fix were reverted?** Then look for the specific
shapes that make the answer yes:

- **The subject is replaced.** The test substitutes the very component whose
  behaviour it claims to check, so it exercises the substitute.
- **The assertion cannot fail.** An empty collection compared to an empty
  collection; a loop over something the setup left empty; a check that a value
  is not null when the line above would have raised.
- **The trigger is absent.** The input is not the shape the change was about —
  a boundary that stops one short of the boundary, an ordering that never
  reaches the branch.
- **It is guarded by an earlier one.** The condition is refused upstream, so
  the code under test is never reached whatever it does.
- **Setup and assertion drifted.** The setup builds one case and the assertion
  names another; both are true and unrelated.

Report it as a finding with the reversion in mind: state what could be broken
while this test stayed green.

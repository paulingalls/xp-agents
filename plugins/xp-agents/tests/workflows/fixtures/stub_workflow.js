// A minimal workflow script, shaped exactly like a real one, used to prove the
// harness before anything depends on it.
//
// Three shapes here are the whole reason a harness is needed, and a fixture
// missing any of them would let the harness pass while being unable to load
// what actually ships:
//
//   * `export const meta` — module syntax, illegal inside a function body.
//   * a TOP-LEVEL `return` — illegal in a module, legal in a function body.
//     A Workflow script is therefore neither an ES module nor a plain script.
//   * free identifiers (`agent`, `phase`, `log`, `args`) the runtime injects.
//
// Deliberately NOT a copy of the shipped orchestrator: this fixture exists to
// pin the loading contract, so it must stay small enough that a failure here
// means the harness broke and never that the review logic did.
export const meta = {
  name: 'stub-workflow',
  description: 'Fixture: exercises the loading contract, spawns one agent',
  phases: [{ title: 'Only', detail: 'one agent' }],
}

phase('Only')
log('stub running')
const answer = await agent('what is the answer', { label: 'stub', phase: 'Only' })
return { answer, argsSeen: args === undefined ? null : args }

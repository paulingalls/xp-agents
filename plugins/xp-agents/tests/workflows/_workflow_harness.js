'use strict'

// Load a Workflow script and drive it with stubbed agents.
//
// WHY A HARNESS AT ALL. A Workflow script is neither an ES module nor a plain
// script: it carries `export const meta` (module syntax) AND a top-level
// `return` (illegal in a module, legal only in a function body). Node can load
// neither form, so `require`/`import` are both out. The runtime evidently wraps
// the source in a function and injects its helpers as parameters; this does the
// same thing, which is a TRANSFORMATION of what ships rather than a second copy
// of it. Nothing here rewrites logic.
//
// What that buys: the orchestration — fan-out width, how candidates group, what
// the cap drops, what synthesis merges — becomes ordinary testable code instead
// of text a structural pin can only look at. Text pins over a launch call are
// exactly what let close Step 4b ship a name registered nowhere.

const { readFile } = require('node:fs/promises')

const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor

// The names the Workflow runtime injects, IN ITS ORDER — positional, because
// they arrive as function parameters. This list is the suite's load-bearing
// assumption: a rename or reorder upstream leaves every test green against a
// script that cannot run, and nothing in this repo would notice. Only a real
// launch does, which is why the dogfood step is not optional.
const RUNTIME_GLOBALS = ['agent', 'parallel', 'pipeline', 'phase', 'log', 'args', 'budget']

// `export` is stripped, not deleted: `const meta = {...}` still evaluates, so a
// script whose meta block is malformed fails here rather than passing a test and
// failing at launch. Anchored per-line so the word `export` inside prose or a
// prompt string is left alone.
const _stripExport = (src) => src.replace(/^export const meta/m, 'const meta')

// Faithful to the documented contract, NOT to convenience: a thunk that throws
// resolves to `null` instead of rejecting. Orchestration code is written against
// that (`.filter(Boolean)` after a fan-out), so a harness that rejected instead
// would make correct scripts look broken and hide the missing filter in ones
// that are.
const _parallel = (thunks) =>
  Promise.all(
    thunks.map(async (thunk) => {
      try {
        return await thunk()
      } catch {
        return null
      }
    }),
  )

// Also per contract: no barrier between stages, and a stage that throws drops
// ITS item to null without touching the others.
const _pipeline = (items, ...stages) =>
  Promise.all(
    items.map(async (item, index) => {
      let value = item
      for (const stage of stages) {
        try {
          value = await stage(value, item, index)
        } catch {
          return null
        }
      }
      return value
    }),
  )

const _defaultBudget = () => ({
  total: null,
  spent: () => 0,
  remaining: () => Infinity,
})

/**
 * Run `scriptPath` with `agent` stubbed.
 *
 * Returns `{ result, calls, logs, phases }` — the script's own return value,
 * every agent call in order with its options, and whatever it announced. The
 * call log is the point: fan-out width and grouping are assertions about which
 * agents ran, not about what they said.
 *
 * `agent` is invoked exactly as the script wrote it, and its rejection
 * propagates. Swallowing here would report every orchestration test green no
 * matter what the script did.
 */
async function runWorkflow(scriptPath, { agent, args, budget } = {}) {
  const src = _stripExport(await readFile(scriptPath, 'utf8'))
  const body = new AsyncFunction(...RUNTIME_GLOBALS, src)

  const calls = []
  const logs = []
  const phases = []

  const recordingAgent = async (prompt, opts = {}) => {
    calls.push({ prompt, opts })
    return agent(prompt, opts)
  }

  const result = await body(
    recordingAgent,
    _parallel,
    _pipeline,
    (title) => phases.push(title),
    (message) => logs.push(message),
    args,
    budget ?? _defaultBudget(),
  )

  return { result, calls, logs, phases }
}

module.exports = { runWorkflow, RUNTIME_GLOBALS }

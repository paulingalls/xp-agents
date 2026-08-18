'use strict'

// Tests for _workflow_harness.js — can we load and drive a Workflow script?
//
// Until this existed, a Workflow script was untestable in this repo and the only
// available checks were structural text pins over its source. That is the same
// class of check that let close Step 4b ship a launch call naming a workflow
// registered nowhere: every pin asserted the string was PRESENT, none that it
// was runnable.
//
// CommonJS on purpose. The repo has no JS convention to match and no
// package.json anywhere; `require` keeps it that way, where `import` would need
// one (or an .mjs suffix that fights the `_test.js` shape pre_tool_write.py
// already recognises). The script under test is unaffected either way — the
// harness reads it as TEXT, so its syntax never reaches Node's module resolver.

const test = require('node:test')
const assert = require('node:assert')
const path = require('node:path')

const { runWorkflow, RUNTIME_GLOBALS } = require('./_workflow_harness.js')

const STUB = path.join(__dirname, 'fixtures', 'stub_workflow.js')

test('it loads a script that is neither a module nor a plain script', async () => {
  // `export const meta` plus a top-level `return` in one file parses as neither.
  // If the harness ever stops stripping or stops wrapping, this is the failure.
  const { result } = await runWorkflow(STUB, { agent: async () => 42 })
  assert.strictEqual(result.answer, 42)
})

test('it passes args through untouched', async () => {
  const args = { level: 'high', range: 'main...HEAD' }
  const { result } = await runWorkflow(STUB, { agent: async () => 0, args })
  assert.deepStrictEqual(result.argsSeen, args)
})

test('it records every agent call, with its options', async () => {
  const { calls } = await runWorkflow(STUB, { agent: async () => 1 })
  assert.strictEqual(calls.length, 1)
  assert.strictEqual(calls[0].opts.label, 'stub')
  assert.match(calls[0].prompt, /what is the answer/)
})

test('it captures log() output rather than printing it', async () => {
  const { logs } = await runWorkflow(STUB, { agent: async () => 1 })
  assert.deepStrictEqual(logs, ['stub running'])
})

test('a throwing stub agent surfaces, it is not swallowed', async () => {
  // A harness that swallowed errors would report every orchestration test green
  // no matter what the script did.
  await assert.rejects(
    () => runWorkflow(STUB, { agent: async () => { throw new Error('boom') } }),
    /boom/,
  )
})

test('the injected globals are declared in one place, in runtime order', () => {
  // THE ASSUMPTION THIS SUITE RESTS ON, made visible rather than buried.
  // The harness hard-codes the names and ORDER the Workflow runtime injects. If
  // the runtime renames or reorders them, every test here stays green against a
  // script that cannot actually run — so this list is the thing to re-check
  // against the tool contract when a dogfood launch fails for no visible reason.
  assert.deepStrictEqual(RUNTIME_GLOBALS, [
    'agent',
    'parallel',
    'pipeline',
    'phase',
    'log',
    'args',
    'budget',
  ])
})

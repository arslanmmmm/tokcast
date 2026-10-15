import { expect, mock, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import type { On, PluginOptions, ProcessRunInit } from 'claude-code'

import type { RateLimit } from '../hooks/args'

const PROPS = {
  hasSurvey: false,
  isWorking: false,
  maxRows: 10,
  bodyColumns: 80,
  scroll: { offset: 0, bodyRows: 10 },
  view: {},
}

const FORECAST = JSON.stringify({
  classification: { task_type: 'bugfix' },
  context: { mode: 'new chat', tokens: 60000, note: 'built-in assumption' },
  estimates: [
    {
      total: { low: 100000, median: 400000, high: 1500000 },
      level: 'prior',
      group: 'all turns',
      n: 0,
      limit_pct: null,
    },
  ],
  new_chat: null,
  limit_window: '5h',
  limit_readings: 0,
  weekly_pct: null,
  weekly_readings: 0,
})

const LIMITS: RateLimit[] = [
  { kind: 'five_hour', percentUsed: 23.5, resetsAt: '2026-10-15T14:00:00Z' },
  { kind: 'seven_day', percentUsed: 41, resetsAt: '2026-10-20T09:00:00Z' },
]

type Answer = { exitCode: number; stdout: string; stderr: string }
type Session = { contextTokens?: number; limits?: RateLimit[] }

// The test's hooks stand in for the engine: the prompt box holds `draft`, the
// session has the given context and usage windows, and every command run is
// recorded and answered with `answer`.
function engine(on: On, draft: string, answer: Answer, session: Session = {}) {
  const runs: Array<{ argv: readonly string[]; init?: ProcessRunInit }> = []
  on('prompt.read', () => ({ value: { text: draft, cursor: draft.length } }))
  on('session.model', () => ({ value: 'claude-opus-5-5' }))
  on('session.id', () => ({ value: 'sess-1' }))
  on('session.usage', () => ({
    value: {
      startedAt: 0,
      context: { tokens: session.contextTokens, window: 200_000 },
      rateLimits: session.limits ?? [],
    },
  }))
  on('process.run', (_$, e) => {
    runs.push(e)
    return { value: { ...answer, isStdoutTruncated: false, isStderrTruncated: false } }
  })
  return runs
}

const OK: Answer = { exitCode: 0, stdout: FORECAST, stderr: '' }
const commands = (runs: Array<{ argv: readonly string[] }>) => runs.map(r => r.argv[1])

async function band($: Engine, surface: 'terminal' | 'desktop' = 'terminal') {
  return $.ui.mount({ plugin: 'tokcast-buddy', surface, component: 'AbovePrompt', props: PROPS })
}

for (const surface of ['terminal', 'desktop'] as const) {
  test(`${surface}: a click predicts the draft and shows the basis`, async ($, on) => {
    const runs = engine(on, 'fix the crash in the parser', OK)
    const ui = await band($, surface)

    await ui.press({ key: 'estimate' })

    expect(runs).toHaveLength(1) // no usage windows: nothing to record
    expect(runs[0]?.argv).toEqual(['tokcast', 'predict', '-', '--json', '--no-compare', '--model', 'opus'])
    expect(runs[0]?.init?.stdin).toBe('fix the crash in the parser')
    expect(await ui.find({ type: 'Text', text: /~400k tokens/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /built-in assumption/ })).toBeDefined()
  })
}

test('a click records the live readings first and shows the % used now', async ($, on) => {
  const runs = engine(on, 'hello', OK, { limits: LIMITS })
  const ui = await band($)

  await ui.press({ key: 'estimate' })

  expect(commands(runs)).toEqual(['statusline', 'predict'])
  expect(JSON.parse(runs[0]?.init?.stdin ?? '')).toEqual({
    session_id: 'sess-1',
    rate_limits: {
      five_hour: { used_percentage: 23.5, resets_at: Date.parse('2026-10-15T14:00:00Z') / 1000 },
      seven_day: { used_percentage: 41, resets_at: Date.parse('2026-10-20T09:00:00Z') / 1000 },
    },
  })
  expect(await ui.find({ type: 'Text', text: /5h limit: 24% used now/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /weekly limit: 41% used now/ })).toBeDefined()
})

test('after a turn, a reading is saved and the logs are ingested', async ($, on) => {
  const clock = mock.clock(on)
  const runs = engine(on, '', OK, { limits: LIMITS })
  on('turn.complete', () => ({ text: 'done' }))

  await $.turn.complete({ turnId: 't1', answer: 'done', durationMs: 5, isAborted: false, reason: 'answer' })
  await clock.advance(0)

  expect(commands(runs)).toEqual(['statusline', 'ingest'])
})

// Auto-ingest is off, or TOKCAST_HOME points at another database (e.g. synthetic).
const NO_INGEST: PluginOptions[] = [{ autoIngest: false }, { tokcastHome: '/demo/db' }]
for (const options of NO_INGEST) {
  test(`no ingest with ${JSON.stringify(options)}`, { options }, async ($, on) => {
    const clock = mock.clock(on)
    const runs = engine(on, '', OK, { limits: LIMITS })
    on('turn.complete', () => ({ text: 'done' }))

    await $.turn.complete({ turnId: 't1', answer: 'done', durationMs: 5, isAborted: false, reason: 'answer' })
    await clock.advance(0)

    expect(commands(runs)).toEqual(['statusline'])
  })
}

test('an empty draft asks for a prompt instead of running tokcast', async ($, on) => {
  const runs = engine(on, '   ', OK)
  const ui = await band($)

  await ui.press({ key: 'estimate' })

  expect(runs).toHaveLength(0)
  expect(await ui.find({ type: 'Text', text: /Type a prompt first/ })).toBeDefined()
})

test('a failing tokcast shows its error line', async ($, on) => {
  engine(on, 'hello', { exitCode: 1, stdout: '', stderr: 'Error: database is locked\ntrace...' })
  const ui = await band($)

  await ui.press({ key: 'estimate' })

  expect(await ui.find({ type: 'Text', text: /tokcast failed: Error: database is locked/ })).toBeDefined()
})

test(
  'the command and TOKCAST_HOME options are used',
  { options: { command: 'uv run --project /x tokcast', tokcastHome: '/demo/db' } },
  async ($, on) => {
    const runs = engine(on, 'hello', OK)
    const ui = await band($)

    await ui.press({ key: 'estimate' })

    expect(runs[0]?.argv.slice(0, 5)).toEqual(['uv', 'run', '--project', '/x', 'tokcast'])
    expect(runs[0]?.init?.env).toEqual({ TOKCAST_HOME: '/demo/db' })
  },
)

test('dismiss clears the bubble', async ($, on) => {
  engine(on, 'hello', OK)
  const ui = await band($)

  await ui.press({ key: 'estimate' })
  await ui.press({ key: 'dismiss' })

  expect(await ui.find({ type: 'Text', text: /400k/ })).toBeUndefined()
})

test('a live conversation passes its context size', async ($, on) => {
  const runs = engine(on, 'and now the tests', OK, { contextTokens: 120_400 })
  const ui = await band($)

  await ui.press({ key: 'estimate' })

  expect(runs[0]?.argv).toContain('--context')
  expect(runs[0]?.argv).toContain('120400')
})

test("the main loop's effort is remembered for the next estimate", async ($, on) => {
  const runs = engine(on, 'hello', OK, { contextTokens: 50_000 })
  on('turn.step', async function* (_$, e) {
    return { turnId: e.turnId, index: e.index, answer: 'ok', toolUses: [], stopReason: 'end_turn', usage: null }
  })
  const ui = await band($)

  // A subagent's request must not count; the main loop's must.
  for await (const _ of $.turn.step({ turnId: 't', index: 0, model: 'haiku', effort: 'low', messageCount: 1, agentId: 'a1' })) {
  }
  for await (const _ of $.turn.step({ turnId: 't', index: 1, model: 'opus', effort: 'high', messageCount: 1 })) {
  }
  await ui.press({ key: 'estimate' })

  expect(runs[0]?.argv.slice(-2)).toEqual(['--effort', 'high'])
})

// Stands in for Claude Code's own drawing of the band (here, its survey box).
function surveyBelow(on: On) {
  on('ui.render', { component: 'AbovePrompt' }, ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>How is Claude doing this session?</Text>
  })
}

test("stays under Claude Code's survey box instead of disappearing", async ($, on) => {
  engine(on, 'hello', OK)
  surveyBelow(on)
  const ui = await $.ui.mount({
    plugin: 'tokcast-buddy',
    surface: 'desktop',
    component: 'AbovePrompt',
    props: { ...PROPS, hasSurvey: true },
  })

  expect(await ui.find({ type: 'Text', text: /How is Claude doing/ })).toBeDefined() // kept whole
  expect(await ui.find({ key: 'estimate' })).toBeDefined() // and still there
})

// Stands in for Claude Code's store (kept across sessions): returns what was saved.
function store(on: On, initial: Record<string, unknown> = {}) {
  const saved = new Map(Object.entries(initial))
  on('store.get', (_$, e) => ({ value: saved.get(e.key) }))
  on('store.set', (_$, e) => {
    saved.set(e.key, e.value)
    return { value: undefined }
  })
  return saved
}

test('hide shrinks it to the face, and the face opens it again', async ($, on) => {
  engine(on, 'hello', OK)
  const saved = store(on)
  const ui = await band($)

  await ui.press({ key: 'hide' })
  expect(await ui.find({ key: 'estimate' })).toBeUndefined()
  expect((await ui.find({ key: 'open' }))?.text).toMatch(/tokcast/)

  expect(saved.get('view')).toBe('mini')

  await ui.press({ key: 'open' })
  expect(await ui.find({ key: 'estimate' })).toBeDefined()
  expect(saved.get('view')).toBe('full')
})

test('a new session starts with the last choice', async ($, on) => {
  engine(on, 'hello', OK)
  store(on, { view: 'mini' })
  on('session.start', (_$, e) => ({ cwd: e.cwd }))

  await $.session.start({ cwd: '/x', surface: 'desktop', isInteractive: true })
  const ui = await band($)

  expect(await ui.find({ key: 'open' })).toBeDefined()
  expect(await ui.find({ key: 'estimate' })).toBeUndefined()
})

test('an unknown saved choice (e.g. the removed "off") falls back to the full character', async ($, on) => {
  engine(on, 'hello', OK)
  store(on, { view: 'off' })
  on('session.start', (_$, e) => ({ cwd: e.cwd }))

  await $.session.start({ cwd: '/x', surface: 'desktop', isInteractive: true })
  const ui = await band($)

  expect(await ui.find({ key: 'estimate' })).toBeDefined()
})

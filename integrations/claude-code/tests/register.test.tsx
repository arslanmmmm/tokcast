import { expect, test } from 'claude-code/testing'
import type { On, ProcessRunInit } from 'claude-code'

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
  context: { mode: 'new chat', note: 'built-in assumption' },
  estimates: [
    {
      total: { low: 100000, median: 400000, high: 1500000 },
      level: 'prior',
      group: 'all turns',
      n: 0,
      limit_pct: null,
    },
  ],
  limit_window: '5h',
  limit_readings: 0,
})

// The test's hooks stand in for the engine: the prompt box holds `draft`, and
// every command run is recorded and answered with `answer`.
function engine(on: On, draft: string, answer: { exitCode: number; stdout: string; stderr: string }) {
  const runs: Array<{ argv: readonly string[]; init?: ProcessRunInit }> = []
  on('prompt.read', () => ({ value: { text: draft, cursor: draft.length } }))
  on('process.run', (_$, e) => {
    runs.push(e)
    return { value: { ...answer, isStdoutTruncated: false, isStderrTruncated: false } }
  })
  return runs
}

for (const surface of ['terminal', 'desktop'] as const) {
  test(`${surface}: a click predicts the draft and shows the basis`, async ($, on) => {
    const runs = engine(on, 'fix the crash in the parser', { exitCode: 0, stdout: FORECAST, stderr: '' })
    const ui = await $.ui.mount({ plugin: 'tokcast-buddy', surface, component: 'AbovePrompt', props: PROPS })

    await ui.press({ key: 'estimate' })

    expect(runs).toHaveLength(1)
    expect(runs[0]?.argv).toEqual(['tokcast', 'predict', '-', '--json', '--no-compare'])
    expect(runs[0]?.init?.stdin).toBe('fix the crash in the parser')
    expect(await ui.find({ type: 'Text', text: /~400k tokens/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /built-in assumption/ })).toBeDefined()
  })
}

test('an empty draft asks for a prompt instead of running tokcast', async ($, on) => {
  const runs = engine(on, '   ', { exitCode: 0, stdout: FORECAST, stderr: '' })
  const ui = await $.ui.mount({ plugin: 'tokcast-buddy', surface: 'terminal', component: 'AbovePrompt', props: PROPS })

  await ui.press({ key: 'estimate' })

  expect(runs).toHaveLength(0)
  expect(await ui.find({ type: 'Text', text: /Type a prompt first/ })).toBeDefined()
})

test('a failing tokcast shows its error line', async ($, on) => {
  engine(on, 'hello', { exitCode: 1, stdout: '', stderr: 'Error: database is locked\ntrace...' })
  const ui = await $.ui.mount({ plugin: 'tokcast-buddy', surface: 'terminal', component: 'AbovePrompt', props: PROPS })

  await ui.press({ key: 'estimate' })

  expect(await ui.find({ type: 'Text', text: /tokcast failed: Error: database is locked/ })).toBeDefined()
})

test(
  'the command and TOKCAST_HOME options are used',
  { options: { command: 'uv run --project /x tokcast', tokcastHome: '/demo/db' } },
  async ($, on) => {
    const runs = engine(on, 'hello', { exitCode: 0, stdout: FORECAST, stderr: '' })
    const ui = await $.ui.mount({ plugin: 'tokcast-buddy', surface: 'terminal', component: 'AbovePrompt', props: PROPS })

    await ui.press({ key: 'estimate' })

    expect(runs[0]?.argv.slice(0, 4)).toEqual(['uv', 'run', '--project', '/x'])
    expect(runs[0]?.init?.env).toEqual({ TOKCAST_HOME: '/demo/db' })
  },
)

test('dismiss clears the bubble', async ($, on) => {
  engine(on, 'hello', { exitCode: 0, stdout: FORECAST, stderr: '' })
  const ui = await $.ui.mount({ plugin: 'tokcast-buddy', surface: 'terminal', component: 'AbovePrompt', props: PROPS })

  await ui.press({ key: 'estimate' })
  await ui.press({ key: 'dismiss' })

  expect(await ui.find({ type: 'Text', text: /400k/ })).toBeUndefined()
})

import { describe, expect, test } from 'claude-code/testing'

import { firstLine, parse, summarize, tokens } from '../hooks/bubble'
import type { Forecast } from '../hooks/bubble'

// Shaped like real `tokcast predict --json` output on synthetic data.
function forecast(over: Partial<Forecast['estimates'][0]> = {}, readings = 0): Forecast {
  return {
    classification: { task_type: 'bugfix' },
    context: { mode: 'new chat', tokens: 60210, note: 'median of your 200 first turns' },
    estimates: [
      {
        total: { low: 183185, median: 552233, high: 2531723 },
        level: 'task',
        group: 'bugfix turns',
        n: 518,
        limit_pct: null,
        ...over,
      },
    ],
    new_chat: null,
    limit_window: '5h',
    limit_readings: readings,
    weekly_pct: null,
    weekly_readings: 0,
  }
}

describe('tokens', () => {
  test('rounds to k and M', () => {
    expect(tokens(950)).toBe('950')
    expect(tokens(552233)).toBe('552k')
    expect(tokens(2531723)).toBe('2.5M')
    expect(tokens(12_400_000)).toBe('12M')
  })
})

describe('summarize', () => {
  test('states the range, task type and basis', () => {
    const lines = summarize(forecast())
    expect(lines[0]).toBe('~552k tokens (183k–2.5M) for a bugfix turn')
    expect(lines[3]).toBe('basis: 518 of your bugfix turns · new chat: median of your 200 first turns')
  })

  test('shows what is used now while the limit is still being learned', () => {
    const [, fiveHour, weekly] = summarize(forecast({}, 1), { fiveHour: 23.5, sevenDay: 41 })
    expect(fiveHour).toBe('5h limit: 24% used now → this turn: learning your limit (1/3 readings)')
    expect(weekly).toBe('weekly limit: 41% used now → this turn: learning your limit (0/3 readings)')
  })

  test('shows what this turn adds once calibrated', () => {
    const f = { ...forecast({ limit_pct: [0.4, 2.6, 11.2] }), weekly_pct: [0.1, 0.5, 2] as [number, number, number] }
    const [, fiveHour, weekly] = summarize(f, { fiveHour: 23.5 })
    expect(fiveHour).toBe('5h limit: 24% used now → this turn ≈ +3% (0.4%–11%)')
    expect(weekly).toBe('weekly limit: this turn ≈ +0.5% (0.1%–2%)') // no live reading
  })

  test('an older tokcast without weekly fields still reads', () => {
    const { weekly_pct, weekly_readings, ...old } = forecast()
    expect(summarize(old as Forecast)[2]).toBe('weekly limit: this turn: learning your limit (0/3 readings)')
  })

  test('labels the built-in prior as an assumption', () => {
    expect(summarize(forecast({ level: 'prior', n: 0 }))[3]).toMatch(/^basis: built-in assumption/)
  })

  test('adds a tip when a new chat would be clearly cheaper', () => {
    const f = { ...forecast(), new_chat: { ...forecast().estimates[0]!, total: { low: 1, median: 300_000, high: 2 } } }
    expect(summarize(f)[4]).toBe('tip: in a new chat this would be ~300k tokens')
  })
})

describe('parse', () => {
  test('bad output becomes a message, not a crash', () => {
    expect(parse('not json')).toEqual({ lines: ["Couldn't read tokcast's output."], ok: false })
  })

  test('keeps the first non-empty line of an error', () => {
    expect(firstLine('\nNo conversation found.\nmore')).toBe('No conversation found.')
  })
})

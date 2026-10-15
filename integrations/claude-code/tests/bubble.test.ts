import { describe, expect, test } from 'claude-code/testing'

import { firstLine, parse, summarize, tokens } from '../hooks/bubble'
import type { Forecast } from '../hooks/bubble'

// Shaped like real `tokcast predict --json` output on synthetic data.
function forecast(over: Partial<Forecast['estimates'][0]> = {}, readings = 0): Forecast {
  return {
    classification: { task_type: 'bugfix' },
    context: { mode: 'new chat', note: 'median of your 200 first turns' },
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
    limit_window: '5h',
    limit_readings: readings,
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
    const [cost, , basis] = summarize(forecast())
    expect(cost).toBe('~552k tokens (183k–2.5M) for a bugfix turn')
    expect(basis).toBe('basis: 518 of your bugfix turns · new chat: median of your 200 first turns')
  })

  test('says when % of the limit is not calibrated yet', () => {
    expect(summarize(forecast({}, 1))[1]).toBe(
      '% of 5h limit: not calibrated yet (1/3 status-line readings)',
    )
  })

  test('shows % of the limit once calibrated', () => {
    expect(summarize(forecast({ limit_pct: [0.4, 2.6, 11.2] }))[1]).toBe(
      '≈ 3% of your 5h limit (0.4%–11%)',
    )
  })

  test('labels the built-in prior as an assumption', () => {
    expect(summarize(forecast({ level: 'prior', n: 0 }))[2]).toMatch(/^basis: built-in assumption/)
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

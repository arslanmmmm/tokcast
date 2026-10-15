import { describe, expect, test } from 'claude-code/testing'

import { predictArgs, statuslinePayload, usedNow } from '../hooks/args'

const BASE = ['tokcast', 'predict', '-', '--json', '--no-compare']

describe('predictArgs', () => {
  test('a fresh session with nothing known keeps the new-chat default', () => {
    expect(predictArgs(['tokcast'], {})).toEqual(BASE)
    expect(predictArgs(['tokcast'], { contextTokens: 0 })).toEqual(BASE)
  })

  test('passes the context size, model family and effort', () => {
    expect(
      predictArgs(['tokcast'], { contextTokens: 120400.6, model: 'claude-opus-5-5', effort: 'high' }),
    ).toEqual([...BASE, '--context', '120401', '--model', 'opus', '--effort', 'high'])
  })

  test("leaves out what tokcast wouldn't understand", () => {
    expect(predictArgs(['tokcast'], { model: 'some-other-model', effort: 'turbo' })).toEqual(BASE)
  })
})

describe('statuslinePayload', () => {
  test('keeps the 5h and weekly windows, with reset times in Unix seconds', () => {
    const json = statuslinePayload(
      [
        { kind: 'five_hour', percentUsed: 23.5, resetsAt: '2026-10-15T14:00:00Z' },
        { kind: 'spend_limit', percentUsed: 10, resetsAt: '2026-10-15T14:00:00Z' },
        { kind: 'seven_day', percentUsed: 41 }, // no reset time: can't be placed in a window
      ],
      's1',
    )
    expect(JSON.parse(json ?? '')).toEqual({
      session_id: 's1',
      rate_limits: { five_hour: { used_percentage: 23.5, resets_at: 1792072800 } },
    })
  })

  test('nothing to record gives null', () => {
    expect(statuslinePayload([], 's1')).toBeNull()
  })
})

describe('usedNow', () => {
  test('reads each window, absent when not reported', () => {
    expect(usedNow([{ kind: 'seven_day', percentUsed: 41 }])).toEqual({ fiveHour: undefined, sevenDay: 41 })
  })
})

import { describe, expect, test } from 'claude-code/testing'

import { predictArgs } from '../hooks/args'

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

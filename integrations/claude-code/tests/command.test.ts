import { describe, expect, test } from 'claude-code/testing'

import { isView, parseCommand } from '../hooks/command'

describe('parseCommand', () => {
  test('show, hide and off set the view; any case', () => {
    expect(parseCommand('show')).toEqual({ action: 'view', view: 'full' })
    expect(parseCommand(' HIDE ')).toEqual({ action: 'view', view: 'mini' })
    expect(parseCommand('off')).toEqual({ action: 'view', view: 'off' })
  })

  test('nothing or help asks for help', () => {
    expect(parseCommand('')).toEqual({ action: 'help' })
    expect(parseCommand('help')).toEqual({ action: 'help' })
  })

  test('anything else is a prompt to estimate, kept as typed', () => {
    expect(parseCommand('  hide the sidebar on mobile ')).toEqual({
      action: 'predict',
      text: 'hide the sidebar on mobile',
    })
  })
})

test('isView rejects values from other versions', () => {
  expect(isView('mini')).toBe(true)
  expect(isView('compact')).toBe(false)
  expect(isView(undefined)).toBe(false)
})

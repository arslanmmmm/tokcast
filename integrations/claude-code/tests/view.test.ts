import { expect, test } from 'claude-code/testing'

import { isView } from '../hooks/view'

test('isView accepts full and mini, and rejects values from other versions', () => {
  expect(isView('full')).toBe(true)
  expect(isView('mini')).toBe(true)
  expect(isView('off')).toBe(false) // the removed /tokcast off
  expect(isView(undefined)).toBe(false)
})

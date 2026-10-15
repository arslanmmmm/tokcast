// How the character shows above the prompt; the hide button switches between them.
import type { View } from '../types'

export type { View }

// A value saved by another version must not break the band.
export function isView(value: unknown): value is View {
  return value === 'full' || value === 'mini'
}

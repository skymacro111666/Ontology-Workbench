import { localName } from '../lib/localName'

/** Display name of a canvas card: rdfs:label first, curie local name as
 *  fallback. Shared by toG6Nodes (rendering) and the insertion layout
 *  (sizing) so the two can never drift apart. */
export function cardDisplayName(n: {
  label?: Record<string, string> | null
  curie: string
}): string {
  const human = Object.values(n.label ?? {})[0]
  return human ?? localName(n.curie)
}

/** Card width for a display name — the exact formula toG6Nodes renders
 *  with: ~6.6px per character plus padding, clamped to [72, 220]. */
export function cardWidth(name: string): number {
  return Math.min(220, Math.max(72, Math.round(name.length * 6.6 + 26)))
}

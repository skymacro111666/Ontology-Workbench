import type { Pt } from './layoutPositions'

/** Local insertion layout for progressive-canvas expands (spec §5.3).
 *
 * New children land in one row under their parent, centered on parent.x —
 * existing coordinates are never read for placement, only for collision:
 * while any would-be spot sits within `gap` of a node already on that row,
 * the whole row drops another rowHeight. Pure: returns only the kids' new
 * coordinates, leaving the caller's map untouched.
 */
export function insertChildren(
  parent: Pt,
  kids: string[],
  positions: Record<string, Pt>,
  rowHeight = 90,
  gap = 48,
): Record<string, Pt> {
  const out: Record<string, Pt> = {}
  if (kids.length === 0) return out
  const xs = kids.map((_, i) => parent.x - ((kids.length - 1) * gap) / 2 + i * gap)
  let y = parent.y + rowHeight
  const clashes = () =>
    Object.values(positions).some(
      (p) =>
        Math.abs(p.y - y) < rowHeight / 2 && // same row
        xs.some((x) => Math.abs(x - p.x) < gap), // too close horizontally
    )
  while (clashes()) y += rowHeight
  kids.forEach((id, i) => {
    out[id] = { x: xs[i], y }
  })
  return out
}

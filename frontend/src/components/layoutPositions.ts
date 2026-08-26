/** Saved-layout placement: fill in coordinates for nodes that have none.
 *
 *  When the canvas restores a saved layout (`layout: false` in G6), every
 *  visible node needs explicit x/y. Nodes saved earlier keep their spot;
 *  new ones (freshly created entities, newly revealed instances) are placed
 *  deterministically beside their first positioned neighbor — a new subclass
 *  lands right of its parent, a property right of its domain — and anything
 *  without an anchor goes into a fresh column past maxX. Pure math, no G6.
 */

export interface Pt {
  x: number
  y: number
}

export interface PosNode {
  id: string
}

export interface PosEdge {
  source: string
  target: string
}

/** Column offset from the anchor and vertical stacking step (px). */
const COL_GAP = 240
const ROW_STEP = 48

export function assignFallbackPositions(
  nodes: PosNode[],
  edges: PosEdge[],
  positions: Record<string, Pt>,
): Record<string, Pt> {
  const out: Record<string, Pt> = { ...positions }
  const neighbors = new Map<string, string[]>()
  for (const { source, target } of edges) {
    ;(neighbors.get(source) ?? neighbors.set(source, []).get(source)!).push(target)
    ;(neighbors.get(target) ?? neighbors.set(target, []).get(target)!).push(source)
  }
  // Next free y per column-x, seeded from nodes already sitting in it.
  const colCursor = new Map<number, number>()
  for (const p of Object.values(out)) {
    const startY = Math.ceil((p.y + ROW_STEP) / ROW_STEP) * ROW_STEP
    colCursor.set(p.x, Math.max(colCursor.get(p.x) ?? -Infinity, startY))
  }

  let pending = nodes.filter((nd) => !out[nd.id])
  let placed = true
  while (pending.length && placed) {
    placed = false
    const still: typeof pending = []
    for (const nd of pending) {
      const anchorId = (neighbors.get(nd.id) ?? []).find((m) => out[m])
      if (!anchorId) {
        still.push(nd)
        continue
      }
      const anchor = out[anchorId]
      const colX = anchor.x + COL_GAP
      const y = colCursor.get(colX) ?? anchor.y
      out[nd.id] = { x: colX, y }
      colCursor.set(colX, y + ROW_STEP)
      placed = true
    }
    pending = still
  }

  // No positioned neighbor anywhere: fresh column past maxX, stacked.
  if (pending.length) {
    const xs = Object.values(out).map((p) => p.x)
    const colX = (xs.length ? Math.max(...xs) : 0) + COL_GAP
    let y = colCursor.get(colX) ?? 0
    for (const nd of pending) {
      out[nd.id] = { x: colX, y }
      y += ROW_STEP
    }
  }
  return out
}

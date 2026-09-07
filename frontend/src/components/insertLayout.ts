import type { Pt } from './layoutPositions'

/** One expanded child: its id plus the width of the card the canvas will
 *  render for it (cardWidth in cardSize.ts). */
export interface InsertKid {
  id: string
  width: number
}

export interface InsertOptions {
  /** Parent → first row; matches the auto pipeline's ranksep. */
  rowSep?: number
  /** Gap between folded rows: card height 32 + the auto pipeline's rowGap 24. */
  lineGap?: number
  /** Horizontal gap between siblings in a row (nodesep). */
  sep?: number
  /** Rows wider than this fold into sub-rows (targetRowWidth). */
  maxRowWidth?: number
}

/** Local insertion layout for progressive-canvas expands (spec §5.3).
 *
 * New children land in rows under their parent sized by their REAL card
 * widths — a fixed center gap put wide cards on top of each other (user
 * report 2026-09-07: GO molecular_function's 33 children). Rows wider than
 * maxRowWidth fold into centered sub-rows, the same rhythm the auto
 * pipeline's rank-wrap uses; each row centers on parent.x. Existing
 * coordinates are never read for placement, only for collision: while any
 * would-be card sits on an occupied spot, the whole block drops another
 * lineGap. Pure: returns only the kids' new coordinates, leaving the
 * caller's map untouched.
 */
export function insertChildren(
  parent: Pt,
  kids: InsertKid[],
  positions: Record<string, Pt>,
  opts: InsertOptions = {},
): Record<string, Pt> {
  const { rowSep = 90, lineGap = 56, sep = 48, maxRowWidth = 1700 } = opts
  if (kids.length === 0) return {}

  // Greedy row packing in kid order (curie-sorted by the API): whole rows
  // fill up to maxRowWidth before folding.
  const rows: InsertKid[][] = [[]]
  let rowW = 0
  for (const kid of kids) {
    const row = rows.at(-1)!
    if (row.length && rowW + sep + kid.width > maxRowWidth) {
      rows.push([kid])
      rowW = kid.width
    } else {
      rowW = row.length ? rowW + sep + kid.width : kid.width
      row.push(kid)
    }
  }

  // Row layout: width-swept and centered on parent.x. Positions are card
  // CENTERS (G6's x/y), so each card sits at left-edge + width/2.
  const placed = rows.map((row) => {
    const width = row.reduce((m, k) => m + k.width, 0) + (row.length - 1) * sep
    let left = parent.x - width / 2
    return row.map((k) => {
      const c = { id: k.id, x: left + k.width / 2, w: k.width }
      left += k.width + sep
      return c
    })
  })

  // Collision against existing cards: same landing band (card height 32)
  // and horizontally within this card's half-width plus a nominal 36px for
  // the other card (positions carry centers only, not widths). While any
  // row of the block clashes, drop the whole block one line.
  const clash = (topY: number) =>
    placed.some((row, i) => {
      const y = topY + i * lineGap
      return row.some((c) =>
        Object.values(positions).some(
          (p) => Math.abs(p.y - y) < 32 && Math.abs(p.x - c.x) < c.w / 2 + 36,
        ),
      )
    })
  let topY = parent.y + rowSep
  while (clash(topY)) topY += lineGap

  const out: Record<string, Pt> = {}
  placed.forEach((row, i) => {
    const y = topY + i * lineGap
    for (const c of row) out[c.id] = { x: c.x, y }
  })
  return out
}

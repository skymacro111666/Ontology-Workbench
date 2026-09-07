import { describe, expect, it } from 'vitest'
import { insertChildren } from './insertLayout'
import { cardWidth } from './cardSize'
import type { Pt } from './layoutPositions'

/* Width-aware insertion layout for progressive expands: kids land in rows
   under their parent sized by their real card widths (no overlap), rows
   fold past maxRowWidth, each row centers under the parent, and a busy
   landing zone pushes the whole block down. Existing coordinates are never
   touched. */

describe('insertChildren', () => {
  const P: Pt = { x: 100, y: 0 }

  it('spaces kids by card width, centered under the parent', () => {
    const out = insertChildren(
      P,
      [
        { id: 'a', width: 72 },
        { id: 'b', width: 100 },
        { id: 'c', width: 72 },
      ],
      {},
    )
    expect(Object.keys(out)).toEqual(['a', 'b', 'c'])
    // Row width 72+48+100+48+72 = 340 → left edge 100−170 = −70 (centers).
    expect(out.a).toEqual({ x: -34, y: 90 }) // −70 + 72/2
    expect(out.b).toEqual({ x: 100, y: 90 }) // −70+72+48+50
    expect(out.c).toEqual({ x: 234, y: 90 }) // −70+72+48+100+48+36
  })

  it('single kid lands directly below the parent', () => {
    const out = insertChildren(P, [{ id: 'only', width: 72 }], {})
    expect(out.only).toEqual({ x: 100, y: 90 })
  })

  it('folds an over-wide row into centered sub-rows', () => {
    const out = insertChildren(
      P,
      [
        { id: 'a', width: 100 },
        { id: 'b', width: 100 },
        { id: 'c', width: 100 },
      ],
      {},
      { sep: 20, maxRowWidth: 240 },
    )
    // 100 +20+100 = 220 fits; adding c (340) would overflow → second row.
    expect(out.a).toEqual({ x: 40, y: 90 }) // left edge 100−110, +50 center
    expect(out.b).toEqual({ x: 160, y: 90 })
    expect(out.c).toEqual({ x: 100, y: 90 + 56 }) // own centered row below
  })

  it('drops below an occupied landing row instead of overlapping', () => {
    // A sibling already sits at the natural landing spot (parent.x, y=90).
    const out = insertChildren(
      P,
      [
        { id: 'a', width: 72 },
        { id: 'b', width: 72 },
      ],
      { sib: { x: 100, y: 90 } },
    )
    expect(out.a.y).toBe(90 + 56)
    expect(out.b.y).toBe(90 + 56)
    // Still centered: a and b straddle parent.x symmetrically.
    expect(out.a.x + 60).toBe(out.b.x - 60)
    // Existing coordinates stay untouched.
    expect(out.sib).toBeUndefined()
  })

  it('stays on the landing row when the occupant is far enough away', () => {
    const out = insertChildren(P, [{ id: 'a', width: 72 }], { far: { x: 400, y: 90 } })
    expect(out.a).toEqual({ x: 100, y: 90 })
  })

  it('empty kids list returns an empty map', () => {
    expect(insertChildren(P, [], { a: { x: 1, y: 1 } })).toEqual({})
  })
})

describe('cardWidth', () => {
  it('matches the formula toG6Nodes renders with', () => {
    expect(cardWidth('binding')).toBe(72) // 7 chars → clamped to min
    expect(cardWidth('catalytic activity')).toBe(145) // 18 × 6.6 + 26
    expect(cardWidth('molecular transducer activity')).toBe(217) // 29 chars
    expect(cardWidth('transmembrane signaling receptor activity')).toBe(220) // capped
  })
})

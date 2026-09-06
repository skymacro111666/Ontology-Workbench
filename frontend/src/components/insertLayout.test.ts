import { describe, expect, it } from 'vitest'
import { insertChildren } from './insertLayout'
import type { Pt } from './layoutPositions'

/* Task 16 (progressive canvas): expanded children land in one row under
   their parent without touching existing coordinates; a busy row pushes
   them down another rowHeight instead of overlapping. */

describe('insertChildren', () => {
  const P: Pt = { x: 100, y: 0 }

  it('lays kids out centered under the parent on the next row', () => {
    const out = insertChildren(P, ['a', 'b', 'c'], {})
    expect(Object.keys(out)).toEqual(['a', 'b', 'c'])
    // One row at parent.y + rowHeight, x spread by gap around parent.x.
    expect(out.a).toEqual({ x: 52, y: 90 })
    expect(out.b).toEqual({ x: 100, y: 90 })
    expect(out.c).toEqual({ x: 148, y: 90 })
  })

  it('single kid lands directly below the parent', () => {
    const out = insertChildren(P, ['only'], {})
    expect(out.only).toEqual({ x: 100, y: 90 })
  })

  it('drops to the following row when the target row is occupied', () => {
    // A sibling already sits at the natural landing spot (parent.x, y=90).
    const out = insertChildren(P, ['a', 'b'], { sib: { x: 100, y: 90 } })
    expect(out.a).toEqual({ x: 76, y: 180 })
    expect(out.b).toEqual({ x: 124, y: 180 })
    // Existing coordinates stay untouched.
    expect(out.sib).toBeUndefined()
  })

  it('stays on the target row when the occupant is far enough away', () => {
    const out = insertChildren(P, ['a'], { far: { x: 400, y: 90 } })
    expect(out.a).toEqual({ x: 100, y: 90 })
  })

  it('empty kids list returns an empty map', () => {
    expect(insertChildren(P, [], { a: { x: 1, y: 1 } })).toEqual({})
  })
})

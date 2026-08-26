import { describe, expect, it } from 'vitest'
import { assignFallbackPositions, type Pt } from './layoutPositions'

/* Pure placement math for the saved-layout canvas: nodes without a saved
   position are placed deterministically next to their first positioned
   neighbor (new subclasses/properties/instances land beside their anchor),
   leftovers in a fresh column past maxX. */

const n = (id: string) => ({ id, kind: 'class' as const, curie: id, label: {} })
const e = (source: string, target: string) => ({ source, target, kind: 'subClassOf' })

describe('assignFallbackPositions', () => {
  it('keeps existing positions untouched', () => {
    const pos: Record<string, Pt> = { a: { x: 10, y: 20 } }
    const out = assignFallbackPositions([n('a')], [], pos)
    expect(out.a).toEqual({ x: 10, y: 20 })
    expect(Object.keys(out)).toEqual(['a'])
  })

  it('places a new node beside its positioned neighbor (anchor + 240px)', () => {
    const out = assignFallbackPositions(
      [n('parent'), n('child')],
      [e('child', 'parent')],
      { parent: { x: 100, y: 50 } },
    )
    expect(out.child).toEqual({ x: 340, y: 50 })
  })

  it('stacks several new nodes sharing one anchor 48px apart', () => {
    const out = assignFallbackPositions(
      [n('parent'), n('c1'), n('c2')],
      [e('c1', 'parent'), e('c2', 'parent')],
      { parent: { x: 0, y: 0 } },
    )
    expect(out.c1).toEqual({ x: 240, y: 0 })
    expect(out.c2).toEqual({ x: 240, y: 48 })
  })

  it('resolves chains iteratively (grandchild via the newly placed child)', () => {
    const out = assignFallbackPositions(
      [n('a'), n('b'), n('c')],
      [e('b', 'a'), e('c', 'b')],
      { a: { x: 0, y: 0 } },
    )
    expect(out.b).toEqual({ x: 240, y: 0 })
    expect(out.c).toEqual({ x: 480, y: 0 })
  })

  it('drops anchor-less nodes into a fresh column past maxX', () => {
    const out = assignFallbackPositions(
      [n('a'), n('orphan'), n('island')],
      [],
      { a: { x: 100, y: 0 } },
    )
    expect(out.orphan).toEqual({ x: 340, y: 0 })
    expect(out.island).toEqual({ x: 340, y: 48 })
  })
})

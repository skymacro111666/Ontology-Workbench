import { describe, expect, it } from 'vitest'
import { ROW_HEIGHT, wrapRanks, type WrapEdge, type WrapNode } from './wrapRanks'

/* wrapRanks is the pure second stage of the overview layout pipeline: dagre
   has already assigned rank (y) and a parent-centered order (x). This pass
   keeps each fitting rank exactly where dagre put it (only widening where
   effective node widths would overlap) and folds over-wide ranks into
   centered sub-rows that never interleave sibling groups, so the first-load
   canvas reads as a tidy centered tree instead of flush-left shelves. */

const OPTS = { rowGap: 14, rankGap: 90, nodesep: 16, targetRowWidth: 400 }
const pos = (nodes: WrapNode[], edges: WrapEdge[] = []) =>
  new Map(wrapRanks(nodes, edges, OPTS).map((n) => [n.id, n.style]))

/** A rank-0 row of same-width nodes, dagre-ordered left to right. */
function row(ids: string[], y: number, w = 100): WrapNode[] {
  return ids.map((id, i) => ({
    id,
    style: { x: i * 200, y, size: [w, ROW_HEIGHT] },
    data: { kind: 'class' },
  }))
}

const classNode = (id: string, x: number, y: number, w = 100): WrapNode => ({
  id,
  style: { x, y, size: [w, ROW_HEIGHT] },
  data: { kind: 'class' },
})

describe('wrapRanks', () => {
  it('preserves dagre x for a rank that fits the width budget', () => {
    const p = pos(row(['a', 'b'], 0))
    // dagre put b at x=200 (parent-centered above its own children); the
    // fitting rank keeps that spot instead of being repacked from x=0.
    expect(p.get('a')).toMatchObject({ x: 0, y: 0 })
    expect(p.get('b')).toMatchObject({ x: 200, y: 0 })
  })

  it('only widens dagre x when effective node widths would overlap', () => {
    const p = pos([classNode('a', 0, 0), classNode('b', 60, 0)])
    // dagre gap 60 < width 100 + nodesep 16: b is pushed to a's edge + gap.
    expect(p.get('b')!.x).toBeGreaterThanOrEqual(p.get('a')!.x + 100 + 16)
  })

  it('wraps an over-wide rank into centered sub-rows', () => {
    const p = pos(row(['a', 'b', 'c', 'd'], 0))
    // Dagre extent 0..700 > 400 → fold. No edges → singleton groups;
    // a+b+c (100+16+100+16+100 = 332 ≤ 400) on row 1, d alone on row 2.
    // Axis = median node center (50,250,450,650 → 350); each row centers
    // on it: row 1 starts at 350 − 332/2 = 184, row 2 at 350 − 100/2 = 300.
    expect(p.get('a')).toMatchObject({ x: 184, y: 0 })
    expect(p.get('b')).toMatchObject({ x: 300, y: 0 })
    expect(p.get('c')).toMatchObject({ x: 416, y: 0 })
    expect(p.get('d')).toMatchObject({ x: 300, y: ROW_HEIGHT + 14 })
  })

  it('keeps a sibling group on one sub-row when a wide rank folds', () => {
    const root = classNode('root', 300, 0)
    const kids = ['c1', 'c2', 'c3'].map((id, i) => classNode(id, i * 200, 90))
    const stranger = classNode('other', 900, 90)
    // All c* hang under root; other is unanchored (no edge). The group
    // (3×100 + 2×16 = 332 ≤ 400) stays whole on one row; the anchorless
    // node cannot interleave into the middle of it.
    const edges: WrapEdge[] = kids.map((k) => ({ source: 'root', target: k.id }))
    const p = pos([root, ...kids, stranger], edges)
    const ys = kids.map((k) => p.get(k.id)!.y)
    expect(new Set(ys).size).toBe(1)
    expect(p.get('other')!.y).not.toBe(ys[0])
  })

  it('splits an over-wide sibling group into contiguous chunks, never interleaving', () => {
    const root = classNode('root', 300, 0)
    const kids = ['c1', 'c2', 'c3', 'c4'].map((id, i) => classNode(id, i * 200, 90))
    const stranger = classNode('other', 900, 90)
    const edges: WrapEdge[] = kids.map((k) => ({ source: 'root', target: k.id }))
    const p = pos([root, ...kids, stranger], edges)
    // Group width 4×100 + 3×16 = 448 > 400: it splits after c3 (332).
    // c1–c3 share a row; c4 follows on the next row, other may join it.
    expect(p.get('c1')!.y).toBe(p.get('c2')!.y)
    expect(p.get('c2')!.y).toBe(p.get('c3')!.y)
    expect(p.get('c4')!.y).toBe(p.get('other')!.y)
    expect(p.get('c4')!.y).not.toBe(p.get('c1')!.y)
  })

  it('centers folded rows under their anchors, not flush left', () => {
    const root = classNode('root', 600, 0)
    const kids = ['c1', 'c2', 'c3'].map((id, i) => classNode(id, i * 200, 90))
    const edges: WrapEdge[] = kids.map((k) => ({ source: 'root', target: k.id }))
    const p = pos([root, ...kids], edges)
    // Axis = the anchor's placed center (root spans 600..700 → 650).
    // The folded group row (332 wide) centers on 650 → spans 484..816.
    const xs = kids.map((k) => p.get(k.id)!.x)
    const rowCenter = (xs[0] + xs[2] + 100) / 2
    expect(rowCenter).toBeCloseTo(650, 5)
    expect(xs[0]).toBeCloseTo(484, 5)
  })

  it('groups a multi-parent child with its nearest parent', () => {
    const p1 = classNode('p1', 0, 0)
    const p2 = classNode('p2', 1200, 0)
    const near = ['a', 'b'].map((id, i) => classNode(id, i * 200, 90))
    const m = classNode('m', 260, 90)
    const far = classNode('z', 1000, 90)
    const edges: WrapEdge[] = [
      ...near.map((n) => ({ source: 'p1', target: n.id })),
      { source: 'p1', target: 'm' },
      { source: 'p2', target: 'm' }, // multi-parent: m also hangs off p2
      { source: 'p2', target: 'z' },
    ]
    const p = pos([p1, p2, ...near, m, far], edges)
    // m's dagre x (260) sits near p1's children → same group, same row as a/b.
    expect(p.get('m')!.y).toBe(p.get('a')!.y)
    expect(p.get('z')!.y).not.toBe(p.get('a')!.y)
  })

  it('stacks ranks below each other accounting for each rank\'s folded height', () => {
    const p = pos([...row(['a', 'b', 'c', 'd'], 0), ...row(['e'], 90)])
    // Rank 0 folded to 2 rows: rank 1 starts after 2×(32+14) + 90.
    expect(p.get('e')).toMatchObject({ y: 2 * (ROW_HEIGHT + 14) + 90 })
  })

  it('clusters near-equal y into one rank and keeps dagre order', () => {
    const nodes: WrapNode[] = [classNode('late', 400, 0.4), classNode('early', 0, 0)]
    const p = pos(nodes)
    // Same rank (y within 1px); the swept order still reflects dagre x.
    expect(p.get('early')!.x).toBeLessThan(p.get('late')!.x)
  })

  it('never overlaps: every row keeps nodes at least width + nodesep apart', () => {
    const ids = Array.from({ length: 12 }, (_, i) => `n${i}`)
    const nodes = [...row(ids, 0, 120), ...row(['root'], 90, 80)]
    const placed = wrapRanks(nodes, [], { ...OPTS, targetRowWidth: 300 })
    const byId = new Map(nodes.map((n) => [n.id, n]))
    // Group by y and check horizontal separation inside each group.
    const rows = new Map<number, string[]>()
    for (const n of placed) {
      const y = n.style.y
      const key = [...rows.keys()].find((k) => Math.abs(k - y) < 0.5) ?? y
      rows.set(key, [...(rows.get(key) ?? []), n.id])
    }
    for (const idsOfRow of rows.values()) {
      const xs = idsOfRow.map((id) => placed.find((n) => n.id === id)!.style.x)
      const ws = idsOfRow.map((id) => (byId.get(id)!.style!.size as [number, number])[0])
      for (let i = 1; i < xs.length; i++) expect(xs[i]).toBeGreaterThanOrEqual(xs[i - 1] + ws[i - 1] + OPTS.nodesep)
    }
  })

  it('reserves label room for instance nodes (small circles carry side labels)', () => {
    const nodes: WrapNode[] = [
      { id: 'i1', style: { x: 0, y: 0, size: 12 }, data: { kind: 'instance' } },
      { id: 'i2', style: { x: 100, y: 0, size: 12 }, data: { kind: 'instance' } },
    ]
    const p = pos(nodes)
    // i2 starts beyond i1's circle plus its right-side label allowance.
    expect(p.get('i2')!.x).toBeGreaterThanOrEqual(p.get('i1')!.x + 100)
  })
})

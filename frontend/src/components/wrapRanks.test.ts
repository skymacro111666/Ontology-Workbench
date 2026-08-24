import { describe, expect, it } from 'vitest'
import { ROW_HEIGHT, wrapRanks, type WrapNode } from './wrapRanks'

/* wrapRanks is the pure second stage of the overview layout pipeline: dagre
   has already assigned rank (y) and order (x); this pass re-places each
   rank's nodes in wrapped sub-rows so width scales with the widest ROW,
   not the widest rank (a 54-node rank no longer spans ~9,800px). */

const OPTS = { rowGap: 14, rankGap: 90, nodesep: 16, targetRowWidth: 400 }
const pos = (nodes: WrapNode[]) =>
  new Map(wrapRanks(nodes, OPTS).map((n) => [n.id, n.style]))

/** A rank-0 row of same-width nodes, dagre-ordered left to right. */
function row(ids: string[], y: number, w = 100): WrapNode[] {
  return ids.map((id, i) => ({
    id,
    style: { x: i * 200, y, size: [w, ROW_HEIGHT] },
    data: { kind: 'class' },
  }))
}

describe('wrapRanks', () => {
  it('keeps a rank that already fits on one unchanged row (x packed, y kept)', () => {
    const p = pos(row(['a', 'b'], 0))
    // Two 100px nodes + 16px gap fit 400px: one row, packed left to right.
    expect(p.get('a')).toMatchObject({ x: 0, y: 0 })
    expect(p.get('b')).toMatchObject({ x: 116, y: 0 })
  })

  it('wraps an over-wide rank into staggered sub-rows', () => {
    const p = pos(row(['a', 'b', 'c', 'd'], 0))
    // 4 × 100px + gaps = 348+... a+b+c = 100+16+100+16+100 = 332 ≤ 400, d overflows.
    expect(p.get('a')).toMatchObject({ x: 0, y: 0 })
    expect(p.get('b')).toMatchObject({ x: 116, y: 0 })
    expect(p.get('c')).toMatchObject({ x: 232, y: 0 })
    // Second sub-row drops by one row step, x restarts.
    expect(p.get('d')).toMatchObject({ x: 0, y: ROW_HEIGHT + 14 })
  })

  it('stacks ranks below each other accounting for each rank\'s wrapped height', () => {
    const p = pos([...row(['a', 'b', 'c', 'd'], 0), ...row(['e'], 90)])
    // Rank 0 wrapped to 2 rows: rank 1 starts after 2×(32+14) + 90.
    expect(p.get('e')).toMatchObject({ x: 0, y: 2 * (ROW_HEIGHT + 14) + 90 })
  })

  it('clusters near-equal y into one rank and orders rows by dagre x', () => {
    const nodes: WrapNode[] = [
      { id: 'late', style: { x: 400, y: 0.4, size: [100, ROW_HEIGHT] }, data: { kind: 'class' } },
      { id: 'early', style: { x: 0, y: 0, size: [100, ROW_HEIGHT] }, data: { kind: 'class' } },
    ]
    const p = pos(nodes)
    // Same rank (y within 1px): dagre order by x puts early first.
    expect(p.get('early')).toMatchObject({ x: 0 })
    expect(p.get('late')).toMatchObject({ x: 116 })
  })

  it('never overlaps: every row keeps nodes at least width + nodesep apart', () => {
    const ids = Array.from({ length: 12 }, (_, i) => `n${i}`)
    const nodes = [...row(ids, 0, 120), ...row(['root'], 90, 80)]
    const placed = wrapRanks(nodes, { ...OPTS, targetRowWidth: 300 })
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

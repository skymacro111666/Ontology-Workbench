import { describe, expect, it } from 'vitest'
import { FAST_LAYOUT_NODES, linearTreePositions } from './linearTree'
import { ROW_HEIGHT, wrapRanks, widthOf } from './wrapRanks'

/* The O(V) stand-in for dagre on oversized auto layouts: depth gives the
   rank, DFS leaf order the x, and the shared wrapRanks pass folds. These
   tests pin the guarantees the GraphView integration relies on. */

const node = (id: string) => ({ id })
const edge = (source: string, target: string) => ({ source, target })

describe('linearTreePositions', () => {
  it('places every node of a 3-level tree exactly once, parents above children', () => {
    const nodes = [node('root'), node('m1'), node('m2'), node('m3'),
      ...Array.from({ length: 9 }, (_, i) => node(`l${i}`))]
    const edges = [
      edge('m1', 'root'), edge('m2', 'root'), edge('m3', 'root'),
      ...[0, 1, 2].map((i) => edge(`l${i}`, 'm1')),
      ...[3, 4, 5].map((i) => edge(`l${i}`, 'm2')),
      ...[6, 7, 8].map((i) => edge(`l${i}`, 'm3')),
    ]
    const pos = linearTreePositions(nodes, edges)
    expect(Object.keys(pos)).toHaveLength(13)
    // Parents above children: smaller y (y grows downward on the canvas).
    for (const m of ['m1', 'm2', 'm3']) expect(pos['root'].y).toBeLessThan(pos[m].y)
    for (const m of ['m1', 'm2', 'm3'])
      for (let i = 0; i < 9; i++) expect(pos[`l${i}`].y).toBeGreaterThan(pos[m].y)
  })

  it('folds wide ranks: same-row nodes never overlap and rows stack', () => {
    const nodes = [node('root'), ...Array.from({ length: 60 }, (_, i) => node(`w${i}`))]
    const edges = Array.from({ length: 60 }, (_, i) => edge(`w${i}`, 'root'))
    const pos = linearTreePositions(nodes, edges)
    expect(Object.keys(pos)).toHaveLength(61)
    const byRow = new Map<number, { id: string; x: number }[]>()
    for (const [id, p] of Object.entries(pos)) {
      const row = byRow.get(p.y) ?? []
      row.push({ id, x: p.x })
      byRow.set(p.y, row)
    }
    for (const row of byRow.values()) {
      const sorted = [...row].sort((a, b) => a.x - b.x)
      for (let i = 1; i < sorted.length; i++) {
        // widthOf(node without explicit size) = 72; wrapRanks guarantees ≥ nodesep gaps
        expect(sorted[i].x - (sorted[i - 1].x + 72)).toBeGreaterThanOrEqual(48 - 1)
      }
    }
    expect(byRow.size).toBeGreaterThan(1) // 60 siblings cannot fit one row
  })

  it('handles a forest (multiple roots) without losing nodes', () => {
    const nodes = [node('r1'), node('r2'), node('a'), node('b'), node('c')]
    const pos = linearTreePositions(nodes, [edge('a', 'r1'), edge('b', 'r1'), edge('c', 'r2')])
    expect(Object.keys(pos)).toHaveLength(5)
  })

  it('survives cycles and still places every node', () => {
    const nodes = [node('a'), node('b'), node('c')]
    const pos = linearTreePositions(nodes, [edge('a', 'b'), edge('b', 'a'), edge('c', 'a')])
    expect(Object.keys(pos)).toHaveLength(3)
  })

  it('places a multi-parent node once (first parent wins)', () => {
    const nodes = [node('p1'), node('p2'), node('kid')]
    const pos = linearTreePositions(nodes, [edge('kid', 'p1'), edge('kid', 'p2')])
    expect(Object.keys(pos)).toHaveLength(3)
  })

  it('is empty for an empty graph', () => {
    expect(linearTreePositions([], [])).toEqual({})
  })

  it('normalizes output to the origin (no axis-anchor offset)', () => {
    // GO-shaped reality: thousands of isolated roots — raw leaf cursors push
    // the fold axis to ~300k. Huge magnitudes only amplify float drift in
    // the renderer's bounds comparisons; the map must start at (0,0).
    const nodes = Array.from({ length: 300 }, (_, i) => node(`iso${i}`))
    nodes.push(node('r'), node('kid'))
    const edges = [edge('kid', 'r')]
    const pos = linearTreePositions(nodes, edges)
    const xs = Object.values(pos).map((p) => p.x)
    const ys = Object.values(pos).map((p) => p.y)
    expect(Math.min(...ys)).toBe(0)
    expect(Math.min(...xs)).toBeGreaterThanOrEqual(0)
    expect(Math.min(...xs)).toBeLessThan(100)
  })

  it('lays out a GO-shaped 5000-node graph under one second', () => {
    const nodes = [{ id: 'r0' }]
    const edges: { source: string; target: string }[] = []
    const l2: string[] = []
    for (let i = 0; i < 90; i++) {
      const id = `m${i}`
      l2.push(id)
      nodes.push({ id })
      edges.push({ source: id, target: 'r0' })
    }
    for (let i = 0; i < 4970; i++) {
      const id = `l${i}`
      nodes.push({ id })
      edges.push({ source: id, target: l2[i % 90] })
    }
    const t0 = performance.now()
    const pos = linearTreePositions(nodes, edges)
    const ms = performance.now() - t0
    expect(Object.keys(pos)).toHaveLength(nodes.length)
    // Perf guard: dagre needs ~120s on this shape; this path must stay O(V).
    expect(ms).toBeLessThan(1000)
  })
})

describe('FAST_LAYOUT_NODES contract', () => {
  it('sits above the small graphs dagre still serves', () => {
    expect(FAST_LAYOUT_NODES).toBeGreaterThan(100)
    expect(FAST_LAYOUT_NODES).toBeLessThan(MAX_OVERVIEW_NODES_FRONTEND)
  })
})

// The backend overview budget — imported indirectly to keep the contract
// test honest without pulling server code: mirror of indexes.py's constant.
const MAX_OVERVIEW_NODES_FRONTEND = 5000

describe('wrapRanks re-export sanity', () => {
  it('widthOf defaults unstyled nodes to 72 and wrapRanks stays importable', () => {
    expect(widthOf({ id: 'x' })).toBe(72)
    expect(typeof wrapRanks).toBe('function')
    expect(ROW_HEIGHT).toBe(32)
  })
})

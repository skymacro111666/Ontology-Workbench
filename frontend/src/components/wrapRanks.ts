import { BaseLayout, ExtensionCategory, register } from '@antv/g6'
import type { GraphData } from '@antv/g6'

/** Row height of canvas nodes (rect cards); instance circles share the grid. */
export const ROW_HEIGHT = 32

/** Width an instance node occupies: a 12px circle plus its right-side label. */
const INSTANCE_WIDTH = 100

/** Node datum as the rank-wrap layout stage sees it (structural subset —
 *  G6's NodeStyle.size arrives as number, [w, h], or Float32Array). */
export interface WrapNode {
  id: string
  style?: { x?: number; y?: number; size?: number | number[] | Float32Array }
  data?: { kind?: unknown }
}

/** Edge datum as the layout stage sees it — direction is irrelevant, only
 *  adjacency (which nodes hang off which) feeds the sibling grouping. */
export interface WrapEdge {
  source: string
  target: string
}

export interface WrapOptions {
  /** Vertical gap between folded sub-rows inside one rank. */
  rowGap: number
  /** Vertical gap between rank blocks. */
  rankGap: number
  /** Horizontal gap between nodes in a row (and the sweep's minimum gap). */
  nodesep: number
  /** Ranks wider than this fold into centered sub-rows. */
  targetRowWidth: number
}

export const widthOf = (n: WrapNode): number => {
  if (n.data?.kind === 'instance') return INSTANCE_WIDTH
  const s = n.style?.size
  if (typeof s === 'number') return s
  if (s && s.length) return s[0]
  return 72
}

/** Median of a numbers list (even counts average the middle pair). */
const median = (xs: number[]): number => {
  const s = [...xs].sort((a, b) => a - b)
  const mid = s.length >> 1
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2
}

/** Total width of a packed row: member widths plus inter-node gaps. */
const rowWidthOf = (row: { width: number }[], opts: WrapOptions): number =>
  row.reduce((m, u) => m + u.width, 0) + Math.max(0, row.length - 1) * opts.nodesep

/** Stage 2 of the layout pipeline (after antv-dagre): dagre fixes each
 *  rank's y and a parent-centered x; this pass keeps every fitting rank
 *  exactly where dagre put it (only widening overlaps away) and folds
 *  over-wide ranks into sub-rows centered under their anchors, never
 *  interleaving a sibling group. The first-load canvas reads as a tidy
 *  centered tree; canvas width still scales with the widest ROW, not the
 *  widest rank (54 siblings ≈ 9,800px unfold). */
export function wrapRanks(
  nodes: WrapNode[],
  edges: WrapEdge[],
  opts: WrapOptions,
): { id: string; style: { x: number; y: number } }[] {
  // 1) Cluster into ranks by near-equal y (one y per dagre rank), top down.
  const ranks: { y: number; nodes: WrapNode[] }[] = []
  for (const n of [...nodes].sort((a, b) => (a.style?.y ?? 0) - (b.style?.y ?? 0))) {
    const y = n.style?.y ?? 0
    const last = ranks.at(-1)
    if (last && Math.abs(last.y - y) <= 1) last.nodes.push(n)
    else ranks.push({ y, nodes: [n] })
  }

  // Undirected adjacency for the anchor lookup (attach or property edges
  // alike — any placed neighbor can anchor a sibling group).
  const neighbors = new Map<string, string[]>()
  for (const { source, target } of edges) {
    ;(neighbors.get(source) ?? neighbors.set(source, []).get(source)!).push(target)
    ;(neighbors.get(target) ?? neighbors.set(target, []).get(target)!).push(source)
  }

  const out: { id: string; style: { x: number; y: number } }[] = []
  /** Final x of every placed node (for anchor centers). */
  const centerX = new Map<string, number>()
  let rankBase = 0

  for (const rank of ranks) {
    // 2) Sweep dagre's x right just enough that effective widths (instance
    //    labels included) never overlap; order and gaps ≥ nodesep elsewhere.
    const ordered = [...rank.nodes].sort((a, b) => (a.style?.x ?? 0) - (b.style?.x ?? 0))
    const swept: { n: WrapNode; x: number }[] = []
    for (const n of ordered) {
      const prev = swept.at(-1)
      const dx = n.style?.x ?? 0
      const x = prev ? Math.max(dx, prev.x + widthOf(prev.n) + opts.nodesep) : dx
      swept.push({ n, x })
    }
    const extent = swept.reduce((m, s) => Math.max(m, s.x + widthOf(s.n)), 0)

    // 3) Fitting rank: keep dagre's parent-centered x verbatim.
    const place = (n: WrapNode, x: number, y: number) => {
      out.push({ id: n.id, style: { x, y } })
      centerX.set(n.id, x + widthOf(n) / 2)
    }
    if (extent <= opts.targetRowWidth) {
      for (const s of swept) place(s.n, s.x, rankBase)
      rankBase += ROW_HEIGHT + opts.rowGap + opts.rankGap
      continue
    }

    // 4) Over-wide rank: group members by their nearest placed neighbor
    //    above (the anchor — the shared parent for subclass siblings);
    //    anchorless nodes group alone. Groups order by dagre x.
    const groups = new Map<string, { anchor: number; members: WrapNode[]; minX: number }>()
    for (const s of swept) {
      let anchorId: string | null = null
      let dist = Infinity
      for (const m of neighbors.get(s.n.id) ?? []) {
        const c = centerX.get(m)
        if (c === undefined) continue
        const d = Math.abs(c - (s.x + widthOf(s.n) / 2))
        if (d < dist) {
          dist = d
          anchorId = m
        }
      }
      const key = anchorId ?? `#${s.n.id}`
      const g = groups.get(key) ?? {
        anchor: anchorId ? centerX.get(anchorId)! : s.x + widthOf(s.n) / 2,
        members: [],
        minX: s.x,
      }
      g.members.push(s.n)
      groups.set(key, g)
    }
    // Row axis: the median member anchor — folded rows stack symmetrically
    // under the parents that spawned them, not flush left.
    const axis = median([...groups.values()].flatMap((g) => g.members.map(() => g.anchor)))

    // 5) Split each group into chunk units that fit one row (whole groups
    //    when possible), pack units greedily, center every row on the axis.
    type Unit = { members: WrapNode[]; width: number }
    const units: Unit[] = []
    for (const g of [...groups.values()].sort((a, b) => a.minX - b.minX)) {
      let chunk: WrapNode[] = []
      let w = 0
      const flush = () => {
        if (chunk.length) units.push({ members: chunk, width: w })
        chunk = []
        w = 0
      }
      for (const n of g.members) {
        const nw = widthOf(n)
        if (chunk.length && w + opts.nodesep + nw > opts.targetRowWidth) flush()
        w = chunk.length ? w + opts.nodesep + nw : nw
        chunk.push(n)
      }
      flush()
    }
    const rows: Unit[][] = [[]]
    let rowWidth = 0
    for (const u of units) {
      const row = rows.at(-1)!
      if (row.length && rowWidth + opts.nodesep + u.width > opts.targetRowWidth) {
        rows.push([u])
        rowWidth = u.width
      } else {
        row.push(u)
        rowWidth = rowWidth ? rowWidth + opts.nodesep + u.width : u.width
      }
    }
    rows.forEach((row, i) => {
      const y = rankBase + i * (ROW_HEIGHT + opts.rowGap)
      let x = axis - rowWidthOf(row, opts) / 2
      for (const u of row) {
        u.members.forEach((n, j) => {
          if (j > 0) x += opts.nodesep
          place(n, x, y)
          x += widthOf(n)
        })
        x += opts.nodesep // one gap after the unit, mirrored by rowWidthOf
      }
    })
    rankBase += rows.length * (ROW_HEIGHT + opts.rowGap) + opts.rankGap
  }
  return out
}

/** G6 layout extension running wrapRanks as the pipeline's second stage. */
export class RankWrapLayout extends BaseLayout {
  id = 'rank-wrap'
  async execute(model: GraphData): Promise<GraphData> {
    const { rowGap = 14, rankGap = 90, nodesep = 16, targetRowWidth = 1700 } =
      this.options as Partial<WrapOptions>
    const nodes = wrapRanks(
      (model.nodes ?? []) as WrapNode[],
      (model.edges ?? []) as WrapEdge[],
      { rowGap, rankGap, nodesep, targetRowWidth },
    )
    return { nodes }
  }
}

register(ExtensionCategory.LAYOUT, 'rank-wrap', RankWrapLayout)

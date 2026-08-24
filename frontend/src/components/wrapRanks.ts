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

export interface WrapOptions {
  /** Vertical gap between wrapped sub-rows inside one rank. */
  rowGap: number
  /** Vertical gap between rank blocks. */
  rankGap: number
  /** Horizontal gap between nodes in a row. */
  nodesep: number
  /** Rows wrap once their accumulated width exceeds this. */
  targetRowWidth: number
}

const widthOf = (n: WrapNode): number => {
  if (n.data?.kind === 'instance') return INSTANCE_WIDTH
  const s = n.style?.size
  if (typeof s === 'number') return s
  if (s && s.length) return s[0]
  return 72
}

/** Stage 2 of the overview layout pipeline (after antv-dagre): dagre fixes
 *  each rank's y and the sibling order x; this pass re-packs every rank's
 *  nodes into sub-rows of at most targetRowWidth, staggering overflow rows
 *  downward. Canvas width stops scaling with the widest rank (54 siblings ≈
 *  9,800px) and scales with the widest row instead. */
export function wrapRanks(
  nodes: WrapNode[],
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
  // 2) Per rank: keep dagre's x order (siblings stay adjacent), wrap greedily
  //    by accumulated width, pack each row left to right.
  const out: { id: string; style: { x: number; y: number } }[] = []
  let rankBase = 0
  for (const rank of ranks) {
    const ordered = [...rank.nodes].sort((a, b) => (a.style?.x ?? 0) - (b.style?.x ?? 0))
    const rows: WrapNode[][] = [[]]
    let rowWidth = 0
    for (const n of ordered) {
      const w = widthOf(n)
      const row = rows.at(-1)!
      if (row.length && rowWidth + w > opts.targetRowWidth) {
        rows.push([n])
        rowWidth = w + opts.nodesep
      } else {
        row.push(n)
        rowWidth += w + opts.nodesep
      }
    }
    rows.forEach((rowNodes, i) => {
      let x = 0
      const y = rankBase + i * (ROW_HEIGHT + opts.rowGap)
      for (const n of rowNodes) {
        out.push({ id: n.id, style: { x, y } })
        x += widthOf(n) + opts.nodesep
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
    const nodes = wrapRanks((model.nodes ?? []) as WrapNode[], {
      rowGap,
      rankGap,
      nodesep,
      targetRowWidth,
    })
    return { nodes }
  }
}

register(ExtensionCategory.LAYOUT, 'rank-wrap', RankWrapLayout)

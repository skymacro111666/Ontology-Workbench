import type { Pt } from './layoutPositions'
import { widthOf, wrapRanks, type WrapEdge, type WrapNode, type WrapOptions } from './wrapRanks'

/** Past this auto-layout node count the canvas skips the dagre pipeline for
 *  a linear tree pass. Measured on a GO-shaped graph: dagre needs ~120s for
 *  5000 nodes (main thread, frozen UI) and scales superlinearly, while this
 *  pass is O(V) — sub-second at the backend's 5000-node overview budget.
 *  Below the threshold dagre's sibling ordering is worth its ~5s ceiling. */
export const FAST_LAYOUT_NODES = 1000

/** Fold options shared with the dagre pipeline's rank-wrap stage, so both
 *  auto paths produce the same org-chart rhythm. */
const WRAP_OPTS: WrapOptions = { rowGap: 24, rankGap: 90, nodesep: 48, targetRowWidth: 1700 }

/** Rough horizontal slot for a leaf (default card width + nodesep); the
 *  wrapRanks sweep re-spaces with real widths anyway — this only sets order. */
const SLOT = 72 + 48

/** Distinct-y encoding of depth for wrapRanks' rank clustering (> 1px apart). */
const RANK_STEP = 100

/** O(V) hierarchy layout: depth fixes the rank (y), DFS leaf order fixes x
 *  with parents centered over their children, then the shared wrapRanks pass
 *  sweeps overlaps away and folds over-wide ranks into centered sub-rows.
 *  Edge direction follows subClassOf semantics: source hangs under target;
 *  a multi-parent node is placed once (first parent wins), its other parent
 *  edges simply draw across. Cycles cannot loop the walk (visited check). */
export function linearTreePositions(
  nodes: WrapNode[],
  edges: WrapEdge[],
  opts: WrapOptions = WRAP_OPTS,
): Record<string, Pt> {
  if (!nodes.length) return {}

  const known = new Set(nodes.map((n) => n.id))
  const parentOf = new Map<string, string>()
  const childrenOf = new Map<string, string[]>()
  for (const { source, target } of edges) {
    if (!known.has(source) || !known.has(target) || source === target) continue
    if (parentOf.has(source)) continue // first parent wins; later edges stay visual
    parentOf.set(source, target)
    const kids = childrenOf.get(target) ?? []
    kids.push(source)
    childrenOf.set(target, kids)
  }

  let roots = nodes.filter((n) => !parentOf.has(n.id)).map((n) => n.id)
  if (!roots.length) roots = [nodes[0].id] // pure-cycle defensive fallback

  const depth = new Map<string, number>()
  const x = new Map<string, number>()
  let cursor = 0
  const visit = (id: string, d: number): void => {
    if (depth.has(id)) return
    depth.set(id, d)
    const kids = childrenOf.get(id) ?? []
    if (!kids.length) {
      x.set(id, cursor)
      cursor += SLOT
      return
    }
    for (const k of kids) visit(k, d + 1)
    const xs = kids.flatMap((k) => x.get(k) ?? [])
    if (xs.length) x.set(id, (Math.min(...xs) + Math.max(...xs)) / 2)
    else {
      x.set(id, cursor)
      cursor += SLOT
    }
  }
  for (const r of roots) visit(r, 0)
  // Cycle members unreachable from the fallback root / edge orphans.
  for (const n of nodes) {
    if (depth.has(n.id)) continue
    depth.set(n.id, 0)
    x.set(n.id, cursor)
    cursor += SLOT
  }

  const staged: WrapNode[] = nodes.map((n) => ({
    ...n,
    style: { ...n.style, x: x.get(n.id) ?? 0, y: (depth.get(n.id) ?? 0) * RANK_STEP },
  }))
  const out: Record<string, Pt> = {}
  for (const f of wrapRanks(staged, edges, opts)) out[f.id] = { x: f.style.x, y: f.style.y }
  return out
}

/** Re-exported for the GraphView integration and tests: the widest node a
 *  row must account for (widthOf reads style.size / instance kind). */
export { widthOf }

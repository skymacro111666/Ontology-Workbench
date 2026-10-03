import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Graph } from '@antv/g6'
import type { EdgeData, GraphData, IPointerEvent, NodeData } from '@antv/g6'
import type { GEdge, GNode } from '../api/types'
import { FAST_LAYOUT_NODES, MAX_AUTO_ZOOM, MIN_AUTO_ZOOM, linearTreePositions } from './linearTree'
import type { WrapEdge, WrapNode } from './wrapRanks'
import { localName } from '../lib/localName'
import { cn } from '@/lib/utils'
import { assignFallbackPositions, type Pt } from './layoutPositions'
import { cardDisplayName, cardWidth } from './cardSize'
import { useTheme } from '../theme/ThemeProvider'
import { Toggle } from '@/components/ui/toggle'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
// Side effect: registers the pipeline's second layout stage ('rank-wrap').
import './wrapRanks'

/** Node extended with what the canvas renders beyond the API payload. */
export type GraphViewNode = GNode & {
  highlighted?: boolean
}

/** Which node families the canvas shows — three independent dimensions the
 *  user combines (e.g. 类 + 对象属性). Classes covers class/self/instance
 *  kinds; properties split by ptype (untyped rdf:Property reads as object). */
export type KindFilter = {
  classes: boolean
  objectProps: boolean
  dataProps: boolean
}

/** Every dimension on — the neutral canvas default and the 全部 state. */
export function allKinds(): KindFilter {
  return { classes: true, objectProps: true, dataProps: true }
}

/** The kind keys currently on, for the multiple ToggleGroup's value prop. */
const activeKindKeys = (k: KindFilter): string[] =>
  (['classes', 'objectProps', 'dataProps'] as const).filter((key) => k[key])

const kindsFromKeys = (keys: string[]): KindFilter => ({
  classes: keys.includes('classes'),
  objectProps: keys.includes('objectProps'),
  dataProps: keys.includes('dataProps'),
})

/** Design tokens resolved to concrete colors — G6 draws on canvas, where CSS
 *  variables do not resolve, so values are read at (re)build time. */
export interface CanvasTokens {
  primary: string
  primaryFg: string
  primarySoft: string
  rootTint: string
  panel: string
  panel2: string
  line: string
  ink: string
  ink2: string
  ink3: string
  edgeSub: string
  success: string
  mono: string
}

export function readCanvasTokens(): CanvasTokens {
  const cs = getComputedStyle(document.documentElement)
  const v = (name: string) => cs.getPropertyValue(name).trim()
  return {
    primary: v('--color-primary'),
    primaryFg: v('--color-primary-foreground'),
    primarySoft: v('--color-primary-soft'),
    rootTint: v('--color-root-tint'),
    panel: v('--color-panel'),
    panel2: v('--color-panel-2'),
    line: v('--color-line'),
    ink: v('--color-ink'),
    ink2: v('--color-ink-2'),
    ink3: v('--color-ink-3'),
    edgeSub: v('--color-edge-sub'),
    success: v('--color-success'),
    mono: v('--font-mono'),
  }
}

/** Edge semantics (spec §7.3): subclass dashed purple, object property solid
 *  indigo, data property dotted slate, instance plain grey, assertion thin
 *  green — each with a matching arrowhead. */
function edgeVisualFor(
  kind: string,
  t: CanvasTokens,
): { stroke: string; dash?: number[]; lineWidth?: number } {
  if (kind === 'subClassOf') return { stroke: t.edgeSub, dash: [6, 5] }
  if (kind === 'datatype') return { stroke: t.ink3, dash: [1, 4] }
  if (kind === 'instance') return { stroke: t.ink3 }
  if (kind === 'assertion') return { stroke: t.success, lineWidth: 1 }
  if (kind === 'objectProperty') return { stroke: t.primary }
  return { stroke: t.primary }
}

/** Legend copy tied to the visuals above so the two cannot drift apart.
 *  Labels are i18n keys — the render site translates. */
const LEGEND: { label: string; visual: { stroke: string; dash?: string } }[] = [
  { label: 'canvas.edgeSubClass', visual: { stroke: 'var(--color-edge-sub)', dash: '6 5' } },
  { label: 'canvas.edgeObjectProp', visual: { stroke: 'var(--color-primary)' } },
  { label: 'canvas.edgeDataProp', visual: { stroke: 'var(--color-ink-3)', dash: '1 4' } },
  { label: 'canvas.edgeInstance', visual: { stroke: 'var(--color-ink-3)' } },
  { label: 'canvas.edgeAssertion', visual: { stroke: 'var(--color-success)' } },
]

/** Node ladder legend (v3): the class card styles above as swatches —
 *  root tinted bold, each generation one shade lighter. The DOM legend
 *  resolves CSS variables itself (canvas tokens cannot cross into it). */
const NODE_LEGEND: { label: string; visual: { fill: string; stroke: string; width: number } }[] = [
  { label: 'canvas.nodeRoot', visual: { fill: 'var(--color-root-tint)', stroke: 'var(--color-ink-2)', width: 1.4 } },
  { label: 'canvas.nodeDepth1', visual: { fill: 'var(--color-panel)', stroke: 'var(--color-ink-2)', width: 1.4 } },
  { label: 'canvas.nodeDepth2', visual: { fill: 'var(--color-panel)', stroke: 'var(--color-ink-3)', width: 1 } },
  { label: 'canvas.nodeDepth3', visual: { fill: 'var(--color-panel-2)', stroke: 'var(--color-line)', width: 1 } },
]

/** Two-stage layout pipeline: dagre fixes the ranks and sibling order
 *  top-down, then rank-wrap keeps every fitting rank at dagre's parent-
 *  centered x and folds over-wide ranks into sub-rows of at most ~1700px,
 *  centered under their anchors, sibling groups kept whole — so canvas
 *  width scales with the widest row, not the widest rank (54 siblings in
 *  one row would otherwise span ~9,800px). Orthogonal polyline edges read
 *  org-chart style and dodge the staggered rows. */
const LAYOUT = [
  { type: 'antv-dagre', rankdir: 'TB', nodesep: 48, ranksep: 90 },
  { type: 'rank-wrap', rowGap: 24, rankGap: 90, nodesep: 48, targetRowWidth: 1700 },
]

/** A G6 display object as click events expose it (structural subset). */
export type HitShape = { className?: unknown; parentElement?: HitShape | null }

/** True when the hit shape — or an ancestor up to the node element — is one
 *  of the node's badge sub-shapes. G6 tags them 'badge-0', 'badge-1', … on
 *  className (the name property stays empty), and the hit often lands on
 *  the badge label's nested text/background shape, hence the climb. */
export function hitBadge(hit: HitShape | null | undefined, node: unknown): boolean {
  let shape: HitShape | null | undefined = hit
  while (shape && shape !== node) {
    if (typeof shape.className === 'string' && shape.className.startsWith('badge')) return true
    shape = shape.parentElement
  }
  return false
}

/** True when the hit shape sits inside the FOLD badge. G6 names badge
 *  sub-shapes by array index ('badge-0', …) and ignores any className the
 *  badge option carries, so the fold badge must be badges[0] and this only
 *  ever fires for folded nodes (plain nodes put the instance badge there). */
export function hitFold(hit: HitShape | null | undefined, node: unknown): boolean {
  let shape: HitShape | null | undefined = hit
  while (shape && shape !== node) {
    if (typeof shape.className === 'string' && shape.className === 'badge-0') return true
    shape = shape.parentElement
  }
  return false
}

/** Bucket kinds render as large dashed rectangles (spec §5.2). */
const isBucket = (kind: string) => kind === 'deprecatedBucket' || kind === 'prefixBucket'

/** Class generations for the depth ladder: BFS down the subClassOf edges
 *  from the anchor (anchored canvas) or from the parentless top classes
 *  (fresh overview), so card styles can encode 树干到树叶 (v3 spec). API
 *  edges read source = child, target = parent — toG6Edges swaps them for
 *  the TB layout, this walks the raw direction. Multi-parent nodes keep
 *  the shallowest generation (BFS dequeue order); properties, instances
 *  and buckets never enter the map — they carry their own visual
 *  language. A parent ring unreachable from any root maps nothing. */
export function subclassDepths(
  nodes: GraphViewNode[],
  edges: GEdge[],
  anchorId?: string,
): Map<string, number> {
  const classes = new Set(nodes.filter((n) => n.kind === 'class').map((n) => n.id))
  const children = new Map<string, string[]>()
  const hasParent = new Set<string>()
  for (const e of edges) {
    if (e.kind !== 'subClassOf') continue
    if (!classes.has(e.target) || !classes.has(e.source)) continue
    const list = children.get(e.target)
    if (list) list.push(e.source)
    else children.set(e.target, [e.source])
    hasParent.add(e.source)
  }
  const roots =
    anchorId !== undefined && classes.has(anchorId)
      ? [anchorId]
      : [...classes].filter((id) => !hasParent.has(id))
  const depths = new Map<string, number>()
  const queue: string[] = []
  for (const r of roots) {
    depths.set(r, 0)
    queue.push(r)
  }
  while (queue.length) {
    const id = queue.shift() as string
    const d = depths.get(id) as number
    for (const c of children.get(id) ?? []) {
      if (depths.has(c)) continue
      depths.set(c, d + 1)
      queue.push(c)
    }
  }
  return depths
}

/** Card style (mockup): classes get a solid grey border, property nodes a
 *  dashed violet one (kind encoded in the border), and the highlighted
 *  entity a 2px primary border. Node labels prefer rdfs:label, falling
 *  back to the curie's local name; the inspector carries the full curie.
 *  Instances (on-demand badge reveal) render as small grey circles beside
 *  their class. The depth ladder (v3): the root/anchor carries the
 *  root-tint fill and a bold 1.4px ink2 border, each generation below
 *  one shade lighter — focused keeps priority on border and label, and
 *  composes with the tint (a focused root shows both signals). */
export function toG6Nodes(
  nodes: GraphViewNode[],
  t: CanvasTokens,
  foldedIds?: Set<string>,
  depths?: Map<string, number>,
): NodeData[] {
  return nodes.map((n) => {
    const isProperty = n.kind === 'property'
    const bucket = isBucket(n.kind)
    const focused = !!n.highlighted
    const depth = depths?.get(n.id)
    // 节点显示名 rdfs:label 优先,缺失回退 curie 局部名。
    const name = cardDisplayName(n)
    if (n.kind === 'instance') {
      return {
        id: n.id,
        data: { kind: n.kind, curie: n.curie },
        style: {
          size: 12,
          fill: t.panel,
          stroke: focused ? t.primary : t.ink3,
          lineWidth: focused ? 2 : 1,
          labelText: name,
          labelFill: focused ? t.primary : t.ink,
          labelFontSize: 10,
          labelPlacement: 'right',
        },
      }
    }
    const w = bucket ? 168 : cardWidth(name)
    // Ladder borders: gen 0/1 share ink2 at 1.4px (fill, weight and card
    // height tell the root from gen 1), gen 2 ink3, gen 3+ and ladder-less
    // cards the plain line. Buckets never ladder.
    const ladderStroke = depth === 0 || depth === 1 ? t.ink2 : depth === 2 ? t.ink3 : t.line
    const style: Record<string, unknown> = {
      size: bucket ? [w, 40] : depth === 0 ? [w, 36] : [w, 32],
      radius: 8,
      fill: depth === 0 ? t.rootTint : depth !== undefined && depth >= 3 ? t.panel2 : t.panel,
      stroke: focused ? t.primary : isProperty ? t.edgeSub : ladderStroke,
      lineWidth: focused ? 2 : depth === 0 || depth === 1 ? 1.4 : 1,
      shadowColor: 'rgba(15, 23, 42, 0.08)',
      shadowBlur: 4,
      labelText: name,
      labelFill: focused ? t.primary : depth !== undefined && depth >= 3 ? t.ink2 : t.ink,
      labelFontSize: bucket || depth === 0 ? 13 : 12,
      labelFontWeight: focused ? 700 : depth === 0 ? 700 : bucket || depth === 1 ? 600 : 400,
      labelPlacement: 'center',
    }
    if ((isProperty || bucket) && !focused) style.lineDash = bucket ? [6, 4] : [4, 3]
    // Badges, in a FIXED ORDER: fold first (badge-0, hitFold's index
    // contract), then the instance count (badge-1). The fold badge flips
    // between + and − as foldedIds (currently expanded nodes) changes.
    const badges: Record<string, unknown>[] = []
    if (n.folded) {
      const sign = foldedIds?.has(n.id) ? '−' : '+'
      badges.push({
        text: `${sign}${n.subtreeSize ?? 1}`,
        placement: 'left-top',
        backgroundFill: t.edgeSub,
        fill: t.primaryFg,
        fontSize: 9,
        padding: [2, 5],
        cursor: 'pointer',
      })
    }
    if ((n.instanceCount ?? 0) > 0) {
      badges.push({
        text: String(n.instanceCount),
        placement: 'right-top',
        backgroundFill: t.primary,
        fill: t.primaryFg,
        fontSize: 9,
        padding: [2, 5],
        cursor: 'pointer',
      })
    }
    if (badges.length) style.badges = badges
    return { id: n.id, data: { kind: n.kind, curie: n.curie }, style }
  })
}

/** Map API edges to G6 edges: visibility, label, semantic styling. Edges to
 *  filtered-out endpoints are pruned along with the endpoint itself. The map
 *  doubles as the id→curie lookup for property labels. */
export function toG6Edges(
  edges: GEdge[],
  visible: Map<string, string>,
  showLabels: boolean,
  t: CanvasTokens,
): EdgeData[] {
  const mapped = edges
    .filter((e) => visible.has(e.source) && visible.has(e.target))
    .map((e, i) => {
      const v = edgeVisualFor(e.kind, t)
      // Edge labels: relation words for attach edges (subClassOf, instance),
      // the assertion property's local name for assertion edges (dynamic
      // data, not i18n), the target property's local name for property edges.
      const label =
        e.kind === 'subClassOf'
          ? 'subClassOf'
          : e.kind === 'instance'
            ? 'instance'
            : e.kind === 'assertion' || e.kind === 'objectProperty'
              ? (e.label ?? '→')
              : localName(visible.get(e.target) ?? e.kind)
      // Attach edges (subClassOf child→parent, instance→class) are swapped:
      // dagre TB places a datum's source above its target, so swapping puts
      // parents above children and instances below their class. The arrow
      // moves to the start so on screen it still points at the parent/class.
      const swapped = e.kind === 'subClassOf' || e.kind === 'instance'
      const source = swapped ? e.target : e.source
      const target = swapped ? e.source : e.target
      return {
        id: `e${i}-${source}-${target}`,
        source,
        target,
        // Per-datum, not options-level: G6 resolves options.edge.type before
        // datum.type, so an options default would pin every edge to one shape
        // and the parallel-edge fan below could never take hold.
        type: 'polyline',
        data: { kind: e.kind, propEid: e.eid },
        style: {
          stroke: v.stroke,
          lineWidth: v.lineWidth ?? 1.5,
          ...(v.dash ? { lineDash: v.dash } : {}),
          ...(swapped
            ? { startArrow: true, startArrowSize: 8, startArrowFill: v.stroke }
            : { endArrow: true, endArrowSize: 8, endArrowFill: v.stroke }),
          labelText: showLabels ? label : '',
          labelFill: '#64748B',
          labelFontSize: 10,
          labelFontFamily: t.mono,
          labelBackground: true,
          labelBackgroundFill: t.panel,
          labelBackgroundOpacity: 0.9,
          labelBackgroundRadius: 3,
          labelPadding: [1, 4],
        },
      }
    })
  return fanParallelEdges(mapped)
}

/** Same-pair edges (either direction — manages ↔ reportsTo) fan out as arcs
 *  instead of stacking into one line. Mirrors G6's process-parallel-edges
 *  bundle math (offsets ±FAN_DISTANCE, same sign for reversed pairs because
 *  curveOffset is relative to each edge's own direction), but applied here so
 *  only the parallel pairs switch to quadratic — singletons keep polyline. */
const FAN_DISTANCE = 20

function fanParallelEdges(edges: EdgeData[]): EdgeData[] {
  const groups = new Map<string, number[]>()
  edges.forEach((e, i) => {
    const key = e.source <= e.target ? `${e.source}|${e.target}` : `${e.target}|${e.source}`
    const group = groups.get(key)
    if (group) group.push(i)
    else groups.set(key, [i])
  })
  for (const indices of groups.values()) {
    if (indices.length < 2) continue
    const [first] = indices
    indices.forEach((i, k) => {
      const e = edges[i]
      // Reversed = points against the group's opening edge.
      const reversed = e.source === edges[first].target && e.target === edges[first].source
      const sign = (k % 2 === 0 ? 1 : -1) * (reversed ? -1 : 1)
      const offset =
        indices.length % 2 === 1
          ? sign * Math.ceil(k / 2) * FAN_DISTANCE * 2
          : sign * (Math.floor(k / 2) * FAN_DISTANCE * 2 + FAN_DISTANCE)
      e.type = 'quadratic'
      e.style = { ...e.style, curveOffset: offset }
    })
  }
  return edges
}

function visibleOf(nodes: GraphViewNode[], kinds: KindFilter): GraphViewNode[] {
  return nodes.filter((n) =>
    n.kind !== 'property'
      ? kinds.classes
      : n.ptype === 'DatatypeProperty'
        ? kinds.dataProps
        : kinds.objectProps,
  )
}

/** Direct class→class object-property edges follow the 对象属性 filter,
 *  exactly like the property nodes they replaced. */
function shownEdges(edges: GEdge[], kinds: KindFilter): GEdge[] {
  return edges.filter((e) => e.kind !== 'objectProperty' || kinds.objectProps)
}

function buildData(
  nodes: GraphViewNode[],
  edges: GEdge[],
  kinds: KindFilter,
  showLabels: boolean,
  t: CanvasTokens,
  foldedIds?: Set<string>,
  anchorId?: string,
): GraphData {
  const visible = visibleOf(nodes, kinds)
  const ids = new Map(visible.map((n) => [n.id, n.curie]))
  return {
    nodes: toG6Nodes(visible, t, foldedIds, subclassDepths(visible, edges, anchorId)),
    edges: toG6Edges(shownEdges(edges, kinds), ids, showLabels, t),
  }
}

/**
 * Shared graph canvas on G6 5.x: dagre hierarchy, edge semantics, label
 * toggle, kind filter (spec §7.3; 类/对象属性/数据属性 combine freely, 全部
 * resets). Label/filter controls render as an in-canvas overlay by default;
 * passing the controlled label props moves them to the caller's toolbar.
 */
export default function GraphView({
  nodes,
  edges,
  onSelect,
  onBadgeClick,
  onFoldClick,
  height = '100%',
  focusId,
  showControls = true,
  showLabels: showLabelsProp,
  onShowLabelsChange,
  defaultKinds: defaultKindsProp,
  savedPositions,
  onLayoutChange,
  onResetLayout,
  onContextMenu,
  extraControls,
  foldedIds,
  anchorId,
}: {
  nodes: GraphViewNode[]
  edges: GEdge[]
  onSelect?: (eid: string) => void
  /** Badge (instance-count) click; default no-op. */
  onBadgeClick?: (eid: string) => void
  /** Fold-badge click (progressive canvas); folded=true means "expand me".
   *  Default no-op: without it fold badges render but select nothing. */
  onFoldClick?: (eid: string, folded: boolean) => void
  /** Currently expanded fold ids — flips their badge from + to −. */
  foldedIds?: Set<string>
  /** Root of the depth ladder (the progressive-reveal anchor); without it
   *  the parentless top classes act as roots. */
  anchorId?: string
  height?: number | string
  /** Optional entity to fit-view onto (overview focus param). */
  focusId?: string
  /** Whether the zoom/fit control cluster is rendered (default true). */
  showControls?: boolean
  /** Caller buttons mounted into the control cluster (e.g. B3's 检查). */
  extraControls?: ReactNode
  /** Initial uncontrolled kind filter (the canvas stays all-on; callers
   *  with class-only semantics — e.g. the overview — seed it here). */
  defaultKinds?: KindFilter
  /** Controlled edge-label switch; pass with onShowLabelsChange. */
  showLabels?: boolean
  onShowLabelsChange?: (v: boolean) => void
  /** Saved canvas positions (GET /layout); non-empty switches the canvas
   *  from the auto pipeline to explicit coordinates. */
  savedPositions?: Record<string, Pt>
  /** Debounced whole-map report after drags / layout captures. */
  onLayoutChange?: (positions: Record<string, Pt>) => void
  /** 重排 handler — resets to the automatic layout (DELETE /layout). */
  onResetLayout?: () => void
  /** Right-click report for the canvas context menu (blank or node). */
  onContextMenu?: (info: {
    x: number
    y: number
    targetId?: string
    kind?: string
    curie?: string
  }) => void
}) {
  // `t` reads canvas tokens in a helper below; translations use tr.
  const { t: tr } = useTranslation()
  const resolved = useTheme().resolved
  const [labelsFallback, setLabelsFallback] = useState(true)
  const [kinds, setKinds] = useState<KindFilter>(defaultKindsProp ?? allKinds())
  const [zoomPct, setZoomPct] = useState(100)
  /** Edge legend visibility — the control bar's 图例 button flips it. */
  const [showLegend, setShowLegend] = useState(true)
  const external = onShowLabelsChange !== undefined
  const showLabels = showLabelsProp ?? labelsFallback
  const setShowLabels = onShowLabelsChange ?? setLabelsFallback

  const containerRef = useRef<HTMLDivElement>(null)
  const graphRef = useRef<Graph | null>(null)
  /** Built edge id → objectProperty eid; kept current on every data build
   *  so edge clicks can route to the property's detail page. */
  const edgePropRef = useRef<Map<string, string>>(new Map())
  /** Authoritative node positions this mount knows about: seeded from
   *  savedPositions, backfilled from the layout engine, updated by drags. */
  const positionsRef = useRef<Record<string, Pt>>({})
  const saveTimerRef = useRef<number | undefined>(undefined)
  // onSelect through a ref so the build effect never re-runs for a new callback.
  const onSelectRef = useRef(onSelect)
  useEffect(() => {
    onSelectRef.current = onSelect
  })
  const onBadgeClickRef = useRef(onBadgeClick)
  useEffect(() => {
    onBadgeClickRef.current = onBadgeClick
  })
  const onFoldClickRef = useRef(onFoldClick)
  useEffect(() => {
    onFoldClickRef.current = onFoldClick
  })
  const onLayoutChangeRef = useRef(onLayoutChange)
  useEffect(() => {
    onLayoutChangeRef.current = onLayoutChange
  })
  const onContextMenuRef = useRef(onContextMenu)
  useEffect(() => {
    onContextMenuRef.current = onContextMenu
  })
  // Latest state for the build effect (its deps are narrower than the state).
  // Updated in a render-following effect declared before everything else.
  const stateRef = useRef({ nodes, edges, showLabels, kinds, focusId, foldedIds, anchorId })
  useEffect(() => {
    stateRef.current = { nodes, edges, showLabels, kinds, focusId, foldedIds, anchorId }
  })
  // Change-driven effects (label toggle, kind filter) must not fire on mount:
  // the build effect already rendered the current state. For a 5000-node
  // auto layout the mount-time setData/draw re-render races the first
  // render's RAF ticks — the browser stack-overflowed inside @antv/g's
  // bounds-change cascade; sequential renders never did.
  const firstRun = useRef({ labels: true, kinds: true })

  /** Read the engine's current coordinates into positionsRef (after a
   *  layout pass or a drag) and schedule the debounced whole-map report.
   *  G6 5.x keeps rendered coords on the element — the data model's
   *  style.x is NOT synced after drags (auto-laid-out nodes read 0). */
  const captureAndSchedule = (graph: Graph) => {
    for (const nd of graph.getNodeData() as { id: string }[]) {
      // Point is [x, y] | [x, y, z] | Float32Array — index, don't destructure
      // named fields.
      const p = graph.getElementPosition(nd.id)
      if (p) positionsRef.current[nd.id] = { x: p[0], y: p[1] }
    }
    if (!onLayoutChangeRef.current) return
    window.clearTimeout(saveTimerRef.current)
    saveTimerRef.current = window.setTimeout(() => {
      onLayoutChangeRef.current?.({ ...positionsRef.current })
    }, 800)
  }

  /** (Re)build the graph on data or theme change. The class toggle is
   *  idempotent with ThemeProvider's own and guards first-paint ordering. */
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    document.documentElement.classList.toggle('dark', resolved === 'dark')
    const t = readCanvasTokens()
    const snap = stateRef.current
    // Seed a rebuild from BOTH sources: the server-saved layout and the
    // live coordinates this mount already knows (auto-captured after the
    // first render, moved by drags). Live wins — a data-change rebuild
    // (badge reveal, refresh) must not snap a dragged node back to its
    // saved/auto spot. Ids no longer on the canvas (collapsed reveals,
    // deleted entities) drop out so the saved map cannot grow forever.
    const saved: Record<string, Pt> = savedPositions ?? {}
    const liveIds = new Set(snap.nodes.map((n) => n.id))
    const carried: Record<string, Pt> = {}
    for (const [id, p] of Object.entries(positionsRef.current)) {
      if (liveIds.has(id)) carried[id] = p
    }
    const seeded = { ...saved, ...carried }
    const useSaved = Object.keys(seeded).length > 0
    positionsRef.current = useSaved
      ? assignFallbackPositions(snap.nodes, snap.edges, seeded)
      : {}
    const data = buildData(snap.nodes, snap.edges, snap.kinds, snap.showLabels, t, foldedIds, snap.anchorId)
    edgePropRef.current = new Map(
      (data.edges ?? []).map((ed) => [
        ed.id as string,
        (ed as { data?: { propEid?: string } }).data?.propEid ?? '',
      ]),
    )
    // Oversized auto layouts skip dagre (minutes on wide trees, main thread):
    // a linear tree pass + the shared rank-wrap fold places them in <1s.
    const autoLinear = !useSaved && (data.nodes?.length ?? 0) > FAST_LAYOUT_NODES
    if (autoLinear) {
      positionsRef.current = linearTreePositions(
        (data.nodes ?? []) as WrapNode[],
        (data.edges ?? []) as unknown as WrapEdge[],
      )
      for (const nd of data.nodes ?? []) {
        const p = positionsRef.current[nd.id]
        if (p) nd.style = { ...nd.style, x: p.x, y: p.y }
      }
    }
    if (useSaved) {
      for (const nd of data.nodes ?? []) {
        const p = positionsRef.current[nd.id]
        if (p) nd.style = { ...nd.style, x: p.x, y: p.y }
      }
    }
    // Every Graph gets its own mount node, replaced on cleanup: React dev
    // double-invokes effects (mount → cleanup → mount), and a re-created
    // Graph reusing the same container walked straight into @antv/g's
    // bounds-change recursion between the dying and the fresh canvas — the
    // GO blank-canvas stack overflow. A private node isolates the instances.
    const mount = document.createElement('div')
    mount.style.width = '100%'
    mount.style.height = '100%'
    el.appendChild(mount)
    const graph = new Graph({
      container: mount,
      autoResize: true,
      animation: false,
      theme: resolved,
      padding: [40, 40, 40, 40],
      data,
      // `false` (skip layout, use data x/y) is valid at runtime but missing
      // from G6's LayoutOptions type — see render()'s !options.layout branch.
      layout: (useSaved || autoLinear ? false : LAYOUT) as unknown as typeof LAYOUT,
      node: { type: (d: NodeData) => (d.data?.kind === 'instance' ? 'circle' : 'rect') },
      behaviors: ['drag-canvas', 'zoom-canvas', 'drag-element'],
      plugins: [],
    })
    graphRef.current = graph

    // Stale-instance guard: the render chain is async; a rebuild (or React
    // dev's double-invoked effects) may have destroyed this graph by the
    // time callbacks fire. Never touch a dead instance.
    const isCurrent = () => graphRef.current === graph

    graph.on('node:click', (e) => {
      const evt = e as IPointerEvent & { originalTarget?: HitShape | null }
      const id = evt.target ? (evt.target as unknown as { id: string }).id : undefined
      if (!id) return
      // Click routing, most specific first: the fold badge (badge-0 on a
      // folded node) expands/collapses; the instance badge reveals; the
      // body selects.
      const datum = snap.nodes.find((nd) => nd.id === id)
      if (datum?.folded && hitFold(evt.originalTarget, evt.target)) {
        onFoldClickRef.current?.(id, !snap.foldedIds?.has(id))
      } else if (hitBadge(evt.originalTarget, evt.target)) onBadgeClickRef.current?.(id)
      else onSelectRef.current?.(id)
    })

    // A direct objectProperty edge stands in for its property node: clicking
    // it opens the property's detail page, preserving the node's affordance.
    graph.on('edge:click', (e) => {
      const evt = e as IPointerEvent
      const id = evt.target ? (evt.target as unknown as { id: string }).id : undefined
      const propEid = id ? edgePropRef.current.get(id) : undefined
      if (propEid) onSelectRef.current?.(propEid)
    })

    // A finished drag persists the whole map (debounced).
    graph.on('node:dragend', () => captureAndSchedule(graph))

    // Right-click feeds the canvas context menu (blank vs node target).
    const reportContextMenu = (e: unknown, targetId?: string) => {
      const evt = e as {
        client?: { x: number; y: number }
        preventDefault?: () => void
      }
      evt.preventDefault?.()
      const rect = containerRef.current?.getBoundingClientRect()
      const byId = targetId ? snap.nodes.find((nd) => nd.id === targetId) : undefined
      onContextMenuRef.current?.({
        x: (evt.client?.x ?? 0) - (rect?.left ?? 0),
        y: (evt.client?.y ?? 0) - (rect?.top ?? 0),
        targetId: byId?.id,
        kind: byId?.kind,
        curie: byId?.curie,
      })
    }
    graph.on('canvas:contextmenu', (e) => reportContextMenu(e))
    graph.on('node:contextmenu', (e) => {
      const evt = e as IPointerEvent & { originalTarget?: HitShape | null }
      const id = evt.target ? (evt.target as unknown as { id: string }).id : undefined
      // Badge hits are instance reveals, not entity menus.
      if (!id || hitBadge(evt.originalTarget, evt.target)) {
        evt.preventDefault?.()
        return
      }
      reportContextMenu(e, id)
    })

    void graph
      .render()
      .then(() => {
        if (!isCurrent()) return
        if (!useSaved) {
          // Auto pipeline: capture what dagre/rank-wrap computed so a later
          // drag saves the full map, not just the dragged node.
          for (const nd of graph.getNodeData() as {
            id: string
            style?: { x?: number; y?: number }
          }[]) {
            const { x, y } = nd.style ?? {}
            if (typeof x === 'number' && typeof y === 'number')
              positionsRef.current[nd.id] = { x, y }
          }
        }
        // A stale focus (the entity was just deleted) must not skip the
        // fitView branch — focusElement on a missing node moves nothing and
        // the canvas read blank until the user pressed 适配.
        if (snap.focusId && snap.nodes.some((nd) => nd.id === snap.focusId)) {
          void graph.focusElement(snap.focusId)
        } else {
          // Folded oversized maps tower over the viewport (36k px tall): a raw
          // fitView lands near 2% zoom where cards are invisible dots. Clamp
          // to a readable floor around the viewport center; panning/zoom-out
          // still covers the whole map. Tiny folded overviews fit the other
          // way — past 100% the cards balloon and the block resizes on every
          // expand — so an oversized fit pulls back to the ceiling.
          void graph.fitView().then(() => {
            const zoom = graph.getZoom()
            if (zoom >= MIN_AUTO_ZOOM && zoom <= MAX_AUTO_ZOOM) return undefined
            const target = zoom < MIN_AUTO_ZOOM ? MIN_AUTO_ZOOM : MAX_AUTO_ZOOM
            return graph.zoomTo(target).then(() => {
              setZoomPct(Math.round(graph.getZoom() * 100))
            })
          })
        }
        setZoomPct(Math.round(graph.getZoom() * 100))
      })
      .catch(() => {
        // Render failures leave the canvas blank; the stale-guard above keeps
        // us off destroyed instances, and rebuilds (new data/theme) recover.
      })

    return () => {
      // A pending debounced save must not die with this graph — flush it
      // before destroying. The empty-map guard keeps StrictMode's dev
      // double-mount (rebuild before any drag) from PUTting a blank map
      // over a stored layout.
      if (saveTimerRef.current !== undefined) {
        window.clearTimeout(saveTimerRef.current)
        saveTimerRef.current = undefined
        if (Object.keys(positionsRef.current).length > 0)
          onLayoutChangeRef.current?.({ ...positionsRef.current })
      }
      graph.destroy()
      mount.remove()
      graphRef.current = null
    }
  }, [nodes, edges, resolved, savedPositions, foldedIds, anchorId])

  /** Edge-label toggle without rebuilding (keeps dragged positions). */
  useEffect(() => {
    if (firstRun.current.labels) {
      firstRun.current.labels = false
      return
    }
    const g = graphRef.current
    if (!g) return
    const snap = stateRef.current
    const ids = new Map(visibleOf(snap.nodes, snap.kinds).map((n) => [n.id, n.curie]))
    const nextEdges = toG6Edges(
      shownEdges(snap.edges, snap.kinds),
      ids,
      showLabels,
      readCanvasTokens(),
    )
    edgePropRef.current = new Map(
      nextEdges.map((ed) => [
        ed.id as string,
        (ed as { data?: { propEid?: string } }).data?.propEid ?? '',
      ]),
    )
    g.updateEdgeData(nextEdges)
    void g.draw()
  }, [showLabels])

  /** Kind filter via setData. In saved mode the newly visible nodes need
   *  positions too (deterministic fallbacks); in auto mode dagre reruns. */
  useEffect(() => {
    if (firstRun.current.kinds) {
      firstRun.current.kinds = false
      return
    }
    const g = graphRef.current
    if (!g) return
    const snap = stateRef.current
    const seeded = positionsRef.current
    const useSaved = Object.keys(seeded).length > 0
    const data = buildData(snap.nodes, snap.edges, kinds, snap.showLabels, readCanvasTokens(), undefined, snap.anchorId)
    edgePropRef.current = new Map(
      (data.edges ?? []).map((ed) => [
        ed.id as string,
        (ed as { data?: { propEid?: string } }).data?.propEid ?? '',
      ]),
    )
    if (useSaved) {
      const full = assignFallbackPositions(snap.nodes, snap.edges, seeded)
      positionsRef.current = full
      for (const nd of data.nodes ?? []) {
        const p = full[nd.id]
        if (p) nd.style = { ...nd.style, x: p.x, y: p.y }
      }
    }
    g.setData(data)
    void g.render()
  }, [kinds])

  /** Focus follow: fit the focused entity without rebuilding the graph. */
  useEffect(() => {
    const g = graphRef.current
    if (!g || !focusId) return
    // Stale focus (the entity was just deleted): nothing to center on.
    if (!stateRef.current.nodes.some((nd) => nd.id === focusId)) return
    void g.focusElement(focusId)
  }, [focusId])

  const zoomBy = async (ratio: number) => {
    const g = graphRef.current
    if (!g) return
    await g.zoomBy(ratio)
    setZoomPct(Math.round(g.getZoom() * 100))
  }
  const fit = async () => {
    const g = graphRef.current
    if (!g) return
    await g.fitView()
    // Same ceiling as the auto fit: 适配 means "all visible", not enlarged.
    if (g.getZoom() > MAX_AUTO_ZOOM) await g.zoomTo(MAX_AUTO_ZOOM)
    setZoomPct(Math.round(g.getZoom() * 100))
  }

  const ctlBtn =
    'border-line bg-panel/90 text-ink-2 hover:text-ink rounded-ctl border px-2 py-1 text-xs shadow-xs backdrop-blur'

  return (
    <div
      className="canvas-dots bg-canvas border-line relative overflow-hidden border"
      style={{ height, width: '100%' }}
    >
      <div ref={containerRef} className="h-full w-full" />

      {showControls && (
        <div className="border-line bg-panel/90 rounded-ctl absolute right-2 bottom-2 flex max-w-[calc(100%-1rem)] flex-wrap items-center justify-end gap-1 border p-1 shadow-xs backdrop-blur">
          {!external && (
            <>
              {/* One bar, two segments: display filters | view operations. */}
              <Toggle
                variant="outline"
                size="sm"
                className="h-6 min-w-0 px-2 text-xs"
                pressed={showLabels}
                onPressedChange={setShowLabels}
              >
                {tr('canvas.labels')}
              </Toggle>
              <Toggle
                variant="outline"
                size="sm"
                className="h-6 min-w-0 px-2 text-xs"
                pressed={kinds.classes && kinds.objectProps && kinds.dataProps}
                onPressedChange={() => setKinds(allKinds())}
              >
                {tr('canvas.all')}
              </Toggle>
              <ToggleGroup
                type="multiple"
                variant="outline"
                size="sm"
                className="gap-1"
                value={activeKindKeys(kinds)}
                onValueChange={(v) => {
                  // Empty selection would blank the canvas — keep the last dimension.
                  if (v.length > 0) setKinds(kindsFromKeys(v))
                }}
              >
                <ToggleGroupItem className="h-6 min-w-0 px-2 text-xs" value="classes">
                  {tr('canvas.filterClasses')}
                </ToggleGroupItem>
                <ToggleGroupItem className="h-6 min-w-0 px-2 text-xs" value="objectProps">
                  {tr('canvas.filterObjects')}
                </ToggleGroupItem>
                <ToggleGroupItem className="h-6 min-w-0 px-2 text-xs" value="dataProps">
                  {tr('canvas.filterData')}
                </ToggleGroupItem>
              </ToggleGroup>
              <span className="border-line mx-0.5 h-4 w-px" aria-hidden="true" />
            </>
          )}
          <button type="button" className={ctlBtn} onClick={() => void zoomBy(0.9)}>
            −
          </button>
          <span className="text-ink-2 w-10 text-center font-mono text-[11px]">{zoomPct}%</span>
          <button type="button" className={ctlBtn} onClick={() => void zoomBy(1.1)}>
            +
          </button>
          <button type="button" className={ctlBtn} onClick={() => void fit()}>
            {tr('canvas.fit')}
          </button>
          {onResetLayout && (
            <button type="button" className={ctlBtn} onClick={onResetLayout}>
              {tr('canvas.relayout')}
            </button>
          )}
          {extraControls}
          <button
            type="button"
            className={cn(ctlBtn, showLegend && 'text-primary')}
            aria-pressed={showLegend}
            onClick={() => setShowLegend((v) => !v)}
          >
            {tr('canvas.legend')}
          </button>
        </div>
      )}

      {showLegend && (
        <div className="border-line bg-panel/90 rounded-ctl absolute bottom-2 left-2 flex flex-col gap-1 border p-2 shadow-xs backdrop-blur">
          {LEGEND.map(({ label, visual }) => (
          <div key={label} className="flex items-center gap-2">
            <svg width="26" height="6" aria-hidden="true" className="shrink-0">
              <line
                x1="1"
                y1="3"
                x2="25"
                y2="3"
                stroke={visual.stroke}
                strokeWidth="1.5"
                strokeDasharray={visual.dash}
              />
            </svg>
            <span className="text-ink-2 text-xs">{tr(label)}</span>
          </div>
          ))}
          {NODE_LEGEND.map(({ label, visual }) => (
          <div key={label} className="flex items-center gap-2">
            <svg width="26" height="12" aria-hidden="true" className="shrink-0">
              <rect
                x="1"
                y="1"
                width="24"
                height="10"
                rx="3"
                fill={visual.fill}
                stroke={visual.stroke}
                strokeWidth={visual.width}
              />
            </svg>
            <span className="text-ink-2 text-xs">{tr(label)}</span>
          </div>
          ))}
        </div>
      )}

    </div>
  )
}

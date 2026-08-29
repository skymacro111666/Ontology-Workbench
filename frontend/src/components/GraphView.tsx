import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Graph } from '@antv/g6'
import type { EdgeData, GraphData, IPointerEvent, NodeData } from '@antv/g6'
import type { GEdge, GNode } from '../api/types'
import { FAST_LAYOUT_NODES, linearTreePositions } from './linearTree'
import type { WrapEdge, WrapNode } from './wrapRanks'
import { localName } from '../lib/localName'
import { assignFallbackPositions, type Pt } from './layoutPositions'
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
  panel: string
  line: string
  ink: string
  ink3: string
  edgeSub: string
  mono: string
}

export function readCanvasTokens(): CanvasTokens {
  const cs = getComputedStyle(document.documentElement)
  const v = (name: string) => cs.getPropertyValue(name).trim()
  return {
    primary: v('--color-primary'),
    primaryFg: v('--color-primary-foreground'),
    panel: v('--color-panel'),
    line: v('--color-line'),
    ink: v('--color-ink'),
    ink3: v('--color-ink-3'),
    edgeSub: v('--color-edge-sub'),
    mono: v('--font-mono'),
  }
}

/** Edge semantics (spec §7.3): subclass dashed purple, object property solid
 *  indigo, data property dotted slate, instance plain grey — each with a
 *  matching arrowhead. */
function edgeVisualFor(kind: string, t: CanvasTokens): { stroke: string; dash?: number[] } {
  if (kind === 'subClassOf') return { stroke: t.edgeSub, dash: [6, 5] }
  if (kind === 'datatype') return { stroke: t.ink3, dash: [1, 4] }
  if (kind === 'instance') return { stroke: t.ink3 }
  return { stroke: t.primary }
}

/** Legend copy tied to the visuals above so the two cannot drift apart.
 *  Labels are i18n keys — the render site translates. */
const LEGEND: { label: string; visual: { stroke: string; dash?: string } }[] = [
  { label: 'canvas.edgeSubClass', visual: { stroke: 'var(--color-edge-sub)', dash: '6 5' } },
  { label: 'canvas.edgeObjectProp', visual: { stroke: 'var(--color-primary)' } },
  { label: 'canvas.edgeDataProp', visual: { stroke: 'var(--color-ink-3)', dash: '1 4' } },
  { label: 'canvas.edgeInstance', visual: { stroke: 'var(--color-ink-3)' } },
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

/** Card style (mockup): classes get a solid grey border, property nodes a
 *  dashed violet one (kind encoded in the border), and the highlighted
 *  entity a 2px primary border. Node labels show local names (prefix
 *  stripped); the inspector carries the full curie. Instances (on-demand
 *  badge reveal) render as small grey circles beside their class. */
export function toG6Nodes(nodes: GraphViewNode[], t: CanvasTokens): NodeData[] {
  return nodes.map((n) => {
    const isProperty = n.kind === 'property'
    const focused = !!n.highlighted
    // Instances display their human name when labeled; everything else (and
    // unlabeled instances) falls back to the curie's local name.
    const human = Object.values(n.label ?? {})[0]
    const name = n.kind === 'instance' ? (human ?? localName(n.curie)) : localName(n.curie)
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
    const w = Math.min(220, Math.max(72, Math.round(name.length * 6.6 + 26)))
    const style: Record<string, unknown> = {
      size: [w, 32],
      radius: 8,
      fill: t.panel,
      stroke: focused ? t.primary : isProperty ? t.edgeSub : t.line,
      lineWidth: focused ? 2 : 1,
      shadowColor: 'rgba(15, 23, 42, 0.08)',
      shadowBlur: 4,
      labelText: name,
      labelFill: focused ? t.primary : t.ink,
      labelFontSize: 12,
      labelFontWeight: focused ? 700 : 400,
      labelPlacement: 'center',
    }
    if (isProperty && !focused) style.lineDash = [4, 3]
    // Badge = the class's direct instances; clicking it reveals them.
    if ((n.instanceCount ?? 0) > 0) {
      style.badges = [
        {
          text: String(n.instanceCount),
          placement: 'right-top',
          backgroundFill: t.primary,
          fill: t.primaryFg,
          fontSize: 9,
          padding: [2, 5],
          cursor: 'pointer',
        },
      ]
    }
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
  return edges
    .filter((e) => visible.has(e.source) && visible.has(e.target))
    .map((e, i) => {
      const v = edgeVisualFor(e.kind, t)
      // Edge labels: relation words for attach edges (subClassOf, instance),
      // the target property's local name for property edges.
      const label =
        e.kind === 'subClassOf'
          ? 'subClassOf'
          : e.kind === 'instance'
            ? 'instance'
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
        data: { kind: e.kind },
        style: {
          stroke: v.stroke,
          lineWidth: 1.5,
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

function buildData(
  nodes: GraphViewNode[],
  edges: GEdge[],
  kinds: KindFilter,
  showLabels: boolean,
  t: CanvasTokens,
): GraphData {
  const visible = visibleOf(nodes, kinds)
  const ids = new Map(visible.map((n) => [n.id, n.curie]))
  return {
    nodes: toG6Nodes(visible, t),
    edges: toG6Edges(edges, ids, showLabels, t),
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
}: {
  nodes: GraphViewNode[]
  edges: GEdge[]
  onSelect?: (eid: string) => void
  /** Badge (instance-count) click; default no-op. */
  onBadgeClick?: (eid: string) => void
  height?: number | string
  /** Optional entity to fit-view onto (overview focus param). */
  focusId?: string
  /** Whether the zoom/fit control cluster is rendered (default true). */
  showControls?: boolean
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
  const external = onShowLabelsChange !== undefined
  const showLabels = showLabelsProp ?? labelsFallback
  const setShowLabels = onShowLabelsChange ?? setLabelsFallback

  const containerRef = useRef<HTMLDivElement>(null)
  const graphRef = useRef<Graph | null>(null)
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
  const stateRef = useRef({ nodes, edges, showLabels, kinds, focusId })
  useEffect(() => {
    stateRef.current = { nodes, edges, showLabels, kinds, focusId }
  })

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
    // Saved positions switch the canvas off the auto pipeline: every node
    // needs an explicit spot, unvisited ones get deterministic fallbacks.
    const seeded: Record<string, Pt> = savedPositions ?? {}
    const useSaved = Object.keys(seeded).length > 0
    if (useSaved) {
      positionsRef.current = assignFallbackPositions(snap.nodes, snap.edges, seeded)
    } else {
      positionsRef.current = {}
    }
    const data = buildData(snap.nodes, snap.edges, snap.kinds, snap.showLabels, t)
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
    const graph = new Graph({
      container: el,
      autoResize: true,
      animation: false,
      theme: resolved,
      padding: [40, 40, 40, 40],
      data,
      // `false` (skip layout, use data x/y) is valid at runtime but missing
      // from G6's LayoutOptions type — see render()'s !options.layout branch.
      layout: (useSaved || autoLinear ? false : LAYOUT) as unknown as typeof LAYOUT,
      node: { type: (d: NodeData) => (d.data?.kind === 'instance' ? 'circle' : 'rect') },
      edge: { type: 'polyline' },
      behaviors: ['drag-canvas', 'zoom-canvas', 'drag-element'],
      plugins: [],
    })
    graphRef.current = graph

    graph.on('node:click', (e) => {
      const evt = e as IPointerEvent & { originalTarget?: HitShape | null }
      const id = evt.target ? (evt.target as unknown as { id: string }).id : undefined
      if (!id) return
      // The badge click (any badge-* shape) reveals instances; the body selects.
      if (hitBadge(evt.originalTarget, evt.target)) onBadgeClickRef.current?.(id)
      else onSelectRef.current?.(id)
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

    void graph.render().then(() => {
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
      if (snap.focusId) void graph.focusElement(snap.focusId)
      else void graph.fitView()
      setZoomPct(Math.round(graph.getZoom() * 100))
    })

    return () => {
      window.clearTimeout(saveTimerRef.current)
      graph.destroy()
      graphRef.current = null
    }
  }, [nodes, edges, resolved, savedPositions])

  /** Edge-label toggle without rebuilding (keeps dragged positions). */
  useEffect(() => {
    const g = graphRef.current
    if (!g) return
    const snap = stateRef.current
    const ids = new Map(visibleOf(snap.nodes, snap.kinds).map((n) => [n.id, n.curie]))
    g.updateEdgeData(toG6Edges(snap.edges, ids, showLabels, readCanvasTokens()))
    void g.draw()
  }, [showLabels])

  /** Kind filter via setData. In saved mode the newly visible nodes need
   *  positions too (deterministic fallbacks); in auto mode dagre reruns. */
  useEffect(() => {
    const g = graphRef.current
    if (!g) return
    const snap = stateRef.current
    const seeded = positionsRef.current
    const useSaved = Object.keys(seeded).length > 0
    const data = buildData(snap.nodes, snap.edges, kinds, snap.showLabels, readCanvasTokens())
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
        <div className="border-line bg-panel/90 rounded-ctl absolute right-2 bottom-2 flex items-center gap-1 border p-1 shadow-xs backdrop-blur">
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
        </div>
      )}

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
      </div>

      {!external && (
        <div className="border-line bg-panel/90 rounded-ctl absolute top-2 right-2 flex items-center gap-1 border p-1 shadow-xs backdrop-blur">
          <Toggle variant="outline" size="sm" pressed={showLabels} onPressedChange={setShowLabels}>
            {tr('canvas.labels')}
          </Toggle>
          <Toggle
            variant="outline"
            size="sm"
            pressed={kinds.classes && kinds.objectProps && kinds.dataProps}
            onPressedChange={() => setKinds(allKinds())}
          >
            {tr('canvas.all')}
          </Toggle>
          <ToggleGroup
            type="multiple"
            variant="outline"
            size="sm"
            value={activeKindKeys(kinds)}
            onValueChange={(v) => {
              // Empty selection would blank the canvas — keep the last dimension.
              if (v.length > 0) setKinds(kindsFromKeys(v))
            }}
          >
            <ToggleGroupItem value="classes">{tr('canvas.filterClasses')}</ToggleGroupItem>
            <ToggleGroupItem value="objectProps">{tr('canvas.filterObjects')}</ToggleGroupItem>
            <ToggleGroupItem value="dataProps">{tr('canvas.filterData')}</ToggleGroupItem>
          </ToggleGroup>
        </div>
      )}
    </div>
  )
}

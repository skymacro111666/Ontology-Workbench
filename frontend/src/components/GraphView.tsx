import { useEffect, useRef, useState } from 'react'
import { Graph } from '@antv/g6'
import type { EdgeData, GraphData, IPointerEvent, NodeData } from '@antv/g6'
import type { GEdge, GNode } from '../api/types'
import { localName } from '../lib/localName'
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

/** Legend copy tied to the visuals above so the two cannot drift apart. */
const LEGEND: { label: string; visual: { stroke: string; dash?: string } }[] = [
  { label: '子类（subClassOf）', visual: { stroke: 'var(--color-edge-sub)', dash: '6 5' } },
  { label: '对象属性', visual: { stroke: 'var(--color-primary)' } },
  { label: '数据属性', visual: { stroke: 'var(--color-ink-3)', dash: '1 4' } },
  { label: '实例', visual: { stroke: 'var(--color-ink-3)' } },
]

/** Two-stage layout pipeline: dagre fixes the ranks and sibling order
 *  top-down, then rank-wrap packs each rank's nodes into sub-rows of at
 *  most ~1700px so canvas width scales with the widest row, not the widest
 *  rank (54 siblings in one row would otherwise span ~9,800px). Orthogonal
 *  polyline edges read org-chart style and dodge the staggered rows. */
const LAYOUT = [
  { type: 'antv-dagre', rankdir: 'TB', nodesep: 16, ranksep: 90 },
  { type: 'rank-wrap', rowGap: 14, rankGap: 90, nodesep: 16, targetRowWidth: 1700 },
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
    const name = localName(n.curie)
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
      // Property edges label with the property they point at (local name —
      // prefix stripped, like node labels); subClassOf keeps the relation
      // word, the target is just a parent.
      const label =
        e.kind === 'subClassOf' ? 'subClassOf' : localName(visible.get(e.target) ?? e.kind)
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
}) {
  const resolved = useTheme().resolved
  const [labelsFallback, setLabelsFallback] = useState(true)
  const [kinds, setKinds] = useState<KindFilter>(defaultKindsProp ?? allKinds())
  const [zoomPct, setZoomPct] = useState(100)
  const external = onShowLabelsChange !== undefined
  const showLabels = showLabelsProp ?? labelsFallback
  const setShowLabels = onShowLabelsChange ?? setLabelsFallback

  const containerRef = useRef<HTMLDivElement>(null)
  const graphRef = useRef<Graph | null>(null)
  // onSelect through a ref so the build effect never re-runs for a new callback.
  const onSelectRef = useRef(onSelect)
  useEffect(() => {
    onSelectRef.current = onSelect
  })
  const onBadgeClickRef = useRef(onBadgeClick)
  useEffect(() => {
    onBadgeClickRef.current = onBadgeClick
  })
  // Latest state for the build effect (its deps are narrower than the state).
  // Updated in a render-following effect declared before everything else.
  const stateRef = useRef({ nodes, edges, showLabels, kinds, focusId })
  useEffect(() => {
    stateRef.current = { nodes, edges, showLabels, kinds, focusId }
  })

  /** (Re)build the graph on data or theme change. The class toggle is
   *  idempotent with ThemeProvider's own and guards first-paint ordering. */
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    document.documentElement.classList.toggle('dark', resolved === 'dark')
    const t = readCanvasTokens()
    const snap = stateRef.current
    const graph = new Graph({
      container: el,
      autoResize: true,
      animation: false,
      theme: resolved,
      padding: [40, 40, 40, 40],
      data: buildData(snap.nodes, snap.edges, snap.kinds, snap.showLabels, t),
      layout: LAYOUT,
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

    void graph.render().then(() => {
      if (snap.focusId) void graph.focusElement(snap.focusId)
      else void graph.fitView()
      setZoomPct(Math.round(graph.getZoom() * 100))
    })

    return () => {
      graph.destroy()
      graphRef.current = null
    }
  }, [nodes, edges, resolved])

  /** Edge-label toggle without rebuilding (keeps dragged positions). */
  useEffect(() => {
    const g = graphRef.current
    if (!g) return
    const snap = stateRef.current
    const ids = new Map(visibleOf(snap.nodes, snap.kinds).map((n) => [n.id, n.curie]))
    g.updateEdgeData(toG6Edges(snap.edges, ids, showLabels, readCanvasTokens()))
    void g.draw()
  }, [showLabels])

  /** Kind filter via setData (dagre is deterministic, so the view is stable). */
  useEffect(() => {
    const g = graphRef.current
    if (!g) return
    const snap = stateRef.current
    g.setData(buildData(snap.nodes, snap.edges, kinds, snap.showLabels, readCanvasTokens()))
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
            适配
          </button>
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
            <span className="text-ink-2 text-xs">{label}</span>
          </div>
        ))}
      </div>

      {!external && (
        <div className="border-line bg-panel/90 rounded-ctl absolute top-2 right-2 flex items-center gap-1 border p-1 shadow-xs backdrop-blur">
          <Toggle variant="outline" size="sm" pressed={showLabels} onPressedChange={setShowLabels}>
            标签
          </Toggle>
          <Toggle
            variant="outline"
            size="sm"
            pressed={kinds.classes && kinds.objectProps && kinds.dataProps}
            onPressedChange={() => setKinds(allKinds())}
          >
            全部
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
            <ToggleGroupItem value="classes">类</ToggleGroupItem>
            <ToggleGroupItem value="objectProps">对象</ToggleGroupItem>
            <ToggleGroupItem value="dataProps">数据</ToggleGroupItem>
          </ToggleGroup>
        </div>
      )}
    </div>
  )
}

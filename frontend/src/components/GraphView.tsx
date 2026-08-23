import {
  Controls,
  MarkerType,
  Panel,
  ReactFlow,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useEffect, useMemo, useState } from 'react'
import type { GEdge, GNode } from '../api/types'
import { useTheme } from '../theme/ThemeProvider'
import { Toggle } from '@/components/ui/toggle'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { cn } from '@/lib/utils'

/** Node extended with what the canvas renders beyond the API payload. */
export type GraphViewNode = GNode & {
  highlighted?: boolean
}

export type GraphViewFilter = 'all' | 'classes' | 'props'
type Filter = GraphViewFilter

/**
 * Edge semantics (spec §7.3), expressed through palette tokens so dark mode
 * rides the CSS overrides: subclass dashed purple, object property solid
 * indigo, data property dotted slate.
 */
const EDGE_VISUALS: Record<string, { stroke: string; dash?: string }> = {
  subClassOf: { stroke: 'var(--color-edge-sub)', dash: '6 5' },
  property: { stroke: 'var(--color-primary)' },
  datatype: { stroke: 'var(--color-ink-3)', dash: '1 4' },
}

/** Legend copy tied to the visuals above so the two cannot drift apart. */
const LEGEND: { label: string; visual: { stroke: string; dash?: string } }[] = [
  { label: '子类（subClassOf）', visual: EDGE_VISUALS.subClassOf },
  { label: '对象属性', visual: EDGE_VISUALS.property },
  { label: '数据属性', visual: EDGE_VISUALS.datatype },
]

type EntityNodeData = { curie: string; kind: string; subCount: number; highlighted?: boolean }
type EntityFlowNodeType = Node<EntityNodeData, 'entity'>

/** Rounded-rect node (mockup): classes get a solid grey border, property
 *  nodes a dashed violet one (kind encoded in the border), and the focused
 *  entity a 2px primary border + ★ — no ring. */
function EntityFlowNode({ data }: NodeProps<EntityFlowNodeType>) {
  const isProperty = data.kind === 'property'
  return (
    <div
      className={cn(
        'bg-panel text-ink relative flex items-center rounded-lg border px-2.5 py-1.5 text-[11.5px] shadow-xs',
        data.highlighted
          ? 'text-primary border-primary border-2 font-bold'
          : isProperty
            ? 'border-edge-sub border-dashed'
            : 'border-line border',
      )}
    >
      {data.curie}
      {data.highlighted && <span aria-hidden="true"> ★</span>}
      {data.subCount > 0 && (
        <span
          title="直接子类数"
          className={cn(
            'bg-primary text-primary-foreground absolute -top-2 -right-2 flex h-[16px] min-w-[18px] items-center justify-center rounded-lg px-1 text-[9px] font-bold',
            data.highlighted && 'border-panel border-2',
          )}
        >
          {data.subCount}
        </span>
      )}
    </div>
  )
}

const NODE_TYPES = { entity: EntityFlowNode }

/**
 * Fits the canvas onto one node once nodes are measured; must render inside
 * <ReactFlow> to reach the viewport instance. The timeout lets the first
 * layout pass settle (jsdom-safe no-op).
 */
function FocusFit({ id }: { id: string }) {
  const { fitView } = useReactFlow()
  useEffect(() => {
    const timer = setTimeout(() => {
      void fitView({ nodes: [{ id }], duration: 400, padding: 0.3 })
    }, 120)
    return () => clearTimeout(timer)
  }, [id, fitView])
  return null
}

const LAYER_GAP = 170
const COLUMN_GAP = 210

/**
 * Deterministic layered layout: depth = subClassOf distance to a top node;
 * nodes of one depth stack in input order. Property edges do not drive depth.
 */
function layeredPositions(nodes: GraphViewNode[], edges: GEdge[]): Map<string, { x: number; y: number }> {
  const parentOf = new Map<string, string>()
  for (const e of edges) {
    if (e.kind === 'subClassOf') parentOf.set(e.source, e.target)
  }
  const depth = new Map<string, number>()
  const visiting = new Set<string>()

  const depthOf = (id: string): number => {
    if (depth.has(id)) return depth.get(id) as number
    if (visiting.has(id)) return 0 // cycle guard
    visiting.add(id)
    const parent = parentOf.get(id)
    const d = parent && parent !== id ? depthOf(parent) + 1 : 0
    visiting.delete(id)
    depth.set(id, d)
    return d
  }
  for (const n of nodes) depthOf(n.id)

  const byDepth = new Map<number, GraphViewNode[]>()
  for (const n of nodes) {
    const d = depth.get(n.id) ?? 0
    byDepth.set(d, [...(byDepth.get(d) ?? []), n])
  }

  const pos = new Map<string, { x: number; y: number }>()
  for (const [d, layer] of byDepth) {
    layer.forEach((n, i) => {
      pos.set(n.id, { x: i * COLUMN_GAP, y: d * LAYER_GAP })
    })
  }
  return pos
}

/** Map API edges to React Flow edges: visibility, label, semantic styling.
 *  Each relation kind keeps its own line style AND a matching arrowhead so
 *  inheritance vs property links read apart at a glance (mockup §7.3). */
export function toFlowEdges(edges: GEdge[], visibleIds: Set<string>, showLabels: boolean): Edge[] {
  return edges
    .filter((e) => visibleIds.has(e.source) && visibleIds.has(e.target))
    .map((e, i) => {
      const visual = EDGE_VISUALS[e.kind] ?? EDGE_VISUALS.property
      return {
        id: `e${i}-${e.source}-${e.target}`,
        source: e.source,
        target: e.target,
        label: showLabels ? e.kind : undefined,
        style: { stroke: visual.stroke, strokeDasharray: visual.dash, strokeWidth: 1.5 },
        labelStyle: { fontFamily: 'var(--font-mono)', fontSize: 10, fill: '#64748B' },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: visual.stroke,
          width: 14,
          height: 14,
        },
      }
    })
}

/** Shared graph canvas: edge semantics, label toggle, type filter (spec §7.3).
 *  Label/filter controls render as an in-canvas overlay by default; passing
 *  the controlled props (in pairs) moves them to the caller's toolbar. */
export default function GraphView({
  nodes,
  edges,
  onSelect,
  height = '100%',
  focusId,
  showControls = true,
  showLabels: showLabelsProp,
  onShowLabelsChange,
  typeFilter: typeFilterProp,
  onTypeFilterChange,
}: {
  nodes: GraphViewNode[]
  edges: GEdge[]
  onSelect?: (eid: string) => void
  height?: number | string
  /** Optional entity to fit-view onto (overview focus param). */
  focusId?: string
  /** Whether the zoom/fit control cluster is rendered (default true). */
  showControls?: boolean
  /** Controlled edge-label switch; pass with onShowLabelsChange. */
  showLabels?: boolean
  onShowLabelsChange?: (v: boolean) => void
  /** Controlled node-kind filter; pass with onTypeFilterChange. */
  typeFilter?: Filter
  onTypeFilterChange?: (f: Filter) => void
}) {
  const resolved = useTheme().resolved
  const [labelsFallback, setLabelsFallback] = useState(true)
  const [filterFallback, setFilterFallback] = useState<Filter>('all')
  const external = onShowLabelsChange !== undefined || onTypeFilterChange !== undefined
  const showLabels = showLabelsProp ?? labelsFallback
  const setShowLabels = onShowLabelsChange ?? setLabelsFallback
  const filter = typeFilterProp ?? filterFallback
  const setFilter = onTypeFilterChange ?? setFilterFallback

  const visible = useMemo(() => {
    if (filter === 'all') return nodes
    const want = (kind: string) => (filter === 'props' ? kind === 'property' : kind !== 'property')
    return nodes.filter((n) => want(n.kind))
  }, [nodes, filter])

  /** Direct-subclass badge input: subClassOf edges pointing at each node. */
  const subCounts = useMemo(() => {
    const counts = new Map<string, number>()
    for (const e of edges) {
      if (e.kind === 'subClassOf') counts.set(e.target, (counts.get(e.target) ?? 0) + 1)
    }
    return counts
  }, [edges])

  const flowNodes: EntityFlowNodeType[] = useMemo(() => {
    const pos = layeredPositions(nodes, edges)
    return visible.map((n) => ({
      id: n.id,
      type: 'entity' as const,
      position: pos.get(n.id) ?? { x: 0, y: 0 },
      data: {
        curie: n.curie,
        kind: n.kind,
        subCount: subCounts.get(n.id) ?? 0,
        highlighted: n.highlighted,
      },
    }))
  }, [nodes, edges, visible, subCounts])

  const flowEdges = useMemo(() => {
    const visibleIds = new Set(visible.map((n) => n.id))
    return toFlowEdges(edges, visibleIds, showLabels)
  }, [edges, visible, showLabels])

  return (
    <div
      className="canvas-dots bg-canvas border-line rounded-card relative overflow-hidden border"
      style={{ height, width: '100%' }}
    >
      <ReactFlow
        nodes={flowNodes}
        edges={flowEdges}
        nodeTypes={NODE_TYPES}
        colorMode={resolved}
        fitView
        minZoom={0.15}
        proOptions={{ hideAttribution: true }}
        onNodeClick={(_, node) => onSelect?.(node.id)}
      >
        {showControls && <Controls position="bottom-right" showInteractive={false} />}
        {focusId && <FocusFit id={focusId} />}
        <Panel position="bottom-left">
          <div className="border-line bg-panel/90 rounded-ctl flex flex-col gap-1 border p-2 shadow-xs backdrop-blur">
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
        </Panel>
        {!external && (
          <Panel position="top-right">
          <div className="border-line bg-panel/90 rounded-ctl flex items-center gap-1 border p-1 shadow-xs backdrop-blur">
            <Toggle
              variant="outline"
              size="sm"
              pressed={showLabels}
              onPressedChange={setShowLabels}
            >
              标签
            </Toggle>
            <ToggleGroup
              type="single"
              variant="outline"
              size="sm"
              value={filter}
              onValueChange={(v) => {
                if (v) setFilter(v as Filter)
              }}
            >
              <ToggleGroupItem value="all">全部</ToggleGroupItem>
              <ToggleGroupItem value="classes">仅类</ToggleGroupItem>
              <ToggleGroupItem value="props">仅属性</ToggleGroupItem>
            </ToggleGroup>
          </div>
        </Panel>
        )}
      </ReactFlow>
    </div>
  )
}

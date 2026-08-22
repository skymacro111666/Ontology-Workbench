import {
  Controls,
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
  childCount?: number
  highlighted?: boolean
}

type Filter = 'all' | 'classes' | 'props'

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

type EntityNodeData = { curie: string; subCount: number; highlighted?: boolean }
type EntityFlowNodeType = Node<EntityNodeData, 'entity'>

/** Rounded-rect node: CURIE plus a top-right direct-subclass badge (spec §7.3). */
function EntityFlowNode({ data }: NodeProps<EntityFlowNodeType>) {
  return (
    <div
      className={cn(
        'border-line bg-panel text-ink relative rounded-lg border px-2.5 py-1 font-mono text-xs shadow-xs',
        data.highlighted && 'border-primary ring-primary/25 ring-2',
      )}
    >
      {data.curie}
      {data.subCount > 0 && (
        <span
          title="直接子类数"
          className="bg-primary text-primary-foreground absolute -top-2 -right-2 flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[10px] font-semibold"
        >
          {data.subCount}
        </span>
      )}
    </div>
  )
}

const NODE_TYPES = { entity: EntityFlowNode }

/**
 * useTheme throws outside a provider, and page-level tests mount consumers
 * bare; fall back to the .dark class ThemeProvider itself maintains on
 * <html>, which tracks the same resolved value.
 */
function useResolvedTheme(): 'light' | 'dark' {
  try {
    return useTheme().resolved
  } catch {
    return document.documentElement.classList.contains('dark') ? 'dark' : 'light'
  }
}

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

/** Map API edges to React Flow edges: visibility, label, semantic styling. */
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
        labelStyle: { fontFamily: 'var(--font-mono)', fontSize: 10 },
      }
    })
}

/** Shared graph canvas: edge semantics, label toggle, type filter (spec §7.3). */
export default function GraphView({
  nodes,
  edges,
  onSelect,
  height = '100%',
  focusId,
  showControls = true,
}: {
  nodes: GraphViewNode[]
  edges: GEdge[]
  onSelect?: (eid: string) => void
  height?: number | string
  /** Optional entity to fit-view onto (overview focus param). */
  focusId?: string
  /** Whether the zoom/fit control cluster is rendered (default true). */
  showControls?: boolean
}) {
  const resolved = useResolvedTheme()
  const [showLabels, setShowLabels] = useState(true)
  const [filter, setFilter] = useState<Filter>('all')

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
      data: { curie: n.curie, subCount: subCounts.get(n.id) ?? 0, highlighted: n.highlighted },
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
      </ReactFlow>
    </div>
  )
}

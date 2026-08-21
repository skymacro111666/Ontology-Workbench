import {
  Background,
  Controls,
  Panel,
  ReactFlow,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { Badge, Button, Segmented, theme } from 'antd'
import { useEffect, useId, useMemo, useState } from 'react'
import type { GEdge, GNode } from '../api/types'
import { useSystemTheme } from '../hooks/useSystemTheme'

/** Node extended with what the canvas renders beyond the API payload. */
export type GraphViewNode = GNode & {
  childCount?: number
  highlighted?: boolean
}

type Filter = 'all' | 'classes' | 'props'

/** Edge semantics (spec §7.3): shape + color per relation kind. */
const EDGE_VISUALS: Record<string, { stroke: string; strokeDasharray?: string }> = {
  subClassOf: { stroke: '#8B5CF6', strokeDasharray: '6 4' }, // dashed purple
  property: { stroke: '#0D9488' }, // solid teal
  datatype: { stroke: '#6B7280', strokeDasharray: '1 4' }, // dotted gray
}

type OntNodeData = { curie: string; childCount?: number; highlighted?: boolean }
type OntNodeType = Node<OntNodeData, 'ont'>

/** Rounded-rect node: CURIE + direct-subclass badge (spec §7.3). */
function OntNode({ data }: NodeProps<OntNodeType>) {
  const { token } = theme.useToken()
  return (
    <div
      className="ow-gnode"
      style={{
        padding: '4px 10px',
        borderRadius: token.borderRadius,
        border: `1px solid ${data.highlighted ? token.colorPrimary : token.colorBorder}`,
        background: token.colorBgContainer,
        boxShadow: data.highlighted ? `0 0 0 2px ${token.colorPrimary}33` : undefined,
        fontFamily: "'Fira Code', monospace",
        fontSize: 12,
      }}
    >
      {data.childCount !== undefined && data.childCount > 0 && (
        <Badge
          count={data.childCount}
          size="small"
          color={token.colorPrimary}
          offset={[6, -6]}
          style={{ position: 'absolute', top: -8, right: -10 }}
        />
      )}
      <span>{data.curie}</span>
    </div>
  )
}

const NODE_TYPES = { ont: OntNode }

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
        style: { stroke: visual.stroke, strokeDasharray: visual.strokeDasharray },
        labelStyle: { fontFamily: "'Fira Code', monospace", fontSize: 10 },
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
}: {
  nodes: GraphViewNode[]
  edges: GEdge[]
  onSelect: (eid: string) => void
  height?: number | string
  /** Optional entity to fit-view onto (overview focus param). */
  focusId?: string
}) {
  const { token } = theme.useToken()
  const dark = useSystemTheme()
  const reactId = useId()
  const [showLabels, setShowLabels] = useState(true)
  const [filter, setFilter] = useState<Filter>('all')

  const visible = useMemo(() => {
    if (filter === 'all') return nodes
    const want = (kind: string) => (filter === 'props' ? kind === 'property' : kind !== 'property')
    return nodes.filter((n) => want(n.kind))
  }, [nodes, filter])

  const flowNodes: OntNodeType[] = useMemo(() => {
    const pos = layeredPositions(nodes, edges)
    return visible.map((n) => ({
      id: n.id,
      type: 'ont' as const,
      position: pos.get(n.id) ?? { x: 0, y: 0 },
      data: { curie: n.curie, childCount: n.childCount, highlighted: n.highlighted },
    }))
  }, [nodes, edges, visible])

  const flowEdges = useMemo(() => {
    const visibleIds = new Set(visible.map((n) => n.id))
    return toFlowEdges(edges, visibleIds, showLabels)
  }, [edges, visible, showLabels])

  return (
    <div style={{ height, width: '100%', background: token.colorBgContainer, borderRadius: token.borderRadius }}>
      <ReactFlow
        key={reactId}
        nodes={flowNodes}
        edges={flowEdges}
        nodeTypes={NODE_TYPES}
        colorMode={dark ? 'dark' : 'light'}
        fitView
        minZoom={0.15}
        proOptions={{ hideAttribution: true }}
        onNodeClick={(_, node) => onSelect(node.id)}
      >
        <Background color={token.colorBorderSecondary} gap={24} />
        <Controls position="bottom-left" showInteractive={false} />
        {focusId && <FocusFit id={focusId} />}
        <Panel position="top-right">
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <Button
              size="small"
              aria-pressed={showLabels}
              onClick={() => setShowLabels((v) => !v)}
            >
              标签
            </Button>
            <Segmented<Filter>
              size="small"
              value={filter}
              onChange={(v) => setFilter(v)}
              options={[
                { label: '全部', value: 'all' },
                { label: '仅类', value: 'classes' },
                { label: '仅属性', value: 'props' },
              ]}
            />
          </div>
        </Panel>
      </ReactFlow>
    </div>
  )
}

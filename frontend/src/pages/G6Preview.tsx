import { useEffect, useRef, useState } from 'react'
import { Graph } from '@antv/g6'
import type { EdgeData, GraphData, IPointerEvent, NodeData } from '@antv/g6'
import { useTheme } from '../theme/ThemeProvider'
import { Toggle } from '@/components/ui/toggle'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'

/**
 * G6 5.x canvas sample (review artifact) — mirrors the current GraphView
 * feature set on @antv/g6 instead of @xyflow/react, plus the route-B
 * right-click menu (create on canvas / edit & delete on node / delete on
 * edge). Data is a built-in pizza sample shaped like the /overview payload;
 * nothing here touches the real workspace yet.
 */

type Kind = 'class' | 'property'
type EdgeKind = 'subClassOf' | 'property' | 'datatype'
type Filter = 'all' | 'classes' | 'props'
type LayoutMode = 'layered' | 'dagre' | 'radial'

interface DemoNode {
  id: string
  curie: string
  kind: Kind
}

interface DemoEdge {
  id: string
  source: string
  target: string
  kind: EdgeKind
}

/** Same visual semantics as GraphView's EDGE_VISUALS (spec §7.3); the strings
 *  stay as CSS vars because this map feeds the DOM legend only. */
const LEGEND: { label: string; stroke: string; dash?: string }[] = [
  { label: '子类（subClassOf）', stroke: 'var(--color-edge-sub)', dash: '6 5' },
  { label: '对象属性', stroke: 'var(--color-primary)' },
  { label: '数据属性', stroke: 'var(--color-ink-3)', dash: '1 4' },
]

const SAMPLE_NODES: DemoNode[] = [
  { id: 'pizza:Pizza', curie: 'pizza:Pizza', kind: 'class' },
  { id: 'pizza:NamedPizza', curie: 'pizza:NamedPizza', kind: 'class' },
  { id: 'pizza:VegetarianPizza', curie: 'pizza:VegetarianPizza', kind: 'class' },
  { id: 'pizza:PizzaTopping', curie: 'pizza:PizzaTopping', kind: 'class' },
  { id: 'pizza:MeatTopping', curie: 'pizza:MeatTopping', kind: 'class' },
  { id: 'pizza:CheeseTopping', curie: 'pizza:CheeseTopping', kind: 'class' },
  { id: 'pizza:VegetableTopping', curie: 'pizza:VegetableTopping', kind: 'class' },
  { id: 'pizza:PizzaBase', curie: 'pizza:PizzaBase', kind: 'class' },
  { id: 'pizza:ThinAndCrispyBase', curie: 'pizza:ThinAndCrispyBase', kind: 'class' },
  { id: 'pizza:Spiciness', curie: 'pizza:Spiciness', kind: 'class' },
  { id: 'pizza:hasTopping', curie: 'pizza:hasTopping', kind: 'property' },
  { id: 'pizza:hasBase', curie: 'pizza:hasBase', kind: 'property' },
  { id: 'pizza:hasSpiciness', curie: 'pizza:hasSpiciness', kind: 'property' },
]

const SAMPLE_EDGES: DemoEdge[] = [
  // subClassOf: source = child, target = parent (arrows point at the superclass).
  { id: 'e-np', source: 'pizza:NamedPizza', target: 'pizza:Pizza', kind: 'subClassOf' },
  { id: 'e-vp', source: 'pizza:VegetarianPizza', target: 'pizza:Pizza', kind: 'subClassOf' },
  { id: 'e-mt', source: 'pizza:MeatTopping', target: 'pizza:PizzaTopping', kind: 'subClassOf' },
  { id: 'e-ct', source: 'pizza:CheeseTopping', target: 'pizza:PizzaTopping', kind: 'subClassOf' },
  { id: 'e-vt', source: 'pizza:VegetableTopping', target: 'pizza:PizzaTopping', kind: 'subClassOf' },
  { id: 'e-tcb', source: 'pizza:ThinAndCrispyBase', target: 'pizza:PizzaBase', kind: 'subClassOf' },
  { id: 'e-ht', source: 'pizza:Pizza', target: 'pizza:hasTopping', kind: 'property' },
  { id: 'e-hb', source: 'pizza:Pizza', target: 'pizza:hasBase', kind: 'property' },
  { id: 'e-hs', source: 'pizza:PizzaTopping', target: 'pizza:hasSpiciness', kind: 'property' },
  { id: 'e-dt', source: 'pizza:hasSpiciness', target: 'pizza:Spiciness', kind: 'datatype' },
]

/** Design tokens resolved to concrete colors — G6 draws on canvas, where CSS
 *  variables are not resolvable, so values are read at (re)build time and the
 *  graph is rebuilt when the theme flips. */
function readTokens() {
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

type Tokens = ReturnType<typeof readTokens>

/** Edge visuals on canvas — mirrors GraphView's EDGE_VISUALS. */
function edgeVisuals(kind: EdgeKind, t: Tokens): { stroke: string; dash?: number[] } {
  if (kind === 'subClassOf') return { stroke: t.edgeSub, dash: [6, 5] }
  if (kind === 'datatype') return { stroke: t.ink3, dash: [1, 4] }
  return { stroke: t.primary }
}

const LAYER_GAP = 170
const COLUMN_GAP = 210

/** Deterministic layered layout, same algorithm as GraphView.layeredPositions:
 *  depth = subClassOf distance to a top node; property edges do not drive depth. */
function layeredPositions(nodes: DemoNode[], edges: DemoEdge[]): Map<string, { x: number; y: number }> {
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

  const byDepth = new Map<number, DemoNode[]>()
  for (const n of nodes) {
    const d = depth.get(n.id) ?? 0
    byDepth.set(d, [...(byDepth.get(d) ?? []), n])
  }
  const pos = new Map<string, { x: number; y: number }>()
  for (const [d, layer] of byDepth) {
    layer.forEach((n, i) => pos.set(n.id, { x: i * COLUMN_GAP, y: d * LAYER_GAP }))
  }
  return pos
}

/** Direct-subclass badge input: subClassOf edges pointing at each node. */
function computeSubCounts(edges: DemoEdge[]): Map<string, number> {
  const counts = new Map<string, number>()
  for (const e of edges) {
    if (e.kind === 'subClassOf') counts.set(e.target, (counts.get(e.target) ?? 0) + 1)
  }
  return counts
}

/** Card style (mockup): classes get a solid grey border, property nodes a
 *  dashed violet one; the focused entity gets a 2px primary border + ★. */
function nodeStyle(
  n: DemoNode,
  subCount: number,
  t: Tokens,
  focused: boolean,
  pos?: { x: number; y: number },
): Record<string, unknown> {
  const isProperty = n.kind === 'property'
  const w = Math.min(220, Math.max(96, Math.round(n.curie.length * 7.4 + 26)))
  const style: Record<string, unknown> = {
    size: [w, 32],
    radius: 8,
    fill: t.panel,
    stroke: focused ? t.primary : isProperty ? t.edgeSub : t.line,
    lineWidth: focused ? 2 : 1,
    shadowColor: 'rgba(15, 23, 42, 0.08)',
    shadowBlur: 4,
    labelText: focused ? `${n.curie} ★` : n.curie,
    labelFill: focused ? t.primary : t.ink,
    labelFontSize: 12,
    labelFontWeight: focused ? 700 : 400,
    labelPlacement: 'center',
  }
  if (isProperty && !focused) style.lineDash = [4, 3]
  if (pos) {
    style.x = pos.x
    style.y = pos.y
  }
  if (subCount > 0) {
    style.badges = [
      {
        text: String(subCount),
        placement: 'right-top',
        backgroundFill: t.primary,
        fill: t.primaryFg,
        fontSize: 9,
        padding: [2, 5],
      },
    ]
  }
  return style
}

function edgeStyle(kind: EdgeKind, showLabel: boolean, t: Tokens): Record<string, unknown> {
  const v = edgeVisuals(kind, t)
  return {
    stroke: v.stroke,
    lineWidth: 1.5,
    ...(v.dash ? { lineDash: v.dash } : {}),
    endArrow: true,
    endArrowSize: 8,
    endArrowFill: v.stroke,
    labelText: showLabel ? kind : '',
    labelFill: '#64748B',
    labelFontSize: 10,
    labelFontFamily: t.mono,
    labelBackground: true,
    labelBackgroundFill: t.panel,
    labelBackgroundOpacity: 0.9,
    labelBackgroundRadius: 3,
    labelPadding: [1, 4],
  }
}

function visibleOf(nodes: DemoNode[], filter: Filter): DemoNode[] {
  if (filter === 'all') return nodes
  const want = (kind: Kind) => (filter === 'props' ? kind === 'property' : kind !== 'property')
  return nodes.filter((n) => want(n.kind))
}

function buildGraphData(
  nodes: DemoNode[],
  edges: DemoEdge[],
  filter: Filter,
  focusedId: string | null,
  showLabels: boolean,
  t: Tokens,
): GraphData {
  const visible = visibleOf(nodes, filter)
  const ids = new Set(visible.map((n) => n.id))
  const pos = layeredPositions(nodes, edges)
  const subCounts = computeSubCounts(edges)
  const nodeData: NodeData[] = visible.map((n) => ({
    id: n.id,
    data: { kind: n.kind, curie: n.curie },
    style: nodeStyle(n, subCounts.get(n.id) ?? 0, t, n.id === focusedId, pos.get(n.id)),
  }))
  const edgeData: EdgeData[] = edges
    .filter((e) => ids.has(e.source) && ids.has(e.target))
    .map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      data: { kind: e.kind },
      style: edgeStyle(e.kind, showLabels, t),
    }))
  return { nodes: nodeData, edges: edgeData }
}

type Menu =
  | { x: number; y: number; kind: 'canvas' }
  | { x: number; y: number; kind: 'node'; id: string }
  | { x: number; y: number; kind: 'edge'; id: string }

const MENU_CLASS =
  'border-line bg-panel text-ink fixed z-50 min-w-[160px] cursor-pointer rounded-lg border py-1 text-[13px] shadow-lg'

export default function G6Preview() {
  const resolved = useTheme().resolved
  const [nodes, setNodes] = useState<DemoNode[]>(SAMPLE_NODES)
  const [edges, setEdges] = useState<DemoEdge[]>(SAMPLE_EDGES)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [showLabels, setShowLabels] = useState(true)
  const [filter, setFilter] = useState<Filter>('all')
  const [layoutMode, setLayoutMode] = useState<LayoutMode>('layered')
  const [minimapOn, setMinimapOn] = useState(false)
  const [menu, setMenu] = useState<Menu | null>(null)
  const [edit, setEdit] = useState<{ id: string; value: string } | null>(null)
  const [zoomPct, setZoomPct] = useState(100)

  const containerRef = useRef<HTMLDivElement>(null)
  const graphRef = useRef<Graph | null>(null)
  // Latest state for graph rebuilds that run inside effects with narrower deps.
  // Updated in a render-following effect (declared first so it settles before
  // the graph effects read it).
  const stateRef = useRef({ nodes, edges, selectedId, showLabels, filter })
  useEffect(() => {
    stateRef.current = { nodes, edges, selectedId, showLabels, filter }
  })

  const selected = nodes.find((n) => n.id === selectedId) ?? null

  /** (Re)build the graph. Rebuilt on theme / layout / minimap flips; data
   *  mutations go through the fine-grained APIs instead. */
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    // Idempotent with ThemeProvider's own toggle; guards the first-paint case
    // where this effect runs before the provider has applied the class.
    document.documentElement.classList.toggle('dark', resolved === 'dark')
    const t = readTokens()
    const snap = stateRef.current
    const graph = new Graph({
      container: el,
      autoResize: true,
      animation: false,
      theme: resolved,
      padding: [40, 40, 40, 40],
      data: buildGraphData(snap.nodes, snap.edges, snap.filter, snap.selectedId, snap.showLabels, t),
      // layered (parity): positions baked into node data, no layout engine.
      ...(layoutMode === 'dagre'
        ? { layout: { type: 'antv-dagre' as const, rankdir: 'TB', nodesep: 50, ranksep: 110 } }
        : layoutMode === 'radial'
          ? { layout: { type: 'radial' as const, unitRadius: 110 } }
          : {}),
      node: { type: 'rect' },
      edge: { type: 'line' },
      behaviors: ['drag-canvas', 'zoom-canvas', 'drag-element'],
      plugins: minimapOn ? [{ key: 'minimap', type: 'minimap', size: [180, 120] }] : [],
    })
    graphRef.current = graph

    const idOf = (e: IPointerEvent) => (e.target as unknown as { id: string }).id

    graph.on('node:click', (e) => setSelectedId(idOf(e as IPointerEvent)))
    graph.on('canvas:click', () => setSelectedId(null))
    graph.on('node:contextmenu', (e) => {
      const ev = e as IPointerEvent
      setMenu({ x: ev.client.x, y: ev.client.y, kind: 'node', id: idOf(ev) })
    })
    graph.on('edge:contextmenu', (e) => {
      const ev = e as IPointerEvent
      setMenu({ x: ev.client.x, y: ev.client.y, kind: 'edge', id: idOf(ev) })
    })
    graph.on('canvas:contextmenu', (e) => {
      const ev = e as IPointerEvent
      setMenu({ x: ev.client.x, y: ev.client.y, kind: 'canvas' })
    })

    void graph.render().then(() => {
      graph.fitView()
      setZoomPct(Math.round(graph.getZoom() * 100))
    })

    return () => {
      graph.destroy()
      graphRef.current = null
    }
  }, [resolved, layoutMode, minimapOn])

  /** Focus restyle (★ card) without rebuilding the graph. */
  useEffect(() => {
    const g = graphRef.current
    if (!g) return
    const t = readTokens()
    const snap = stateRef.current
    const subCounts = computeSubCounts(snap.edges)
    g.updateNodeData(
      visibleOf(snap.nodes, snap.filter).map((n) => ({
        id: n.id,
        style: nodeStyle(n, subCounts.get(n.id) ?? 0, t, n.id === snap.selectedId),
      })),
    )
    void g.draw()
  }, [selectedId])

  /** Edge-label toggle without rebuilding. */
  useEffect(() => {
    const g = graphRef.current
    if (!g) return
    g.updateEdgeData(
      stateRef.current.edges.map((e) => ({ id: e.id, style: edgeStyle(e.kind, showLabels, readTokens()) })),
    )
    void g.draw()
  }, [showLabels])

  /** Type filter via full setData (positions are deterministic, so the view
   *  does not jump; viewport is preserved by not re-fitting). */
  useEffect(() => {
    const g = graphRef.current
    if (!g) return
    const snap = stateRef.current
    g.setData(
      buildGraphData(snap.nodes, snap.edges, filter, snap.selectedId, snap.showLabels, readTokens()),
    )
    void g.render()
  }, [filter])

  /** Close the context menu on any click elsewhere. */
  useEffect(() => {
    if (!menu) return
    const close = () => setMenu(null)
    window.addEventListener('click', close)
    return () => window.removeEventListener('click', close)
  }, [menu])

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

  // --- Context-menu actions (route B: our own React menu) ---

  const createNode = (kind: Kind) => {
    const g = graphRef.current
    if (!g || menu?.kind !== 'canvas') return
    const [x, y] = g.getCanvasByClient([menu.x, menu.y])
    const n: DemoNode = {
      id: `demo:New${kind === 'class' ? 'Class' : 'Property'}${nodes.length + 1}`,
      curie: `demo:New${kind === 'class' ? 'Class' : 'Property'}${nodes.length + 1}`,
      kind,
    }
    setNodes((prev) => [...prev, n])
    g.addNodeData([{ id: n.id, data: { kind: n.kind }, style: nodeStyle(n, 0, readTokens(), false, { x, y }) }])
    setMenu(null)
  }

  const deleteNode = (id: string) => {
    const g = graphRef.current
    if (!g) return
    g.removeNodeData([id]) // connected edges are removed with the node
    setNodes((prev) => prev.filter((n) => n.id !== id))
    setEdges((prev) => prev.filter((e) => e.source !== id && e.target !== id))
    if (selectedId === id) setSelectedId(null)
    setMenu(null)
  }

  const deleteEdge = (id: string) => {
    const g = graphRef.current
    if (!g) return
    g.removeData({ edges: [id] })
    setEdges((prev) => prev.filter((e) => e.id !== id))
    setMenu(null)
  }

  const renameNode = () => {
    const g = graphRef.current
    if (!g || !edit || !edit.value.trim()) return
    g.updateNodeData([{ id: edit.id, style: { labelText: edit.value.trim() } }])
    setNodes((prev) => prev.map((n) => (n.id === edit.id ? { ...n, curie: edit.value.trim() } : n)))
    setEdit(null)
  }

  const ctlBtn =
    'border-line bg-panel/90 text-ink-2 hover:text-ink rounded-ctl border px-2 py-1 text-xs shadow-xs backdrop-blur'

  return (
    <div className="mx-auto flex h-full w-full max-w-[1200px] flex-col gap-3 px-4 py-4">
      <header className="flex flex-wrap items-center gap-2">
        <h1 className="text-sm font-bold">G6 5.x 画布样例</h1>
        <p className="text-ink-2 text-xs">
          功能对齐现有工作区画布 + 右键新建/编辑/删除。本页为内置示例数据，不影响现有页面。
        </p>
      </header>

      <div
        className="canvas-dots bg-canvas border-line relative min-h-0 flex-1 overflow-hidden rounded-lg border"
        onContextMenu={(e) => e.preventDefault()}
      >
        <div ref={containerRef} className="h-full w-full" />

        {/* Selection chip — stands in for the InspectorPanel reveal hook. */}
        {selected && (
          <div className="border-line bg-panel/90 rounded-ctl pointer-events-none absolute top-2 left-1/2 -translate-x-1/2 border px-3 py-1 text-xs shadow-xs backdrop-blur">
            已选中 <span className="text-primary font-mono">{selected.curie}</span>
            （真实迁移时将触发 InspectorPanel）
          </div>
        )}

        {/* Top-right overlay: label toggle + type filter + preview extras. */}
        <div className="border-line bg-panel/90 rounded-ctl absolute top-2 right-2 flex flex-col items-end gap-1 border p-1 shadow-xs backdrop-blur">
          <div className="flex items-center gap-1">
            <Toggle variant="outline" size="sm" pressed={showLabels} onPressedChange={setShowLabels}>
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
          <div className="flex items-center gap-1">
            <label className="text-ink-2 flex items-center gap-1 text-[11px]">
              布局
              <select
                className="border-line bg-panel text-ink rounded-ctl border px-1 py-0.5 text-[11px]"
                value={layoutMode}
                onChange={(e) => setLayoutMode(e.target.value as LayoutMode)}
              >
                <option value="layered">层叠（现状）</option>
                <option value="dagre">dagre</option>
                <option value="radial">radial</option>
              </select>
            </label>
            <Toggle variant="outline" size="sm" pressed={minimapOn} onPressedChange={setMinimapOn}>
              缩略图
            </Toggle>
          </div>
        </div>

        {/* Legend (parity with GraphView). */}
        <div className="border-line bg-panel/90 rounded-ctl absolute bottom-2 left-2 flex flex-col gap-1 border p-2 shadow-xs backdrop-blur">
          {LEGEND.map(({ label, stroke, dash }) => (
            <div key={label} className="flex items-center gap-2">
              <svg width="26" height="6" aria-hidden="true" className="shrink-0">
                <line x1="1" y1="3" x2="25" y2="3" stroke={stroke} strokeWidth="1.5" strokeDasharray={dash} />
              </svg>
              <span className="text-ink-2 text-xs">{label}</span>
            </div>
          ))}
        </div>

        {/* Zoom controls (parity with React Flow Controls). */}
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

        {/* Right-click menu: create on canvas, edit/delete on node, delete on edge. */}
        {menu && (
          <div className={MENU_CLASS} style={{ left: menu.x, top: menu.y }}>
            {menu.kind === 'canvas' && (
              <>
                <div className="text-ink-3 border-line cursor-default border-b px-3 py-1 text-[10px]">
                  画布
                </div>
                <button type="button" className="block w-full px-3 py-1.5 text-left hover:bg-canvas" onClick={() => createNode('class')}>
                  ＋ 新建类
                </button>
                <button type="button" className="block w-full px-3 py-1.5 text-left hover:bg-canvas" onClick={() => createNode('property')}>
                  ＋ 新建属性
                </button>
              </>
            )}
            {menu.kind === 'node' && (
              <>
                <div className="text-ink-3 border-line cursor-default border-b px-3 py-1 font-mono text-[10px]">
                  {nodes.find((n) => n.id === menu.id)?.curie}
                </div>
                <button
                  type="button"
                  className="block w-full px-3 py-1.5 text-left hover:bg-canvas"
                  onClick={() => {
                    setEdit({ id: menu.id, value: nodes.find((n) => n.id === menu.id)?.curie ?? '' })
                    setMenu(null)
                  }}
                >
                  ✎ 编辑
                </button>
                <button type="button" className="text-destructive block w-full px-3 py-1.5 text-left hover:bg-canvas" onClick={() => deleteNode(menu.id)}>
                  ✕ 删除
                </button>
              </>
            )}
            {menu.kind === 'edge' && (
              <>
                <div className="text-ink-3 border-line cursor-default border-b px-3 py-1 text-[10px]">
                  {edges.find((e) => e.id === menu.id)?.kind}
                </div>
                <button type="button" className="text-destructive block w-full px-3 py-1.5 text-left hover:bg-canvas" onClick={() => deleteEdge(menu.id)}>
                  ✕ 删除连线
                </button>
              </>
            )}
          </div>
        )}

        {/* Rename dialog (edit action). */}
        {edit && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setEdit(null)}>
            <div
              className="border-line bg-panel text-ink flex flex-col gap-2 rounded-lg border p-4 text-sm shadow-lg"
              onClick={(e) => e.stopPropagation()}
            >
              <label className="flex flex-col gap-1">
                重命名 CURIE
                <input
                  autoFocus
                  className="border-line bg-canvas rounded-ctl border px-2 py-1 font-mono text-sm"
                  value={edit.value}
                  onChange={(e) => setEdit({ ...edit, value: e.target.value })}
                  onKeyDown={(e) => e.key === 'Enter' && renameNode()}
                />
              </label>
              <div className="flex justify-end gap-2">
                <button type="button" className={ctlBtn} onClick={() => setEdit(null)}>
                  取消
                </button>
                <button type="button" className="rounded-ctl bg-primary text-primary-foreground px-3 py-1 text-xs" onClick={renameNode}>
                  确定
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

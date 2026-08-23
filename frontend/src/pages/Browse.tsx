import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { ApiErr, api } from '../api/client'
import type { EntityIR, NodesEdges, OntologyMeta, Ref } from '../api/types'
import ClassTree from '../components/ClassTree'
import EntityDetail from '../components/EntityDetail'
import GraphView, { type GraphViewFilter, type GraphViewNode } from '../components/GraphView'
import InspectorPanel from '../components/InspectorPanel'
import { useBrowseStore, type ViewMode } from '../stores/browseStore'
import { useRequestStore } from '../stores/requestStore'
import { Button } from '@/components/ui/button'
import { Toggle } from '@/components/ui/toggle'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'

const MAX_DEPTH = 32

/** Parse duration for the status bar: "870ms" under a second, "1.2s" above. */
function formatParseMs(ms: number): string {
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s`
}

/** One lineage level: renders its own ancestor chain first, then itself.
 *  An external (undeclared) ancestor renders as plain text and ends the chain.
 *  Each level's /entities call is a cached query, so revisits are instant. */
function Lineage({ oid, ancestor, depth }: { oid: string; ancestor: Ref; depth: number }) {
  const reveal = useBrowseStore((s) => s.reveal)
  const { data: ent, isError } = useQuery({
    queryKey: ['entity', oid, ancestor.eid],
    queryFn: () =>
      api.get<EntityIR>(`/api/ontologies/${oid}/entities/${encodeURIComponent(ancestor.eid)}`),
    retry: false,
  })

  if (isError) {
    return <span className="text-ink-3">{ancestor.curie}</span>
  }
  const parent = depth < MAX_DEPTH ? ent?.parents.find((p) => p.eid !== ancestor.eid) : undefined
  return (
    <>
      {ent && parent && (
        <>
          <Lineage oid={oid} ancestor={parent} depth={depth + 1} />
          <span className="text-ink-3 mx-1.5" aria-hidden="true">
            ›
          </span>
        </>
      )}
      <button
        type="button"
        className="text-primary hover:text-primary-hover truncate underline-offset-4 hover:underline"
        onClick={() => reveal(ancestor.eid)}
      >
        {ent?.curie ?? ancestor.curie}
      </button>
    </>
  )
}

/** Toolbar breadcrumb: root › … › selected; every level funnels through
 *  reveal() so the class tree follows the navigation (spec §7.4). */
function EntityBreadcrumb({ oid }: { oid: string }) {
  const selectedEid = useBrowseStore((s) => s.selectedEid)
  const { data: ent } = useQuery({
    enabled: selectedEid !== null,
    queryKey: ['entity', oid, selectedEid],
    queryFn: () =>
      api.get<EntityIR>(
        `/api/ontologies/${oid}/entities/${encodeURIComponent(selectedEid as string)}`,
      ),
    retry: false,
  })

  if (!selectedEid || !ent) return null
  const parent = ent.parents.find((p) => p.eid !== selectedEid)
  return (
    <nav aria-label="类谱系" className="flex min-w-0 items-baseline">
      {parent && (
        <>
          <Lineage oid={oid} ancestor={parent} depth={0} />
          <span className="text-ink-3 mx-1.5" aria-hidden="true">
            ›
          </span>
        </>
      )}
      <strong className="truncate">{ent.curie}</strong>
    </nav>
  )
}

/** Neighbors canvas for split/graph modes: /neighbors around the selection
 *  (ported from the deleted LocalGraph; the overview link moved to the toolbar). */
function NeighborsCanvas({
  oid,
  eid,
  showLabels,
  onShowLabelsChange,
  typeFilter,
  onTypeFilterChange,
}: {
  oid: string
  eid: string | null
  showLabels: boolean
  onShowLabelsChange: (v: boolean) => void
  typeFilter: GraphViewFilter
  onTypeFilterChange: (f: GraphViewFilter) => void
}) {
  const reveal = useBrowseStore((s) => s.reveal)
  const { data: nb, isError } = useQuery({
    enabled: eid !== null,
    queryKey: ['neighbors', oid, eid],
    queryFn: () =>
      api.get<NodesEdges>(
        `/api/ontologies/${oid}/entities/${encodeURIComponent(eid as string)}/neighbors`,
      ),
    retry: false,
  })
  // Shares the ['entity'] cache with the detail pane, breadcrumb, inspector.
  const { data: ent } = useQuery({
    enabled: eid !== null,
    queryKey: ['entity', oid, eid],
    queryFn: () =>
      api.get<EntityIR>(
        `/api/ontologies/${oid}/entities/${encodeURIComponent(eid as string)}`,
      ),
    retry: false,
  })

  if (eid === null) {
    return (
      <div className="border-line text-ink-3 rounded-card flex h-full items-center justify-center border border-dashed text-sm">
        先选择一个实体
      </div>
    )
  }
  if (isError) {
    // Mirrors EntityDetail: undeclared eids 404 on the neighbors endpoint.
    return (
      <div className="border-line text-ink-3 rounded-card flex h-full items-center justify-center border border-dashed text-sm">
        外部实体（未在本体中声明），无局部图
      </div>
    )
  }
  if (!nb) {
    return <div className="text-ink-3 py-16 text-center text-sm">加载中…</div>
  }

  // The self node ships kind:'self'; map it to its real type so the type
  // filter treats it as the class/property it actually is, and ring it as
  // the anchor of the neighborhood.
  const nodes: GraphViewNode[] = nb.nodes.map((n) => {
    if (n.id !== eid) return n
    return {
      ...n,
      kind: ent ? (ent.type === 'Class' ? 'class' : 'property') : n.kind,
      highlighted: true,
    }
  })

  return (
    <GraphView
      nodes={nodes}
      edges={nb.edges}
      onSelect={reveal}
      showLabels={showLabels}
      onShowLabelsChange={onShowLabelsChange}
      typeFilter={typeFilter}
      onTypeFilterChange={onTypeFilterChange}
    />
  )
}

/** Main workspace: four-zone grid — class tree, content (three view modes),
 *  resident inspector, status bar (spec §7.2). */
export default function Browse() {
  const { oid = '' } = useParams()
  const [sp] = useSearchParams()
  const eidParam = sp.get('eid')
  const viewMode = useBrowseStore((s) => s.viewMode)
  const setViewMode = useBrowseStore((s) => s.setViewMode)
  const selectedEid = useBrowseStore((s) => s.selectedEid)
  const setSelected = useBrowseStore((s) => s.setSelected)
  const ttlFocusEid = useBrowseStore((s) => s.ttlFocusEid)
  const ttlNonce = useBrowseStore((s) => s.ttlNonce)
  // Canvas controls shared by split/graph modes, kept across mode switches.
  const [showLabels, setShowLabels] = useState(true)
  const [typeFilter, setTypeFilter] = useState<GraphViewFilter>('all')
  // Last completed OK request, recorded by the api client (status bar).
  const lastRequest = useRequestStore((s) => s.lastRequest)
  // Deep link from the overview page (?eid=...) preselects the entity.
  useEffect(() => {
    if (eidParam) setSelected(eidParam)
  }, [eidParam, setSelected])
  const { data: meta, isError, error, refetch } = useQuery({
    queryKey: ['ontology', oid],
    queryFn: () => api.get<OntologyMeta>(`/api/ontologies/${oid}/meta`),
    retry: false,
  })

  if (isError) {
    const missing = error instanceof ApiErr && error.code === 'NOT_FOUND'
    return (
      <div className="border-line rounded-card text-ink-2 mx-auto mt-16 flex w-full max-w-[420px] flex-col items-center gap-3 border px-6 py-12 text-center">
        <div className="flex flex-col gap-1">
          <p className="font-medium">{missing ? '本体不存在' : '加载失败'}</p>
          <p className="text-sm">
            {missing ? '它可能已被删除，或不属于当前用户。' : '无法连接服务器，请确认后端已启动。'}
          </p>
        </div>
        {missing ? (
          <Button size="sm" asChild>
            <Link to="/">返回首页</Link>
          </Button>
        ) : (
          <Button size="sm" variant="outline" onClick={() => void refetch()}>
            重试
          </Button>
        )}
      </div>
    )
  }
  if (!meta) {
    return <div className="text-ink-3 py-16 text-center text-sm">加载中…</div>
  }

  return (
    <div className="grid h-full min-h-0 grid-cols-[264px_1fr_312px] grid-rows-[1fr_30px]">
      {/* Zone 1: class tree */}
      <aside className="border-line min-h-0 overflow-hidden border-r p-2">
        <ClassTree oid={oid} />
      </aside>

      {/* Zone 2: content — toolbar over the three view modes */}
      <section aria-label="内容区" className="border-line flex min-h-0 flex-col border-r">
        <div className="border-line flex shrink-0 items-center gap-3 border-b px-3 py-2">
          <ToggleGroup
            type="single"
            variant="outline"
            size="sm"
            value={viewMode}
            onValueChange={(v) => {
              if (v) setViewMode(v as ViewMode)
            }}
          >
            <ToggleGroupItem value="detail">详情</ToggleGroupItem>
            <ToggleGroupItem value="split">分屏</ToggleGroupItem>
            <ToggleGroupItem value="graph">图</ToggleGroupItem>
          </ToggleGroup>
          <div className="text-ink-2 min-w-0 flex-1 font-mono text-xs">
            <EntityBreadcrumb oid={oid} />
          </div>
          {viewMode !== 'detail' && (
            <>
              <Toggle
                variant="outline"
                size="sm"
                pressed={showLabels}
                onPressedChange={setShowLabels}
              >
                边标签
              </Toggle>
              <ToggleGroup
                type="single"
                variant="outline"
                size="sm"
                value={typeFilter}
                onValueChange={(v) => {
                  if (v) setTypeFilter(v as GraphViewFilter)
                }}
              >
                <ToggleGroupItem value="all">全部类型</ToggleGroupItem>
                <ToggleGroupItem value="classes">仅类</ToggleGroupItem>
                <ToggleGroupItem value="props">仅属性</ToggleGroupItem>
              </ToggleGroup>
            </>
          )}
          {selectedEid !== null && (
            <Button variant="outline" size="sm" className="shrink-0" asChild>
              <Link to={`/graph/${oid}?focus=${encodeURIComponent(selectedEid)}`}>
                在总览中查看
              </Link>
            </Button>
          )}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {viewMode === 'detail' && (
            // Re-keyed per inspector TTL request so the pane remounts with
            // its TTL tab open; nonce keeps repeated asks re-triggering.
            <EntityDetail
              oid={oid}
              eid={selectedEid}
              key={ttlFocusEid !== null && ttlFocusEid === selectedEid ? `ttl-${ttlNonce}` : 'default'}
            />
          )}
          {viewMode === 'split' && (
            <div className="flex h-full min-h-0 gap-4">
              <div className="min-w-0 flex-1">
                <NeighborsCanvas
                  oid={oid}
                  eid={selectedEid}
                  showLabels={showLabels}
                  onShowLabelsChange={setShowLabels}
                  typeFilter={typeFilter}
                  onTypeFilterChange={setTypeFilter}
                />
              </div>
              <div className="w-[400px] shrink-0 overflow-y-auto">
                <EntityDetail oid={oid} eid={selectedEid} compact />
              </div>
            </div>
          )}
          {viewMode === 'graph' && (
            <NeighborsCanvas
              oid={oid}
              eid={selectedEid}
              showLabels={showLabels}
              onShowLabelsChange={setShowLabels}
              typeFilter={typeFilter}
              onTypeFilterChange={setTypeFilter}
            />
          )}
        </div>
      </section>

      {/* Zone 3: resident inspector */}
      <aside className="min-h-0 overflow-hidden p-2">
        <InspectorPanel oid={oid} eid={selectedEid} />
      </aside>

      {/* Zone 4: status bar */}
      <footer className="border-line bg-panel text-ink-2 row-start-2 col-span-full flex items-center gap-2 border-t px-3 text-xs">
        <span className="font-mono">{meta.filename}</span>
        <span className="text-ink-3" aria-hidden="true">
          ·
        </span>
        <span>{meta.classCount} 类</span>
        <span className="text-ink-3" aria-hidden="true">
          ·
        </span>
        <span>{meta.propertyCount} 属性</span>
        <span className="text-ink-3" aria-hidden="true">
          ·
        </span>
        <span>{meta.axiomCount} 公理</span>
        <span className="text-ink-3" aria-hidden="true">
          ·
        </span>
        <span>解析 OK</span>
        {meta.parseMs != null && (
          <>
            <span className="text-ink-3" aria-hidden="true">
              ·
            </span>
            <span>{formatParseMs(meta.parseMs)}</span>
          </>
        )}
        {lastRequest && (
          <span className="text-ink-3 ml-auto flex shrink-0 items-center gap-1.5 font-mono">
            <span>{`${lastRequest.method} ${lastRequest.path}`}</span>
            <span>{Math.round(lastRequest.ms)}ms</span>
            <span>{lastRequest.requestId.slice(0, 6)}</span>
          </span>
        )}
      </footer>
    </div>
  )
}

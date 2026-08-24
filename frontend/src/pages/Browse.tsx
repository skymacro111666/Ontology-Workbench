import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { ApiErr, api } from '../api/client'
import type { OntologyMeta } from '../api/types'
import ClassTree from '../components/ClassTree'
import GraphOverview from '../components/GraphOverview'
import InspectorPanel from '../components/InspectorPanel'
import { useBrowseStore } from '../stores/browseStore'
import { Button } from '@/components/ui/button'

/** Parse duration for the status bar: "870ms" under a second, "1.2s" above. */
function formatParseMs(ms: number): string {
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s`
}

/** Workspace: four-zone grid — class tree, whole-ontology canvas (the single
 *  content view, controls live on the canvas overlay), resident inspector,
 *  status bar (mockup §5.4). Entity details live in the inspector column. */
export default function Browse() {
  const { oid = '' } = useParams()
  const [sp] = useSearchParams()
  const eidParam = sp.get('eid')
  const focusParam = sp.get('focus')
  const selectedEid = useBrowseStore((s) => s.selectedEid)
  const setSelected = useBrowseStore((s) => s.setSelected)
  // Deep links (?eid=… or the redirected /graph focus param) preselect.
  useEffect(() => {
    const target = focusParam ?? eidParam
    if (target) setSelected(target)
  }, [eidParam, focusParam, setSelected])
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

      {/* Zone 2: whole-ontology canvas with in-canvas controls */}
      <section aria-label="内容区" className="border-line min-h-0 border-r p-1">
        <GraphOverview oid={oid} focus={selectedEid} />
      </section>

      {/* Zone 3: resident inspector */}
      <aside className="min-h-0 overflow-hidden p-2">
        <InspectorPanel oid={oid} eid={selectedEid} />
      </aside>
      {/* Zone 4: status bar (mockup: breathing gaps, no dot separators) */}
      <footer className="border-line bg-panel text-ink-3 row-start-2 col-span-full flex items-center gap-3.5 border-t px-3.5 text-[11.5px]">
        <span className="font-mono">{meta.filename}</span>
        <span>{meta.classCount} 类</span>
        <span>{meta.propertyCount} 属性</span>
        <span>{meta.axiomCount} 公理</span>
        <span className="text-success flex items-center gap-1">
          <span aria-hidden="true">●</span>
          {meta.parseMs != null ? `解析 OK · ${formatParseMs(meta.parseMs)}` : '解析 OK'}
        </span>
      </footer>
    </div>
  )
}

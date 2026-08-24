import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { ApiErr, api } from '../api/client'
import type { NodesEdges } from '../api/types'
import { useBrowseStore } from '../stores/browseStore'
import GraphView, { type GraphViewNode } from './GraphView'
import { Button } from '@/components/ui/button'

/** Whole-ontology overview canvas — the workspace's single content view;
 *  degrades to the top 3 levels past 5000 entities (spec §7.5). Label switch
 *  and type filter render as the canvas's in-canvas overlay controls. */
export default function GraphOverview({
  oid,
  focus,
}: {
  oid: string
  focus?: string | null
}) {
  const reveal = useBrowseStore((s) => s.reveal)
  const { data, isError, error, refetch } = useQuery({
    queryKey: ['overview', oid],
    queryFn: () => api.get<NodesEdges>(`/api/ontologies/${oid}/overview`),
    retry: false,
  })

  const nodes: GraphViewNode[] = useMemo(
    () => (data?.nodes ?? []).map((n) => (n.id === focus ? { ...n, highlighted: true } : n)),
    [data, focus],
  )

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
        {!missing && (
          <Button size="sm" variant="outline" onClick={() => void refetch()}>
            重试
          </Button>
        )}
      </div>
    )
  }
  if (!data) {
    return <div className="text-ink-3 py-16 text-center text-sm">加载中…</div>
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-2">
      {data.truncated && (
        <div
          role="status"
          className="border-primary-border bg-primary-soft text-ink-2 rounded-ctl shrink-0 border px-3 py-2 text-sm"
        >
          本体超过 5000 实体，仅显示顶层 3 层（共 {data.totalCount}）
        </div>
      )}
      <div className="min-h-0 flex-1">
        <GraphView nodes={nodes} edges={data.edges} focusId={focus ?? undefined} onSelect={reveal} />
      </div>
    </div>
  )
}

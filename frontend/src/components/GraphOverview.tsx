import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { toast } from 'sonner'
import { ApiErr, api } from '../api/client'
import type { NodesEdges } from '../api/types'
import { localName } from '../lib/localName'
import { useBrowseStore } from '../stores/browseStore'
import { useUiStore } from '../stores/uiStore'
import GraphContextMenu, { type MenuItem } from './GraphContextMenu'
import GraphView, { type GraphViewNode } from './GraphView'
import type { Pt } from './layoutPositions'
import { Button } from '@/components/ui/button'

/** Menu rows for a right-click report: blank area offers creation, a class
 *  node additionally offers subclass/edit/delete, property nodes the
 *  property edit set (competitor parity, spec §4). */
function menuItems(
  menu: { targetId?: string; kind?: string; curie?: string },
  setEntityDialog: (s: {
    mode: 'class' | 'subclass' | 'objectProperty' | 'dataProperty' | 'editClass' | 'editProperty' | 'delete'
    parent?: string
    eid?: string
  }) => void,
  _close: () => void,
): MenuItem[] {
  if (!menu.targetId) {
    return [
      { key: 'class', label: '＋ 新建类', onSelect: () => setEntityDialog({ mode: 'class' }) },
    ]
  }
  if (menu.kind === 'property') {
    return [
      {
        key: 'edit',
        label: '编辑属性',
        onSelect: () => setEntityDialog({ mode: 'editProperty', eid: menu.targetId }),
      },
      {
        key: 'delete',
        label: `删除 ${menu.curie ? localName(menu.curie) : ''}`,
        danger: true,
        onSelect: () => setEntityDialog({ mode: 'delete', eid: menu.targetId }),
      },
    ]
  }
  return [
    {
      key: 'subclass',
      label: '新建子类',
      onSelect: () => setEntityDialog({ mode: 'subclass', parent: menu.targetId }),
    },
    {
      key: 'objectProperty',
      label: '新建对象属性',
      onSelect: () => setEntityDialog({ mode: 'objectProperty', parent: menu.targetId }),
    },
    {
      key: 'dataProperty',
      label: '新建数据属性',
      onSelect: () => setEntityDialog({ mode: 'dataProperty', parent: menu.targetId }),
    },
    {
      key: 'edit',
      label: '编辑类',
      onSelect: () => setEntityDialog({ mode: 'editClass', eid: menu.targetId }),
    },
    {
      key: 'delete',
      label: `删除 ${menu.curie ? localName(menu.curie) : ''}`,
      danger: true,
      onSelect: () => setEntityDialog({ mode: 'delete', eid: menu.targetId }),
    },
  ]
}

/** Whole-ontology overview canvas — the workspace's single content view;
 *  degrades to the top 3 levels past 5000 entities (spec §7.5). Label switch
 *  and kind filter render as the canvas's in-canvas overlay controls. The
 *  instance badge reveals a class's named individuals on demand. Opens
 *  class-only (defaultKinds) — properties join via the kind toggles / 全部. */
export default function GraphOverview({
  oid,
  focus,
}: {
  oid: string
  focus?: string | null
}) {
  const reveal = useBrowseStore((s) => s.reveal)
  const setEntityDialog = useUiStore((s) => s.setEntityDialog)
  const queryClient = useQueryClient()
  /** Open canvas context menu: blank-area or node right-click report. */
  const [menu, setMenu] = useState<{
    x: number
    y: number
    targetId?: string
    kind?: string
    curie?: string
  } | null>(null)
  const { data, isError, error, refetch } = useQuery({
    queryKey: ['overview', oid],
    queryFn: () => api.get<NodesEdges>(`/api/ontologies/${oid}/overview`),
    retry: false,
  })
  /** Saved canvas positions gate the mount: rendering before they arrive
   *  would auto-layout first and then never rebuild onto the saved spots. */
  const { data: layoutData, isPending: layoutPending } = useQuery({
    queryKey: ['layout', oid],
    queryFn: () => api.get<{ positions: Record<string, Pt> }>(`/api/ontologies/${oid}/layout`),
    retry: false,
  })
  const saveLayout = useMutation({
    mutationFn: (positions: Record<string, Pt>) =>
      api.put(`/api/ontologies/${oid}/layout`, { positions }),
    onError: () => toast.error('布局保存失败，稍后自动重试拖动即可'),
  })
  /** Remount nonce: bumping after 重排 forces GraphView back to the auto
   *  pipeline with a clean positionsRef. */
  const [layoutKey, setLayoutKey] = useState(0)
  const resetLayout = async () => {
    try {
      await api.del(`/api/ontologies/${oid}/layout`)
    } catch {
      // Reset is best-effort: an already-empty row is fine.
    }
    queryClient.setQueryData(['layout', oid], { positions: {} })
    setLayoutKey((k) => k + 1)
  }

  /** Revealed instances per class eid (badge toggle), null while loading. */
  const [revealed, setRevealed] = useState<Record<string, NodesEdges | null>>({})
  const toggleInstances = async (eid: string) => {
    if (eid in revealed) {
      setRevealed((m) => {
        const next = { ...m }
        delete next[eid]
        return next
      })
      return
    }
    setRevealed((m) => ({ ...m, [eid]: null }))
    try {
      const inst = await api.get<NodesEdges>(
        `/api/ontologies/${oid}/entities/${encodeURIComponent(eid)}/instances`,
      )
      setRevealed((m) => ({ ...m, [eid]: inst }))
    } catch {
      // Loading failed — drop the placeholder so the badge can be retried.
      setRevealed((m) => {
        const next = { ...m }
        delete next[eid]
        return next
      })
    }
  }

  const nodes: GraphViewNode[] = useMemo(
    () => [
      ...(data?.nodes ?? []).map((n) => (n.id === focus ? { ...n, highlighted: true } : n)),
      ...Object.values(revealed).flatMap((p) => (p?.nodes ?? []) as GraphViewNode[]),
    ],
    [data, focus, revealed],
  )
  const edges = useMemo(
    () => [...(data?.edges ?? []), ...Object.values(revealed).flatMap((p) => p?.edges ?? [])],
    [data, revealed],
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
  if (!data || layoutPending) {
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
      <div className="relative min-h-0 flex-1">
        <GraphView
          key={layoutKey}
          nodes={nodes}
          edges={edges}
          focusId={focus ?? undefined}
          onSelect={reveal}
          onBadgeClick={(eid) => void toggleInstances(eid)}
          defaultKinds={{ classes: true, objectProps: false, dataProps: false }}
          savedPositions={layoutData?.positions}
          onLayoutChange={(positions) => saveLayout.mutate(positions)}
          onResetLayout={() => void resetLayout()}
          onContextMenu={(info) => setMenu(info)}
        />
        {menu && (
          <GraphContextMenu
            x={menu.x}
            y={menu.y}
            onClose={() => setMenu(null)}
            items={menuItems(menu, setEntityDialog, () => setMenu(null))}
          />
        )}
      </div>
    </div>
  )
}

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { TFunction } from 'i18next'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { ApiErr, api } from '../api/client'
import type { AssertionEdgePayload, NodesEdges } from '../api/types'
import { localName } from '../lib/localName'
import { useBrowseStore } from '../stores/browseStore'
import { useUiStore } from '../stores/uiStore'
import GraphContextMenu, { type MenuItem } from './GraphContextMenu'
import GraphView, { type GraphViewNode } from './GraphView'
import type { Pt } from './layoutPositions'
import { Button } from '@/components/ui/button'

/** Menu rows for a right-click report: blank area offers creation, a class
 *  node additionally offers subclass/instance/edit/delete, property nodes the
 *  property edit set, instance nodes reveal/delete (competitor parity,
 *  spec §4). */
function menuItems(
  menu: { targetId?: string; kind?: string; curie?: string },
  setEntityDialog: (s: {
    mode: 'class' | 'subclass' | 'objectProperty' | 'dataProperty' | 'editClass' | 'editProperty' | 'delete'
    parent?: string
    eid?: string
  }) => void,
  setInstanceDialog: (s: { mode: 'create' | 'delete'; parent?: string; eid?: string } | null) => void,
  reveal: (eid: string) => void,
  t: TFunction,
): MenuItem[] {
  if (!menu.targetId) {
    return [
      { key: 'class', label: t('canvas.newClass'), onSelect: () => setEntityDialog({ mode: 'class' }) },
    ]
  }
  if (menu.kind === 'property') {
    return [
      {
        key: 'edit',
        label: t('canvas.editProperty'),
        onSelect: () => setEntityDialog({ mode: 'editProperty', eid: menu.targetId }),
      },
      {
        key: 'delete',
        label: t('canvas.deleteCurie', { name: menu.curie ? localName(menu.curie) : '' }),
        danger: true,
        onSelect: () => setEntityDialog({ mode: 'delete', eid: menu.targetId }),
      },
    ]
  }
  if (menu.kind === 'instance') {
    return [
      {
        key: 'edit',
        label: t('canvas.editInstance'),
        onSelect: () => reveal(menu.targetId as string),
      },
      {
        key: 'delete',
        label: t('canvas.deleteCurie', { name: menu.curie ? localName(menu.curie) : '' }),
        danger: true,
        onSelect: () => setInstanceDialog({ mode: 'delete', eid: menu.targetId }),
      },
    ]
  }
  return [
    {
      key: 'subclass',
      label: t('canvas.newSubclass'),
      onSelect: () => setEntityDialog({ mode: 'subclass', parent: menu.targetId }),
    },
    {
      key: 'instance',
      label: t('canvas.newInstance'),
      onSelect: () => setInstanceDialog({ mode: 'create', parent: menu.targetId }),
    },
    {
      key: 'objectProperty',
      label: t('canvas.newObjectProp'),
      onSelect: () => setEntityDialog({ mode: 'objectProperty', parent: menu.targetId }),
    },
    {
      key: 'dataProperty',
      label: t('canvas.newDataProp'),
      onSelect: () => setEntityDialog({ mode: 'dataProperty', parent: menu.targetId }),
    },
    {
      key: 'edit',
      label: t('canvas.editClass'),
      onSelect: () => setEntityDialog({ mode: 'editClass', eid: menu.targetId }),
    },
    {
      key: 'delete',
      label: t('canvas.deleteCurie', { name: menu.curie ? localName(menu.curie) : '' }),
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
  const { t } = useTranslation()
  const reveal = useBrowseStore((s) => s.reveal)
  const setEntityDialog = useUiStore((s) => s.setEntityDialog)
  const setInstanceDialog = useUiStore((s) => s.setInstanceDialog)
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
  /** A focus outside a TRUNCATED overview used to degrade silently (backlog
   *  T12①); say so once per (oid, focus). Non-truncated overviews stay quiet —
   *  an absent entity there is a dead link, and the inspector already reports
   *  it; in-app selections of off-canvas entities need no toast either. */
  const focusNotified = useRef<string | null>(null)
  useEffect(() => {
    if (!data || !focus || !data.truncated) return
    const key = `${oid}:${focus}`
    if (focusNotified.current === key) return
    if (!data.nodes.some((n) => n.id === focus)) {
      focusNotified.current = key
      toast.info(t('canvas.focusMissingToast'))
    }
  }, [data, focus, oid, t])
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
    onError: () => toast.error(t('canvas.layoutSaveFailed')),
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
  /** Revealed instance eids across all badges — the assertion-edge scope:
   *  the backend joins every pair whose both ends are expanded. */
  const revealedIds = useMemo(
    () => Object.values(revealed).flatMap((p) => (p?.nodes ?? []).map((n) => n.id)),
    [revealed],
  )
  const edgeKey = useMemo(() => [...revealedIds].sort().join(','), [revealedIds])
  const { data: aEdges } = useQuery({
    enabled: revealedIds.length >= 2,
    queryKey: ['assertion-edges', oid, edgeKey],
    queryFn: () =>
      api.get<AssertionEdgePayload>(
        `/api/ontologies/${oid}/assertion-edges?eids=${revealedIds.map(encodeURIComponent).join(',')}`,
      ),
    retry: false,
  })
  /** A truncated assertion-edge payload warns once per revealed set — the
   *  same cached payload re-notifying on collapse/expand would nag. */
  const truncNotified = useRef<string | null>(null)
  useEffect(() => {
    if (!aEdges?.truncated || truncNotified.current === edgeKey) return
    truncNotified.current = edgeKey
    toast.info(t('canvas.assertionTruncated'))
  }, [aEdges, edgeKey, t])
  const edges = useMemo(
    () => [
      ...(data?.edges ?? []),
      ...Object.values(revealed).flatMap((p) => p?.edges ?? []),
      ...(aEdges?.edges ?? []).map((e) => ({ ...e, kind: 'assertion' as const })),
    ],
    [data, revealed, aEdges],
  )

  if (isError) {
    const missing = error instanceof ApiErr && error.code === 'NOT_FOUND'
    return (
      <div className="border-line rounded-card text-ink-2 mx-auto mt-16 flex w-full max-w-[420px] flex-col items-center gap-3 border px-6 py-12 text-center">
        <div className="flex flex-col gap-1">
          <p className="font-medium">{missing ? t('browse.notFound') : t('shell.loadFailed')}</p>
          <p className="text-sm">
            {missing ? t('browse.missingHint') : t('browse.offline')}
          </p>
        </div>
        {!missing && (
          <Button size="sm" variant="outline" onClick={() => void refetch()}>
            {t('common.retry')}
          </Button>
        )}
      </div>
    )
  }
  if (!data || layoutPending) {
    return <div className="text-ink-3 py-16 text-center text-sm">{t('common.loading')}</div>
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-2">
      {data.truncated && (
        <div
          role="status"
          className="border-primary-border bg-primary-soft text-ink-2 rounded-ctl shrink-0 border px-3 py-2 text-sm"
        >
          {t('canvas.truncatedNote', { total: data.totalCount })}
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
            items={menuItems(menu, setEntityDialog, setInstanceDialog, reveal, t)}
          />
        )}
      </div>
    </div>
  )
}

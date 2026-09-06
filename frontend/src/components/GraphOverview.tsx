import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { TFunction } from 'i18next'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { ApiErr, api } from '../api/client'
import type { AssertionEdgePayload, EntityIR, NodesEdges } from '../api/types'
import { localName } from '../lib/localName'
import { useBrowseStore } from '../stores/browseStore'
import { useUiStore } from '../stores/uiStore'
import GraphContextMenu, { type MenuItem } from './GraphContextMenu'
import GraphView, { type GraphViewNode } from './GraphView'
import { insertChildren } from './insertLayout'
import { useLint } from './LintPanel'
import LintSettingsDialog from './LintSettingsDialog'
import type { Pt } from './layoutPositions'
import { Button } from '@/components/ui/button'
import { Toggle } from '@/components/ui/toggle'

/** Menu rows for a right-click report: blank area offers creation, a class
 *  node additionally offers subclass/instance/edit/delete, property nodes the
 *  property edit set, instance nodes reveal/auto-edit/delete (competitor
 *  parity, spec §4). */
function menuItems(
  menu: { targetId?: string; kind?: string; curie?: string },
  setEntityDialog: (s: {
    mode: 'class' | 'subclass' | 'objectProperty' | 'dataProperty' | 'editClass' | 'editProperty' | 'delete'
    parent?: string
    eid?: string
  }) => void,
  setInstanceDialog: (s: { mode: 'create' | 'delete'; parent?: string; eid?: string } | null) => void,
  reveal: (eid: string) => void,
  setAutoEdit: (eid: string) => void,
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
        // Reveal + flag auto-edit: the detail opens straight in edit mode,
        // not the view state a plain (left-click) select already shows.
        onSelect: () => {
          reveal(menu.targetId as string)
          setAutoEdit(menu.targetId as string)
        },
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

/** Descendants an eid's collapse must remove: every node reachable from it
 *  against the collected expand edges (child→parent direction), not the eid
 *  itself — nested expanded folds ride along through their root edges. */
function collectSubtree(root: string, expanded: Record<string, NodesEdges>): Set<string> {
  const out = new Set<string>()
  const childEdges = Object.values(expanded).flatMap((p) => p.edges)
  const stack = [root]
  while (stack.length) {
    const cur = stack.pop()!
    for (const e of childEdges) {
      if (e.target === cur && !out.has(e.source)) {
        out.add(e.source)
        stack.push(e.source)
      }
    }
  }
  return out
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
  const setInstanceAutoEdit = useUiStore((s) => s.setInstanceAutoEdit)
  const queryClient = useQueryClient()
  /** B3 lint slices: the button rides the control cluster, the drawer
   *  anchors to the relative canvas container (not the cluster box). The
   *  settings dialog is Task 19's — opened from the drawer's 设置 link. */
  const [settingsOpen, setSettingsOpen] = useState(false)
  const lint = useLint(oid, () => setSettingsOpen(true))
  /** Open canvas context menu: blank-area or node right-click report. */
  const [menu, setMenu] = useState<{
    x: number
    y: number
    targetId?: string
    kind?: string
    curie?: string
  } | null>(null)
  /** Session-level deprecated visibility (D0): off by default, never
   *  persisted — the overview refetches through the includeDeprecated param. */
  const [showDeprecated, setShowDeprecated] = useState(false)
  /** Session-level tiering override (spec §3): 'auto' follows liveCount,
   *  the toggles force the legacy walk or the folded view. */
  const [viewOverride, setViewOverride] = useState<'auto' | 'full' | 'progressive'>('auto')
  const { data, isError, error, refetch } = useQuery({
    queryKey: ['overview', oid, showDeprecated, viewOverride],
    queryFn: () =>
      api.get<NodesEdges>(
        `/api/ontologies/${oid}/overview?includeDeprecated=${showDeprecated}&view=${viewOverride}`,
      ),
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

  /** Progressive canvas (spec §5): expanded fold payloads per eid. Expanding
   *  fetches /expand and merges; collapsing collects the expanded subtree
   *  (along the expand edges, nested folds included) and removes it. */
  const [expanded, setExpanded] = useState<Record<string, NodesEdges>>({})
  /** Session-local insert coordinates for expanded children (spec §5.3):
   *  keeps a SAVED canvas stable across expands — the new row lands under
   *  the parent's saved spot instead of dagre re-flowing everything. The
   *  auto pipeline (nothing saved) keeps re-running dagre instead. */
  const [insertedPos, setInsertedPos] = useState<Record<string, Pt>>({})
  const toggleFold = async (eid: string, folded: boolean) => {
    if (!folded) {
      if (anchor && eid === anchor.self.id) {
        // Collapsing the anchor root exits the anchored view: back to the
        // overview's folded root layer.
        setAnchor(null)
        setExpanded({})
        return
      }
      const doomed = collectSubtree(eid, expanded)
      setExpanded((prev) => {
        const next = { ...prev }
        delete next[eid]
        for (const d of doomed) delete next[d]
        return next
      })
      // Instances revealed inside the folded-away subtree leave with it.
      setRevealed((prev) => {
        const next = { ...prev }
        for (const d of doomed) delete next[d]
        return next
      })
      return
    }
    try {
      const payload = await api.get<NodesEdges>(
        `/api/ontologies/${oid}/entities/${encodeURIComponent(eid)}/expand`,
      )
      setExpanded((prev) => ({ ...prev, [eid]: payload }))
      const saved = layoutData?.positions ?? {}
      const parentPt = saved[eid] ?? insertedPos[eid]
      if (parentPt) {
        const known = { ...saved, ...insertedPos }
        const fresh = insertChildren(
          parentPt,
          payload.nodes.map((n) => n.id),
          known,
        )
        setInsertedPos((prev) => ({ ...prev, ...fresh }))
      }
    } catch {
      // Failed expand: no state moved, the badge stays a retry-able +.
    }
  }
  /** Progressive reveal anchor (spec §5.4): revealing an entity the folded
   *  view cannot show (search hit deep in a collapsed subtree) resets the
   *  canvas to that entity + its foldable children instead of a dead end.
   *  ClassTree owns revealEid's tree walk and clears it; this side reads it
   *  without consuming. Classes only — instances never ride the fold view. */
  const [anchor, setAnchor] = useState<{
    self: GraphViewNode
    payload: NodesEdges
  } | null>(null)
  const revealEid = useBrowseStore((s) => s.revealEid)
  useEffect(() => {
    if (!revealEid || data?.mode !== 'progressive') return
    let cancelled = false
    ;(async () => {
      try {
        const [ent, payload] = await Promise.all([
          api.get<EntityIR>(
            `/api/ontologies/${oid}/entities/${encodeURIComponent(revealEid)}`,
          ),
          api.get<NodesEdges>(
            `/api/ontologies/${oid}/entities/${encodeURIComponent(revealEid)}/expand`,
          ),
        ]) as [EntityIR, NodesEdges]
        if (cancelled || ent.type !== 'Class') return
        setAnchor({
          self: {
            id: ent.eid,
            curie: ent.curie,
            label: ent.label,
            kind: 'class',
            folded: true,
            subtreeSize: (payload.totalCount ?? 0) + 1,
          },
          payload,
        })
        // Reset the exploration state: the new anchor starts a fresh canvas.
        setExpanded({})
        setInsertedPos({})
      } catch {
        // Off-canvas fetch failed: keep the current view.
      }
    })()
    return () => {
      cancelled = true
    }
  }, [revealEid, data?.mode, oid])

  /** The effective fold payloads: the anchor's own expand rides first so
   *  its children merge exactly like a manual fold click. */
  const expandedAll = useMemo(
    () =>
      anchor ? { [anchor.self.id]: anchor.payload, ...expanded } : expanded,
    [anchor, expanded],
  )
  /** Effective expanded ids including the anchor (its badge reads −). */
  const foldedIdsAll = useMemo(() => new Set(Object.keys(expandedAll)), [expandedAll])
  const nodes: GraphViewNode[] = useMemo(() => {
    /** Merge by id: a multi-type instance appears in several class payloads
     *  (james is both Manager and FullTimeEmployee) — feeding G6 duplicate
     *  node ids whited the page on the second reveal. First payload wins. */
    const byId = new Map<string, GraphViewNode>()
    const base: GraphViewNode[] = anchor ? [anchor.self] : (data?.nodes ?? [])
    for (const n of base) byId.set(n.id, n)
    for (const p of Object.values(expandedAll))
      for (const n of p.nodes as GraphViewNode[]) if (!byId.has(n.id)) byId.set(n.id, n)
    for (const p of Object.values(revealed))
      for (const n of (p?.nodes ?? []) as GraphViewNode[]) if (!byId.has(n.id)) byId.set(n.id, n)
    // Bucket labels are i18n, not data: the backend ships label:{} and the
    // canvas's name fallback (localName of the sentinel curie) would read
    // "__deprecated__" — inject the translated bucket name (copied, never
    // mutating the query-cache payload objects in place).
    for (const n of byId.values()) {
      if (n.kind === 'deprecatedBucket')
        byId.set(n.id, { ...n, label: { '': t('canvas.deprecatedBucket') } })
      else if (n.kind === 'prefixBucket')
        byId.set(n.id, { ...n, label: { '': t('canvas.prefixBucket') } })
    }
    if (focus) {
      const hit = byId.get(focus)
      if (hit) byId.set(focus, { ...hit, highlighted: true })
    }
    return [...byId.values()]
  }, [data, anchor, focus, revealed, expandedAll, t])
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
      ...Object.values(expanded).flatMap((p) => p.edges),
      ...Object.values(revealed).flatMap((p) => p?.edges ?? []),
      ...(aEdges?.edges ?? []).map((e) => ({ ...e, kind: 'assertion' as const })),
    ],
    [data, revealed, aEdges, expandedAll, anchor],
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
      {/* Hidden-deprecated count hint: only while the filter keeps them out. */}
      {!showDeprecated && (data.deprecatedCount ?? 0) > 0 && (
        <div
          role="status"
          className="border-primary-border bg-primary-soft text-ink-2 rounded-ctl shrink-0 border px-3 py-2 text-sm"
        >
          {t('canvas.deprecatedHidden', { count: data.deprecatedCount })}
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
          onFoldClick={(eid, folded) => void toggleFold(eid, folded)}
          foldedIds={foldedIdsAll}
          defaultKinds={{ classes: true, objectProps: false, dataProps: false }}
          savedPositions={
            layoutData ? { ...layoutData.positions, ...insertedPos } : undefined
          }
          onLayoutChange={(positions) => saveLayout.mutate(positions)}
          onResetLayout={() => void resetLayout()}
          onContextMenu={(info) => setMenu(info)}
          extraControls={
            <>
              {lint.button}
              <Toggle
                variant="outline"
                size="sm"
                className="h-6 min-w-0 px-2 text-xs"
                pressed={viewOverride === 'full'}
                onPressedChange={(v) => setViewOverride(v ? 'full' : 'auto')}
              >
                {t('canvas.viewFull')}
              </Toggle>
              <Toggle
                variant="outline"
                size="sm"
                className="h-6 min-w-0 px-2 text-xs"
                pressed={viewOverride === 'progressive'}
                onPressedChange={(v) => setViewOverride(v ? 'progressive' : 'auto')}
              >
                {t('canvas.viewProgressive')}
              </Toggle>
              <Toggle
                variant="outline"
                size="sm"
                className="h-6 min-w-0 px-2 text-xs"
                pressed={showDeprecated}
                onPressedChange={setShowDeprecated}
              >
                {t('canvas.showDeprecated')}
              </Toggle>
            </>
          }
        />
        {lint.drawer}
        <LintSettingsDialog oid={oid} open={settingsOpen} onOpenChange={setSettingsOpen} />
        {menu && (
          <GraphContextMenu
            x={menu.x}
            y={menu.y}
            onClose={() => setMenu(null)}
            items={menuItems(
              menu,
              setEntityDialog,
              setInstanceDialog,
              reveal,
              setInstanceAutoEdit,
              t,
            )}
          />
        )}
      </div>
    </div>
  )
}

import { useQuery } from '@tanstack/react-query'
import { lazy, Suspense, useEffect } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { useTranslation } from 'react-i18next'
import { ApiErr, api } from '../api/client'
import type { OntologyMeta } from '../api/types'
import ClassTree from '../components/ClassTree'
import EntityDialogs from '../components/EntityDialogs'
import InspectorPanel from '../components/InspectorPanel'
// Zone-2 views load lazily: each drags a heavy editor/graph stack (G6,
// CodeMirror) that must not sit in the entry chunk.
const GraphOverview = lazy(() => import('../components/GraphOverview'))
const SourceView = lazy(() => import('../components/SourceView'))
import { useBrowseStore } from '../stores/browseStore'
import { useUiStore, type BrowseView } from '../stores/uiStore'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

/** Parse duration for the status bar: "870ms" under a second, "1.2s" above. */
function formatParseMs(ms: number): string {
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s`
}

/** Sidebar column templates per collapse state — literal class strings so
 *  Tailwind emits them; a collapsed sidebar shrinks to a 24px rail. */
const GRAPH_COLS = {
  both: 'grid-cols-[264px_1fr_312px]',
  left: 'grid-cols-[24px_1fr_312px]',
  right: 'grid-cols-[264px_1fr_24px]',
  none: 'grid-cols-[24px_1fr_24px]',
} as const
const TEXT_COLS = {
  both: 'grid-cols-[264px_1fr]',
  left: 'grid-cols-[24px_1fr]',
} as const

const colsFor = (view: BrowseView, lc: boolean, rc: boolean): string =>
  view === 'graph'
    ? lc && rc
      ? GRAPH_COLS.none
      : lc
        ? GRAPH_COLS.left
        : rc
          ? GRAPH_COLS.right
          : GRAPH_COLS.both
    : lc
      ? TEXT_COLS.left
      : TEXT_COLS.both

/** Chevron chrome shared by the rail and collapse buttons (matches the
 *  canvas control cluster). */
const railBtn =
  'border-line bg-panel/90 text-ink-2 hover:text-ink rounded-ctl border px-1 py-0.5 text-xs shadow-xs backdrop-blur'

/** Collapsed rail: a 24px strip with the expand chevron at its top. */
function Rail({ label, chev, onExpand }: { label: string; chev: '«' | '»'; onExpand: () => void }) {
  return (
    <div className="flex h-full w-6 items-start justify-center pt-2">
      <button
        type="button"
        className={railBtn}
        aria-label={label}
        aria-expanded={false}
        onClick={onExpand}
      >
        {chev}
      </button>
    </div>
  )
}

/** Workspace: four-zone grid — class tree, whole-ontology canvas (the single
 *  content view, controls live on the canvas overlay), resident inspector,
 *  status bar (mockup §5.4). Entity details live in the inspector column. */
export default function Browse() {
  const { t } = useTranslation()
  const { oid = '' } = useParams()
  const [sp] = useSearchParams()
  const eidParam = sp.get('eid')
  const focusParam = sp.get('focus')
  const selectedEid = useBrowseStore((s) => s.selectedEid)
  const setSelected = useBrowseStore((s) => s.setSelected)
  const browseView = useUiStore((s) => s.browseView)
  const leftCollapsed = useUiStore((s) => s.leftCollapsed)
  const rightCollapsed = useUiStore((s) => s.rightCollapsed)
  const setLeftCollapsed = useUiStore((s) => s.setLeftCollapsed)
  const setRightCollapsed = useUiStore((s) => s.setRightCollapsed)
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
          <p className="font-medium">{missing ? t('browse.notFound') : t('shell.loadFailed')}</p>
          <p className="text-sm">
            {missing ? t('browse.missingHint') : t('browse.offline')}
          </p>
        </div>
        {missing ? (
          <Button size="sm" asChild>
            <Link to="/">{t('browse.backHome')}</Link>
          </Button>
        ) : (
          <Button size="sm" variant="outline" onClick={() => void refetch()}>
            {t('common.retry')}
          </Button>
        )}
      </div>
    )
  }
  if (!meta) {
    return <div className="text-ink-3 py-16 text-center text-sm">{t('common.loading')}</div>
  }
  return (
    <div
      className={cn(
        'grid h-full min-h-0 grid-rows-[1fr_30px] transition-[grid-template-columns] duration-200',
        colsFor(browseView, leftCollapsed, rightCollapsed),
      )}
    >
      {/* Zone 1: class tree. Collapses to a left rail; the panel stays
       *  mounted (display-hidden) so tree expansion state survives. */}
      <aside className="border-line relative min-h-0 overflow-hidden border-r">
        {leftCollapsed ? (
          <Rail label={t('browse.expandTree')} chev="»" onExpand={() => setLeftCollapsed(false)} />
        ) : (
          <button
            type="button"
            className={cn(railBtn, 'absolute top-1/2 right-0 -translate-y-1/2 rounded-r-none border-r-0')}
            aria-label={t('browse.collapseTree')}
            aria-expanded
            onClick={() => setLeftCollapsed(true)}
          >
            «
          </button>
        )}
        <div className={cn('h-full p-2', leftCollapsed && 'hidden')}>
          <ClassTree oid={oid} />
        </div>
      </aside>

      {/* Zone 2: whole-ontology canvas (graph) or source text (text),
       *  per the topbar's 图形/文本 switch (spec: single content view). */}
      <section aria-label={t('browse.contentArea')} className="border-line min-h-0 border-r p-1">
        <Suspense fallback={<div className="text-ink-3 py-16 text-center text-sm">{t('common.loading')}</div>}>
          {browseView === 'graph' ? (
            <GraphOverview oid={oid} focus={selectedEid} />
          ) : (
            <SourceView oid={oid} />
          )}
        </Suspense>
      </section>

      {/* Zone 3: resident inspector (graph mode only). Collapses to a
       *  right rail the same way; text mode drops the column entirely. */}
      {browseView === 'graph' && (
        <aside className="relative min-h-0 overflow-hidden">
          {rightCollapsed ? (
            <Rail label={t('browse.expandInspector')} chev="«" onExpand={() => setRightCollapsed(false)} />
          ) : (
            <button
              type="button"
              className={cn(railBtn, 'absolute top-1/2 left-0 -translate-y-1/2 rounded-l-none border-l-0')}
              aria-label={t('browse.collapseInspector')}
              aria-expanded
              onClick={() => setRightCollapsed(true)}
            >
              »
            </button>
          )}
          <div className={cn('h-full p-2', rightCollapsed && 'hidden')}>
            <InspectorPanel oid={oid} eid={selectedEid} />
          </div>
        </aside>
      )}
      {/* Zone 4: status bar (mockup: breathing gaps, no dot separators) */}
      <footer className="border-line bg-panel text-ink-3 row-start-2 col-span-full flex items-center gap-3.5 border-t px-3.5 text-[11.5px]">
        <span className="font-mono">{meta.filename}</span>
        <span>{t('browse.statClass', { n: meta.classCount })}</span>
        <span>{t('browse.statProperty', { n: meta.propertyCount })}</span>
        <span>{t('browse.statInstance', { n: meta.instanceCount })}</span>
        <span>{t('browse.statAxiom', { n: meta.axiomCount })}</span>
        <span className="text-success flex items-center gap-1">
          <span aria-hidden="true">●</span>
          {meta.parseMs != null
            ? t('browse.parseOkMs', { ms: formatParseMs(meta.parseMs) })
            : t('browse.parseOk')}
        </span>
      </footer>

      {/* A2 canvas-editing dialogs (right-click menu opens one). */}
      <EntityDialogs oid={oid} />
    </div>
  )
}

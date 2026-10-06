import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { HistoryIcon, Loader2Icon, RefreshCwIcon } from 'lucide-react'
import { api, ApiErr } from '../api/client'
import type { RegistryEvent, RegistryPage } from '../api/types'
import { useBrowseStore } from '../stores/browseStore'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

/** Registry — the 记录 view (Phase 1 spec 2026-10-06 §8): newest-first
 *  operation journal over GET /ontologies/{oid}/events. Pull-only (manual
 *  refresh, polling is Phase 3); a row click focuses that entity in the
 *  graph view through the browse store (same channel as lint chips).
 *  Page 1 is a react-query read (Browse's meta pattern); older pages
 *  accumulate in local state keyed off the first page's cursor. */

/** Badge tint per action group — the profile-badge color convention. */
const GROUP_TINT: Record<string, string> = {
  entity: 'text-profile-ql border-profile-ql/40 bg-profile-ql/10',
  instance: 'text-profile-el border-profile-el/40 bg-profile-el/10',
  ontology: 'text-profile-rl border-profile-rl/40 bg-profile-rl/10',
  source: 'text-profile-dl border-profile-dl/40 bg-profile-dl/10',
}

/** "2026-10-06 12:00:03" — journal rows read as one glanceable timestamp. */
const timeOf = (iso: string | null): string => {
  if (!iso) return ''
  const d = new Date(iso)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

/** Prefer the curie, fall back to the eid/filename inside detail. */
const summaryOf = (e: RegistryEvent): string => {
  const d = e.detail
  if (!d) return e.action
  if (typeof d.curie === 'string' && d.curie) return d.curie
  if (typeof d.eid === 'string' && d.eid) return d.eid.replace(/^.*[/#]/, '')
  if (typeof d.filename === 'string' && d.filename) return d.filename
  return e.action
}

/** One change value, journal-readable: label maps collapse to their
 *  values, arrays join, null reads as ∅ (spec §8.2 display side). */
const fmtValue = (v: unknown): string => {
  if (v == null) return '∅'
  if (typeof v === 'string') return v
  if (Array.isArray(v)) return v.length ? v.map(fmtValue).join(', ') : '[]'
  if (typeof v === 'object') {
    const vals = Object.values(v as Record<string, unknown>)
    if (vals.length && vals.every((x) => typeof x === 'string')) return vals.join(' / ')
    return JSON.stringify(v)
  }
  return String(v)
}

/** "label: Payment → Zahlung | comment: ∅ → net" — every field, inline on
 *  the row; long content wraps rather than being cut (user call 10-06). */
const changesOf = (e: RegistryEvent): string | null => {
  const ch = e.detail?.changes
  if (!ch || typeof ch !== 'object') return null
  const parts = Object.entries(ch as Record<string, { from?: unknown; to?: unknown }>).map(
    ([field, c]) => `${field}: ${fmtValue(c?.from)} → ${fmtValue(c?.to)}`,
  )
  return parts.length ? parts.join(' | ') : null
}

function RegistryConsoleImpl({ oid }: { oid: string }) {
  const { t } = useTranslation()
  const setSelected = useBrowseStore((s) => s.setSelected)
  const [older, setOlder] = useState<RegistryPage[]>([])
  const [fetchingMore, setFetchingMore] = useState(false)

  const { data, error, refetch, isFetching } = useQuery({
    queryKey: ['registry', oid],
    queryFn: () => api.get<RegistryPage>(`/api/v1/ontologies/${oid}/events`),
    retry: false,
  })

  const items = [...(data?.items ?? []), ...older.flatMap((p) => p.items)]
  const lastPage = older.length ? older[older.length - 1] : data
  const nextBeforeId = lastPage?.nextBeforeId ?? null
  const errorText =
    error instanceof ApiErr
      ? [error.message, error.hint].filter(Boolean).join(' — ')
      : error
        ? t('registry.loadFailed')
        : null

  const refresh = () => {
    setOlder([])
    void refetch()
  }
  const loadMore = async () => {
    if (nextBeforeId == null) return
    setFetchingMore(true)
    try {
      const p = await api.get<RegistryPage>(
        `/api/v1/ontologies/${oid}/events?before_id=${nextBeforeId}`,
      )
      setOlder((prev) => [...prev, p])
    } finally {
      setFetchingMore(false)
    }
  }

  const focus = (e: RegistryEvent) => {
    const eid = e.detail?.eid
    if (typeof eid === 'string' && eid) setSelected(eid)
  }
  const busy = isFetching || fetchingMore

  return (
    <div className="flex h-full flex-col gap-3 overflow-hidden p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-ink flex items-center gap-2 text-sm font-medium">
          <HistoryIcon className="size-4" aria-hidden="true" />
          {t('registry.title')}
        </h2>
        <Button size="sm" variant="outline" disabled={busy} onClick={refresh}>
          {busy ? (
            <Loader2Icon className="animate-spin" aria-hidden="true" />
          ) : (
            <RefreshCwIcon aria-hidden="true" />
          )}
          {t('registry.refresh')}
        </Button>
      </div>
      {errorText && <p className="text-destructive text-sm">{errorText}</p>}
      {items.length === 0 && !busy && !errorText && (
        <p className="text-ink-2 pt-8 text-center text-sm">{t('registry.empty')}</p>
      )}
      <ul className="border-line divide-line overflow-y-auto rounded-card border divide-y">
        {items.map((e) => {
          const group = e.action.split('.')[0]
          return (
            <li key={e.id}>
              <button
                type="button"
                onClick={() => focus(e)}
                className="hover:bg-panel/60 flex w-full items-center gap-3 px-3 py-2 text-left text-sm"
              >
                <span className="text-ink-3 w-44 shrink-0 font-mono text-xs">
                  {timeOf(e.createdAt)}
                </span>
                <span
                  className={cn(
                    'rounded-ctl shrink-0 border px-1.5 py-0.5 font-mono text-xs',
                    GROUP_TINT[group],
                  )}
                >
                  {e.action}
                </span>
                <span className="text-ink-2 min-w-0 flex-1 break-all leading-snug">
                  {summaryOf(e)}
                  {changesOf(e) && (
                    <span className="text-ink-3 font-mono text-xs"> {changesOf(e)}</span>
                  )}
                </span>
                {e.origin === 'agent' && (
                  <span className="text-ink-3 ml-auto shrink-0 text-xs">agent</span>
                )}
              </button>
            </li>
          )
        })}
      </ul>
      {nextBeforeId !== null && (
        <Button size="sm" variant="ghost" disabled={busy} onClick={() => void loadMore()}>
          {t('registry.loadMore')}
        </Button>
      )}
    </div>
  )
}

/** The console resets wholly on oid switch (the 2026-10-05 residue
 *  contract every oid-bound console follows): remount via key so loaded
 *  older pages and cursors from one ontology never bleed into another's
 *  journal — same wrapper shape as ValidationConsole. */
export default function RegistryConsole(props: { oid: string }) {
  return <RegistryConsoleImpl key={props.oid} {...props} />
}

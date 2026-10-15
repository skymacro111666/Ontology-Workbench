import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { ApiErr, api } from '../api/client'
import { errText } from '../i18n/errText'
import type { DbConnectionSummary, R2rmlDoc, R2rmlDriftResult } from '../api/types'
import R2rmlEditor from './R2rmlEditor'

const fieldCls =
  'border-line bg-panel-2 text-ink rounded-ctl border px-2 py-1.5 text-sm w-full'

/** Browse content-area R2RML workbench (P2+P3): 结构/源码页签 + 手动漂移检查.
 *  Both panes stay mounted (hidden, not unmounted) so the editor keeps its
 *  text and dirty state across tab switches. */
export default function R2rmlPage({ oid }: { oid: string }) {
  const { t } = useTranslation()
  const [tab, setTab] = useState<'structure' | 'source'>('structure')
  const doc = useQuery({
    queryKey: ['r2rml', oid],
    queryFn: () => api.get<R2rmlDoc>(`/api/v1/ontologies/${oid}/r2rml`),
    retry: false,
  })
  const missing = doc.error instanceof ApiErr && doc.error.code === 'NOT_FOUND'

  const [checking, setChecking] = useState(false)
  const [drift, setDrift] = useState<R2rmlDriftResult | null>(null)
  const [pickOpen, setPickOpen] = useState(false)

  async function runDrift(connectionId?: string) {
    setChecking(true)
    try {
      setDrift(
        await api.post<R2rmlDriftResult>(
          `/api/v1/ontologies/${oid}/r2rml/drift`,
          connectionId ? { connectionId } : {},
        ),
      )
    } catch (e) {
      if (e instanceof ApiErr && e.code === 'NOT_FOUND') {
        setPickOpen(true) // 档案连接已被删 → 回落挑连接(spec 决策 2「档已删」分支)
        return
      }
      toast.error(errText(e, t)) // 横幅不动:上次结果保持可见
    } finally {
      setChecking(false)
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-2 p-2">
      <div className="flex items-center gap-2">
        <ToggleGroup
          type="single"
          variant="outline"
          size="sm"
          value={tab}
          onValueChange={(v) => v && setTab(v as 'structure' | 'source')}
          aria-label={t('r2rml.title')}
        >
          <ToggleGroupItem value="structure">{t('r2rml.tabStructure')}</ToggleGroupItem>
          <ToggleGroupItem value="source">{t('r2rml.tabSource')}</ToggleGroupItem>
        </ToggleGroup>
        <Button
          variant="outline"
          size="sm"
          className="ml-auto"
          disabled={checking || !doc.data}
          onClick={() => (doc.data?.dbConnectionId ? void runDrift() : setPickOpen(true))}
        >
          {checking ? t('r2rml.driftChecking') : t('r2rml.checkDrift')}
        </Button>
      </div>
      {drift && (
        <div
          className={
            drift.drifted
              ? 'border-amber-500/40 bg-amber-500/10 text-amber-600 dark:text-amber-400 rounded-ctl border px-3 py-2 text-xs'
              : 'border-green-500/40 bg-green-500/10 text-green-600 dark:text-green-400 rounded-ctl border px-3 py-2 text-xs'
          }
          role="status"
        >
          <p className="font-medium">
            {drift.drifted
              ? t('r2rml.driftFound')
              : `${t('r2rml.driftClean')} (${new Date(drift.checkedAt).toLocaleTimeString([], {
                  hour: '2-digit',
                  minute: '2-digit',
                })})`}
          </p>
          {drift.findings.map((f, i) => (
            <p key={`${i}-${f.table}-${f.kind}`} className="font-mono">
              {f.detail}
            </p>
          ))}
        </div>
      )}
      {doc.isLoading ? (
        <p className="text-ink-3 text-xs">{t('common.loading')}</p>
      ) : missing ? (
        <p className="text-ink-2 p-8 text-center text-xs">{t('r2rml.noMapping')}</p>
      ) : doc.data ? (
        <>
          <div className={tab === 'structure' ? 'flex min-h-0 flex-1 flex-col' : 'hidden'}>
            <R2rmlStructure doc={doc.data} />
          </div>
          <div className={tab === 'source' ? 'flex min-h-0 flex-1 flex-col' : 'hidden'}>
            <R2rmlEditor oid={oid} doc={doc.data} />
          </div>
        </>
      ) : null}
      {pickOpen && (
        <DriftPicker
          onOpenChange={setPickOpen}
          onConfirm={(cid) => {
            setPickOpen(false)
            void runDrift(cid)
          }}
        />
      )}
    </div>
  )
}

/** Structured correspondences — one collapsible card per table (mockup
 *  2026-10-16: A1 cards + A2 row semantics + B2 collapse). */
function R2rmlStructure({ doc }: { doc: R2rmlDoc }) {
  const { t } = useTranslation()
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-auto">
      {doc.skippedTables.length > 0 && (
        <p className="text-ink-3 text-xs">
          {t('r2rml.skippedBadge')}: {doc.skippedTables.join('、')}
        </p>
      )}
      <div className="flex flex-col gap-2">
        {doc.structure.map((m, mi) => (
          <TableCard key={`${mi}-${m.table}`} m={m} />
        ))}
      </div>
    </div>
  )
}

function TableCard({ m }: { m: R2rmlDoc['structure'][number] }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(true)
  return (
    <div className="border-line bg-panel overflow-hidden rounded-card border">
      <button
        type="button"
        className="bg-panel-2 border-line flex w-full cursor-pointer items-center gap-2 border-b px-2.5 py-1.5 text-left"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <span
          className={cn(
            'text-ink-3 inline-block text-[10px] transition-transform',
            !open && '-rotate-90',
          )}
        >
          ▼
        </span>
        <span className="text-xs font-semibold font-mono">{m.table}</span>
        <span className="border-primary-border bg-primary-soft text-primary rounded-full px-2 py-0.5 text-[10.5px] font-semibold">
          {m.className}
        </span>
        <span className="text-ink-3 ml-auto text-[10.5px] whitespace-nowrap">
          {t('r2rml.mapStats', { cols: m.columnProps.length, fks: m.fkProps.length })}
        </span>
      </button>
      {open && (
        <div className="px-2.5 pt-1 pb-2">
          {m.columnProps.map((p, ci) => (
            <div
              key={`${ci}-${p.column}`}
              className="flex flex-wrap items-center gap-2 py-0.5 text-xs"
            >
              <span className="min-w-[140px] font-mono">{p.column}</span>
              <span className="text-ink-3">→</span>
              <span className="text-ink-2 font-mono">{p.predicate}</span>
              <span className="text-ink-2 border-line bg-canvas rounded-full border px-1.5 py-0.5 font-mono text-[10px]">
                {p.datatype}
              </span>
            </div>
          ))}
          {m.fkProps.map((p, fi) => (
            <div
              key={`${fi}-${p.predicate}`}
              className="text-primary flex flex-wrap items-center gap-2 py-0.5 text-xs"
            >
              <span className="border-primary-border bg-primary-soft rounded-md border px-1 py-px text-[10px]">
                ⇄
              </span>
              <span className="min-w-[140px] font-mono">{p.predicate}</span>
              <span className="text-ink-3">→</span>
              <span className="font-mono">
                {p.childColumn} → {p.parentTable}.{p.parentColumn}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/** P3: pick a saved connection when the mapping row carries none. */
function DriftPicker({
  onOpenChange,
  onConfirm,
}: {
  onOpenChange: (v: boolean) => void
  onConfirm: (connectionId: string) => void
}) {
  const { t } = useTranslation()
  const connections = useQuery({
    queryKey: ['db-connections'],
    queryFn: () => api.get<DbConnectionSummary[]>('/api/v1/db-connections'),
  })
  const [picked, setPicked] = useState('')
  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>{t('r2rml.driftPickTitle')}</DialogTitle>
        </DialogHeader>
        {connections.data && connections.data.length === 0 ? (
          <p className="text-ink-3 text-xs">{t('r2rml.driftNoConn')}</p>
        ) : (
          <select
            className={fieldCls}
            aria-label={t('r2rml.driftPickTitle')}
            value={picked}
            onChange={(e) => setPicked(e.target.value)}
          >
            <option value="">—</option>
            {connections.data?.map((c) => (
              <option key={c.id} value={c.id}>
                🔒 {c.name} · {c.dbType}
              </option>
            ))}
          </select>
        )}
        <DialogFooter>
          <Button variant="ghost" size="sm" onClick={() => onOpenChange(false)}>
            {t('common.cancel')}
          </Button>
          <Button size="sm" disabled={!picked} onClick={() => onConfirm(picked)}>
            {t('r2rml.checkDrift')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { ApiErr, api } from '../api/client'
import type { R2rmlDoc } from '../api/types'
import { useUiStore } from '../stores/uiStore'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

/** Browse-side R2RML view: structured correspondences + read-only Turtle.
 *  P1 is view-only; editing arrives with P2. */
export default function R2rmlDialog({ oid }: { oid: string }) {
  const { t } = useTranslation()
  const open = useUiStore((s) => s.r2rmlOpen)
  const setR2rmlOpen = useUiStore((s) => s.setR2rmlOpen)
  // Radix only ever delivers `false` through onOpenChange (opening comes
  // from the shell button via the store), so no form state to reset here —
  // the render-time pattern is kept only to stay consistent with the other
  // store-driven dialogs.
  const [prevOpen, setPrevOpen] = useState(open)
  if (open !== prevOpen) setPrevOpen(open)

  const doc = useQuery({
    queryKey: ['r2rml', oid],
    queryFn: () => api.get<R2rmlDoc>(`/api/v1/ontologies/${oid}/r2rml`),
    enabled: open,
    retry: false,
  })
  const missing = doc.error instanceof ApiErr && doc.error.code === 'NOT_FOUND'
  return (
    <Dialog open={open} onOpenChange={(o) => !o && setR2rmlOpen(false)}>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{t('r2rml.title')}</DialogTitle>
          <DialogDescription>{doc.data?.filename ?? ''}</DialogDescription>
        </DialogHeader>
        {doc.isLoading ? (
          <p className="text-ink-3 text-xs">{t('common.loading')}</p>
        ) : missing ? (
          <p className="text-ink-2 text-xs">{t('r2rml.noMapping')}</p>
        ) : (
          doc.data && (
            <div className="flex flex-col gap-3">
              {doc.data.skippedTables.length > 0 && (
                <p className="text-ink-3 text-xs">
                  {t('r2rml.skippedBadge')}: {doc.data.skippedTables.join('、')}
                </p>
              )}
              <div className="border-line max-h-72 overflow-auto rounded-ctl border text-xs">
                {doc.data.structure.map((m) => (
                  <div
                    key={m.table}
                    className="border-line border-b border-dashed px-2 py-1.5 last:border-0"
                  >
                    <div className="font-mono">
                      {m.table} → {m.className}
                    </div>
                    {m.columnProps.map((p) => (
                      <div key={p.column} className="text-ink-2 font-mono">
                        {'  '}
                        {p.column} → {p.predicate} ({p.datatype})
                      </div>
                    ))}
                    {m.fkProps.map((p) => (
                      <div key={p.predicate} className="text-primary font-mono">
                        {'  '}
                        {p.predicate}: {p.childColumn} → {p.parentTable}.{p.parentColumn}
                      </div>
                    ))}
                  </div>
                ))}
              </div>
              <details className="border-line rounded-ctl border">
                <summary className="text-ink-2 cursor-pointer px-2 py-1 text-xs">
                  {t('r2rml.source')}
                </summary>
                <pre className="text-ink-2 max-h-40 overflow-auto px-2 pb-2 font-mono text-[11px] whitespace-pre-wrap">
                  {doc.data.content}
                </pre>
              </details>
            </div>
          )
        )}
      </DialogContent>
    </Dialog>
  )
}

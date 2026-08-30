import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { api } from '../api/client'
import type { LintReportT, OntologyMeta } from '../api/types'
import { errText } from '../i18n/errText'
import { useBrowseStore } from '../stores/browseStore'
import { cn } from '@/lib/utils'

const SEV_ORDER = ['error', 'warning', 'info'] as const

/** B3's lint state machine: manual run + stale tracking. Returned as two
 *  render slices because their DOM homes differ — the button rides the
 *  canvas control cluster (an absolutely-positioned box the drawer must
 *  NOT anchor to), the drawer anchors to the canvas container itself. */
export function useLint(oid: string, onOpenSettings?: () => void) {
  const { t } = useTranslation()
  const setSelected = useBrowseStore((s) => s.setSelected)
  const [report, setReport] = useState<LintReportT | null>(null)
  const [open, setOpen] = useState(true)
  const { data: meta } = useQuery({
    queryKey: ['ontology', oid],
    queryFn: () => api.get<OntologyMeta>(`/api/ontologies/${oid}/meta`),
  })
  const stale = report !== null && meta !== undefined && report.fileHash !== meta.fileHash

  const run = useMutation({
    mutationFn: () => api.post<LintReportT>(`/api/ontologies/${oid}/lint/run`, {}),
    onSuccess: (r) => {
      setReport(r)
      setOpen(true)
    },
    onError: (e) => toast.error(errText(e, t)),
  })

  const worst = report
    ? report.counts.error > 0
      ? 'error'
      : report.counts.warning > 0
        ? 'warning'
        : 'info'
    : null

  const button = (
    <button
      type="button"
      onClick={() => run.mutate()}
      disabled={run.isPending}
      className="border-line bg-panel/90 text-ink-2 hover:text-primary rounded-ctl border px-2 py-1 text-xs shadow-xs backdrop-blur"
    >
      {run.isPending ? t('lint.checking') : t('lint.check')}
      {report && !run.isPending && (
        <span
          className={cn(
            'ml-1 rounded-full px-1.5 text-[10px] text-white',
            stale
              ? 'bg-ink-3'
              : worst === 'error'
                ? 'bg-red-500'
                : worst === 'warning'
                  ? 'bg-amber-500'
                  : 'bg-ink-3',
          )}
        >
          {report.counts.error + report.counts.warning + report.counts.info}
        </span>
      )}
    </button>
  )

  const drawer =
    report && open ? (
      <div className="border-line bg-panel absolute inset-x-2 bottom-2 z-10 flex max-h-[45%] flex-col rounded-card border shadow-md">
        <div className="border-line flex items-center gap-2 border-b px-3 py-1.5 text-xs">
          <span className="text-ink-2 font-medium">{t('lint.results')}</span>
          {SEV_ORDER.map((s) =>
            report.counts[s] > 0 ? (
              <span
                key={s}
                className={cn(
                  'rounded-full px-1.5 text-[10px] text-white',
                  s === 'error' ? 'bg-red-500' : s === 'warning' ? 'bg-amber-500' : 'bg-ink-3',
                )}
              >
                {t(`lint.${s}`)} {report.counts[s]}
              </span>
            ) : null,
          )}
          {stale && (
            <span className="text-amber-600 dark:text-amber-400">{t('lint.stale')}</span>
          )}
          <span className="text-ink-3 ml-auto">
            {t('lint.tookMs', { ms: report.durationMs })}
          </span>
          {onOpenSettings && (
            <button
              type="button"
              onClick={onOpenSettings}
              className="text-ink-2 hover:text-primary"
            >
              {t('lint.settings')}
            </button>
          )}
          <button
            type="button"
            onClick={() => setOpen(false)}
            aria-label={t('common.close')}
            className="text-ink-3 hover:text-ink"
          >
            ×
          </button>
        </div>
        <div className="flex flex-col gap-2 overflow-y-auto px-3 py-2">
          {report.results
            .filter((r) => r.findings.length > 0 || r.error)
            .map((r) => {
              const title = r.name ?? t(`lint.ruleName.${r.ruleId}`)
              return (
                <div key={r.ruleId} className="flex flex-col gap-1">
                  <span className="text-ink-2 text-xs font-medium">
                    {title} ({r.total})
                    {r.truncated && (
                      <span className="text-ink-3">
                        {' '}
                        · {t('lint.showing', { n: r.findings.length })}
                      </span>
                    )}
                    <span className="text-ink-3 ml-1 font-mono text-[10px]">
                      {r.durationMs}ms
                    </span>
                  </span>
                  {r.error ? (
                    <span className="text-amber-600 dark:text-amber-400 text-xs">
                      {r.error === 'TIMEOUT' ? t('lint.timeout') : r.error}
                    </span>
                  ) : (
                    r.findings.map((f, i) => (
                      <div key={i} className="flex flex-wrap items-baseline gap-1.5 text-xs">
                        <button
                          type="button"
                          title={f.subjectCurie}
                          onClick={() => setSelected(f.subject)}
                          className="bg-primary-soft border-primary-border text-primary rounded-ctl border px-1.5 py-0.5 font-mono"
                        >
                          {f.subjectCurie.split(/[#:/]/).pop()}
                        </button>
                        <span className="text-ink-2">
                          {r.name
                            ? Object.values(f.params).join(' · ') || f.subjectCurie
                            : t(`lint.rule.${r.ruleId}`, { ...f.params })}
                        </span>
                      </div>
                    ))
                  )}
                </div>
              )
            })}
          {report.results.every((r) => !r.findings.length && !r.error) && (
            <span className="text-ink-3 py-4 text-center text-xs">{t('lint.noIssues')}</span>
          )}
        </div>
      </div>
    ) : null

  return { button, drawer }
}

/** Convenience mount: both slices under one relatively-positioned parent.
 *  The canvas wiring (GraphOverview) places the two slices separately. */
export default function LintPanel({
  oid,
  onOpenSettings,
}: {
  oid: string
  onOpenSettings?: () => void
}) {
  const { button, drawer } = useLint(oid, onOpenSettings)
  return (
    <>
      {button}
      {drawer}
    </>
  )
}

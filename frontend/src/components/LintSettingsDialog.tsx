import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Fragment, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { CheckIcon } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '../api/client'
import type { LintReportT, LintRuleResultT } from '../api/types'
import { errText } from '../i18n/errText'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { cn } from '@/lib/utils'

/** The nine builtin rules (id → default severity), in display order. */
const BUILTIN_IDS: [string, string][] = [
  ['disjoint-parents', 'error'],
  ['instance-disjoint', 'error'],
  ['subclass-cycle', 'error'],
  ['domain-range', 'error'],
  ['missing-label', 'warning'],
  ['orphan-class', 'warning'],
  ['unused-property', 'warning'],
  ['undeclared-ref', 'info'],
  ['duplicate-label', 'info'],
]

/** Editable mirror of one custom rule (id only exists once saved). */
interface CustomDraft {
  id: string | null
  name: string
  severity: string
  sparql: string
  enabled: boolean
}

const SEVERITIES = ['error', 'warning', 'info'] as const

/** Shared enable toggle for both tables: a square that fills with a check
 *  mark when on — one visual language for builtin and custom rules alike. */
function CheckMark({
  label,
  on,
  onToggle,
}: {
  label: string
  on: boolean
  onToggle: () => void
}) {
  return (
    <button
      type="button"
      aria-label={label}
      aria-pressed={on}
      onClick={onToggle}
      className={cn(
        'border-line hover:border-primary flex h-3.5 w-3.5 items-center justify-center rounded-[3px] border transition-colors',
        on ? 'border-primary bg-primary text-white' : 'bg-transparent',
      )}
    >
      {on && <CheckIcon className="h-2.5 w-2.5" strokeWidth={3} />}
    </button>
  )
}

/** B3 rule settings: builtin toggles + custom SPARQL rules, both as tables.
 *  Saving PUTs the whole config; 「测试」 saves first (so a fresh rule gets a
 *  server id), then runs just that rule via onlyRuleId and previews its
 *  findings — no separate manual save needed to activate the button. */
export default function LintSettingsDialog({
  oid,
  open,
  onOpenChange,
}: {
  oid: string
  open: boolean
  onOpenChange: (o: boolean) => void
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()

  const { data: cfg } = useQuery({
    queryKey: ['lint-config', oid],
    queryFn: () =>
      api.get<{ disabled: string[]; custom: CustomDraft[] }>(
        `/api/ontologies/${oid}/lint/config`,
      ),
    enabled: open,
  })

  // Form state mirrors the fetched config; reset on every open transition.
  const [prevOpen, setPrevOpen] = useState(false)
  const [disabled, setDisabled] = useState<Set<string>>(new Set())
  const [customs, setCustoms] = useState<CustomDraft[]>([])
  const [preview, setPreview] = useState<{ idx: number; result: LintRuleResultT | null } | null>(
    null,
  )
  // Reset on every closed→open transition, in render time (the file dialogs'
  // pattern — setState inside an effect trips react-hooks/set-state-in-effect,
  // which CI's eslint gate rejects). Seeds only when the config is already in
  // hand at the transition, matching the previous effect's behavior.
  if (open !== prevOpen) {
    setPrevOpen(open)
    if (open && cfg) {
      setDisabled(new Set(cfg.disabled))
      setCustoms(
        cfg.custom.map((c) => ({
          id: c.id,
          name: c.name,
          severity: c.severity,
          sparql: c.sparql,
          enabled: c.enabled,
        })),
      )
      setPreview(null)
    }
  }

  const body = () => ({
    disabled: [...disabled],
    custom: customs.map((c) => ({
      name: c.name,
      severity: c.severity,
      sparql: c.sparql,
      enabled: c.enabled,
    })),
  })

  /** Adopt server-assigned ids from a config echo (save or 测试's own PUT). */
  const adoptIds = (echo: { custom: { id: string }[] }) =>
    setCustoms((cs) => cs.map((c, i) => ({ ...c, id: echo.custom[i]?.id ?? c.id })))

  const save = useMutation({
    mutationFn: (payload: ReturnType<typeof body>) =>
      api.put<{ disabled: string[]; custom: { id: string }[] }>(
        `/api/ontologies/${oid}/lint/config`,
        payload,
      ),
    onSuccess: (echo) => {
      adoptIds(echo)
      void queryClient.invalidateQueries({ queryKey: ['lint-config', oid] })
    },
    onError: (e) => toast.error(errText(e, t)),
  })

  const test = useMutation({
    mutationFn: async (i: number) => {
      // 测试 saves first: the server assigns the id this run is keyed by.
      const echo = await api.put<{ custom: { id: string }[] }>(
        `/api/ontologies/${oid}/lint/config`,
        body(),
      )
      const rid = echo.custom[i]?.id ?? ''
      const report = await api.post<LintReportT>(`/api/ontologies/${oid}/lint/run`, {
        onlyRuleId: rid,
      })
      return { echo, report }
    },
    onSuccess: ({ echo, report }, i) => {
      adoptIds(echo)
      setPreview({ idx: i, result: report.results[0] ?? null })
    },
    onError: (e) => toast.error(errText(e, t)),
  })

  const fieldCls =
    'border-line bg-panel-2 text-ink rounded-ctl border px-2 py-1.5 text-sm w-full'
  const cellCls = 'px-2 py-1.5 align-middle'
  /** Muted compact headers over roomier content rows (user direction):
   *  heads shrink to 11px grey, row text stays at the body size. */
  const headCls = 'h-8 px-2 text-[11px] font-medium text-ink-3'

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('lint.settings')}</DialogTitle>
        </DialogHeader>

        <div className="flex max-h-[60vh] flex-col gap-4 overflow-y-auto">
          <section className="flex flex-col gap-1.5">
            <span className="microlabel">{t('lint.builtin')}</span>
            <Table className="[&_tr]:border-line">
              <TableHeader>
                <TableRow>
                  <TableHead className={cn(headCls, 'w-8')}>{t('lint.enabled')}</TableHead>
                  <TableHead className={headCls}>{t('lint.nameLabel')}</TableHead>
                  <TableHead className={cn(headCls, 'w-16')}>{t('lint.severity')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {BUILTIN_IDS.map(([id, sev]) => (
                  <TableRow key={id}>
                    <TableCell className={cellCls}>
                      <CheckMark
                        label={t(`lint.ruleName.${id}`)}
                        on={!disabled.has(id)}
                        onToggle={() =>
                          setDisabled((s) => {
                            const next = new Set(s)
                            if (next.has(id)) next.delete(id)
                            else next.add(id)
                            return next
                          })
                        }
                      />
                    </TableCell>
                    <TableCell className={cn(cellCls, 'text-ink text-sm')}>
                      {t(`lint.ruleName.${id}`)}
                    </TableCell>
                    <TableCell className={cn(cellCls, 'text-ink-2 text-sm')}>
                      {t(`lint.${sev}`)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </section>

          <section className="flex flex-col gap-1.5">
            <div className="flex items-center justify-between">
              <span className="microlabel">{t('lint.custom')}</span>
              <button
                type="button"
                onClick={() =>
                  setCustoms((cs) => [
                    ...cs,
                    { id: null, name: '', severity: 'info', sparql: '', enabled: true },
                  ])
                }
                className="border-line text-ink-2 hover:text-primary rounded-ctl border px-1.5 text-[11px]"
              >
                {t('lint.newRule')}
              </button>
            </div>
            <Table className="[&_tr]:border-line">
              <TableHeader>
                <TableRow>
                  <TableHead className={cn(headCls, 'w-8')}>{t('lint.enabled')}</TableHead>
                  <TableHead className={headCls}>{t('lint.nameLabel')}</TableHead>
                  <TableHead className={cn(headCls, 'w-24')}>{t('lint.severity')}</TableHead>
                  <TableHead className={cn(headCls, 'w-32 text-right')}>
                    {t('lint.actions')}
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {customs.map((c, i) => (
                  <Fragment key={i}>
                    <TableRow>
                      <TableCell className={cellCls}>
                        <CheckMark
                          label={c.name || t('lint.newRule')}
                          on={c.enabled}
                          onToggle={() =>
                            setCustoms((cs) =>
                              cs.map((x, j) => (j === i ? { ...x, enabled: !x.enabled } : x)),
                            )
                          }
                        />
                      </TableCell>
                      <TableCell className={cellCls}>
                        <input
                          value={c.name}
                          onChange={(e) =>
                            setCustoms((cs) =>
                              cs.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)),
                            )
                          }
                          aria-label={t('lint.nameLabel')}
                          className={fieldCls}
                        />
                      </TableCell>
                      <TableCell className={cellCls}>
                        <select
                          value={c.severity}
                          onChange={(e) =>
                            setCustoms((cs) =>
                              cs.map((x, j) =>
                                j === i ? { ...x, severity: e.target.value } : x,
                              ),
                            )
                          }
                          aria-label={t('lint.severity')}
                          className={fieldCls}
                        >
                          {SEVERITIES.map((s) => (
                            <option key={s} value={s}>
                              {t(`lint.${s}`)}
                            </option>
                          ))}
                        </select>
                      </TableCell>
                      <TableCell className={cn(cellCls, 'text-right')}>
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={!c.sparql.trim() || test.isPending}
                          onClick={() => test.mutate(i)}
                        >
                          {t('lint.test')}
                        </Button>
                        <button
                          type="button"
                          onClick={() => setCustoms((cs) => cs.filter((_, j) => j !== i))}
                          className="text-ink-3 hover:text-red-500 ml-2 text-xs"
                        >
                          {t('common.delete')}
                        </button>
                      </TableCell>
                    </TableRow>
                    <TableRow>
                      <TableCell colSpan={4} className={cn(cellCls, 'pb-3')}>
                        <textarea
                          value={c.sparql}
                          onChange={(e) =>
                            setCustoms((cs) =>
                              cs.map((x, j) => (j === i ? { ...x, sparql: e.target.value } : x)),
                            )
                          }
                          aria-label={t('lint.query')}
                          rows={3}
                          placeholder="SELECT ?s WHERE { … }"
                          className={`${fieldCls} resize-none font-mono text-xs`}
                        />
                        {preview?.idx === i && preview.result && (
                          <div className="text-ink-2 mt-1.5 flex flex-col gap-1 text-xs">
                            <span className="text-ink-3">
                              {preview.result.total} 条 · {preview.result.durationMs}ms
                            </span>
                            {preview.result.findings.slice(0, 10).map((f, j) => (
                              <span key={j} className="font-mono">
                                {f.subjectCurie}
                              </span>
                            ))}
                          </div>
                        )}
                      </TableCell>
                    </TableRow>
                  </Fragment>
                ))}
              </TableBody>
            </Table>
          </section>
        </div>

        <DialogFooter>
          <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
            {t('common.cancel')}
          </Button>
          <Button size="sm" disabled={save.isPending} onClick={() => save.mutate(body())}>
            {t('common.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

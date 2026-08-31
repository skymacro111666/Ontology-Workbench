import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { api } from '../api/client'
import type { LintReportT, LintRuleResultT } from '../api/types'
import { errText } from '../i18n/errText'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

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

/** B3 rule settings: builtin toggles + custom SPARQL rules. Saving PUTs the
 *  whole config; 「测试」 saves first, then runs just that rule via
 *  onlyRuleId and previews its findings. */
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
  const [preview, setPreview] = useState<LintRuleResultT | null>(null)
  useEffect(() => {
    if (open && !prevOpen && cfg) {
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
    setPrevOpen(open)
  }, [open, prevOpen, cfg])

  const body = () => ({
    disabled: [...disabled],
    custom: customs.map((c) => ({
      name: c.name,
      severity: c.severity,
      sparql: c.sparql,
      enabled: c.enabled,
    })),
  })

  const save = useMutation({
    mutationFn: (payload: ReturnType<typeof body>) =>
      api.put<{ disabled: string[]; custom: { id: string }[] }>(
        `/api/ontologies/${oid}/lint/config`,
        payload,
      ),
    onSuccess: (echo) => {
      // Adopt the server-assigned ids so 测试 can address a fresh rule.
      setCustoms((cs) =>
        cs.map((c, i) => ({ ...c, id: echo.custom[i]?.id ?? c.id })),
      )
      void queryClient.invalidateQueries({ queryKey: ['lint-config', oid] })
    },
    onError: (e) => toast.error(errText(e, t)),
  })

  const test = useMutation({
    mutationFn: async (id: string) => {
      // 测试 saves first: an unsaved rule has no id to run by.
      const echo = await api.put<{ custom: { id: string }[] }>(
        `/api/ontologies/${oid}/lint/config`,
        body(),
      )
      const rid = echo.custom.find((c) => c.id === id)?.id ?? id
      return api.post<LintReportT>(`/api/ontologies/${oid}/lint/run`, { onlyRuleId: rid })
    },
    onSuccess: (r) => setPreview(r.results[0] ?? null),
    onError: (e) => toast.error(errText(e, t)),
  })

  const fieldCls =
    'border-line bg-panel-2 text-ink rounded-ctl border px-2 py-1.5 text-sm w-full'
  const labelCls = 'text-ink-2 text-xs font-medium'

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('lint.settings')}</DialogTitle>
          <DialogDescription>{t('lint.builtin')} · {t('lint.custom')}</DialogDescription>
        </DialogHeader>

        <div className="flex max-h-[60vh] flex-col gap-4 overflow-y-auto">
          <section className="flex flex-col gap-1.5">
            <span className="microlabel">{t('lint.builtin')}</span>
            {BUILTIN_IDS.map(([id, sev]) => (
              <div key={id} className="flex items-center justify-between gap-2 text-xs">
                <span className="text-ink flex items-baseline gap-1.5">
                  {t(`lint.ruleName.${id}`)}
                  <span className="text-ink-3 text-[10px]">{t(`lint.${sev}`)}</span>
                </span>
                <button
                  type="button"
                  aria-label={t(`lint.ruleName.${id}`)}
                  aria-pressed={!disabled.has(id)}
                  onClick={() =>
                    setDisabled((s) => {
                      const next = new Set(s)
                      if (next.has(id)) next.delete(id)
                      else next.add(id)
                      return next
                    })
                  }
                  className={disabled.has(id) ? 'text-ink-3' : 'text-primary'}
                >
                  {disabled.has(id) ? '○' : '●'}
                </button>
              </div>
            ))}
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
            {customs.map((c, i) => (
              <div key={i} className="border-line rounded-ctl flex flex-col gap-2 border p-2">
                <div className="grid grid-cols-[4rem_1fr] items-center gap-2">
                  <span className={labelCls}>{t('lint.nameLabel')}</span>
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
                </div>
                <div className="grid grid-cols-[4rem_1fr] items-center gap-2">
                  <span className={labelCls}>{t('lint.severity')}</span>
                  <select
                    value={c.severity}
                    onChange={(e) =>
                      setCustoms((cs) =>
                        cs.map((x, j) => (j === i ? { ...x, severity: e.target.value } : x)),
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
                </div>
                <div className="grid grid-cols-[4rem_1fr] items-start gap-2">
                  <span className={labelCls}>{t('lint.query')}</span>
                  <textarea
                    value={c.sparql}
                    onChange={(e) =>
                      setCustoms((cs) =>
                        cs.map((x, j) => (j === i ? { ...x, sparql: e.target.value } : x)),
                      )
                    }
                    aria-label={t('lint.query')}
                    rows={3}
                    className={`${fieldCls} resize-none font-mono text-xs`}
                  />
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={!c.id || test.isPending}
                    onClick={() => c.id && test.mutate(c.id)}
                  >
                    {t('lint.test')}
                  </Button>
                  <button
                    type="button"
                    onClick={() => setCustoms((cs) => cs.filter((_, j) => j !== i))}
                    className="text-ink-3 hover:text-red-500 ml-auto text-xs"
                  >
                    {t('common.delete')}
                  </button>
                </div>
                {preview && (
                  <div className="text-ink-2 flex flex-col gap-1 text-xs">
                    <span className="text-ink-3">
                      {preview.total} 条 · {preview.durationMs}ms
                    </span>
                    {preview.findings.slice(0, 10).map((f, j) => (
                      <span key={j} className="font-mono">
                        {f.subjectCurie}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
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

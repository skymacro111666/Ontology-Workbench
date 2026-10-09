import { Loader2Icon, RefreshCwIcon, SearchIcon, SparklesIcon } from 'lucide-react'
import { useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { useTranslation } from 'react-i18next'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ApiErr, api } from '../api/client'
import { errText } from '../i18n/errText'
import { LAST_OID_KEY } from '../auth/AuthContext'
import type { AiStatus, DbConnectionSummary, DbEngine, DraftJob, DraftResult, SchemaModel } from '../api/types'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { useUiStore } from '@/stores/uiStore'

const fieldCls = 'border-line bg-panel-2 text-ink rounded-ctl border px-2 py-1.5 text-sm w-full'
const labelCls = 'text-ink-2 text-xs font-medium'

/** Draft-from-database wizard (spec §5): 连接 → 选表与选项 → 预览与导入.
 *  Step 1 reflects a database (saved connection or raw values); later steps
 *  build on the SchemaModel held in state. Save-connection fires only after
 *  a successful read — bad credentials are never persisted. */
export default function DraftFromDbDialog() {
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
  const open = useUiStore((s) => s.draftOpen)
  const setDraftOpen = useUiStore((s) => s.setDraftOpen)
  const setAiSettingsOpen = useUiStore((s) => s.setAiSettingsOpen)
  const queryClient = useQueryClient()

  const [step, setStep] = useState(1)
  const [pickedId, setPickedId] = useState('') // saved connection id, '' = manual
  const [dbType, setDbType] = useState('') // '' → first installed engine
  const [host, setHost] = useState('')
  const [port, setPort] = useState('')
  const [database, setDatabase] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [saveConn, setSaveConn] = useState(false)
  const [connName, setConnName] = useState('')
  const [schema, setSchema] = useState<SchemaModel | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Step 2: table selection, wizard options, generate-job state.
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [search, setSearch] = useState('')
  const [namespace, setNamespace] = useState('')
  const [labelLang, setLabelLang] = useState<'' | 'zh' | 'en'>('')
  const [progress, setProgress] = useState<{ batch: number; batchCount: number } | null>(null)
  const [result, setResult] = useState<DraftResult | null>(null)
  // Step 3: checked items per group — the kept sets the import body carries.
  const [kept, setKept] = useState<Set<string>>(new Set())
  const [keptObj, setKeptObj] = useState<Set<string>>(new Set())
  const [keptData, setKeptData] = useState<Set<string>>(new Set())
  const [genLang, setGenLang] = useState<'zh' | 'en'>('zh')
  const [filename, setFilename] = useState('')
  // Invalidate in-flight poll loops on any open toggle or new generate: a
  // loop from a closed session must not land its result in a fresh one.
  const pollGen = useRef(0)

  // Store-opened dialog (no DialogTrigger): Radix only delivers `false` via
  // onOpenChange, so reset on the closed→open transition in render time —
  // same pattern as the other file dialogs (no set-state-in-effect).
  const [prevOpen, setPrevOpen] = useState(open)
  if (open !== prevOpen) {
    setPrevOpen(open)
    pollGen.current += 1
    if (open) {
      setStep(1)
      setPickedId('')
      setDbType('')
      setHost('')
      setPort('')
      setDatabase('')
      setUsername('')
      setPassword('')
      setSaveConn(false)
      setConnName('')
      setSchema(null)
      setBusy(false)
      setError(null)
      setSelected(new Set())
      setSearch('')
      setNamespace('')
      setLabelLang('')
      setProgress(null)
      setResult(null)
      setKept(new Set())
      setKeptObj(new Set())
      setKeptData(new Set())
      setGenLang('zh')
      setFilename('')
    }
  }

  const engines = useQuery({
    queryKey: ['db-engines'],
    queryFn: () => api.get<DbEngine[]>('/api/v1/db-connections/engines'),
    enabled: open,
  })
  const connections = useQuery({
    queryKey: ['db-connections'],
    queryFn: () => api.get<DbConnectionSummary[]>('/api/v1/db-connections'),
    enabled: open,
  })
  const aiStatus = useQuery({
    queryKey: ['ai-status'],
    queryFn: () => api.get<AiStatus>('/api/v1/ai/status'),
    enabled: open && step === 2,
  })

  const installed = (engines.data ?? []).filter((e) => e.installed)
  const effectiveType = dbType || installed[0]?.dbType || ''
  const isSqlite = effectiveType === 'sqlite'
  const picked = (connections.data ?? []).find((c) => c.id === pickedId) ?? null

  const readSchema = async () => {
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      const body = picked
        ? { connectionId: picked.id }
        : isSqlite
          ? { dbType: effectiveType, database }
          : { dbType: effectiveType, host, port: port ? Number(port) : undefined, database, username, password }
      const data = await api.post<{ schema: SchemaModel; tableCount: number }>(
        '/api/v1/ontologies/drafting/schema',
        body,
      )
      // Save-this-connection lands only after a successful read: a profile
      // with bad credentials would otherwise be persisted.
      if (!picked && saveConn && connName.trim()) {
        await api.post('/api/v1/db-connections', {
          name: connName.trim(),
          dbType: effectiveType,
          host: isSqlite ? undefined : host,
          port: isSqlite || !port ? undefined : Number(port),
          database,
          username: isSqlite ? undefined : username,
          password: isSqlite ? undefined : password,
        })
        void queryClient.invalidateQueries({ queryKey: ['db-connections'] })
      }
      setSchema(data.schema)
      setSelected(new Set(data.schema.tables.map((t) => t.name)))
      setNamespace(`https://local/${data.schema.databaseName}#`)
      setFilename(`${data.schema.databaseName}-draft.ttl`)
      setStep(2)
    } catch (e) {
      setError(e instanceof ApiErr ? errText(e, t) : t('shell.loadFailed'))
    } finally {
      setBusy(false)
    }
  }

  const generate = async () => {
    if (busy || !schema) return
    setBusy(true)
    setError(null)
    setProgress(null)
    // This attempt owns the poll loop: closing/reopening the dialog or
    // starting another generate bumps the counter and orphans this loop.
    const token = (pollGen.current += 1)
    try {
      const lang =
        labelLang || (i18n.resolvedLanguage?.startsWith('zh') ? 'zh' : 'en')
      setGenLang(lang)
      const subset: SchemaModel = {
        databaseName: schema.databaseName,
        tables: schema.tables.filter((t) => selected.has(t.name)),
      }
      const { jobId } = await api.post<{ jobId: string }>(
        '/api/v1/ontologies/drafting/generate',
        { schema: subset, namespace, labelLanguage: lang },
      )
      // Poll until done/failed; a stale token (closed/reopened/superseded)
      // aborts so an old result never lands in a fresh session.
      for (;;) {
        if (pollGen.current !== token) return
        const job = await api.get<DraftJob>(`/api/v1/ontologies/drafting/jobs/${jobId}`)
        if (job.status === 'done') {
          setResult(job.result ?? null)
          setKept(new Set((job.result?.decisions.classes ?? []).map((c) => c.name)))
          setKeptObj(
            new Set((job.result?.decisions.objectProperties ?? []).map((p) => p.name)),
          )
          setKeptData(
            new Set(
              (job.result?.decisions.dataProperties ?? []).map((d) => `${d.domain}.${d.name}`),
            ),
          )
          setStep(3)
          return
        }
        if (job.status === 'failed') {
          setError(
            job.code && i18n.exists(`err.${job.code}`) ? t(`err.${job.code}`) : job.message ?? '',
          )
          return
        }
        setProgress({ batch: job.batch, batchCount: job.batchCount })
        await new Promise((r) => setTimeout(r, 300))
      }
    } catch (e) {
      setError(e instanceof ApiErr ? errText(e, t) : t('shell.loadFailed'))
    } finally {
      setBusy(false)
    }
  }

  const importDraft = async () => {
    if (busy || !schema || !result) return
    setBusy(true)
    setError(null)
    try {
      const meta = await api.post<{ ontologyId: string; title: string; lintFindings: unknown[] }>(
        '/api/v1/ontologies/drafting/import',
        {
          schema,
          decisions: {
            classes: result.decisions.classes.filter((c) => kept.has(c.name)),
            objectProperties: result.decisions.objectProperties.filter((p) => keptObj.has(p.name)),
            dataProperties: result.decisions.dataProperties.filter((d) =>
              keptData.has(`${d.domain}.${d.name}`),
            ),
          },
          rejectedClassNames: result.decisions.classes
            .filter((c) => !kept.has(c.name))
            .map((c) => c.name),
          namespace,
          filename: filename.trim() || `${schema.databaseName}-draft.ttl`,
          labelLanguage: genLang,
        },
      )
      toast.success(t('draftDialog.importedToast', { name: meta.title }), {
        description: t('draftDialog.importedSub', {
          classes: kept.size,
          objProps: result.decisions.objectProperties.length,
          dataProps: result.decisions.dataProperties.length,
          lint: meta.lintFindings.length,
        }),
      })
      void queryClient.invalidateQueries({ queryKey: ['ontologies'] })
      localStorage.setItem(LAST_OID_KEY, meta.ontologyId)
      setDraftOpen(false)
      navigate(`/browse/${meta.ontologyId}`)
    } catch (e) {
      setError(e instanceof ApiErr ? errText(e, t) : t('shell.loadFailed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && setDraftOpen(false)}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t('draftDialog.title')}</DialogTitle>
          <DialogDescription data-step-name>
            {step === 1 ? t('draftDialog.stepConnection') : step === 2 ? t('draftDialog.stepTables') : t('draftDialog.stepPreview')}
          </DialogDescription>
        </DialogHeader>

        {step === 1 && (
          <div className="flex flex-col gap-3">
            {(connections.data ?? []).length > 0 && (
              <div className="grid grid-cols-[7rem_1fr] items-center gap-2">
                <span className={labelCls}>{t('draftDialog.savedConnections')}</span>
                <select
                  value={pickedId}
                  onChange={(e) => setPickedId(e.target.value)}
                  className={fieldCls}
                  aria-label={t('draftDialog.savedConnections')}
                >
                  <option value="">{t('draftDialog.newConnection')}</option>
                  {connections.data?.map((c) => (
                    <option key={c.id} value={c.id}>
                      🔒 {c.name} · {c.dbType}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {!picked && (
              <>
                <div className="grid grid-cols-[7rem_1fr] items-center gap-2">
                  <span className={labelCls}>{t('draftDialog.dbType')}</span>
                  <select
                    value={effectiveType}
                    onChange={(e) => setDbType(e.target.value)}
                    className={fieldCls}
                    aria-label={t('draftDialog.dbType')}
                  >
                    {(engines.data ?? []).map((e) => (
                      <option
                        key={e.dbType}
                        value={e.dbType}
                        disabled={!e.installed}
                        title={e.installed ? undefined : `${e.label}`}
                      >
                        {e.label}
                        {e.installed ? '' : `（${t('err.DB_DRIVER_MISSING')}）`}
                      </option>
                    ))}
                  </select>
                </div>

                {isSqlite ? (
                  <div className="grid grid-cols-[7rem_1fr] items-center gap-2">
                    <span className={labelCls}>{t('draftDialog.path')}</span>
                    <Input
                      value={database}
                      onChange={(e) => setDatabase(e.target.value)}
                      aria-label={t('draftDialog.path')}
                      placeholder="/data/shop.db"
                      className="text-sm"
                    />
                  </div>
                ) : (
                  <>
                    <div className="grid grid-cols-2 gap-2">
                      <div className="grid grid-cols-[5rem_1fr] items-center gap-2">
                        <span className={labelCls}>{t('draftDialog.host')}</span>
                        <Input value={host} onChange={(e) => setHost(e.target.value)} aria-label={t('draftDialog.host')} className="text-sm" />
                      </div>
                      <div className="grid grid-cols-[5rem_1fr] items-center gap-2">
                        <span className={labelCls}>{t('draftDialog.port')}</span>
                        <Input value={port} onChange={(e) => setPort(e.target.value)} aria-label={t('draftDialog.port')} className="text-sm" />
                      </div>
                    </div>
                    <div className="grid grid-cols-[7rem_1fr] items-center gap-2">
                      <span className={labelCls}>{t('draftDialog.database')}</span>
                      <Input value={database} onChange={(e) => setDatabase(e.target.value)} aria-label={t('draftDialog.database')} className="text-sm" />
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <div className="grid grid-cols-[5rem_1fr] items-center gap-2">
                        <span className={labelCls}>{t('draftDialog.username')}</span>
                        <Input value={username} onChange={(e) => setUsername(e.target.value)} aria-label={t('draftDialog.username')} className="text-sm" />
                      </div>
                      <div className="grid grid-cols-[5rem_1fr] items-center gap-2">
                        <span className={labelCls}>{t('draftDialog.password')}</span>
                        <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} aria-label={t('draftDialog.password')} className="text-sm" />
                      </div>
                    </div>
                  </>
                )}

                <label className="text-ink-2 flex items-center gap-2 text-xs">
                  <input
                    type="checkbox"
                    checked={saveConn}
                    onChange={(e) => setSaveConn(e.target.checked)}
                    className="accent-primary"
                  />
                  {t('draftDialog.saveConnection')}
                  {saveConn && (
                    <Input
                      value={connName}
                      onChange={(e) => setConnName(e.target.value)}
                      aria-label={t('draftDialog.connectionName')}
                      placeholder={t('draftDialog.connectionName')}
                      className="ml-2 w-44 text-xs"
                    />
                  )}
                </label>
              </>
            )}

            {error && (
              <div role="alert" className="text-destructive text-xs">
                {error}
              </div>
            )}
          </div>
        )}

        {step === 2 && schema && (
          <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2">
              <div className="relative flex-1">
                <SearchIcon aria-hidden="true" className="text-ink-3 pointer-events-none absolute top-1/2 left-2 size-3.5 -translate-y-1/2" />
                <Input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  aria-label={t('draftDialog.searchTables')}
                  placeholder={t('draftDialog.searchTables')}
                  className="text-ink pl-7 text-xs"
                />
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setSelected(new Set(schema.tables.map((tb) => tb.name)))}
              >
                {t('draftDialog.selectAll')}
              </Button>
            </div>

            <div className="border-line max-h-56 overflow-auto rounded-ctl border">
              {schema.tables
                .filter((t) =>
                  search.trim()
                    ? (t.name + ' ' + (t.comment ?? '')).toLowerCase().includes(search.trim().toLowerCase())
                    : true,
                )
                .map((tbl) => (
                  <label key={tbl.name} className="hover:bg-panel-2 flex cursor-pointer items-center gap-2 border-b border-dashed px-2 py-1.5 text-xs last:border-0">
                    <input
                      type="checkbox"
                      checked={selected.has(tbl.name)}
                      onChange={(e) =>
                        setSelected((prev) => {
                          const next = new Set(prev)
                          if (e.target.checked) next.add(tbl.name)
                          else next.delete(tbl.name)
                          return next
                        })
                      }
                      className="accent-primary"
                      aria-label={tbl.name}
                    />
                    <span className="text-ink font-mono">{tbl.name}</span>
                    <span className="text-ink-2 flex-1 truncate">{tbl.comment}</span>
                    <span className="text-ink-3 font-mono">{t('draftDialog.columnsCount', { n: tbl.columns.length })}</span>
                    {tbl.foreignKeys.length > 0 && (
                      <span className="text-primary font-mono">{t('draftDialog.fkCount', { n: tbl.foreignKeys.length })}</span>
                    )}
                  </label>
                ))}
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div className="grid grid-cols-[6rem_1fr] items-center gap-2">
                <span className={labelCls}>{t('draftDialog.namespace')}</span>
                <Input
                  value={namespace}
                  onChange={(e) => setNamespace(e.target.value)}
                  aria-label={t('draftDialog.namespace')}
                  className="text-ink text-xs"
                />
              </div>
              <div className="grid grid-cols-[6rem_1fr] items-center gap-2">
                <span className={labelCls}>{t('draftDialog.labelLanguage')}</span>
                <select
                  value={labelLang}
                  onChange={(e) => setLabelLang(e.target.value as '' | 'zh' | 'en')}
                  className={fieldCls}
                  aria-label={t('draftDialog.labelLanguage')}
                >
                  <option value="">{t('draftDialog.followUi')}</option>
                  <option value="zh">中文</option>
                  <option value="en">English</option>
                </select>
              </div>
            </div>

            {aiStatus.data && !aiStatus.data.configured && (
              <div className="border-line bg-panel-2 flex items-center gap-2 rounded-ctl border px-2 py-1.5 text-xs">
                <span className="text-ink-2 flex-1">{t('draftDialog.aiNotConfigured')}</span>
                <Button variant="outline" size="sm" onClick={() => setAiSettingsOpen(true)}>
                  {t('draftDialog.goSettings')}
                </Button>
              </div>
            )}

            {busy && progress && (
              <div className="text-primary flex items-center gap-2 text-xs">
                <Loader2Icon aria-hidden="true" className="size-3.5 animate-spin" />
                {t('draftDialog.generatingBatch', { k: progress.batch, n: progress.batchCount })}
              </div>
            )}

            {error && (
              <div role="alert" className="text-destructive text-xs">
                {error}
              </div>
            )}
          </div>
        )}

        {step === 3 && result && (
          <div className="flex flex-col gap-3">
            <div className="text-ink-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
              <span>
                <span className="text-ink font-mono font-bold">{result.stats.classCount}</span>{' '}
                {t('draftDialog.classes')}
              </span>
              <span>
                <span className="text-ink font-mono font-bold">{result.stats.objectPropertyCount}</span>{' '}
                {t('draftDialog.objectProperties')}
              </span>
              <span>
                <span className="text-ink font-mono font-bold">{result.stats.dataPropertyCount}</span>{' '}
                {t('draftDialog.dataProperties')}
              </span>
              <span className="text-ink-3 font-mono">{result.stats.elapsedMs}ms</span>
              <span className="text-ink-3 font-mono">
                ↑{result.stats.inTokens} ↓{result.stats.outTokens}
              </span>
            </div>

            <p className="text-ink-2 text-xs">{t('draftDialog.keepHint')}</p>

            <div className="border-line max-h-60 overflow-auto rounded-ctl border">
              {result.decisions.classes.map((c) => (
                <label
                  key={c.name}
                  className="hover:bg-panel-2 flex cursor-pointer items-center gap-2 border-b border-dashed px-2 py-1.5 text-xs last:border-0"
                >
                  <input
                    type="checkbox"
                    checked={kept.has(c.name)}
                    onChange={(e) =>
                      setKept((prev) => {
                        const next = new Set(prev)
                        if (e.target.checked) next.add(c.name)
                        else next.delete(c.name)
                        return next
                      })
                    }
                    className="accent-primary"
                    aria-label={c.name}
                  />
                  <span className="text-ink font-mono font-medium">{c.name}</span>
                  <span className="text-ink-2 flex-1 truncate">{c.label}</span>
                  {c.parentName && (
                    <span className="text-ink-3 font-mono">↦ {c.parentName}</span>
                  )}
                  <span className="text-ink-3 font-mono">{c.sourceTable}</span>
                </label>
              ))}
              {result.decisions.objectProperties.map((p) => (
                <label
                  key={p.name}
                  className="hover:bg-panel-2 flex cursor-pointer items-center gap-2 border-b border-dashed px-2 py-1.5 text-xs last:border-0"
                >
                  <input
                    type="checkbox"
                    checked={keptObj.has(p.name)}
                    onChange={(e) =>
                      setKeptObj((prev) => {
                        const next = new Set(prev)
                        if (e.target.checked) next.add(p.name)
                        else next.delete(p.name)
                        return next
                      })
                    }
                    className="accent-primary"
                    aria-label={p.name}
                  />
                  <span className="text-ink font-mono font-medium">{p.name}</span>
                  <span className="text-ink-2 font-mono">
                    {p.domain} → {p.range}
                  </span>
                  <span className="text-primary-soft border-primary-border text-primary rounded-ctl border px-1 py-px text-[10px]">
                    {t('draftDialog.fkAutoTag')}
                  </span>
                </label>
              ))}
              {result.decisions.dataProperties.map((d) => (
                <label
                  key={`${d.domain}.${d.name}`}
                  className="hover:bg-panel-2 flex cursor-pointer items-center gap-2 px-2 py-1.5 text-xs"
                >
                  <input
                    type="checkbox"
                    checked={keptData.has(`${d.domain}.${d.name}`)}
                    onChange={(e) =>
                      setKeptData((prev) => {
                        const next = new Set(prev)
                        const key = `${d.domain}.${d.name}`
                        if (e.target.checked) next.add(key)
                        else next.delete(key)
                        return next
                      })
                    }
                    className="accent-primary"
                    aria-label={`${d.domain}.${d.name}`}
                  />
                  <span className="text-ink font-mono font-medium">{d.name}</span>
                  <span className="text-ink-2 font-mono">{d.datatype}</span>
                  <span className="text-ink-3 flex-1 truncate font-mono">{d.sourceColumn}</span>
                </label>
              ))}
            </div>

            <div className="grid grid-cols-[6rem_1fr] items-center gap-2">
              <span className={labelCls}>{t('draftDialog.filename')}</span>
              <Input
                value={filename}
                onChange={(e) => setFilename(e.target.value)}
                aria-label={t('draftDialog.filename')}
                className="text-ink text-xs"
              />
            </div>

            {result.lintFindings.some((r) => r.findings.length > 0) && (
              <div className="border-line bg-panel-2 flex flex-col gap-1 rounded-ctl border px-2 py-1.5">
                {result.lintFindings
                  .filter((r) => r.findings.length > 0)
                  .map((r) => {
                    const sev = r.severity ?? 'info'
                    return (
                      <div key={r.ruleId} className="flex items-center gap-1.5 text-xs">
                        <span
                          className={cn(
                            'rounded-full px-1.5 text-[10px] text-white',
                            sev === 'error' ? 'bg-red-500' : sev === 'warning' ? 'bg-amber-500' : 'bg-ink-3',
                          )}
                        >
                          {t(`lint.${sev}`)}
                        </span>
                        <span className="text-ink-2">{r.name ?? r.ruleId}</span>
                        <span className="text-ink-3">({r.total})</span>
                      </div>
                    )
                  })}
              </div>
            )}

            <details className="border-line rounded-ctl border">
              <summary className="text-ink-2 hover:text-ink cursor-pointer px-2 py-1 text-xs">
                {t('draftDialog.ttlPreview')}
              </summary>
              <pre className="text-ink-2 max-h-40 overflow-auto px-2 pb-2 font-mono text-[11px] whitespace-pre-wrap">
                {result.ttl}
              </pre>
            </details>

            {error && (
              <div role="alert" className="text-destructive text-xs">
                {error}
              </div>
            )}
          </div>
        )}

        <DialogFooter>
          {step === 2 && schema && (
            <span className="text-ink-2 mr-auto text-xs">
              {t('draftDialog.selectedCount', { n: selected.size, max: 500 })}
            </span>
          )}
          <Button variant="outline" onClick={() => setDraftOpen(false)} disabled={busy}>
            {t('common.cancel')}
          </Button>
          {step === 1 && (
            <Button onClick={() => void readSchema()} disabled={busy || (!picked && !database)}>
              {busy ? <Loader2Icon aria-hidden="true" className="animate-spin" /> : <RefreshCwIcon aria-hidden="true" />}
              {busy ? t('draftDialog.reading') : t('draftDialog.readSchema')}
            </Button>
          )}
          {step === 2 && (
            <Button
              onClick={() => void generate()}
              disabled={busy || selected.size === 0 || !aiStatus.data?.configured}
            >
              {busy ? <Loader2Icon aria-hidden="true" className="animate-spin" /> : <SparklesIcon aria-hidden="true" />}
              {t('draftDialog.generate')}
            </Button>
          )}
          {step === 3 && (
            <>
              <Button variant="outline" onClick={() => setStep(2)} disabled={busy}>
                <RefreshCwIcon aria-hidden="true" />
                {t('draftDialog.regenerate')}
              </Button>
              <Button onClick={() => void importDraft()} disabled={busy || kept.size === 0}>
                {busy ? (
                  <Loader2Icon aria-hidden="true" className="animate-spin" />
                ) : (
                  <SparklesIcon aria-hidden="true" />
                )}
                {t('draftDialog.import')}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

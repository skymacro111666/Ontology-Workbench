import { Loader2Icon, RefreshCwIcon } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiErr, api } from '../api/client'
import { errText } from '../i18n/errText'
import type { DbConnectionSummary, DbEngine, SchemaModel } from '../api/types'
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
  const { t } = useTranslation()
  const open = useUiStore((s) => s.draftOpen)
  const setDraftOpen = useUiStore((s) => s.setDraftOpen)
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

  // Store-opened dialog (no DialogTrigger): Radix only delivers `false` via
  // onOpenChange, so reset on the closed→open transition in render time —
  // same pattern as the other file dialogs (no set-state-in-effect).
  const [prevOpen, setPrevOpen] = useState(open)
  if (open !== prevOpen) {
    setPrevOpen(open)
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
      setStep(2)
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
          <DialogDescription>
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
          // Step 2 选表 lands in the next task; the heading + count confirm
          // the reflect succeeded and the wizard advanced.
          <div className="flex flex-col gap-2">
            <div className="font-mono text-ink-2 text-xs">
              {schema.databaseName} · {schema.tables.length}
            </div>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => setDraftOpen(false)} disabled={busy}>
            {t('common.cancel')}
          </Button>
          {step === 1 && (
            <Button onClick={() => void readSchema()} disabled={busy || (!picked && !database)}>
              {busy ? <Loader2Icon aria-hidden="true" className="animate-spin" /> : <RefreshCwIcon aria-hidden="true" />}
              {busy ? t('draftDialog.reading') : t('draftDialog.readSchema')}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

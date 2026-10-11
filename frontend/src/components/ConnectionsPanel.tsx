import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Fragment, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { ApiErr, api } from '../api/client'
import { errText } from '../i18n/errText'
import type { DbConnectionSummary, DbEngine } from '../api/types'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

const fieldCls = 'text-sm'

/** host:port/database for network engines; the bare path for sqlite.
 *  Shared with the draft wizard's picked-connection summary line. */
export function targetOf(c: DbConnectionSummary): string {
  if (c.dbType === 'sqlite') return c.database
  const host = c.host ?? ''
  const port = c.port ? `:${c.port}` : ''
  return `${host}${port}/${c.database}`
}

/** One connect-test outcome: pending spinner, ok line with elapsed time,
 *  or a failure carrying the backend's bucketed reason code plus the raw
 *  driver text. */
type TestState =
  | { status: 'pending' }
  | { status: 'done'; ok: true; elapsedMs?: number }
  | { status: 'done'; ok: false; reason?: string; message?: string }

/** The bucketed reason's localized one-liner (fallback: UNKNOWN). */
function failReasonText(reason: string | undefined, t: (k: string) => string) {
  return t(`conn.failReason.${reason ?? 'UNKNOWN'}`)
}

/** Success line: 连接成功 · 0.8 秒 — shared by the status column and the dialog. */
function OkLine({ elapsedMs }: { elapsedMs?: number }) {
  const { t } = useTranslation()
  return (
    <span className="text-xs text-emerald-600">
      {t('conn.testOk')}
      {elapsedMs != null && ` · ${(elapsedMs / 1000).toFixed(1)}${t('conn.secUnit')}`}
    </span>
  )
}

/** Inline connect-test outcome for the create dialog's raw-value test:
 *  ok line, or the reason one-liner with the raw driver text truncated
 *  behind it (full text on hover). */
function TestOutcome({ state }: { state?: TestState | null }) {
  const { t } = useTranslation()
  if (!state || state.status !== 'done') return null
  if (state.ok) return <OkLine elapsedMs={state.elapsedMs} />
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-destructive text-xs">{failReasonText(state.reason, t)}</span>
      {state.message && (
        <span className="text-ink-3 truncate font-mono text-xs" title={state.message}>
          {state.message}
        </span>
      )}
    </div>
  )
}

/** The status column cell: quiet until tested, then this session's test
 *  outcome. A failed result is a dotted-underline button toggling the
 *  detail sub-row below the connection's row. */
function StatusCell({
  state,
  expanded,
  onToggle,
}: {
  state?: TestState
  expanded: boolean
  onToggle: () => void
}) {
  const { t } = useTranslation()
  if (!state) return <span className="text-ink-3 text-xs">{t('conn.untested')}</span>
  if (state.status === 'pending')
    return <span className="text-ink-3 animate-pulse text-xs">{t('conn.testing')}</span>
  if (state.ok) return <OkLine elapsedMs={state.elapsedMs} />
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={expanded}
      title={t('conn.toggleReason')}
      className="text-destructive inline-flex items-center gap-0.5 text-xs underline decoration-dotted underline-offset-2"
    >
      {t('conn.testFail')}
      <span aria-hidden className={expanded ? 'rotate-180 transition-transform' : 'transition-transform'}>
        ▾
      </span>
    </button>
  )
}

/** Create/edit form state; `editing` null = create. Blank password in edit
 *  mode means "keep the stored ciphertext" — the PUT body omits the key. */
interface FormState {
  name: string
  dbType: string
  host: string
  port: string
  database: string
  username: string
  password: string
}

const EMPTY_FORM: FormState = {
  name: '',
  dbType: '',
  host: '',
  port: '',
  database: '',
  username: '',
  password: '',
}

/** Connections section of the Settings page: saved profiles for the
 *  draft-from-database wizard. List carries no password material (the API
 *  serves hasPassword only); create/edit/test/delete round out the CRUD
 *  the backend already exposes. */
export default function ConnectionsPanel() {
  const { t } = useTranslation()
  const qc = useQueryClient()

  const connections = useQuery({
    queryKey: ['db-connections'],
    queryFn: () => api.get<DbConnectionSummary[]>('/api/v1/db-connections'),
  })
  const engines = useQuery({
    queryKey: ['db-engines'],
    queryFn: () => api.get<DbEngine[]>('/api/v1/db-connections/engines'),
  })

  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<DbConnectionSummary | null>(null)
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [formErr, setFormErr] = useState<string | null>(null)
  // Row tests (by saved id) and form tests (raw values) each show their
  // outcome inline next to where they were triggered. Row status is
  // session-only (no persistence): a fresh page shows 未测试 everywhere.
  const [rowTests, setRowTests] = useState<Record<string, TestState>>({})
  const [expandedRow, setExpandedRow] = useState<string | null>(null)
  const [formTest, setFormTest] = useState<TestState | null>(null)

  const installed = (engines.data ?? []).filter((e) => e.installed)
  const effectiveType = form.dbType || installed[0]?.dbType || ''
  const isSqlite = effectiveType === 'sqlite'

  const openCreate = () => {
    setEditing(null)
    setForm(EMPTY_FORM)
    setFormErr(null)
    setFormTest(null)
    setFormOpen(true)
  }

  const openEdit = (c: DbConnectionSummary) => {
    setEditing(c)
    setForm({
      name: c.name,
      dbType: c.dbType,
      host: c.host ?? '',
      port: c.port ? String(c.port) : '',
      database: c.database,
      username: c.username ?? '',
      // blank keeps the stored ciphertext — the PUT body omits the key
      password: '',
    })
    setFormErr(null)
    setFormTest(null)
    setFormOpen(true)
  }

  /** Engine switch: port follows the registry default so the user only
   *  overrides when the deployment actually differs. */
  const switchType = (dbType: string) => {
    const port = engines.data?.find((e) => e.dbType === dbType)?.defaultPort
    setForm((f) => ({ ...f, dbType, port: port ? String(port) : '' }))
  }

  /** Client-side gates before the request: a bad port or a duplicate name
   *  (the backend 422s both on create) fails inline in the dialog. */
  const submit = () => {
    if (!isSqlite && form.port) {
      const n = Number(form.port)
      if (!/^\d+$/.test(form.port) || n < 1 || n > 65535) {
        setFormErr(t('conn.portInvalid'))
        return
      }
    }
    const name = form.name.trim()
    if (connections.data?.some((c) => c.name === name && c.id !== editing?.id)) {
      setFormErr(t('conn.duplicateName'))
      return
    }
    setFormErr(null)
    save.mutate()
  }

  const save = useMutation({
    mutationFn: async () => {
      if (editing) {
        // Partial PUT: sqlite profiles carry no host/port/username; the
        // password key rides along only when the user typed a new one.
        const body: Record<string, unknown> = {
          name: form.name.trim(),
          database: form.database,
        }
        if (!isSqlite) {
          body.host = form.host
          body.port = form.port ? Number(form.port) : null
          body.username = form.username
        }
        if (form.password) body.password = form.password
        return api.put(`/api/v1/db-connections/${editing.id}`, body)
      }
      return api.post('/api/v1/db-connections', {
        name: form.name.trim(),
        dbType: effectiveType,
        ...(isSqlite
          ? { database: form.database }
          : {
              host: form.host,
              port: form.port ? Number(form.port) : undefined,
              database: form.database,
              username: form.username,
              password: form.password,
            }),
      })
    },
    onSuccess: () => {
      toast.success(t('conn.savedToast'))
      setFormOpen(false)
      void qc.invalidateQueries({ queryKey: ['db-connections'] })
    },
    onError: (e) => setFormErr(e instanceof ApiErr ? errText(e, t) : t('common.operationFailed')),
  })

  const remove = useMutation({
    mutationFn: (id: string) => api.del(`/api/v1/db-connections/${id}`),
    onSuccess: () => {
      toast.success(t('conn.deletedToast'))
      void qc.invalidateQueries({ queryKey: ['db-connections'] })
    },
    onError: (e) => toast.error(errText(e, t)),
  })

  /** SELECT 1 either way: raw form values (create dialog, nothing persisted)
   *  or the saved id (list rows). Failures arrive bucketed (reason code +
   *  raw driver text) for the human-readable line. */
  const runTest = async (body: Record<string, unknown>, onDone: (s: TestState) => void) => {
    onDone({ status: 'pending' })
    try {
      const r = await api.post<{
        ok: boolean
        elapsedMs?: number
        reason?: string
        message?: string
      }>('/api/v1/db-connections/test', body)
      onDone(
        r.ok
          ? { status: 'done', ok: true, elapsedMs: r.elapsedMs }
          : { status: 'done', ok: false, reason: r.reason, message: r.message },
      )
    } catch (e) {
      onDone({
        status: 'done',
        ok: false,
        message: e instanceof ApiErr ? errText(e, t) : t('common.operationFailed'),
      })
    }
  }

  const set = (k: keyof FormState) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }))

  return (
    <section className="flex flex-col gap-3">
      {/* No section heading here — the page (数据库设置) owns the only
          heading; this row just carries the create action, right-aligned. */}
      <div className="flex items-center justify-end gap-4">
        <Button size="sm" onClick={openCreate}>
          {t('conn.new')}
        </Button>
      </div>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t('conn.name')}</TableHead>
            <TableHead>{t('conn.dbType')}</TableHead>
            <TableHead>{t('conn.target')}</TableHead>
            <TableHead>{t('conn.createdAt')}</TableHead>
            <TableHead>{t('conn.status')}</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          {(connections.data ?? []).map((c) => {
            const st = rowTests[c.id]
            // Narrowed failure (or null) so the sub-row JSX can read it safely.
            const fail = st?.status === 'done' && !st.ok ? st : null
            return (
              <Fragment key={c.id}>
                <TableRow>
                  <TableCell className="text-xs">
                    {c.name}
                    {!c.hasPassword && (
                      <span className="text-ink-3 ml-2">{t('conn.noPassword')}</span>
                    )}
                  </TableCell>
                  <TableCell className="font-mono text-xs">{c.dbType}</TableCell>
                  <TableCell className="font-mono text-xs">{targetOf(c)}</TableCell>
                  <TableCell className="text-xs">{new Date(c.createdAt).toLocaleString()}</TableCell>
                  <TableCell className="text-xs">
                    <StatusCell
                      state={st}
                      expanded={expandedRow === c.id}
                      onToggle={() => setExpandedRow((cur) => (cur === c.id ? null : c.id))}
                    />
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-1">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => {
                          setExpandedRow(null)
                          setRowTests((s) => ({ ...s, [c.id]: { status: 'pending' } }))
                          void runTest({ connectionId: c.id }, (s) =>
                            setRowTests((prev) => ({ ...prev, [c.id]: s })),
                          )
                        }}
                      >
                        {rowTests[c.id]?.status === 'pending' ? t('conn.testing') : t('conn.test')}
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => openEdit(c)}>
                        {t('conn.edit')}
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="text-destructive"
                        onClick={() => {
                          // Native confirm for v1 (same idiom as token revoke).
                          if (
                            window.confirm(
                              `${t('conn.deleteConfirmTitle')}\n${t('conn.deleteConfirmDesc')}`,
                            )
                          )
                            remove.mutate(c.id)
                        }}
                      >
                        {t('conn.delete')}
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
                {/* Failure detail sub-row: reason one-liner + selectable raw text. */}
                {fail && expandedRow === c.id && (
                  <TableRow className="hover:bg-transparent">
                    <TableCell colSpan={6} className="bg-panel-2 px-4 py-3">
                      <div className="text-destructive text-xs">
                        {failReasonText(fail.reason, t)}
                      </div>
                      {fail.message && (
                        <div className="text-ink-3 mt-1 select-text font-mono text-xs whitespace-pre-wrap break-all">
                          {fail.message}
                        </div>
                      )}
                    </TableCell>
                  </TableRow>
                )}
              </Fragment>
            )
          })}
          {connections.data?.length === 0 && (
            <TableRow>
              <TableCell colSpan={6} className="text-ink-3 py-6 text-center text-xs">
                {t('conn.empty')}
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>

      <Dialog open={formOpen} onOpenChange={(o) => !o && setFormOpen(false)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{editing ? t('conn.edit') : t('conn.new')}</DialogTitle>
          </DialogHeader>

          <div className="flex flex-col gap-3">
            <div className="grid grid-cols-2 gap-2">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="conn-name">{t('conn.name')}</Label>
                <Input
                  id="conn-name"
                  value={form.name}
                  maxLength={64}
                  onChange={set('name')}
                  aria-label={t('conn.name')}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="conn-type">{t('conn.dbType')}</Label>
                <select
                  id="conn-type"
                  value={effectiveType}
                  onChange={(e) => switchType(e.target.value)}
                  className="border-line bg-panel-2 text-ink rounded-ctl border px-2 py-1.5 text-sm"
                  aria-label={t('conn.dbType')}
                  disabled={!!editing}
                >
                  {(engines.data ?? []).map((e) => (
                    <option key={e.dbType} value={e.dbType} disabled={!e.installed}>
                      {e.label}
                      {e.installed ? '' : `（${t('err.DB_DRIVER_MISSING')}）`}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {/* Engines still loading: effectiveType is '' → the network form
                would flash before flipping to the sqlite path field. */}
            {engines.isLoading ? (
              <p className="text-ink-3 text-xs">{t('common.loading')}</p>
            ) : isSqlite ? (
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="conn-path">{t('conn.path')}</Label>
                <Input
                  id="conn-path"
                  value={form.database}
                  onChange={set('database')}
                  aria-label={t('conn.path')}
                  placeholder="/data/shop.db"
                  className={fieldCls}
                />
              </div>
            ) : (
              <>
                <div className="grid grid-cols-[1fr_7rem] gap-2">
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="conn-host">{t('conn.host')}</Label>
                    <Input id="conn-host" value={form.host} onChange={set('host')} aria-label={t('conn.host')} className={fieldCls} />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="conn-port">{t('conn.port')}</Label>
                    <Input id="conn-port" value={form.port} onChange={set('port')} aria-label={t('conn.port')} className={fieldCls} />
                  </div>
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="conn-database">{t('conn.database')}</Label>
                  <Input id="conn-database" value={form.database} onChange={set('database')} aria-label={t('conn.database')} className={fieldCls} />
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="conn-username">{t('conn.username')}</Label>
                    <Input id="conn-username" value={form.username} onChange={set('username')} aria-label={t('conn.username')} className={fieldCls} />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="conn-password">{t('conn.password')}</Label>
                    <Input
                      id="conn-password"
                      type="password"
                      value={form.password}
                      onChange={set('password')}
                      aria-label={t('conn.password')}
                      placeholder={editing ? t('conn.passwordKeepHint') : undefined}
                      className={fieldCls}
                    />
                  </div>
                </div>
              </>
            )}

            <TestOutcome state={formTest} />
            {formErr && (
              <div role="alert" className="text-destructive text-xs">
                {formErr}
              </div>
            )}
          </div>

          <DialogFooter>
            {!editing && (
              <Button
                variant="outline"
                className="mr-auto"
                disabled={!form.database || formTest?.status === 'pending'}
                onClick={() =>
                  void runTest(
                    {
                      dbType: effectiveType,
                      ...(isSqlite
                        ? { database: form.database }
                        : {
                            host: form.host,
                            port: form.port ? Number(form.port) : undefined,
                            database: form.database,
                            username: form.username,
                            password: form.password,
                          }),
                    },
                    setFormTest,
                  )
                }
              >
                {formTest?.status === 'pending' ? t('conn.testing') : t('conn.testConn')}
              </Button>
            )}
            <Button variant="outline" onClick={() => setFormOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button
              onClick={submit}
              disabled={save.isPending || !form.name.trim() || !form.database}
            >
              {t('common.save')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  )
}

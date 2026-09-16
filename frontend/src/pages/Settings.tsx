import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { api } from '../api/client'
import type { AgentTokenCreated, AgentTokenSummary } from '../api/types'
import { errText } from '../i18n/errText'
import { Button } from '@/components/ui/button'
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

/** Copy with the non-secure-context fallback: plain-http LAN deployments
 *  have no navigator.clipboard, so fall back to the legacy (deprecated but
 *  universal) execCommand path — same idiom as the export dialog's copy. */
async function copyText(text: string): Promise<boolean> {
  let ok = false
  if (navigator.clipboard) {
    try {
      await navigator.clipboard.writeText(text)
      ok = true
    } catch {
      ok = false
    }
  }
  if (!ok) {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    try {
      ok = document.execCommand('copy')
    } catch {
      ok = false
    }
    ta.remove()
  }
  return ok
}

/** One-time plaintext block: copy + warning. Closing discards the only
 *  copy the client ever holds — the API will not serve it again. */
function FreshToken({ token, onDone }: { token: string; onDone: () => void }) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)
  return (
    <div className="rounded-card border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
      <p className="mb-2 font-medium">{t('settings.created')}</p>
      <div className="flex items-center gap-2">
        <Input
          readOnly
          value={token}
          aria-label={t('settings.created')}
          className="font-mono text-xs"
        />
        <Button
          size="sm"
          variant="outline"
          onClick={() => {
            void copyText(token).then((ok) => {
              if (ok) {
                setCopied(true)
                toast.success(t('settings.copyOk'))
              }
            })
          }}
        >
          {copied ? '✓' : t('common.copy')}
        </Button>
      </div>
      <p className="text-ink-3 mt-2 text-xs">{t('settings.createdWarning')}</p>
      <Button size="sm" className="mt-2" onClick={onDone}>
        {t('common.close')}
      </Button>
    </div>
  )
}

/** Settings (/settings): agent-token management for MCP clients — list
 *  (prefix only), create (plaintext shown exactly once), revoke (hard
 *  delete, effective on the client's next request). */
export default function Settings() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [creating, setCreating] = useState(false)
  const [label, setLabel] = useState('')
  const [fresh, setFresh] = useState<string | null>(null)

  const tokens = useQuery({
    queryKey: ['agent-tokens'],
    queryFn: () => api.get<AgentTokenSummary[]>('/api/v1/agent-tokens'),
  })

  const create = useMutation({
    mutationFn: () => api.post<AgentTokenCreated>('/api/v1/agent-tokens', { label }),
    onSuccess: (d) => {
      setFresh(d.token)
      setCreating(false)
      setLabel('')
      void qc.invalidateQueries({ queryKey: ['agent-tokens'] })
    },
    onError: (e) => toast.error(errText(e, t)),
  })

  const revoke = useMutation({
    mutationFn: (id: string) => api.del(`/api/v1/agent-tokens/${id}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['agent-tokens'] })
    },
    onError: (e) => toast.error(errText(e, t)),
  })

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 px-6 py-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold">{t('settings.title')}</h1>
          <p className="text-ink-3 text-xs">{t('settings.subtitle')}</p>
        </div>
        {!creating && (
          <Button size="sm" onClick={() => setCreating(true)}>
            {t('settings.newToken')}
          </Button>
        )}
      </div>

      {fresh && <FreshToken token={fresh} onDone={() => setFresh(null)} />}

      {creating && (
        <form
          className="border-line bg-panel rounded-card flex items-end gap-2 border p-3"
          onSubmit={(e) => {
            e.preventDefault()
            create.mutate()
          }}
        >
          <div className="flex flex-1 flex-col gap-1.5">
            <Label htmlFor="agent-token-label">{t('settings.label')}</Label>
            <Input
              id="agent-token-label"
              value={label}
              maxLength={64}
              onChange={(e) => setLabel(e.target.value)}
              placeholder={t('settings.labelPlaceholder')}
            />
          </div>
          <Button size="sm" type="submit" disabled={!label.trim() || create.isPending}>
            {t('common.save')}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              setCreating(false)
              setLabel('')
            }}
          >
            {t('common.cancel')}
          </Button>
        </form>
      )}

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t('settings.label')}</TableHead>
            <TableHead>{t('settings.prefix')}</TableHead>
            <TableHead>{t('settings.createdAt')}</TableHead>
            <TableHead>{t('settings.lastUsedAt')}</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          {(tokens.data ?? []).map((row) => (
            <TableRow key={row.id}>
              <TableCell className="text-xs">{row.label}</TableCell>
              <TableCell className="font-mono text-xs">{row.tokenPrefix}…</TableCell>
              <TableCell className="text-xs">{new Date(row.createdAt).toLocaleString()}</TableCell>
              <TableCell className="text-xs">
                {row.lastUsedAt ? new Date(row.lastUsedAt).toLocaleString() : t('settings.never')}
              </TableCell>
              <TableCell>
                <Button
                  size="sm"
                  variant="ghost"
                  className="text-destructive"
                  onClick={() => {
                    // Native confirm for v1; the AlertDialog upgrade is
                    // deferred. Revocation is immediate and irreversible.
                    if (
                      window.confirm(
                        `${t('settings.revokeConfirmTitle')}\n${t('settings.revokeConfirmDesc')}`,
                      )
                    )
                      revoke.mutate(row.id)
                  }}
                >
                  {t('settings.revoke')}
                </Button>
              </TableCell>
            </TableRow>
          ))}
          {tokens.data?.length === 0 && (
            <TableRow>
              <TableCell colSpan={5} className="text-ink-3 py-6 text-center text-xs">
                {t('settings.empty')}
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  )
}

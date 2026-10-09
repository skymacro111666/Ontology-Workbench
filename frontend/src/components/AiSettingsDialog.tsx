import { Loader2Icon, PlugZapIcon } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ApiErr, api } from '../api/client'
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
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useUiStore } from '../stores/uiStore'

const fieldCls = 'border-line bg-panel-2 text-ink rounded-ctl border px-2 py-1.5 text-sm w-full'

/** GET /ai/settings payload — the key is write-only (hasKey + last4 only). */
interface AiSettings {
  provider: string
  baseUrl: string | null
  model: string | null
  hasKey: boolean
  keyLast4: string | null
  source: 'env' | 'db'
}

/** Store-opened AI settings dialog (spec §2): provider/baseUrl/model fields,
 *  a write-only API key, a one-token connection probe, and the effective
 *  config's source (db row over env bootstrap). */
export default function AiSettingsDialog() {
  const { t } = useTranslation()
  const open = useUiStore((s) => s.aiSettingsOpen)
  const setAiSettingsOpen = useUiStore((s) => s.setAiSettingsOpen)
  const queryClient = useQueryClient()

  const [provider, setProvider] = useState('openai')
  const [baseUrl, setBaseUrl] = useState('')
  const [model, setModel] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [testing, setTesting] = useState(false)
  const [probe, setProbe] = useState<{ ok: boolean; latencyMs?: number; message?: string } | null>(
    null,
  )

  const settings = useQuery({
    queryKey: ['ai-settings'],
    queryFn: () => api.get<AiSettings>('/api/v1/ai/settings'),
    enabled: open,
  })

  // Copy the fetched row into the form once per data identity (render-time
  // sync, same pattern as the closed→open resets — no set-state-in-effect).
  const [synced, setSynced] = useState<AiSettings | undefined>(undefined)
  if (settings.data !== synced) {
    setSynced(settings.data)
    if (settings.data) {
      setProvider(settings.data.provider)
      setBaseUrl(settings.data.baseUrl ?? '')
      setModel(settings.data.model ?? '')
      setApiKey('')
      setError(null)
      setProbe(null)
    }
  }

  const save = async () => {
    if (busy || testing) return
    setBusy(true)
    setError(null)
    try {
      // apiKey omitted = keep the stored key (backend contract)
      const body: Record<string, string> = { provider, baseUrl, model }
      const key = apiKey.trim()
      if (key) body.apiKey = key
      await api.put('/api/v1/ai/settings', body)
      toast.success(t('aiSettings.saved'))
      setApiKey('')
      void queryClient.invalidateQueries({ queryKey: ['ai-settings'] })
      void queryClient.invalidateQueries({ queryKey: ['ai-status'] })
    } catch (e) {
      setError(e instanceof ApiErr ? errText(e, t) : t('shell.loadFailed'))
    } finally {
      setBusy(false)
    }
  }

  const testConn = async () => {
    if (busy || testing) return
    setTesting(true)
    setProbe(null)
    try {
      const r = await api.post<{ ok: boolean; latencyMs?: number; message?: string }>(
        '/api/v1/ai/test',
        {},
      )
      setProbe(r)
    } catch (e) {
      setError(e instanceof ApiErr ? errText(e, t) : t('shell.loadFailed'))
    } finally {
      setTesting(false)
    }
  }

  const keyHint = settings.data?.hasKey
    ? settings.data.keyLast4
      ? t('aiSettings.keyLast4', { last4: settings.data.keyLast4 })
      : t('aiSettings.hasKey')
    : t('aiSettings.noKey')

  return (
    <Dialog open={open} onOpenChange={(o) => !o && setAiSettingsOpen(false)}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t('aiSettings.title')}</DialogTitle>
          <DialogDescription>{keyHint}</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="text-ink-2 flex items-center gap-1.5 text-xs">
            <span>{t('aiSettings.source')}</span>
            <span className="text-ink font-medium">
              {settings.data?.source === 'db'
                ? t('aiSettings.sourceDb')
                : t('aiSettings.sourceEnv')}
            </span>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="ai-provider">{t('aiSettings.provider')}</Label>
              <select
                id="ai-provider"
                value={provider}
                onChange={(e) => setProvider(e.target.value)}
                aria-label={t('aiSettings.provider')}
                className={fieldCls}
              >
                <option value="openai">{t('aiSettings.providerOpenai')}</option>
                <option value="anthropic">{t('aiSettings.providerAnthropic')}</option>
              </select>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="ai-model">{t('aiSettings.model')}</Label>
              <Input
                id="ai-model"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                aria-label={t('aiSettings.model')}
                className="text-sm"
              />
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="ai-baseurl">{t('aiSettings.baseUrl')}</Label>
            <Input
              id="ai-baseurl"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              aria-label={t('aiSettings.baseUrl')}
              placeholder="https://api.openai.com/v1"
              className="text-sm"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="ai-key">{t('aiSettings.apiKey')}</Label>
            <Input
              id="ai-key"
              type="password"
              autoComplete="off"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              aria-label={t('aiSettings.apiKey')}
              placeholder={
                settings.data?.hasKey && settings.data.keyLast4
                  ? `••••${settings.data.keyLast4}`
                  : t('aiSettings.keyKeep')
              }
              className="text-sm"
            />
          </div>

          {probe && (
            <div className="flex flex-wrap items-center gap-1.5 text-xs">
              {probe.ok ? (
                <span className="text-primary">{t('aiSettings.testOk', { ms: probe.latencyMs })}</span>
              ) : (
                <>
                  <span className="text-destructive">{t('aiSettings.testFail')}</span>
                  {probe.message && <span className="text-ink-2">{probe.message}</span>}
                </>
              )}
            </div>
          )}

          {error && (
            <p role="alert" className="text-destructive text-sm">
              {error}
            </p>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" size="sm" onClick={() => setAiSettingsOpen(false)} disabled={busy}>
            {t('common.cancel')}
          </Button>
          <Button variant="outline" size="sm" onClick={() => void testConn()} disabled={busy || testing}>
            {testing ? (
              <Loader2Icon aria-hidden="true" className="animate-spin" />
            ) : (
              <PlugZapIcon aria-hidden="true" />
            )}
            {testing ? t('aiSettings.testing') : t('aiSettings.test')}
          </Button>
          <Button size="sm" onClick={() => void save()} disabled={busy || testing}>
            {busy && <Loader2Icon aria-hidden="true" className="animate-spin" />}
            {t('aiSettings.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

import { CopyIcon, DownloadIcon, Loader2Icon } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { ApiErr, api } from '../api/client'
import { LAST_OID_KEY } from '../auth/AuthContext'
import { errText } from '../i18n/errText'
import type { ExportSiteResult } from '../api/types'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { useUiStore } from '@/stores/uiStore'

/** Docs-site export dialog: output-dir option, force switch, in-dialog
 *  result with zip download and path copy. The floating replacement for
 *  the former /export page — the file menu guards on a chosen ontology
 *  before opening, so a last oid is always available at submit time. */
export default function ExportDialog() {
  const { t } = useTranslation()
  const open = useUiStore((s) => s.exportOpen)
  const setExportOpen = useUiStore((s) => s.setExportOpen)
  const [outDir, setOutDir] = useState('')
  const [force, setForce] = useState(false)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<ExportSiteResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [downloading, setDownloading] = useState(false)

  // Opening always comes from the store (this dialog has no DialogTrigger),
  // so Radix only ever delivers `false` through onOpenChange; reset the form
  // on the closed→open transition in render time (same pattern as the other
  // file dialogs — a useEffect here would trip react-hooks/set-state-in-effect).
  const [prevOpen, setPrevOpen] = useState(open)
  if (open !== prevOpen) {
    setPrevOpen(open)
    if (open) {
      setOutDir('')
      setForce(false)
      setBusy(false)
      setResult(null)
      setError(null)
    }
  }

  const submit = async () => {
    const oid = localStorage.getItem(LAST_OID_KEY)
    if (!oid || busy) return
    setBusy(true)
    // A resubmit invalidates the previous run: drop the stale result block.
    setResult(null)
    setError(null)
    try {
      setResult(
        await api.post<ExportSiteResult>(`/api/ontologies/${oid}/export/site`, {
          outDir: outDir.trim() || undefined,
          force,
        }),
      )
    } catch (e) {
      if (e instanceof ApiErr && e.code === 'VALIDATION_ERROR') {
        setError(t('exportDialog.dirNotEmpty'))
      } else if (e instanceof ApiErr) {
        setError(errText(e, t))
      } else {
        setError(t('exportDialog.exportFailed'))
      }
    } finally {
      setBusy(false)
    }
  }

  /** Zip the exported directory server-side and land it in the browser's
   *  downloads; the server copy stays put for deployment use. */
  const downloadZip = async () => {
    const oid = localStorage.getItem(LAST_OID_KEY)
    if (!result || !oid) return
    setDownloading(true)
    try {
      const name = await api.downloadBinary(
        `/api/ontologies/${oid}/export/site/archive?dir_path=${encodeURIComponent(result.outputDir)}`,
        'docs-site.zip',
      )
      toast.success(t('exportDialog.downloaded', { name }))
    } catch (e) {
      toast.error(errText(e, t))
    } finally {
      setDownloading(false)
    }
  }

  const copyDir = async () => {
    if (!result) return
    let ok = false
    if (navigator.clipboard) {
      try {
        await navigator.clipboard.writeText(result.outputDir)
        ok = true
      } catch {
        ok = false
      }
    }
    if (!ok) {
      // Plain-http LAN deployments are not a secure context: the async
      // clipboard API does not exist there, so fall back to the legacy
      // (deprecated but universally supported) execCommand path.
      const ta = document.createElement('textarea')
      ta.value = result.outputDir
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
    if (ok) toast.success(t('exportDialog.copied'))
    else toast.error(t('exportDialog.copyFailed'))
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && setExportOpen(false)}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t('exportDialog.title')}</DialogTitle>
          <DialogDescription>{t('exportDialog.desc')}</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="export-outdir">{t('exportDialog.outDirLabel')}</Label>
            <Input
              id="export-outdir"
              value={outDir}
              placeholder={t('exportDialog.outDirPlaceholder')}
              onChange={(e) => setOutDir(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !busy) void submit()
              }}
              disabled={busy}
            />
            <p className="text-ink-3 text-xs">{t('exportDialog.outDirHint')}</p>
          </div>
          <div className="flex items-center gap-2">
            <Switch
              id="export-force"
              checked={force}
              onCheckedChange={setForce}
              disabled={busy}
            />
            <Label htmlFor="export-force">{t('exportDialog.forceLabel')}</Label>
          </div>
          {error && (
            <p role="alert" className="text-destructive text-sm">
              {error}
            </p>
          )}
          {result && (
            <div className="border-line flex flex-col gap-2 rounded-card border p-3">
              <p className="text-ink-2 text-sm font-medium">{t('exportDialog.resultTitle')}</p>
              <div className="flex items-center gap-2">
                <code className="text-ink-2 min-w-0 flex-1 font-mono text-sm break-all">
                  {result.outputDir}
                </code>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="shrink-0"
                  disabled={downloading}
                  onClick={() => void downloadZip()}
                >
                  <DownloadIcon />
                  {t('exportDialog.download')}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="shrink-0"
                  onClick={() => void copyDir()}
                >
                  <CopyIcon />
                  {t('common.copy')}
                </Button>
              </div>
              <p className="text-ink-2 text-sm">
                {t('exportDialog.pages', {
                  total: result.pageCount,
                  entities: result.pageCount - 1,
                })}
              </p>
            </div>
          )}
        </div>
        <Button
          type="button"
          size="sm"
          className="w-fit"
          disabled={busy}
          onClick={() => void submit()}
        >
          {busy && <Loader2Icon aria-hidden className="animate-spin" />}
          {busy ? t('exportDialog.exporting') : t('exportDialog.submit')}
        </Button>
      </DialogContent>
    </Dialog>
  )
}

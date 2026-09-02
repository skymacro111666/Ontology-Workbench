import { zodResolver } from '@hookform/resolvers/zod'
import { CopyIcon, DownloadIcon } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { useParams } from 'react-router'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { z } from 'zod'
import { ApiErr, api } from '../api/client'
import { errText } from '../i18n/errText'
import type { ExportSiteResult } from '../api/types'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'

const exportSchema = z.object({
  outDir: z.string(),
})

type ExportForm = z.infer<typeof exportSchema>

/** One-click docs-site export: output-dir option, force switch, copyable result path. */
export default function Export() {
  const { t } = useTranslation()
  const { oid = '' } = useParams()
  const [force, setForce] = useState(false)
  const [result, setResult] = useState<ExportSiteResult | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const [downloading, setDownloading] = useState(false)
  const form = useForm<ExportForm>({
    resolver: zodResolver(exportSchema),
    defaultValues: { outDir: '' },
  })
  const submitting = form.formState.isSubmitting

  const onSubmit = async (values: ExportForm) => {
    // A resubmit invalidates the previous run: drop the stale success card.
    setResult(null)
    setFormError(null)
    try {
      setResult(
        await api.post<ExportSiteResult>(`/api/ontologies/${oid}/export/site`, {
          outDir: values.outDir.trim() || undefined,
          force,
        }),
      )
    } catch (err) {
      if (err instanceof ApiErr && err.code === 'VALIDATION_ERROR') {
        setFormError(t('exportPage.dirNotEmpty'))
      } else if (err instanceof ApiErr) {
        setFormError(errText(err, t))
      } else {
        setFormError(t('exportPage.exportFailed'))
      }
    }
  }

  /** Zip the exported directory server-side and land it in the browser's
   *  downloads; the server copy stays put for deployment use. */
  const downloadZip = async () => {
    if (!result) return
    setDownloading(true)
    try {
      const name = await api.downloadBinary(
        `/api/ontologies/${oid}/export/site/archive?dir_path=${encodeURIComponent(result.outputDir)}`,
        'docs-site.zip',
      )
      toast.success(t('exportPage.downloaded', { name }))
    } catch (err) {
      toast.error(errText(err, t))
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
    if (ok) toast.success(t('exportPage.copied'))
    else toast.error(t('exportPage.copyFailed'))
  }

  return (
    <div className="mx-auto flex w-full max-w-[640px] flex-col gap-6 px-6 py-10">
      <Card className="rounded-card">
        <CardHeader>
          <CardTitle>{t('exportPage.title')}</CardTitle>
          <CardDescription>{t('exportPage.desc')}</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={form.handleSubmit(onSubmit)} className="flex flex-col gap-4" noValidate>
            {formError && (
              <p role="alert" className="text-sm text-destructive">
                {formError}
              </p>
            )}
            <div className="flex flex-col gap-2">
              <Label htmlFor="outDir">{t('exportPage.outDirLabel')}</Label>
              <Input
                id="outDir"
                placeholder={t('exportPage.outDirPlaceholder')}
                disabled={submitting}
                {...form.register('outDir')}
              />
              <p className="text-ink-3 text-xs">{t('exportPage.outDirHint')}</p>
            </div>
            <div className="flex items-center gap-2">
              <Switch
                id="force"
                checked={force}
                onCheckedChange={setForce}
                disabled={submitting}
              />
              <Label htmlFor="force">{t('exportPage.forceLabel')}</Label>
            </div>
            <Button type="submit" className="w-fit" disabled={submitting}>
              {t('exportPage.submit')}
            </Button>
          </form>
        </CardContent>
      </Card>

      {result && (
        <Card className="rounded-card">
          <CardHeader>
            <CardTitle>{t('exportPage.resultTitle')}</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
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
                {t('exportPage.download')}
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
              {t('exportPage.pages', { total: result.pageCount, entities: result.pageCount - 1 })}
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

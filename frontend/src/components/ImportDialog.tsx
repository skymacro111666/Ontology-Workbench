import { useQueryClient } from '@tanstack/react-query'
import { CloudUploadIcon, Loader2Icon } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import type { OntologyMeta } from '../api/types'
import { ApiErr, api } from '../api/client'
import { errText } from '../i18n/errText'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useUiStore } from '@/stores/uiStore'

const MAX_BYTES = 150 * 1024 * 1024
const ACCEPT = '.ttl,.owl,.rdf,.jsonld,.json'

/** Import dialog: pick/drop an ontology file, upload it, toast the outcome. */
export default function ImportDialog() {
  const { t } = useTranslation()
  const open = useUiStore((s) => s.importOpen)
  const setImportOpen = useUiStore((s) => s.setImportOpen)
  const queryClient = useQueryClient()
  const [status, setStatus] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [sizeError, setSizeError] = useState<string | null>(null)
  /** Upload bytes sent so far (null until the first progress event). */
  const [progress, setProgress] = useState<{ loaded: number; total: number } | null>(null)
  /** Bytes done, response pending: the server is parsing (minutes for 100MB+). */
  const [parsing, setParsing] = useState(false)

  /** Guard the 150MB limit, then upload and report the outcome. */
  async function handleFile(chosen: File) {
    if (chosen.size > MAX_BYTES) {
      setSizeError(t('importDialog.tooLarge', { name: chosen.name }))
      return
    }
    setSizeError(null)
    setStatus(t('importDialog.importing', { name: chosen.name }))
    setProgress(null)
    setParsing(false)
    setUploading(true)
    try {
      await api.upload<OntologyMeta>(chosen, (loaded, total) => {
        setProgress({ loaded, total })
        if (loaded >= total) setParsing(true)
      })
      setStatus(t('importDialog.imported', { name: chosen.name }))
      toast.success(t('importDialog.success'))
      void queryClient.invalidateQueries({ queryKey: ['ontologies'] })
      setImportOpen(false)
    } catch (err) {
      setStatus(t('importDialog.failed', { name: chosen.name }))
      if (err instanceof ApiErr) {
        toast.error(
          err.code === 'DUPLICATE_FILENAME' ? t('importDialog.duplicate') : errText(err, t),
        )
      } else {
        toast.error(t('importDialog.uploadFailed'))
      }
    } finally {
      setUploading(false)
      setProgress(null)
      setParsing(false)
    }
  }

  // Opening always comes from the store (this dialog has no DialogTrigger),
  // so Radix only ever delivers `false` through onOpenChange; clear the last
  // session's messages on the closed→open transition (render-time state
  // adjustment per react.dev "You Might Not Need an Effect" — a useEffect here
  // trips react-hooks/set-state-in-effect).
  const [prevOpen, setPrevOpen] = useState(open)
  if (open !== prevOpen) {
    setPrevOpen(open)
    if (open) {
      setSizeError(null)
      setStatus(null)
      // A still-pending upload from the closed session must not disable the
      // fresh one's input (backlog T3rr); its finally will settle harmlessly.
      setUploading(false)
    }
  }

  return (
    <>
      {/* Outside the portal so it outlives the closing dialog (status messages
          for screen readers; visually the success toast carries the outcome). */}
      {status && (
        <p role="status" className="sr-only">
          {status}
        </p>
      )}
      <Dialog open={open} onOpenChange={setImportOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('importDialog.title')}</DialogTitle>
            <DialogDescription>{t('importDialog.desc')}</DialogDescription>
          </DialogHeader>
          <label
            htmlFor="import-file"
            className="border-line hover:border-primary flex cursor-pointer flex-col items-center gap-2 rounded-card border border-dashed p-8 text-center transition-colors"
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault()
              const dropped = e.dataTransfer.files[0]
              if (dropped) void handleFile(dropped)
            }}
          >
            <CloudUploadIcon className="text-ink-3 size-8" aria-hidden />
            <span className="text-ink-2 text-sm">{t('importDialog.dropHint')}</span>
          </label>
          <input
            id="import-file"
            type="file"
            accept={ACCEPT}
            className="sr-only"
            onChange={(e) => {
              const chosen = e.target.files?.[0]
              if (chosen) void handleFile(chosen)
              e.target.value = ''
            }}
            disabled={uploading}
          />
          {uploading && !parsing && progress && progress.total > 0 && (
            <div role="status" className="flex flex-col gap-1">
              {(() => {
                const pct = Math.min(100, Math.round((progress.loaded / progress.total) * 100))
                return (
                  <>
                    <div
                      role="progressbar"
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={pct}
                      className="border-line h-1.5 w-full overflow-hidden rounded-full border"
                    >
                      <div
                        className="bg-primary h-full rounded-full transition-[width] duration-150"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <span className="text-ink-3 text-xs">
                      {t('importDialog.uploadProgress', {
                        loaded: (progress.loaded / 1048576).toFixed(1),
                        total: (progress.total / 1048576).toFixed(1),
                        pct,
                      })}
                    </span>
                  </>
                )
              })()}
            </div>
          )}
          {uploading && parsing && (
            <p role="status" className="text-ink-2 flex items-center gap-2 text-sm">
              <Loader2Icon className="text-ink-3 size-4 animate-spin" aria-hidden />
              {t('importDialog.parsing')}
            </p>
          )}
          {sizeError && (
            <p className="text-destructive text-sm" role="alert">
              {sizeError}
            </p>
          )}
        </DialogContent>
      </Dialog>
    </>
  )
}

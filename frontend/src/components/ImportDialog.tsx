import { useQueryClient } from '@tanstack/react-query'
import { CloudUploadIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import type { OntologyMeta } from '../api/types'
import { ApiErr, api } from '../api/client'
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
  const open = useUiStore((s) => s.importOpen)
  const setImportOpen = useUiStore((s) => s.setImportOpen)
  const queryClient = useQueryClient()
  const [status, setStatus] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [sizeError, setSizeError] = useState<string | null>(null)

  /** Guard the 150MB limit, then upload and report the outcome. */
  async function handleFile(chosen: File) {
    if (chosen.size > MAX_BYTES) {
      setSizeError(`「${chosen.name}」文件超过 150MB 限制`)
      return
    }
    setSizeError(null)
    setStatus(`正在导入：${chosen.name}`)
    setUploading(true)
    try {
      await api.upload<OntologyMeta>(chosen)
      setStatus(`已导入：${chosen.name}`)
      toast.success('导入成功')
      void queryClient.invalidateQueries({ queryKey: ['ontologies'] })
      setImportOpen(false)
    } catch (err) {
      setStatus(`导入失败：${chosen.name}`)
      if (err instanceof ApiErr) {
        toast.error(
          err.code === 'DUPLICATE_FILENAME' ? '同名本体已存在，请重命名或先删除' : err.message,
        )
      } else {
        toast.error('上传失败，请稍后重试')
      }
    } finally {
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
      <Dialog
        open={open}
        onOpenChange={(next) => {
          setImportOpen(next)
          if (next) {
            setSizeError(null)
            setStatus(null)
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>导入本体</DialogTitle>
            <DialogDescription>
              支持 .ttl / .owl / .rdf / .jsonld / .json，单个文件最大 150MB
            </DialogDescription>
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
            <span className="text-ink-2 text-sm">点击或拖拽文件到此处上传</span>
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

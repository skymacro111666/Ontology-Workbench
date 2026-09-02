import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import type { OntologyMeta } from '../api/types'
import { ApiErr, api } from '../api/client'
import { LAST_OID_KEY } from '../auth/AuthContext'
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
import { useUiStore } from '@/stores/uiStore'

/** Blank-create dialog: name a new ontology, POST /ontologies/blank, jump
 *  into the workspace. The server mints a skeleton (header + label + one
 *  class and one property), so the canvas opens alive rather than empty. */
export default function BlankOntologyDialog() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const open = useUiStore((s) => s.blankOpen)
  const setBlankOpen = useUiStore((s) => s.setBlankOpen)
  const [name, setName] = useState('')
  const [namespace, setNamespace] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const close = () => {
    setName('')
    setNamespace('')
    setError(null)
    setBusy(false)
    setBlankOpen(false)
  }

  const submit = async () => {
    const trimmed = name.trim()
    if (!trimmed) return
    const ns = namespace.trim()
    if (/\s/.test(ns)) {
      setError(t('blankDialog.nsWhitespace'))
      return
    }
    setError(null)
    setBusy(true)
    // A custom namespace needs a trailing # or / — without one, entity IRIs
    // glue onto the path (…/vocabExample). The backend only strips, never
    // appends, so the dialog normalizes before sending.
    const body: { name: string; namespace?: string } = { name: trimmed }
    if (ns) {
      body.namespace = ns.endsWith('#') || ns.endsWith('/') ? ns : `${ns}#`
    }
    try {
      const meta = await api.post<OntologyMeta>('/api/ontologies/blank', body)
      toast.success(t('blankDialog.created', { name: trimmed }))
      void queryClient.invalidateQueries({ queryKey: ['ontologies'] })
      localStorage.setItem(LAST_OID_KEY, meta.id)
      close()
      navigate(`/browse/${meta.id}`)
    } catch (e) {
      setError(
        e instanceof ApiErr && e.code === 'DUPLICATE_FILENAME'
          ? t('blankDialog.duplicate')
          : errText(e, t),
      )
      setBusy(false)
    }
  }

  // Opening always comes from the store (this dialog has no DialogTrigger),
  // so Radix only ever delivers `false` through onOpenChange; reset the form
  // on the closed→open transition in render time (same pattern as ImportDialog
  // — a useEffect here would trip react-hooks/set-state-in-effect).
  const [prevOpen, setPrevOpen] = useState(open)
  if (open !== prevOpen) {
    setPrevOpen(open)
    if (open) {
      setName('')
      setNamespace('')
      setError(null)
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && close()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>{t('blankDialog.title')}</DialogTitle>
          <DialogDescription>{t('blankDialog.desc')}</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="blank-name">{t('blankDialog.name')}</Label>
            <Input
              id="blank-name"
              value={name}
              placeholder={t('blankDialog.namePlaceholder')}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && name.trim() && !busy) void submit()
              }}
              disabled={busy}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="blank-ns">{t('blankDialog.namespace')}</Label>
            <Input
              id="blank-ns"
              value={namespace}
              placeholder={t('blankDialog.nsPlaceholder')}
              onChange={(e) => setNamespace(e.target.value)}
              disabled={busy}
            />
          </div>
          {error && (
            <p role="alert" className="text-destructive text-sm">
              {error}
            </p>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" size="sm" onClick={close} disabled={busy}>
            {t('common.cancel')}
          </Button>
          <Button size="sm" onClick={() => void submit()} disabled={busy || !name.trim()}>
            {t('blankDialog.create')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

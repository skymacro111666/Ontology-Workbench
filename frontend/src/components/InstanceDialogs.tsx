import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Trans, useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { ApiErr, api } from '../api/client'
import { errText } from '../i18n/errText'
import type { NodesEdges, OntologyMeta } from '../api/types'
import { localName } from '../lib/localName'
import { useBrowseStore } from '../stores/browseStore'
import { useUiStore } from '../stores/uiStore'
import { Button } from '@/components/ui/button'
import { ClassPicker } from './EntityDialogs'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

/** The B2 instance dialog family: minimal create (prefix/name/types/comment)
 *  and delete confirm. Creation lands straight in the detail's edit mode —
 *  assertions join inline there (spec §0 create-flow decision) — so the form
 *  deliberately carries no assertion rows. Same mode-driven shape as
 *  EntityDialogs: shared queries ride the callers' cache entries, every
 *  submit invalidates the whole tree. */
export default function InstanceDialogs({ oid }: { oid: string }) {
  const { t } = useTranslation()
  const dialog = useUiStore((s) => s.instanceDialog)
  const setInstanceDialog = useUiStore((s) => s.setInstanceDialog)
  const setInstanceAutoEdit = useUiStore((s) => s.setInstanceAutoEdit)
  const reveal = useBrowseStore((s) => s.reveal)
  const setSelected = useBrowseStore((s) => s.setSelected)
  const queryClient = useQueryClient()

  const { data: meta } = useQuery({
    queryKey: ['ontology', oid],
    queryFn: () => api.get<OntologyMeta>(`/api/ontologies/${oid}/meta`),
    enabled: !!dialog,
  })
  const { data: overview } = useQuery({
    queryKey: ['overview', oid],
    queryFn: () => api.get<NodesEdges>(`/api/ontologies/${oid}/overview`),
    enabled: dialog?.mode === 'create',
  })
  const classes = (overview?.nodes ?? []).filter((n) => n.kind === 'class')
  const prefixes = Object.keys(meta?.prefixes ?? {})

  const open = !!dialog

  // ---- form state, reset on open (EntityDialogs' prevOpen pattern) ----
  const [prevOpen, setPrevOpen] = useState(false)
  const [name, setName] = useState('')
  const [prefix, setPrefix] = useState('ex')
  const [comment, setComment] = useState('')
  const [picked, setPicked] = useState<string[]>([])
  const [nameError, setNameError] = useState<string | null>(null)
  useEffect(() => {
    if (open && !prevOpen) {
      // Fires once per open transition, so the cascading renders the rule
      // fears cannot loop here.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setName('')
      setPrefix(Object.keys(meta?.prefixes ?? { ex: '' })[0] ?? 'ex')
      setComment('')
      setPicked(dialog?.parent ? [dialog.parent] : [])
      setNameError(null)
    }
    setPrevOpen(open)
  }, [open, prevOpen, dialog, meta])

  const mutation = useMutation({
    mutationFn: async () => {
      const fileHash = meta?.fileHash ?? ''
      if (dialog?.mode === 'create') {
        return api.post<{ entity: { eid: string } }>(`/api/ontologies/${oid}/instances`, {
          name: name.trim(),
          prefix,
          comment: comment.trim() === '' ? null : comment.trim(),
          classes: picked,
          baseFileHash: fileHash,
        })
      }
      return api.del(
        `/api/ontologies/${oid}/instances/${encodeURIComponent(dialog?.eid ?? '')}` +
          `?baseFileHash=${fileHash}`,
      )
    },
    onSuccess: (r) => {
      toast.success(t('common.saved'))
      setInstanceDialog(null)
      void queryClient.invalidateQueries()
      if (dialog?.mode === 'create') {
        const eid = (r as { entity?: { eid?: string } } | null)?.entity?.eid
        if (eid) {
          reveal(eid)
          setInstanceAutoEdit(eid)
        }
      } else {
        setSelected(null)
      }
    },
    onError: (e) => {
      if (e instanceof ApiErr && e.code === 'DUPLICATE_ENTITY') {
        setNameError(t('entityDialogs.nameTaken'))
        return
      }
      toast.error(errText(e, t))
    },
  })

  if (!dialog) return null

  const submit = () => {
    if (dialog.mode === 'create' && !/^[A-Za-z_][\w.-]*$/.test(name.trim())) {
      setNameError(t('entityDialogs.nameRule'))
      return
    }
    mutation.mutate()
  }

  const fieldCls =
    'border-line bg-panel-2 text-ink rounded-ctl border px-2 py-1.5 text-sm w-full'
  const labelCls = 'text-ink-2 text-xs font-medium'

  return (
    <Dialog open={open} onOpenChange={(o) => !o && setInstanceDialog(null)}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>
            {dialog.mode === 'create' ? t('instance.createTitle') : t('instance.deleteTitle')}
          </DialogTitle>
          <DialogDescription>
            {dialog.mode === 'create' ? t('instance.createDesc') : t('instance.deleteDesc')}
          </DialogDescription>
        </DialogHeader>

        {dialog.mode === 'create' ? (
          <div className="flex flex-col gap-3">
            <div className="grid grid-cols-[7rem_1fr] items-center gap-2">
              <span className={labelCls}>{t('entityDialogs.prefix')}</span>
              <select
                value={prefix}
                onChange={(e) => setPrefix(e.target.value)}
                className={fieldCls}
                aria-label={t('entityDialogs.prefix')}
              >
                {prefixes.map((p) => (
                  <option key={p} value={p}>
                    {p}:
                  </option>
                ))}
              </select>
            </div>
            <div className="grid grid-cols-[7rem_1fr] items-center gap-2">
              <span className={labelCls}>{t('entityDialogs.name')}</span>
              <input
                value={name}
                onChange={(e) => {
                  setName(e.target.value)
                  setNameError(null)
                }}
                aria-label={t('entityDialogs.name')}
                placeholder={t('entityDialogs.namePlaceholder')}
                className={fieldCls}
              />
            </div>
            {nameError && (
              <p role="alert" className="text-amber-600 dark:text-amber-400 pl-[7.75rem] text-xs">
                {nameError}
              </p>
            )}
            <div className="grid grid-cols-[7rem_1fr] items-start gap-2">
              <span className={labelCls}>{t('entityDialogs.description')}</span>
              <textarea
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                aria-label={t('entityDialogs.description')}
                rows={2}
                placeholder={t('entityDialogs.descPlaceholder')}
                className={`${fieldCls} resize-none`}
              />
            </div>
            <div className="grid grid-cols-[7rem_1fr] items-start gap-2">
              <span className={labelCls}>{t('instance.typeSection')}</span>
              <ClassPicker classes={classes} value={picked} onChange={setPicked} multiple />
            </div>
          </div>
        ) : (
          <p className="text-ink text-sm break-all">
            <Trans
              i18nKey="instance.confirmDelete"
              values={{ name: localName(dialog.eid ?? '') }}
              components={{ name: <span className="text-primary font-mono" /> }}
            />
          </p>
        )}

        <DialogFooter>
          <Button variant="outline" size="sm" onClick={() => setInstanceDialog(null)}>
            {t('common.cancel')}
          </Button>
          <Button size="sm" disabled={mutation.isPending} onClick={submit}>
            {dialog.mode === 'delete' ? t('common.delete') : t('common.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

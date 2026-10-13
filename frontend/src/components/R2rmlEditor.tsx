import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { EditorState, Prec } from '@codemirror/state'
import { EditorView, keymap, lineNumbers } from '@codemirror/view'
import { StreamLanguage, syntaxHighlighting } from '@codemirror/language'
import { openSearchPanel, search, searchKeymap } from '@codemirror/search'
import { turtle } from '@codemirror/legacy-modes/mode/turtle'
import { SearchIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { ApiErr, api } from '../api/client'
import { errText } from '../i18n/errText'
import { useUiStore } from '../stores/uiStore'
import type { R2rmlDoc } from '../api/types'
import { editorHighlight, editorTheme } from './SourceView'

/** PUT /r2rml response shape (P2 spec §5). */
interface R2rmlSaveResult {
  filename: string
  content: string
  contentHash: string
  previousExists: boolean
}

/** Editable Turtle over the R2RML mapping (P2 source tab). Saving PUTs the
 *  doc with contentHash as the optimistic lock; 422 findings render inline.
 *  The view lifecycle mirrors SourceView: never clobber local edits, a clean
 *  view adopts server text when it moves on. */
export default function R2rmlEditor({ oid, doc }: { oid: string; doc: R2rmlDoc }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const setR2rmlDirty = useUiStore((s) => s.setR2rmlDirty)
  const holderRef = useRef<HTMLDivElement>(null)
  const viewRef = useRef<EditorView | null>(null)
  const baselineRef = useRef(doc.content)
  const baseHashRef = useRef(doc.contentHash)
  const [dirty, setDirty] = useState(false)
  const [findings, setFindings] = useState<string[] | null>(null)
  const [rollbackOpen, setRollbackOpen] = useState(false)

  const rollback = useMutation({
    mutationFn: () =>
      api.post<R2rmlSaveResult>(`/api/v1/ontologies/${oid}/r2rml/rollback`, {
        baseHash: baseHashRef.current,
      }),
    onSuccess: (result) => {
      // The swap already happened server-side; adopt the returned text as
      // the new baseline so the editor rebuilds clean (never-clobber would
      // otherwise keep the dirty pre-rollback text).
      setDirty(false)
      setR2rmlDirty(false)
      baselineRef.current = result.content
      baseHashRef.current = result.contentHash
      void queryClient.invalidateQueries({ queryKey: ['r2rml', oid] })
    },
    onError: (err) => toast.error(errText(err, t)),
  })

  const save = useMutation({
    mutationFn: (content: string) =>
      api.put<R2rmlSaveResult>(`/api/v1/ontologies/${oid}/r2rml`, {
        content,
        baseHash: baseHashRef.current,
      }),
    onSuccess: (result, content) => {
      setFindings(null)
      baselineRef.current = content
      baseHashRef.current = result.contentHash
      setDirty(false)
      setR2rmlDirty(false)
      void queryClient.invalidateQueries({ queryKey: ['r2rml', oid] })
    },
    onError: (err) => {
      if (err instanceof ApiErr && err.code === 'R2RML_INVALID') {
        setFindings((err.hint ?? err.message).split('\n'))
        return
      }
      toast.error(errText(err, t))
      if (err instanceof ApiErr && err.code === 'R2RML_STALE')
        void queryClient.invalidateQueries({ queryKey: ['r2rml', oid] })
    },
  })
  const saveRef = useRef(save)
  useEffect(() => {
    saveRef.current = save
  })

  useEffect(() => {
    const el = holderRef.current
    if (!el) return
    const existing = viewRef.current
    if (existing) {
      if (dirty) return // never clobber local edits
      if (existing.state.doc.toString() === doc.content) {
        baseHashRef.current = doc.contentHash // same text, fresh hash
        return
      }
      existing.destroy() // clean + server moved on: adopt it
      viewRef.current = null
    }
    const view = new EditorView({
      parent: el,
      state: EditorState.create({
        doc: doc.content,
        extensions: [
          lineNumbers(),
          editorTheme,
          syntaxHighlighting(editorHighlight),
          StreamLanguage.define(turtle),
          EditorView.lineWrapping,
          search({ top: true }),
          keymap.of(searchKeymap),
          Prec.highest(
            keymap.of([
              {
                key: 'Mod-s',
                preventDefault: true,
                run: () => {
                  const text = viewRef.current?.state.doc.toString() ?? ''
                  if (!saveRef.current.isPending) saveRef.current.mutate(text)
                  return true
                },
              },
            ]),
          ),
          EditorView.updateListener.of((u) => {
            if (u.docChanged) {
              const d = u.state.doc.toString() !== baselineRef.current
              setDirty(d)
              setR2rmlDirty(d)
            }
          }),
        ],
      }),
    })
    baselineRef.current = doc.content
    baseHashRef.current = doc.contentHash
    setDirty(false)
    setR2rmlDirty(false)
    viewRef.current = view
  }, [doc, dirty, setR2rmlDirty])

  useEffect(
    () => () => {
      viewRef.current?.destroy()
      viewRef.current = null
      setR2rmlDirty(false)
    },
    [setR2rmlDirty],
  )

  // Browser close / hard navigation guard while dirty.
  useEffect(() => {
    if (!dirty) return
    const h = (e: BeforeUnloadEvent) => e.preventDefault()
    window.addEventListener('beforeunload', h)
    return () => window.removeEventListener('beforeunload', h)
  }, [dirty])

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <div className="flex items-center gap-2">
        <Button
          size="sm"
          disabled={!dirty || save.isPending}
          onClick={() => save.mutate(viewRef.current?.state.doc.toString() ?? '')}
        >
          {t('r2rml.save')}
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={!doc.previousExists || rollback.isPending}
          onClick={() => setRollbackOpen(true)}
        >
          {t('r2rml.rollback')}
        </Button>
        {dirty && <span className="text-ink-3 text-xs">{t('r2rml.unsaved')}</span>}
        <Button
          size="sm"
          variant="outline"
          className="ml-auto h-6 gap-1 px-2 text-xs"
          title={t('r2rml.findReplace')}
          onClick={() => viewRef.current && openSearchPanel(viewRef.current)}
        >
          <SearchIcon className="size-3" aria-hidden="true" />
          {t('r2rml.search')}
        </Button>
      </div>
      <AlertDialog open={rollbackOpen} onOpenChange={setRollbackOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('r2rml.rollbackTitle')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t(dirty ? 'r2rml.rollbackDescDirty' : 'r2rml.rollbackDesc')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={() => rollback.mutate()}>
              {t('r2rml.rollbackConfirm')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      {findings && (
        <div className="border-line bg-panel-2 rounded-ctl border p-2 text-xs">
          <p className="text-ink-1 mb-1 font-medium">{t('r2rml.findingsTitle')}</p>
          {findings.map((f) => (
            <p key={f} className="text-ink-2 font-mono">
              {f}
            </p>
          ))}
        </div>
      )}
      <div
        ref={holderRef}
        className="border-line min-h-0 flex-1 overflow-auto rounded-ctl border"
        aria-label={t('r2rml.tabSource')}
      />
    </div>
  )
}

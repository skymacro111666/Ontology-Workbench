import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { EditorState, Prec } from '@codemirror/state'
import { EditorView, keymap, lineNumbers } from '@codemirror/view'
import { HighlightStyle, StreamLanguage, syntaxHighlighting } from '@codemirror/language'
import { xml } from '@codemirror/lang-xml'
import { turtle } from '@codemirror/legacy-modes/mode/turtle'
import { tags as t } from '@lezer/highlight'
import { ApiErr, api } from '../api/client'
import type { OntologyMeta } from '../api/types'
import { useUiStore } from '../stores/uiStore'
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

/** /source payload: the stored ontology file, verbatim. */
interface SourcePayload {
  filename: string
  format: string
  content: string
  fileHash: string
}

/** Ontology format → editor language. Turtle/N3 share the Turtle grammar;
 *  unknown formats fall back to plain text (line numbers still on). */
export function languageFor(format: string) {
  if (format === 'xml' || format === 'rdf+xml') return xml()
  if (format === 'turtle' || format === 'n3') return StreamLanguage.define(turtle)
  return undefined
}

/* CodeMirror renders real DOM, so its theme can use CSS variables directly —
   light/dark follow ThemeProvider for free, no rebuild on theme switch. */
const editorTheme = EditorView.theme({
  '&': { height: '100%' },
  '.cm-scroller': {
    fontFamily: 'var(--font-mono)',
    fontSize: '12px',
    lineHeight: '1.7',
  },
  '.cm-content': { paddingBottom: '24px', maxWidth: '150ch' },
  '.cm-gutters': {
    backgroundColor: 'transparent',
    color: 'var(--color-ink-3)',
    border: 'none',
    borderRight: '1px solid var(--color-line)',
  },
})

/** Three-tone highlighting from the project palette: comments grey,
 *  keywords violet, IRIs/literals/numbers indigo, identifiers ink. */
const editorHighlight = HighlightStyle.define([
  { tag: t.comment, color: 'var(--color-ink-3)', fontStyle: 'italic' },
  { tag: t.keyword, color: 'var(--color-edge-sub)' },
  { tag: t.string, color: 'var(--color-primary)' },
  { tag: t.number, color: 'var(--color-primary)' },
  { tag: t.atom, color: 'var(--color-edge-sub)' },
  { tag: t.variableName, color: 'var(--color-ink)' },
])

/** Editable CodeMirror over the ontology source (workspace text view):
 *  dirty = doc differs from the loaded baseline; saving PUTs the doc with
 *  the baseline fileHash as the optimistic lock. */
export default function SourceView({ oid }: { oid: string }) {
  const holderRef = useRef<HTMLDivElement>(null)
  const viewRef = useRef<EditorView | null>(null)
  /** Loaded baseline: dirty === doc !== baseline. */
  const baselineRef = useRef('')
  /** fileHash the baseline was loaded under (PUT optimistic lock). */
  const baseHashRef = useRef('')
  /** Mirror of dirty for stable closures (keymap, registered save). */
  const dirtyRef = useRef(false)
  const [dirty, setDirty] = useState(false)
  const setSourceDirty = useUiStore((s) => s.setSourceDirty)
  const queryClient = useQueryClient()
  const { data, isError, error, refetch } = useQuery({
    queryKey: ['source', oid],
    queryFn: () => api.get<SourcePayload>(`/api/ontologies/${oid}/source`),
    retry: false,
  })

  const markDirty = (d: boolean) => {
    dirtyRef.current = d
    setDirty(d)
    setSourceDirty(d)
  }

  const saveMutation = useMutation({
    mutationFn: (content: string) =>
      api.put<OntologyMeta>(`/api/ontologies/${oid}/source`, {
        content,
        baseFileHash: baseHashRef.current,
      }),
    onSuccess: (meta, content) => {
      toast.success('已保存')
      baselineRef.current = content
      baseHashRef.current = meta.fileHash
      markDirty(false)
      void queryClient.invalidateQueries()
    },
    onError: (e) => {
      if (!(e instanceof ApiErr && (e.code === 'PARSE_FAILED' || e.code === 'EDIT_CONFLICT')))
        toast.error(e instanceof ApiErr ? e.message : '保存失败，请稍后重试')
    },
  })

  const err = saveMutation.error
  const parseErr = err instanceof ApiErr && err.code === 'PARSE_FAILED' ? err : null
  const conflict = err instanceof ApiErr && err.code === 'EDIT_CONFLICT'

  /** Conflict dialog "reload": drop local edits, refetch the server version. */
  const reloadFromServer = () => {
    saveMutation.reset()
    markDirty(false)
    dirtyRef.current = false
    baselineRef.current = viewRef.current?.state.doc.toString() ?? baselineRef.current
    void refetch()
  }

  /** Single save path for button, Mod-s, and the switch-guard dialog. */
  const save = async (): Promise<boolean> => {
    const view = viewRef.current
    if (!view || !dirtyRef.current || saveMutation.isPending) return false
    try {
      await saveMutation.mutateAsync(view.state.doc.toString())
      return true
    } catch {
      return false // rendered by the error paths (Task 7)
    }
  }
  const saveRef = useRef(save)
  saveRef.current = save

  useEffect(() => {
    const el = holderRef.current
    if (!el || !data) return
    const language = languageFor(data.format)
    const view = new EditorView({
      parent: el,
      state: EditorState.create({
        doc: data.content,
        extensions: [
          lineNumbers(),
          editorTheme,
          syntaxHighlighting(editorHighlight),
          EditorView.lineWrapping,
          Prec.highest(
            keymap.of([
              {
                key: 'Mod-s',
                preventDefault: true,
                run: () => {
                  void saveRef.current()
                  return true
                },
              },
            ]),
          ),
          EditorView.updateListener.of((u) => {
            if (u.docChanged)
              markDirty(u.state.doc.toString() !== baselineRef.current)
          }),
          ...(language ? [language] : []),
        ],
      }),
    })
    baselineRef.current = data.content
    baseHashRef.current = data.fileHash
    markDirty(false)
    viewRef.current = view
    return () => {
      view.destroy()
      viewRef.current = null
    }
  }, [data])

  if (isError) {
    const missing = error instanceof ApiErr && error.code === 'NOT_FOUND'
    return (
      <div className="border-line rounded-card text-ink-2 mx-auto mt-16 flex w-full max-w-[420px] flex-col items-center gap-3 border px-6 py-12 text-center">
        <div className="flex flex-col gap-1">
          <p className="font-medium">{missing ? '本体不存在' : '加载失败'}</p>
          <p className="text-sm">
            {missing ? '它可能已被删除，或不属于当前用户。' : '无法连接服务器，请确认后端已启动。'}
          </p>
        </div>
        {!missing && (
          <Button size="sm" variant="outline" onClick={() => void refetch()}>
            重试
          </Button>
        )}
      </div>
    )
  }
  if (!data) {
    return <div className="text-ink-3 py-16 text-center text-sm">加载中…</div>
  }
  return (
    <div className="flex h-full min-h-0 flex-col gap-2">
      <div className="text-ink-3 flex shrink-0 items-center gap-2 px-1 text-xs">
        <span className="font-mono">{data.filename}</span>
        <span className="border-line text-ink-2 rounded-ctl border px-1.5 py-0.5 text-[10px]">
          {data.format}
        </span>
        {dirty && (
          <>
            <span className="text-amber-600 dark:text-amber-400" aria-live="polite">
              ● 未保存
            </span>
            <Button
              size="sm"
              className="ml-auto h-6 px-2 text-xs"
              disabled={saveMutation.isPending}
              onClick={() => void saveRef.current()}
            >
              保存
            </Button>
          </>
        )}
      </div>
      {parseErr && (
        <div
          role="alert"
          className="border-line bg-panel text-ink rounded-ctl flex shrink-0 flex-col gap-0.5 border px-3 py-2 text-xs"
        >
          <span className="text-amber-600 dark:text-amber-400 font-medium">
            解析失败：{parseErr.message}
          </span>
          {parseErr.hint && <span className="text-ink-3">{parseErr.hint}</span>}
        </div>
      )}
      <div
        ref={holderRef}
        className="border-line bg-panel rounded-ctl min-h-0 flex-1 overflow-auto border"
        aria-label="本体源码"
      />
      <AlertDialog
        open={conflict}
        onOpenChange={(o) => {
          if (!o) saveMutation.reset()
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>文件已在别处更新</AlertDialogTitle>
            <AlertDialogDescription>
              源文件在你编辑期间被保存过新版本。重新加载会丢弃本地修改。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => saveMutation.reset()}>继续编辑</AlertDialogCancel>
            <AlertDialogAction onClick={reloadFromServer}>重新加载</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

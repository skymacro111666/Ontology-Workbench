import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { EditorState } from '@codemirror/state'
import { EditorView, lineNumbers } from '@codemirror/view'
import { HighlightStyle, StreamLanguage, syntaxHighlighting } from '@codemirror/language'
import { xml } from '@codemirror/lang-xml'
import { turtle } from '@codemirror/legacy-modes/mode/turtle'
import { tags as t } from '@lezer/highlight'
import { ApiErr, api } from '../api/client'
import { Button } from '@/components/ui/button'

/** /source payload: the stored ontology file, verbatim. */
interface SourcePayload {
  filename: string
  format: string
  content: string
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

/** Read-only CodeMirror over the ontology source (workspace text view).
 *  Read-only now; the editor groundwork (line numbers, highlighting,
 *  viewport rendering) is what the future edit mode builds on. */
export default function SourceView({ oid }: { oid: string }) {
  const holderRef = useRef<HTMLDivElement>(null)
  const viewRef = useRef<EditorView | null>(null)
  const { data, isError, error, refetch } = useQuery({
    queryKey: ['source', oid],
    queryFn: () => api.get<SourcePayload>(`/api/ontologies/${oid}/source`),
    retry: false,
  })

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
          // Wrap long lines at the .cm-content max-width cap instead of
          // horizontal scrolling; CM's wrap mode also breaks unbroken runs
          // (long IRIs) via overflow-wrap: anywhere.
          EditorView.lineWrapping,
          EditorState.readOnly.of(true),
          EditorView.editable.of(false),
          ...(language ? [language] : []),
        ],
      }),
    })
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
      </div>
      <div
        ref={holderRef}
        className="border-line bg-panel rounded-ctl min-h-0 flex-1 overflow-auto border"
        aria-label="本体源码"
      />
    </div>
  )
}

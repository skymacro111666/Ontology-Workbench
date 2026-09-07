import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { EditorState, Prec } from '@codemirror/state'
import { EditorView, keymap, lineNumbers } from '@codemirror/view'
import { HighlightStyle, StreamLanguage, syntaxHighlighting } from '@codemirror/language'
import { sparql } from '@codemirror/legacy-modes/mode/sparql'
import { tags as t } from '@lezer/highlight'
import { api, ApiErr } from '../api/client'
import type { QueryCell, QueryResult } from '../api/types'
import { Button } from '@/components/ui/button'

/** SPARQL query console — the 查询 view (M1, spec 2026-09-07). Read-only
 *  queries over the pooled store; layout mirrors the accepted mockup:
 *  toolbar / editor / meta row / results. Ctrl/⌘+Enter runs. */
export default function QueryConsole({ oid }: { oid: string }) {
  const { t: tr } = useTranslation()
  const holderRef = useRef<HTMLDivElement>(null)
  const viewRef = useRef<EditorView | null>(null)
  /** Latest run handler for the keymap closure (stable across renders). */
  const runRef = useRef<() => void>(() => {})
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<QueryResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  /** Built-in sample queries: generic (any ontology), never GO-bound. */
  const samples = [
    { label: tr('query.sampleAll'), qs: ALL_CLASSES },
    { label: tr('query.sampleNoLabel'), qs: NO_LABEL },
    { label: tr('query.sampleWide'), qs: WIDEST },
  ]
  const [sampleIdx, setSampleIdx] = useState(0)

  const run = async () => {
    const qs = viewRef.current?.state.doc.toString() ?? ''
    if (!qs.trim() || running) return
    setRunning(true)
    setError(null)
    try {
      const data = await api.post<QueryResult>(`/api/ontologies/${oid}/query`, { qs })
      setResult(data)
    } catch (e) {
      setResult(null)
      setError(
        e instanceof ApiErr
          ? [e.message, e.hint].filter(Boolean).join(' — ')
          : tr('common.offline'),
      )
    } finally {
      setRunning(false)
    }
  }
  runRef.current = () => void run()

  // Editor mounts once with the first sample; sample switches rewrite the doc.
  useEffect(() => {
    const el = holderRef.current
    if (!el || viewRef.current) return
    const view = new EditorView({
      parent: el,
      state: EditorState.create({
        doc: ALL_CLASSES,
        extensions: [
          lineNumbers(),
          consoleTheme,
          syntaxHighlighting(consoleHighlight),
          StreamLanguage.define(sparql),
          EditorView.lineWrapping,
          Prec.highest(
            keymap.of([
              {
                key: 'Mod-Enter',
                preventDefault: true,
                run: () => {
                  runRef.current()
                  return true
                },
              },
            ]),
          ),
        ],
      }),
    })
    viewRef.current = view
    return () => {
      view.destroy()
      viewRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const loadSample = (idx: number) => {
    setSampleIdx(idx)
    setError(null)
    setResult(null)
    viewRef.current?.dispatch({
      changes: { from: 0, to: viewRef.current.state.doc.length, insert: samples[idx].qs },
    })
  }

  const pill =
    'rounded-ctl border px-2 py-0.5 text-[10.5px] font-bold tracking-wide whitespace-nowrap'

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Toolbar: samples / read-only + cap badges / run (mockup §②). */}
      <div className="border-line flex flex-wrap items-center gap-2 border-b p-2">
        <label htmlFor="qc-sample" className="text-ink-2 text-xs font-semibold">
          {tr('query.samples')}
        </label>
        <select
          id="qc-sample"
          className="border-line bg-panel-2 text-ink rounded-ctl h-7 max-w-[300px] cursor-pointer border px-2 text-xs"
          value={sampleIdx}
          onChange={(e) => loadSample(Number(e.target.value))}
        >
          {samples.map((s, i) => (
            <option key={s.qs} value={i}>
              {s.label}
            </option>
          ))}
        </select>
        <span
          className={`border-success text-success ${pill}`}
          title={tr('query.readonlyHint')}
        >
          ● {tr('query.readonly')}
        </span>
        <span className={`border-line text-ink-3 border-dashed ${pill}`}>
          {tr('query.rowLimit', { n: 1000 })}
        </span>
        <Button
          size="sm"
          className="ml-auto"
          disabled={running}
          onClick={() => runRef.current()}
        >
          {running ? tr('query.running') : tr('query.run')}
          <kbd className="border-ink-3/40 ml-1.5 rounded border px-1 font-mono text-[9.5px] font-normal opacity-80">
            Ctrl ↵
          </kbd>
        </Button>
      </div>

      {/* Editor: 40% of the pane, scroller inside (mirrors SourceView's). */}
      <div
        ref={holderRef}
        className="border-line h-[40%] min-h-[120px] shrink-0 overflow-hidden border-b"
      />

      {/* Meta row: form / row count / timing / truncation + semantics note. */}
      <div className="border-line bg-panel-2 text-ink-3 flex flex-wrap items-center gap-3 border-b px-3 py-1 text-[11.5px]">
        {result && (
          <>
            <span className="text-primary font-mono text-[11px] font-bold uppercase">
              {result.kind}
            </span>
            {result.kind === 'select' && (
              <>
                <span>{tr('query.rows', { n: result.rowCount })}</span>
                <span>{tr('query.ms', { ms: result.elapsedMs })}</span>
                <span>{result.truncated ? tr('query.truncated') : tr('query.notTruncated')}</span>
              </>
            )}
            {result.kind === 'ask' && <span>{tr('query.ms', { ms: result.elapsedMs })}</span>}
            {result.kind === 'construct' && (
              <>
                <span>{tr('query.rows', { n: result.tripleCount })}</span>
                <span>{tr('query.ms', { ms: result.elapsedMs })}</span>
                <span>{result.truncated ? tr('query.truncated') : tr('query.notTruncated')}</span>
              </>
            )}
          </>
        )}
        <span className="ml-auto hidden md:inline">{tr('query.assertedNote')}</span>
      </div>

      {/* Results: table (select) / boolean (ask) / turtle (construct). */}
      <div className="min-h-0 flex-1 overflow-auto">
        {error && (
          <div
            role="alert"
            className="border-destructive text-destructive m-3 rounded-card border px-3 py-2 text-sm"
          >
            <p className="font-semibold">{tr('query.errorTitle')}</p>
            <p className="font-mono mt-1 text-xs break-words">{error}</p>
          </div>
        )}
        {!error && !result && (
          <p className="text-ink-3 m-3 text-sm">{tr('query.idleHint')}</p>
        )}
        {!error && result?.kind === 'select' && (
          result.rows.length === 0 ? (
            <p className="text-ink-3 m-3 text-sm">{tr('query.empty')}</p>
          ) : (
            <table className="w-full text-[12.5px]">
              <thead>
                <tr>
                  {result.columns.map((c) => (
                    <th
                      key={c}
                      className="border-line bg-panel text-ink-3 sticky top-0 border-b px-3 py-1.5 text-left text-[11px] font-bold tracking-wider uppercase"
                    >
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="font-mono">
                {result.rows.map((row, i) => (
                  <tr key={i} className="border-line border-b hover:bg-primary-soft">
                    {result.columns.map((c) => (
                      <td key={c} className="px-3 py-1.5 align-top">
                        <Cell cell={row[c]} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          )
        )}
        {!error && result?.kind === 'ask' && (
          <p className="m-3 flex items-center gap-2 text-sm">
            <span
              className={`rounded-ctl border px-2 py-0.5 text-sm font-bold ${
                result.boolean
                  ? 'border-success text-success'
                  : 'border-line text-ink-3'
              }`}
            >
              {result.boolean ? tr('query.askTrue') : tr('query.askFalse')}
            </span>
            <span className="text-ink-3">{tr('query.ms', { ms: result.elapsedMs })}</span>
          </p>
        )}
        {!error && result?.kind === 'construct' && (
          <pre className="font-mono text-ink-2 m-3 text-xs whitespace-pre-wrap">
            {result.turtle}
          </pre>
        )}
      </div>
    </div>
  )
}

/** One table cell: IRIs render shortened (curie) in mono with the full IRI
 *  in the title; literals show their lexical form with lang/datatype hinted. */
function Cell({ cell }: { cell: QueryCell | null }) {
  if (!cell) return <span className="text-ink-3">—</span>
  if (cell.type === 'literal') {
    const meta = [cell.language, cell.datatype].filter(Boolean).join(' · ')
    return <span title={meta || undefined}>{cell.value}</span>
  }
  return (
    <span className={cell.type === 'bnode' ? 'text-ink-3' : undefined} title={cell.value}>
      {cell.curie ?? cell.value}
    </span>
  )
}

/* Editor chrome mirrors SourceView's (project tokens, theme-following). */
const consoleTheme = EditorView.theme({
  '&': { height: '100%' },
  '.cm-scroller': {
    fontFamily: 'var(--font-mono)',
    fontSize: '12px',
    lineHeight: '1.7',
  },
  '.cm-content': { paddingBottom: '16px', maxWidth: '150ch' },
  '.cm-gutters': {
    backgroundColor: 'transparent',
    color: 'var(--color-ink-3)',
    border: 'none',
    borderRight: '1px solid var(--color-line)',
  },
})

const consoleHighlight = HighlightStyle.define([
  { tag: t.comment, color: 'var(--color-ink-3)', fontStyle: 'italic' },
  { tag: t.keyword, color: 'var(--color-edge-sub)' },
  { tag: t.string, color: 'var(--color-primary)' },
  { tag: t.number, color: 'var(--color-primary)' },
  { tag: t.atom, color: 'var(--color-edge-sub)' },
  { tag: t.variableName, color: 'var(--color-ink)' },
])

/* Generic sample queries (spec §3): work on any OWL ontology. */
const ALL_CLASSES = `PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?class ?label WHERE {
  ?class a owl:Class .
  OPTIONAL { ?class rdfs:label ?label }
}
ORDER BY ?class
LIMIT 100`

const NO_LABEL = `PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?class WHERE {
  ?class a owl:Class .
  FILTER NOT EXISTS { ?class rdfs:label ?anyLabel }
}
LIMIT 100`

const WIDEST = `PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?class (COUNT(DISTINCT ?child) AS ?children) WHERE {
  ?child rdfs:subClassOf ?class .
}
GROUP BY ?class
ORDER BY DESC(?children)
LIMIT 10`

import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { EditorState, Prec } from '@codemirror/state'
import { EditorView, keymap, lineNumbers } from '@codemirror/view'
import { HighlightStyle, StreamLanguage, syntaxHighlighting } from '@codemirror/language'
import { turtle } from '@codemirror/legacy-modes/mode/turtle'
import { tags as t } from '@lezer/highlight'
import { ChevronDownIcon, DownloadIcon, Loader2Icon } from 'lucide-react'
import { api, ApiErr } from '../api/client'
import type { OntologyMeta } from '../api/types'
import { useBrowseStore } from '../stores/browseStore'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { cn } from '@/lib/utils'

/** SHACL 校验 view (M1, spec 2026-09-08 §3): 上 shapes 编辑器、下归一化
 *  报告。Read-only against the store; layout mirrors the 查询 console. */

export interface ValidationItem {
  severity: 'violation' | 'warning' | 'info'
  focusIri: string | null
  focusCurie: string | null
  path: string | null
  constraint: string | null
  message: string | null
  value: string | null
}

export interface ValidationRunResult {
  conforms: boolean
  focusCount: number
  counts: Record<'violation' | 'warning' | 'info', number>
  results: ValidationItem[]
  truncated: boolean
  engine: string
  elapsedMs: number
  afWarnings: string[]
  deprecatedFiltered: number
  /** Kept-universe size (post-filter) — the honest "共 N 条" count. */
  totalResults: number
}

interface Preset {
  id: string
  name: string
  source: string
}

interface ShapesPayload {
  source: string | null
  updatedAt: string | null
  presets: Preset[]
}

const PAGE = 50
const SEVS = ['violation', 'warning', 'info'] as const
type Filter = 'all' | (typeof SEVS)[number]

const SEV_BAR: Record<string, string> = {
  violation: 'bg-red-500',
  warning: 'bg-amber-500',
  info: 'bg-ink-3',
}
const SEV_LABEL: Record<string, string> = {
  violation: 'border-destructive text-destructive',
  warning: 'border-amber-500 text-amber-600 dark:text-amber-400',
  info: 'border-line text-ink-3',
}

export default function ValidationConsole({ oid }: { oid: string }) {
  const { t: tr } = useTranslation()
  const setSelected = useBrowseStore((s) => s.setSelected)
  const holderRef = useRef<HTMLDivElement>(null)
  const viewRef = useRef<EditorView | null>(null)
  /** Latest run handler for the keymap closure (stable across renders). */
  const runRef = useRef<() => void>(() => {})
  const [running, setRunning] = useState(false)
  const [saving, setSaving] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [result, setResult] = useState<ValidationRunResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [elapsed, setElapsed] = useState(0)
  const [presetId, setPresetId] = useState('')
  const [filter, setFilter] = useState<Filter>('all')
  const [showAll, setShowAll] = useState(false)
  /** M2 忽略已废弃: on by default — deprecated-focus rows are noise (GO's
   * 13,894 parentless deprecated classes all fire the 孤立类 Info rule). */
  const [ignoreDep, setIgnoreDep] = useState(true)
  /** Guard: fill the editor from stored shapes exactly once, then it's the
   *  user's (a preset selection overwrites it) — refetches must not clobber. */
  const filledRef = useRef(false)

  const { data: meta } = useQuery({
    queryKey: ['ontology', oid],
    queryFn: () => api.get<OntologyMeta>(`/api/ontologies/${oid}/meta`),
  })
  const { data: shapes } = useQuery({
    queryKey: ['validation-shapes', oid],
    queryFn: () => api.get<ShapesPayload>(`/api/ontologies/${oid}/validation/shapes`),
  })
  const big =
    (meta?.classCount ?? 0) + (meta?.propertyCount ?? 0) + (meta?.instanceCount ?? 0) > 2000

  const doc = () => viewRef.current?.state.doc.toString() ?? ''

  const run = async () => {
    if (running) return
    setElapsed(0)
    setRunning(true)
    setError(null)
    try {
      // 恒带编辑器当前内容:未保存的 shapes 也能直接跑(inline shadows stored)。
      const data = await api.post<ValidationRunResult>(
        `/api/ontologies/${oid}/validation/run`,
        { source: doc(), includeDeprecated: !ignoreDep },
      )
      setResult(data)
      setShowAll(false)
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
  // Latest-ref for the Mod-Enter keymap: reassigned after every render so
  // the closure always sees fresh state (refs must not be written in render).
  useEffect(() => {
    runRef.current = () => void run()
  })

  const save = async () => {
    if (saving) return
    setSaving(true)
    setError(null)
    try {
      await api.put(`/api/ontologies/${oid}/validation/shapes`, { source: doc() })
      toast.success(tr('validationView.saved'))
    } catch (e) {
      setError(
        e instanceof ApiErr
          ? [e.message, e.hint].filter(Boolean).join(' — ')
          : tr('common.offline'),
      )
    } finally {
      setSaving(false)
    }
  }

  // 全量导出(缓存命中秒出;与 run 同口径——编辑器当前内容+忽略废弃开关)。
  const doExport = async (format: 'csv' | 'json') => {
    if (exporting) return
    setExporting(true)
    setError(null)
    try {
      const name = await api.downloadBinary(
        `/api/ontologies/${oid}/validation/export`,
        `validation.${format}`,
        { method: 'POST', body: { source: doc(), includeDeprecated: !ignoreDep, format } },
      )
      toast.success(tr('validationView.exported', { name }))
    } catch (e) {
      setError(
        e instanceof ApiErr
          ? [e.message, e.hint].filter(Boolean).join(' — ')
          : tr('common.offline'),
      )
    } finally {
      setExporting(false)
    }
  }

  // Editor mounts once empty; the stored shapes (if any) fill it when the
  // query lands. Preset selections rewrite the doc without auto-saving.
  useEffect(() => {
    const el = holderRef.current
    if (!el || viewRef.current) return
    const view = new EditorView({
      parent: el,
      state: EditorState.create({
        doc: '',
        extensions: [
          lineNumbers(),
          consoleTheme,
          syntaxHighlighting(consoleHighlight),
          StreamLanguage.define(turtle),
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
  }, [])

  useEffect(() => {
    if (filledRef.current || !shapes) return
    filledRef.current = true
    const view = viewRef.current
    if (shapes.source && view)
      view.dispatch({
        changes: { from: 0, to: view.state.doc.length, insert: shapes.source },
      })
  }, [shapes])

  // Waiting UX (spec §2.2): tick seconds while the engine runs; clean up on
  // end/unmount so no interval outlives the view.
  useEffect(() => {
    if (!running) return
    const t0 = Date.now()
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - t0) / 1000)), 1000)
    return () => clearInterval(id)
  }, [running])

  const loadPreset = (id: string) => {
    setPresetId(id)
    setError(null)
    const p = shapes?.presets.find((x) => x.id === id)
    const view = viewRef.current
    if (p && view)
      view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: p.source } }) // 填入编辑器,不自动保存(行为 1)
  }

  const filtered = useMemo(
    () =>
      result
        ? filter === 'all'
          ? result.results
          : result.results.filter((r) => r.severity === filter)
        : [],
    [result, filter],
  )
  const visible = showAll ? filtered : filtered.slice(0, PAGE)
  const hidden = filtered.length - visible.length

  const pill =
    'rounded-ctl border px-2 py-0.5 text-[10.5px] font-bold tracking-wide whitespace-nowrap'

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Toolbar: presets / save / read-only + engine badges / run (spec §③). */}
      <div className="border-line flex flex-wrap items-center gap-2 border-b p-2">
        <label htmlFor="vc-preset" className="text-ink-2 text-xs font-semibold">
          {tr('validationView.presetLabel')}
        </label>
        <select
          id="vc-preset"
          className="border-line bg-panel-2 text-ink rounded-ctl h-7 max-w-[240px] cursor-pointer border px-2 text-xs"
          value={presetId}
          onChange={(e) => loadPreset(e.target.value)}
        >
          <option value="">{tr('validationView.presetPlaceholder')}</option>
          {shapes?.presets.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        <Button size="sm" variant="outline" disabled={saving} onClick={() => void save()}>
          {saving && <Loader2Icon className="size-3.5 animate-spin" aria-hidden />}
          {tr('validationView.save')}
        </Button>
        <span className={`border-success text-success ${pill}`}>
          ● {tr('validationView.readOnly')}
        </span>
        <span className={`border-line text-ink-3 border-dashed ${pill}`}>
          {tr('validationView.engine')} {result?.engine ?? 'pyrudof'}
        </span>
        <label
          htmlFor="vc-ignore-dep"
          className="border-line text-ink-2 ml-1 flex cursor-pointer items-center gap-1.5 text-xs font-semibold"
        >
          <input
            id="vc-ignore-dep"
            type="checkbox"
            checked={ignoreDep}
            onChange={(e) => setIgnoreDep(e.target.checked)}
            className="accent-primary size-3 cursor-pointer"
          />
          {tr('validationView.ignoreDeprecated')}
        </label>
        <div className="ml-auto flex items-center gap-2">
          {/* 导出 ▾(方案 1:与「运行」同组——都是执行动词;缓存 miss 会重跑) */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="sm" variant="outline" disabled={exporting}>
                {exporting ? (
                  <Loader2Icon className="size-3.5 animate-spin" aria-hidden />
                ) : (
                  <DownloadIcon className="size-3.5" aria-hidden />
                )}
                {tr('validationView.export')}
                <ChevronDownIcon className="size-3 opacity-70" aria-hidden />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => void doExport('csv')}>
                {tr('validationView.exportCsv')}
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => void doExport('json')}>
                {tr('validationView.exportJson')}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <Button size="sm" disabled={running} onClick={() => runRef.current()}>
            {running ? (
              <>
                <Loader2Icon className="size-3.5 animate-spin" aria-hidden />
                {tr('validationView.running')}
                <span className="text-ink-3 font-normal">· {tr('validationView.elapsedS', { s: elapsed })}</span>
              </>
            ) : (
              tr('validationView.run')
            )}
            <kbd className="border-ink-3/40 ml-1.5 rounded border px-1 font-mono text-[9.5px] font-normal opacity-80">
              Ctrl ↵
            </kbd>
          </Button>
        </div>
      </div>

      {/* Big-ontology waiting notice (spec §2.2: waiting UX by design). */}
      {big && (
        <p className="border-amber-500/40 text-amber-600 dark:text-amber-400 border-b px-3 py-1 text-xs">
          {tr('validationView.slowHint')}
        </p>
      )}

      {/* SHACL-AF terms the engine silently ignores (spike finding). */}
      {result && result.afWarnings.length > 0 && (
        <p className="border-amber-500/40 bg-amber-500/10 text-amber-600 dark:text-amber-400 border-b px-3 py-1 text-xs">
          {tr('validationView.afWarning')}({result.afWarnings.join(', ')})
        </p>
      )}

      {/* Shapes editor: 40% of the pane like the 查询 console's. */}
      <div
        ref={holderRef}
        aria-label={tr('validationView.editorLabel')}
        className="border-line h-[40%] min-h-[120px] shrink-0 overflow-hidden border-b"
      />

      {/* Verdict banner: fail carries the three counts; pass is a plain ✓
       *  (the engine reports no evaluated-focus total — spec §3 backfill). */}
      {result && (
        <div
          role="status"
          className={cn(
            'flex flex-wrap items-center gap-2 border-b px-3 py-1.5 text-sm font-semibold',
            result.conforms
              ? 'border-success/40 text-success'
              : 'border-destructive/40 text-destructive',
          )}
        >
          <span aria-hidden>{result.conforms ? '✓' : '✗'}</span>
          {result.conforms ? tr('validationView.passBanner') : tr('validationView.failBanner')}
          {!result.conforms &&
            SEVS.map((s) => (
              <span
                key={s}
                className={cn('rounded-ctl border px-1.5 text-[10.5px] font-bold', SEV_LABEL[s])}
              >
                {tr(`validationView.filter${s.charAt(0).toUpperCase()}${s.slice(1)}`)}{' '}
                {result.counts[s]}
              </span>
            ))}
          {result.deprecatedFiltered > 0 && (
            <span className="text-ink-3 text-[11.5px] font-normal">
              {tr('validationView.deprecatedHidden', { n: result.deprecatedFiltered })}
            </span>
          )}
          <span className="text-ink-3 ml-auto text-[11.5px] font-normal">
            {tr('validationView.ms', { ms: result.elapsedMs })}
          </span>
        </div>
      )}

      {/* Severity filter chips: counts ride along, zero-count chips stay. */}
      {result && (
        <div className="border-line flex flex-wrap items-center gap-1.5 border-b px-3 py-1.5">
          {(['all', ...SEVS] as const).map((f) => (
            <button
              key={f}
              type="button"
              aria-pressed={filter === f}
              onClick={() => setFilter(f)}
              className={cn(
                'rounded-ctl flex items-center gap-1 border px-2 py-0.5 text-[11px] font-semibold',
                filter === f
                  ? 'border-primary-border text-primary bg-primary-soft'
                  : 'border-line text-ink-3 hover:text-ink',
              )}
            >
              <span>
                {f === 'all'
                  ? tr('validationView.filterAll')
                  : tr(
                      `validationView.filter${f.charAt(0).toUpperCase()}${f.slice(1)}`,
                    )}
              </span>
              <span className="rounded-full bg-ink-3/20 px-1 text-[10px] font-bold">
                {f === 'all'
                  ? result.results.length
                  : result.results.filter((r) => r.severity === f).length}
              </span>
            </button>
          ))}
        </div>
      )}

      {/* Report table / error / idle (spec §3 §⑤). */}
      <div className="min-h-0 flex-1 overflow-auto">
        {error && (
          <div
            role="alert"
            className="border-destructive text-destructive m-3 rounded-card border px-3 py-2 text-sm"
          >
            <p className="font-semibold">{tr('validationView.errorTitle')}</p>
            <p className="font-mono mt-1 text-xs break-words">{error}</p>
          </div>
        )}
        {!error && !result && (
          <p className="text-ink-3 m-3 text-sm">{tr('validationView.notRun')}</p>
        )}
        {!error && result && visible.length === 0 && (
          <p className="text-ink-3 m-3 text-sm">{tr('validationView.emptyFilter')}</p>
        )}
        {!error && result && visible.length > 0 && (
          <table className="w-full text-[12.5px]">
            <thead>
              <tr>
                {(
                  [
                    'colSeverity',
                    'colFocus',
                    'colPath',
                    'colConstraint',
                    'colMessage',
                  ] as const
                ).map((k) => (
                  <th
                    key={k}
                    className="border-line bg-panel text-ink-3 sticky top-0 border-b px-3 py-1.5 text-left text-[11px] font-bold tracking-wider uppercase"
                  >
                    {tr(`validationView.${k}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="font-mono">
              {visible.map((r, i) => (
                <tr key={i} className="border-line border-b hover:bg-primary-soft">
                  <td className="px-3 py-1.5 align-top">
                    <span className="flex items-center gap-1.5">
                      <span aria-hidden className={cn('h-3.5 w-1 rounded-full', SEV_BAR[r.severity])} />
                      <span
                        className={cn(
                          'rounded-ctl border px-1.5 text-[10.5px] font-bold whitespace-nowrap',
                          SEV_LABEL[r.severity],
                        )}
                      >
                        {tr(`validationView.filter${r.severity.charAt(0).toUpperCase()}${r.severity.slice(1)}`)}
                      </span>
                    </span>
                  </td>
                  <td className="px-3 py-1.5 align-top">
                    {r.focusIri ? (
                      <button
                        type="button"
                        title={r.focusIri}
                        onClick={() => setSelected(r.focusIri)}
                        className="bg-primary-soft border-primary-border text-primary rounded-ctl border px-1.5 py-0.5"
                      >
                        {r.focusCurie ?? r.focusIri}
                      </button>
                    ) : (
                      <span className="text-ink-3">—</span>
                    )}
                  </td>
                  <td className="px-3 py-1.5 align-top">
                    {r.path ? <span title={r.path}>{r.path}</span> : <span className="text-ink-3">—</span>}
                  </td>
                  <td className="px-3 py-1.5 align-top">
                    {r.constraint ? (
                      <span title={r.constraint}>{shortTerm(r.constraint)}</span>
                    ) : (
                      <span className="text-ink-3">—</span>
                    )}
                  </td>
                  <td className="px-3 py-1.5 align-top font-sans">{r.message ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {!error && result && hidden > 0 && (
          <p className="text-ink-3 px-3 py-1.5 text-xs">
            <button
              type="button"
              onClick={() => setShowAll(true)}
              className="text-primary hover:underline"
            >
              {tr('validationView.showAll', { n: filtered.length })}
            </button>
          </p>
        )}
        {!error && result?.truncated && (
          <p className="text-ink-3 px-3 py-1.5 text-xs">
            {tr('validationView.truncatedTotal', {
              count: result.totalResults.toLocaleString(),
              shown: result.results.length,
            })}
          </p>
        )}
      </div>
    </div>
  )
}

/** Constraint components read best shortened: sh:XXXConstraintComponent → XXX. */
function shortTerm(uri: string): string {
  const local = uri.split(/[#/]/).pop() ?? uri
  return local.replace(/ConstraintComponent$/, '')
}

/* Editor chrome mirrors the 查询 console's (project tokens, theme-following). */
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

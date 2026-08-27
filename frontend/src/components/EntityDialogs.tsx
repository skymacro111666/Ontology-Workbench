import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { ApiErr, api } from '../api/client'
import type { EntityIR, GNode, NodesEdges, OntologyMeta } from '../api/types'
import { localName } from '../lib/localName'
import { useBrowseStore } from '../stores/browseStore'
import { useUiStore, type EntityDialogMode } from '../stores/uiStore'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

/** The A2 dialog family behind the canvas context menu: create class /
 *  subclass / object / datatype property, edit, delete. One component, the
 *  uiStore's entityDialog picks the mode; shared queries (ontology meta for
 *  baseFileHash + prefixes, overview for the class picker, entity for edit
 *  initial values) ride the callers' existing cache entries.
 *
 *  Design spec 2026-08-26 §4 (frontend): every submit invalidates the whole
 *  tree so overview/tree/inspector/source all re-read the rewritten file. */

const XSD_TYPES = [
  ['http://www.w3.org/2001/XMLSchema#string', 'xsd:string'],
  ['http://www.w3.org/2001/XMLSchema#integer', 'xsd:integer'],
  ['http://www.w3.org/2001/XMLSchema#decimal', 'xsd:decimal'],
  ['http://www.w3.org/2001/XMLSchema#boolean', 'xsd:boolean'],
  ['http://www.w3.org/2001/XMLSchema#date', 'xsd:date'],
  ['http://www.w3.org/2001/XMLSchema#dateTime', 'xsd:dateTime'],
  ['http://www.w3.org/2001/XMLSchema#anyURI', 'xsd:anyURI'],
  ['http://www.w3.org/2000/01/rdf-schema#Literal', 'rdfs:Literal'],
] as const

const LANGS = [
  ['zh', '中文'],
  ['en', 'English'],
] as const

const isCreate = (m: EntityDialogMode) => m === 'class' || m === 'subclass'
const isProperty = (m: EntityDialogMode) => m === 'objectProperty' || m === 'dataProperty'
const isEdit = (m: EntityDialogMode) => m === 'editClass' || m === 'editProperty'

/** Filterable class list; multi for parents/domains, single for range. */
function ClassPicker({
  classes,
  value,
  onChange,
  multiple,
}: {
  classes: GNode[]
  value: string[]
  onChange: (next: string[]) => void
  multiple: boolean
}) {
  const [q, setQ] = useState('')
  const shown = classes.filter((c) => localName(c.curie).toLowerCase().includes(q.toLowerCase()))
  const toggle = (id: string) => {
    if (multiple)
      onChange(value.includes(id) ? value.filter((v) => v !== id) : [...value, id])
    else onChange(value.includes(id) ? [] : [id])
  }
  return (
    <div className="border-line bg-panel rounded-ctl flex flex-col gap-1 border p-1">
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="过滤类…"
        className="text-ink bg-panel-2 border-line rounded-ctl border px-2 py-1 text-xs"
      />
      <div className="flex max-h-36 flex-col gap-0.5 overflow-y-auto">
        {shown.map((c) => (
          <button
            key={c.id}
            type="button"
            onClick={() => toggle(c.id)}
            className={
              'rounded-ctl px-2 py-1 text-left text-xs ' +
              (value.includes(c.id)
                ? 'bg-primary-soft text-primary font-medium'
                : 'text-ink-2 hover:bg-panel-2')
            }
          >
            {localName(c.curie)}
          </button>
        ))}
        {shown.length === 0 && <span className="text-ink-3 px-2 py-1 text-xs">无匹配</span>}
      </div>
    </div>
  )
}

export default function EntityDialogs({ oid }: { oid: string }) {
  const dialog = useUiStore((s) => s.entityDialog)
  const setEntityDialog = useUiStore((s) => s.setEntityDialog)
  const reveal = useBrowseStore((s) => s.reveal)
  const queryClient = useQueryClient()

  const { data: meta } = useQuery({
    queryKey: ['ontology', oid],
    queryFn: () => api.get<OntologyMeta>(`/api/ontologies/${oid}/meta`),
    enabled: !!dialog,
  })
  const { data: overview } = useQuery({
    queryKey: ['overview', oid],
    queryFn: () => api.get<NodesEdges>(`/api/ontologies/${oid}/overview`),
    enabled: !!dialog && !isEdit(dialog.mode) && dialog.mode !== 'delete',
  })
  const editEid = dialog && isEdit(dialog.mode) ? dialog.eid : undefined
  const { data: entity } = useQuery({
    queryKey: ['entity', oid, editEid],
    queryFn: () => api.get<EntityIR>(`/api/ontologies/${oid}/entities/${encodeURIComponent(editEid ?? '')}`),
    enabled: !!editEid,
  })

  const classes = useMemo(
    () => (overview?.nodes ?? []).filter((n) => n.kind === 'class'),
    [overview],
  )
  const prefixes = Object.keys(meta?.prefixes ?? {})

  const open = !!dialog
  const mode = dialog?.mode ?? 'class'

  // ---- form state, reset on open (ImportDialog's prevOpen pattern) ----
  const [prevOpen, setPrevOpen] = useState(false)
  const [name, setName] = useState('')
  const [prefix, setPrefix] = useState('ex')
  const [lang, setLang] = useState('zh')
  const [labelValue, setLabelValue] = useState('')
  const [comment, setComment] = useState('')
  const [picked, setPicked] = useState<string[]>([])
  const [range, setRange] = useState<string[]>([])
  const [nameError, setNameError] = useState<string | null>(null)
  useEffect(() => {
    if (open && !prevOpen) {
      setName('')
      setPrefix(Object.keys(meta?.prefixes ?? { ex: '' })[0] ?? 'ex')
      setLang('zh')
      setLabelValue('')
      setComment('')
      setPicked(dialog?.parent ? [dialog.parent] : [])
      setRange([])
      setNameError(null)
      if (entity) {
        setLabelValue(Object.values(entity.label ?? {})[0] ?? '')
        setComment(entity.comment ?? '')
        setPicked((entity.parents ?? []).map((p) => p.eid))
        setRange((entity.properties ?? []).length ? [] : [])
        setPicked(
          dialog?.mode === 'editClass'
            ? (entity.parents ?? []).map((p) => p.eid)
            : dialog?.parent
              ? [dialog.parent]
              : [],
        )
        if (dialog?.mode === 'editProperty') {
          const dom = (entity.referencedBy ?? [])
            .filter((r) => r.relation === 'rdfs:domain')
            .map((r) => r.eid)
          setPicked(dom.length ? dom : dialog?.parent ? [dialog.parent] : [])
        }
      }
    }
    setPrevOpen(open)
  }, [open, prevOpen, dialog, entity, meta])

  const afterSuccess = (eid?: string) => {
    toast.success('已保存')
    setEntityDialog(null)
    void queryClient.invalidateQueries()
    if (eid) reveal(eid)
  }

  const mutation = useMutation({
    mutationFn: async () => {
      const fileHash = meta?.fileHash ?? ''
      const label =
        labelValue.trim() === '' ? null : { value: labelValue.trim(), lang: lang || null }
      const cleanComment = comment.trim() === '' ? null : comment.trim()
      if (mode === 'class' || mode === 'subclass') {
        return api.post<{ entity: { eid: string } }>(`/api/ontologies/${oid}/classes`, {
          name: name.trim(),
          prefix,
          label,
          comment: cleanComment,
          parents: picked,
          baseFileHash: fileHash,
        })
      }
      if (mode === 'objectProperty' || mode === 'dataProperty') {
        return api.post<{ entity: { eid: string } }>(`/api/ontologies/${oid}/properties`, {
          name: name.trim(),
          prefix,
          ptype: mode === 'objectProperty' ? 'ObjectProperty' : 'DatatypeProperty',
          label,
          comment: cleanComment,
          domains: picked,
          ranges: range,
          baseFileHash: fileHash,
        })
      }
      if (mode === 'editClass' || mode === 'editProperty') {
        const body: Record<string, unknown> = { baseFileHash: fileHash }
        if (labelValue.trim() !== '') body.label = label
        else body.label = null
        body.comment = cleanComment
        if (mode === 'editClass') body.parents = picked
        else {
          body.domains = picked
          body.ranges = range
        }
        return api.put(`/api/ontologies/${oid}/entities/${encodeURIComponent(dialog?.eid ?? '')}`, body)
      }
      // delete
      return api.del(
        `/api/ontologies/${oid}/entities/${encodeURIComponent(dialog?.eid ?? '')}` +
          `?baseFileHash=${fileHash}&prune=true`,
      )
    },
    onSuccess: (r) => {
      const created = r as { entity?: { eid?: string } } | null
      afterSuccess(created?.entity?.eid)
    },
    onError: (e) => {
      if (e instanceof ApiErr && e.code === 'DUPLICATE_ENTITY') {
        setNameError('该名称已存在，换一个名字或前缀。')
        return
      }
      toast.error(e instanceof ApiErr ? e.message : '保存失败，请稍后重试')
    },
  })

  if (!dialog) return null

  const submit = () => {
    if ((isCreate(mode) || isProperty(mode)) && !/^[A-Za-z_][\w.-]*$/.test(name.trim())) {
      setNameError('名称需以字母/下划线开头，仅含字母、数字、.、-、_。')
      return
    }
    mutation.mutate()
  }

  const titles: Record<EntityDialogMode | 'delete', string> = {
    class: '新建类',
    subclass: '新建子类',
    objectProperty: '新建对象属性',
    dataProperty: '新建数据属性',
    editClass: '编辑类',
    editProperty: '编辑属性',
    delete: '删除实体',
  }
  const fieldCls =
    'border-line bg-panel-2 text-ink rounded-ctl border px-2 py-1.5 text-sm w-full'
  const labelCls = 'text-ink-2 text-xs font-medium'

  return (
    <Dialog open={open} onOpenChange={(o) => !o && setEntityDialog(null)}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{titles[mode]}</DialogTitle>
          <DialogDescription>
            {dialog.mode === 'delete'
              ? '删除会同时清理指向它的子类/属性引用（可恢复地写在 RDF 里不可逆）。'
              : '保存后会重写本体源文件（Turtle 排版会重排）。'}
          </DialogDescription>
        </DialogHeader>

        {mode === 'delete' ? (
          <div className="flex flex-col gap-2">
            <p className="text-ink text-sm break-all">
              确认删除 <span className="text-primary font-mono">{localName(dialog.eid ?? '')}</span>？
            </p>
            <p className="text-ink-3 text-xs">
              将一并移除：指向它的 subClassOf / domain / range / 实例类型（prune）。
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {(isCreate(mode) || isProperty(mode)) && (
              <div className="grid grid-cols-[7rem_1fr] items-center gap-2">
                <span className={labelCls}>前缀</span>
                <select
                  value={prefix}
                  onChange={(e) => setPrefix(e.target.value)}
                  className={fieldCls}
                  aria-label="前缀"
                >
                  {prefixes.map((p) => (
                    <option key={p} value={p}>
                      {p}:
                    </option>
                  ))}
                </select>
              </div>
            )}
            <div className="grid grid-cols-[7rem_1fr] items-center gap-2">
              <span className={labelCls}>名称</span>
              {isEdit(mode) ? (
                <code className="text-ink-2 bg-panel-2 border-line rounded-ctl border px-2 py-1.5 text-sm">
                  {localName(entity?.curie ?? dialog.eid ?? '')}
                </code>
              ) : (
                <input
                  value={name}
                  onChange={(e) => {
                    setName(e.target.value)
                    setNameError(null)
                  }}
                  aria-label="名称"
                  placeholder="例如 Cat"
                  className={fieldCls}
                />
              )}
            </div>
            {nameError && (
              <p role="alert" className="text-amber-600 dark:text-amber-400 pl-[7.75rem] text-xs">
                {nameError}
              </p>
            )}
            <div className="grid grid-cols-[7rem_1fr] items-center gap-2">
              <span className={labelCls}>标签</span>
              <div className="flex gap-2">
                <input
                  value={labelValue}
                  onChange={(e) => setLabelValue(e.target.value)}
                  aria-label="标签"
                  placeholder="显示名（可选）"
                  className={fieldCls}
                />
                <select
                  value={lang}
                  onChange={(e) => setLang(e.target.value)}
                  aria-label="语言"
                  className={`${fieldCls} w-20 shrink-0`}
                >
                  {LANGS.map(([v, l]) => (
                    <option key={v} value={v}>
                      {l}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div className="grid grid-cols-[7rem_1fr] items-start gap-2">
              <span className={labelCls}>描述</span>
              <textarea
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                aria-label="描述"
                rows={2}
                placeholder="rdfs:comment（可选）"
                className={`${fieldCls} resize-none`}
              />
            </div>
            {mode !== 'dataProperty' && (isCreate(mode) || isProperty(mode) || mode === 'editClass') && (
              <div className="grid grid-cols-[7rem_1fr] items-start gap-2">
                <span className={labelCls}>{isProperty(mode) ? 'domain' : '父类'}</span>
                <ClassPicker classes={classes} value={picked} onChange={setPicked} multiple />
              </div>
            )}
            {mode === 'dataProperty' && (
              <div className="grid grid-cols-[7rem_1fr] items-center gap-2">
                <span className={labelCls}>domain</span>
                <ClassPicker classes={classes} value={picked} onChange={setPicked} multiple />
              </div>
            )}
            {isProperty(mode) && (
              <div className="grid grid-cols-[7rem_1fr] items-center gap-2">
                <span className={labelCls}>range</span>
                <ClassPicker classes={classes} value={range} onChange={setRange} multiple={false} />
              </div>
            )}
            {mode === 'dataProperty' && (
              <div className="grid grid-cols-[7rem_1fr] items-center gap-2">
                <span className={labelCls}>数据类型</span>
                <select
                  value={range[0] ?? XSD_TYPES[0][0]}
                  onChange={(e) => setRange([e.target.value])}
                  aria-label="数据类型"
                  className={fieldCls}
                >
                  {XSD_TYPES.map(([v, l]) => (
                    <option key={v} value={v}>
                      {l}
                    </option>
                  ))}
                </select>
              </div>
            )}
            {mode === 'editProperty' && (
              <div className="grid grid-cols-[7rem_1fr] items-center gap-2">
                <span className={labelCls}>range</span>
                <select
                  value={range[0] ?? XSD_TYPES[0][0]}
                  onChange={(e) => setRange([e.target.value])}
                  aria-label="range"
                  className={fieldCls}
                >
                  {XSD_TYPES.map(([v, l]) => (
                    <option key={v} value={v}>
                      {l}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" size="sm" onClick={() => setEntityDialog(null)}>
            取消
          </Button>
          <Button size="sm" disabled={mutation.isPending} onClick={submit}>
            {dialog.mode === 'delete' ? '删除' : '保存'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

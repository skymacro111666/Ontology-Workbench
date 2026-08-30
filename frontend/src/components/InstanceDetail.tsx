import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { api } from '../api/client'
import type { InstanceIR, NodesEdges, OntologyMeta, SchemaProp, SearchHit } from '../api/types'
import { errText } from '../i18n/errText'
import { localName } from '../lib/localName'
import { Button } from '@/components/ui/button'
import { ClassPicker, XSD_TYPES } from './EntityDialogs'
import { Chip, Section } from './InspectorPanel'

/** One editable assertion row: object rows carry the target instance eid,
 *  data rows the literal plus its xsd datatype. */
export interface Row {
  property: string
  kind: 'object' | 'data'
  value: string
  datatype?: string
}

/** Instance search picker (spec §4.2 edit mode): a small query box whose
 *  hits popover lists matching instances; picking one resolves the row. */
function InstancePickerRow({ oid, onPick }: { oid: string; onPick: (eid: string) => void }) {
  const { t } = useTranslation()
  const [q, setQ] = useState('')
  const { data: hits } = useQuery({
    enabled: q.trim().length > 0,
    queryKey: ['inst-search', oid, q],
    queryFn: () =>
      api.get<SearchHit[]>(
        `/api/ontologies/${oid}/search?type=instance&q=${encodeURIComponent(q)}`,
      ),
  })
  return (
    <div className="flex flex-col gap-1">
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder={t('instance.pickInstance')}
        aria-label={t('instance.pickInstance')}
        className="text-ink bg-panel border-line rounded-ctl border px-1.5 py-1 text-xs"
      />
      {(hits ?? []).length > 0 && (
        <div className="border-line bg-panel-2 rounded-ctl flex flex-col gap-0.5 border p-1">
          {(hits ?? []).map((h) => (
            <button
              key={h.eid}
              type="button"
              title={h.curie}
              onClick={() => onPick(h.eid)}
              className="text-ink-2 hover:bg-panel rounded-ctl px-1.5 py-1 text-left text-xs"
            >
              {Object.values(h.label)[0] ?? localName(h.curie)}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

/** Inline assertion row editor (spec §4.2 edit mode): each row pairs a
 *  schema property with an instance search (object) or typed literal (data);
 *  + 添加属性 lists the class-schema properties not already on a row.
 *  Exported for the Task 9 instance-create dialog. */
export function AssertionRows({
  oid,
  schema,
  rows,
  setRows,
}: {
  oid: string
  schema: SchemaProp[]
  rows: Row[]
  setRows: (next: Row[]) => void
}) {
  const { t } = useTranslation()
  const [adding, setAdding] = useState(false)
  const unused = schema.filter((p) => !rows.some((r) => r.property === p.eid))
  const setRow = (i: number, patch: Partial<Row>) =>
    setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  return (
    <div className="flex flex-col gap-2">
      {rows.map((row, i) => {
        const prop = schema.find((p) => p.eid === row.property)
        // A declared xsd range locks the row's datatype (plain text, no select).
        const lockedXsd = prop?.target?.kind === 'datatype' ? prop.target.curie : null
        return (
          <div key={i} className="border-line bg-panel-2 rounded-ctl flex flex-col gap-1 border p-1.5">
            <div className="flex items-center justify-between gap-2">
              <span className="text-ink-2 font-mono text-xs break-all" title={row.property}>
                {prop ? localName(prop.curie) : row.property}
              </span>
              <button
                type="button"
                aria-label={t('instance.removeRow')}
                onClick={() => setRows(rows.filter((_, j) => j !== i))}
                className="text-ink-3 hover:text-red-500 px-1 text-xs"
              >
                ×
              </button>
            </div>
            {row.kind === 'object' ? (
              row.value ? (
                <button
                  type="button"
                  title={row.value}
                  onClick={() => setRow(i, { value: '' })}
                  className="text-primary text-left font-mono text-xs break-all"
                >
                  {row.value.split(/[#/]/).pop()}
                </button>
              ) : (
                <InstancePickerRow oid={oid} onPick={(eid) => setRow(i, { value: eid })} />
              )
            ) : (
              <div className="flex gap-1">
                <input
                  value={row.value}
                  aria-label={t('instance.literalValue')}
                  onChange={(e) => setRow(i, { value: e.target.value })}
                  className="text-ink bg-panel border-line rounded-ctl border px-1.5 py-1 text-xs flex-1"
                />
                {lockedXsd ? (
                  <span className="text-ink-3 py-1 font-mono text-[11px]">{localName(lockedXsd)}</span>
                ) : (
                  <select
                    value={row.datatype ?? XSD_TYPES[0][0]}
                    aria-label={t('entityDialogs.dataType')}
                    onChange={(e) => setRow(i, { datatype: e.target.value })}
                    className="text-ink bg-panel border-line rounded-ctl border px-1 text-[11px]"
                  >
                    {XSD_TYPES.map(([v, l]) => (
                      <option key={v} value={v}>
                        {l}
                      </option>
                    ))}
                  </select>
                )}
              </div>
            )}
          </div>
        )
      })}
      {adding ? (
        <div className="flex flex-col gap-0.5">
          {unused.map((p) => (
            <button
              key={p.eid}
              type="button"
              onClick={() => {
                setRows([
                  ...rows,
                  {
                    property: p.eid,
                    kind: p.ptype === 'DatatypeProperty' ? 'data' : 'object',
                    value: '',
                    datatype: p.target?.kind === 'datatype' ? p.target.curie : undefined,
                  },
                ])
                setAdding(false)
              }}
              className="text-ink-2 hover:bg-panel-2 rounded-ctl px-2 py-1 text-left text-xs"
            >
              {localName(p.curie)}
              {p.inherited && (
                <span className="text-ink-3">
                  {' '}
                  · {t('inspector.inheritedFrom')} {p.via}
                </span>
              )}
            </button>
          ))}
          {unused.length === 0 && (
            <span className="text-ink-3 px-2 py-1 text-xs">{t('inspector.none')}</span>
          )}
          <button type="button" onClick={() => setAdding(false)} className="text-ink-3 px-2 py-1 text-xs">
            {t('common.cancel')}
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setAdding(true)}
          className="border-line text-ink-2 hover:text-primary rounded-ctl border border-dashed px-2 py-1 text-xs"
        >
          + {t('instance.addProp')}
        </button>
      )}
    </div>
  )
}

/** Instance detail (spec §4.2): identity + 类型 chips + 对象/数据属性行。
 *  对象属性行的值是可导航 Chip——实例从详情到详情,无死路。编辑态把
 *  comment/类型/断言行收进一张表单,一次 PUT 全量保存。 */
export default function InstanceDetail({ oid, eid, inst }: { oid: string; eid: string; inst: InstanceIR }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(inst.eid)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // Fallback for non-secure origins or missing clipboard API
      const textarea = document.createElement('textarea')
      textarea.value = inst.eid
      textarea.style.position = 'fixed'
      textarea.style.opacity = '0'
      document.body.appendChild(textarea)
      textarea.select()
      const success = document.execCommand('copy')
      document.body.removeChild(textarea)
      if (success) {
        setCopied(true)
        setTimeout(() => setCopied(false), 1500)
      }
    }
  }

  // ---- edit mode: local draft, seeded on entry, flushed by one PUT ----
  const [editing, setEditing] = useState(false)
  const [comment, setComment] = useState('')
  const [classes, setClasses] = useState<string[]>([])
  const [rows, setRows] = useState<Row[]>([])
  const enterEdit = () => {
    setComment(inst.comment ?? '')
    setClasses(inst.classes.map((c) => c.eid))
    setRows([
      ...inst.objectAssertions.map((a) => ({
        property: a.property.eid, kind: 'object' as const, value: a.object.eid,
      })),
      ...inst.dataAssertions.map((a) => ({
        property: a.property.eid, kind: 'data' as const, value: a.value, datatype: a.datatype,
      })),
    ])
    setEditing(true)
  }

  const { data: meta } = useQuery({
    enabled: editing,
    queryKey: ['ontology', oid],
    queryFn: () => api.get<OntologyMeta>(`/api/ontologies/${oid}/meta`),
  })
  const { data: overview } = useQuery({
    enabled: editing,
    queryKey: ['overview', oid],
    queryFn: () => api.get<NodesEdges>(`/api/ontologies/${oid}/overview`),
  })
  const allClasses = useMemo(
    () => (overview?.nodes ?? []).filter((n) => n.kind === 'class'),
    [overview],
  )
  const { data: schema } = useQuery({
    enabled: editing && classes.length > 0,
    queryKey: ['assertion-schema', oid, [...classes].sort().join(',')],
    queryFn: () =>
      api.get<SchemaProp[]>(
        `/api/ontologies/${oid}/assertion-schema?classes=${classes.map(encodeURIComponent).join(',')}`,
      ),
  })

  const save = useMutation({
    mutationFn: () =>
      api.put(`/api/ontologies/${oid}/instances/${encodeURIComponent(eid)}`, {
        comment: comment.trim() === '' ? null : comment.trim(),
        classes,
        // Half-filled rows (property picked, no value yet) never submit —
        // the backend would reject the empty object eid / junk literal.
        assertions: rows
          .filter((r) => r.value.trim() !== '')
          .map((r) => ({
            property: r.property,
            kind: r.kind,
            value: r.value,
            ...(r.kind === 'data' ? { datatype: r.datatype ?? XSD_TYPES[0][0] } : {}),
          })),
        baseFileHash: meta?.fileHash ?? '',
      }),
    onSuccess: () => {
      toast.success(t('common.saved'))
      setEditing(false)
      void queryClient.invalidateQueries()
    },
    // Failure keeps the edit state; EDIT_CONFLICT's mapped text says reload.
    onError: (e) => toast.error(errText(e, t)),
  })

  if (editing) {
    return (
      <div className="flex h-full flex-col gap-3 overflow-y-auto px-4 pt-3.5 pb-3">
        <div className="flex items-center justify-between">
          <span className="microlabel">{t('inspector.detail')}</span>
          <span className="bg-primary-soft border-primary-border text-primary rounded-full border px-2 py-0.5 text-[10px] font-semibold tracking-wide">
            {t('instance.badge')}
          </span>
        </div>
        <h3 className="text-primary font-mono text-sm font-bold break-all" title={inst.curie}>
          {localName(inst.curie)}
        </h3>
        <Section label={t('inspector.description')}>
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            aria-label={t('inspector.description')}
            rows={2}
            className="text-ink bg-panel-2 border-line rounded-ctl resize-none border px-2 py-1.5 text-xs w-full"
          />
        </Section>
        <Section label={t('instance.typeSection')} count={classes.length}>
          <ClassPicker classes={allClasses} value={classes} onChange={setClasses} multiple />
        </Section>
        <Section label={t('instance.assertSection')} count={rows.length}>
          <AssertionRows oid={oid} schema={schema ?? []} rows={rows} setRows={setRows} />
        </Section>
        <div className="mt-auto flex justify-end gap-2 pt-1">
          <Button variant="outline" size="sm" onClick={() => setEditing(false)}>
            {t('common.cancel')}
          </Button>
          <Button size="sm" disabled={save.isPending} onClick={() => save.mutate()}>
            {save.isPending ? t('instance.saving') : t('common.save')}
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto px-4 pt-3.5 pb-3">
      <div className="flex items-center justify-between">
        <span className="microlabel">{t('inspector.detail')}</span>
        <div className="flex items-center gap-2">
          <span className="bg-primary-soft border-primary-border text-primary rounded-full border px-2 py-0.5 text-[10px] font-semibold tracking-wide">
            {t('instance.badge')}
          </span>
          <button
            type="button"
            onClick={enterEdit}
            className="border-line text-ink-2 rounded-ctl border px-2 py-0.5 text-[11px]"
          >
            {t('instance.edit')}
          </button>
        </div>
      </div>
      <h3 className="text-primary font-mono text-sm font-bold break-all" title={inst.curie}>
        {localName(inst.curie)}
      </h3>
      <Section label="URI">
        <div className="flex items-start gap-1.5">
          <pre className="text-ink bg-panel-2 border-line rounded-ctl flex-1 border p-1.5 px-2 font-mono text-xs break-all whitespace-pre-wrap">
            {inst.eid}
          </pre>
          <button
            type="button"
            onClick={() => void copy()}
            className="border-line text-ink-2 hover:text-primary rounded-ctl border px-1 py-0.5 text-[11px]"
          >
            {copied ? t('instance.copied') : t('instance.copyUri')}
          </button>
        </div>
      </Section>
      {Object.keys(inst.label).length > 0 && (
        <Section label={t('inspector.labels')}>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(inst.label).map(([lang, value]) => (
              <span key={lang} className="border-line text-ink-2 rounded-full border px-2 py-px text-[11px]">
                {Object.keys(inst.label).length > 1 ? `${value} (${lang})` : value}
              </span>
            ))}
          </div>
        </Section>
      )}
      {inst.comment && (
        <Section label={t('inspector.description')}>
          <p className="text-ink-2 text-xs">{inst.comment}</p>
        </Section>
      )}
      <Section label={t('instance.typeSection')} count={inst.classes.length}>
        <div className="flex flex-wrap gap-1.5">
          {inst.classes.map((c) => (
            <Chip key={c.eid} {...c} />
          ))}
        </div>
      </Section>
      <Section label={t('instance.objectProps')} count={inst.objectAssertions.length}>
        <div className="flex flex-col gap-1">
          {inst.objectAssertions.map((a, i) => (
            <div key={`${a.property.eid}-${i}`} className="flex flex-wrap items-baseline gap-1.5 text-xs">
              <span className="text-ink-2 font-mono">{localName(a.property.curie)}</span>
              <span className="text-ink-3">→</span>
              <Chip {...a.object} />
            </div>
          ))}
        </div>
      </Section>
      <Section label={t('instance.dataProps')} count={inst.dataAssertions.length}>
        <div className="flex flex-col gap-1">
          {inst.dataAssertions.map((a, i) => (
            <div key={`${a.property.eid}-${i}`} className="flex flex-wrap items-baseline gap-1.5 text-xs">
              <span className="text-ink-2 font-mono">{localName(a.property.curie)}</span>
              <span className="text-ink-3">=</span>
              <span className="text-ink font-medium">{a.value}</span>
              <span className="text-ink-3 font-mono text-[10px]">{a.datatype.split('#').pop()}</span>
            </div>
          ))}
        </div>
      </Section>
    </div>
  )
}

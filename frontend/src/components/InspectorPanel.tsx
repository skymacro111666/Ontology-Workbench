import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { api } from '../api/client'
import type { EntityIR, PropRef, Ref, ReferencedRef } from '../api/types'
import { useBrowseStore } from '../stores/browseStore'
import { Button } from '@/components/ui/button'

/** Clickable entity chip (mockup linklist): soft primary pill, mono curie;
 *  selecting navigates the whole workspace along. */
function Chip({ eid, curie }: Ref) {
  const setSelected = useBrowseStore((s) => s.setSelected)
  return (
    <button
      type="button"
      onClick={() => setSelected(eid)}
      className="bg-primary-soft border-primary-border text-primary hover:bg-panel rounded-ctl font-mono text-xs border px-2 py-0.5 transition-colors break-all"
    >
      {curie}
    </button>
  )
}

/** Chip list with the mockup's muted 无 placeholder. */
function ChipList({ refs }: { refs: Ref[] }) {
  if (refs.length === 0) return <span className="text-ink-3 text-xs">无</span>
  return (
    <div className="flex flex-wrap gap-1.5">
      {refs.map((r) => (
        <Chip key={r.eid} {...r} />
      ))}
    </div>
  )
}

/** Compact property table (mockup mini): curie | 类型. */
function MiniProps({ rows }: { rows: PropRef[] }) {
  if (rows.length === 0) return <span className="text-ink-3 text-xs">无</span>
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="border-line border-b">
          <th className="text-ink-3 px-1.5 py-1 text-left font-semibold">curie</th>
          <th className="text-ink-3 px-1.5 py-1 text-left font-semibold">类型</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.eid} className="border-line border-b">
            <td className="text-ink px-1.5 py-1 font-mono break-all">{r.curie}</td>
            <td className="text-ink-2 px-1.5 py-1">{r.ptype}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/** Backref chips: who mentions this entity (relation kept as the title). */
function BackRefChips({ refs }: { refs: ReferencedRef[] }) {
  if (refs.length === 0) return <span className="text-ink-3 text-xs">无</span>
  return (
    <div className="flex flex-wrap gap-1.5">
      {refs.map((r) => (
        <span key={r.eid} title={r.relation}>
          <Chip {...r} />
        </span>
      ))}
    </div>
  )
}

function Section({ label, children }: { label: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-1.5">
      <span className="microlabel">{label}</span>
      {children}
    </section>
  )
}

/** Resident right-column summary of the selected entity: identity header,
 *  relation chips, property mini table, and two navigation actions.
 *  Compact by design — the full content lives in the central detail view. */
export default function InspectorPanel({ oid, eid }: { oid: string; eid: string | null }) {
  const setViewMode = useBrowseStore((s) => s.setViewMode)
  const openTtl = useBrowseStore((s) => s.openTtl)

  const { data: ent, isError } = useQuery({
    enabled: eid !== null,
    queryKey: ['entity', oid, eid],
    queryFn: () =>
      api.get<EntityIR>(`/api/ontologies/${oid}/entities/${encodeURIComponent(eid as string)}`),
    retry: false,
  })

  if (eid === null) {
    return (
      <div className="text-ink-3 rounded-card border-line flex h-full items-center justify-center border border-dashed p-6 text-center text-sm">
        在树或图中选择一个实体
      </div>
    )
  }
  if (isError) {
    return (
      <div className="text-ink-3 rounded-card border-line flex h-full items-center justify-center border border-dashed p-6 text-center text-sm">
        外部实体（未在本体中声明），无详情页
      </div>
    )
  }
  if (!ent) {
    return <div className="text-ink-3 py-10 text-center text-sm">加载中…</div>
  }

  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto px-4 pt-3.5 pb-3">
      <div className="flex flex-col gap-3">
        {/* mockup head: Inspector microlabel + type pill */}
        <div className="flex items-center justify-between">
          <span className="microlabel">Inspector</span>
          <span className="bg-primary-soft border-primary-border text-primary rounded-full border px-2 py-0.5 text-[10px] font-semibold tracking-wide">
            {ent.type.toUpperCase()}
          </span>
        </div>
        <h3 className="text-primary font-mono text-sm font-bold break-all">{ent.curie}</h3>
        <Section label="URI">
          <pre className="text-ink bg-panel-2 border-line rounded-ctl inline-block max-w-full border p-1.5 px-2 font-mono text-xs break-all whitespace-pre-wrap">
            {ent.eid}
          </pre>
        </Section>
        {Object.keys(ent.label).length > 0 && (
          <Section label="标签">
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(ent.label).map(([lang, value]) => (
                <span
                  key={lang}
                  className="border-line text-ink-2 rounded-full border px-2 py-px text-[11px]"
                >{`${value} ${lang}`}</span>
              ))}
            </div>
          </Section>
        )}
        {ent.comment && (
          <Section label="描述">
            <p className="text-ink-2 line-clamp-2 text-xs" title={ent.comment}>
              {ent.comment}
            </p>
          </Section>
        )}
      </div>

      <Section label="父类">
        <ChipList refs={ent.parents} />
      </Section>
      <Section label="直接子类">
        <ChipList refs={ent.children} />
      </Section>
      <Section label="属性">
        <MiniProps rows={ent.properties} />
      </Section>
      <Section label="被引用">
        <BackRefChips refs={ent.referencedBy} />
      </Section>

      <div className="border-line mt-auto flex gap-2 border-t pt-3.5">
        {/* Switches to detail AND opens the central TTL tab via the store
            signal EntityDetail consumes (T11 assembly wiring). */}
        <Button
          variant="outline"
          size="sm"
          className="flex-1"
          onClick={() => {
            setViewMode('detail')
            openTtl(ent.eid)
          }}
        >
          查看原始 TTL
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="flex-1"
          onClick={() => setViewMode('overview')}
        >
          在总览中查看
        </Button>
      </div>
    </div>
  )
}

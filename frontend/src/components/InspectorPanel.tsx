import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { api } from '../api/client'
import type { EntityIR, PropRef, Ref, ReferencedRef } from '../api/types'
import { useBrowseStore } from '../stores/browseStore'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'

/** Clickable entity chip (parents/children/backrefs); selecting navigates
 *  the whole workspace — tree, content area, and inspector follow along. */
function Chip({ eid, curie }: Ref) {
  const setSelected = useBrowseStore((s) => s.setSelected)
  return (
    <button
      type="button"
      onClick={() => setSelected(eid)}
      className="border-line bg-panel text-primary rounded-ctl hover:border-primary-border hover:bg-primary-soft font-mono text-xs border px-2 py-0.5 transition-colors break-all"
    >
      {curie}
    </button>
  )
}

/** Chip list with the shared "nothing here" dash. */
function ChipList({ refs }: { refs: Ref[] }) {
  if (refs.length === 0) return <span className="text-ink-3 text-xs">—</span>
  return (
    <div className="flex flex-wrap gap-1.5">
      {refs.map((r) => (
        <Chip key={r.eid} {...r} />
      ))}
    </div>
  )
}

/** Compact property listing: one bordered row per curie → type. */
function MiniProps({ rows }: { rows: PropRef[] }) {
  if (rows.length === 0) return <span className="text-ink-3 text-xs">—</span>
  return (
    <div className="border-line rounded-ctl divide-line border divide-y">
      {rows.map((r) => (
        <div key={r.eid} className="flex items-baseline justify-between gap-2 px-2 py-1">
          <span className="font-mono text-xs break-all">{r.curie}</span>
          <span className="text-ink-3 font-mono text-xs shrink-0">{r.ptype}</span>
        </div>
      ))}
    </div>
  )
}

/** Backref chips: who mentions this entity (relation kept as the title). */
function BackRefChips({ refs }: { refs: ReferencedRef[] }) {
  if (refs.length === 0) return <span className="text-ink-3 text-xs">暂无反向引用</span>
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
    <div className="flex h-full flex-col gap-4 overflow-y-auto p-1 pb-2">
      <div className="flex flex-col gap-2">
        <Badge variant="outline" className="microlabel border-line rounded-ctl">
          {ent.type}
        </Badge>
        <h3 className="text-primary font-mono text-sm font-semibold break-all">{ent.curie}</h3>
        <pre className="text-ink-2 bg-canvas border-line rounded-ctl border p-2 font-mono text-xs break-all whitespace-pre-wrap">
          {ent.eid}
        </pre>
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(ent.label).map(([lang, value]) => (
            <Badge key={lang} variant="secondary" className="font-mono text-xs">
              {lang}: {value}
            </Badge>
          ))}
        </div>
        {ent.comment && (
          <p className="text-ink-2 line-clamp-2 text-xs" title={ent.comment}>
            {ent.comment}
          </p>
        )}
      </div>

      <Section label="父类">
        <ChipList refs={ent.parents} />
      </Section>
      <Section label="子类">
        <ChipList refs={ent.children} />
      </Section>
      <Section label="属性">
        <MiniProps rows={ent.properties} />
      </Section>
      <Section label="被引用">
        <BackRefChips refs={ent.referencedBy} />
      </Section>

      <div className="border-line mt-auto flex flex-col gap-2 border-t pt-3">
        <Button
          variant="outline"
          size="sm"
          className="w-full"
          onClick={() => setViewMode('detail')}
        >
          原始 TTL
        </Button>
        {/* TODO(T11): after switching to detail, scroll the central EntityDetail
            to its TTL tab — needs a store signal that does not exist yet. */}
        <Button variant="secondary" size="sm" className="w-full" asChild>
          <Link to={`/graph/${oid}?focus=${encodeURIComponent(ent.eid)}`}>在总览中查看</Link>
        </Button>
      </div>
    </div>
  )
}

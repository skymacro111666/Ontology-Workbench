import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../api/client'
import type { CounterpartRef, EntityIR, GNode, InstanceIR, NodesEdges, Ref, ReferencedRef } from '../api/types'
import { errText } from '../i18n/errText'
import { localName } from '../lib/localName'
import { useBrowseStore } from '../stores/browseStore'
import { useUiStore } from '../stores/uiStore'
import { cn } from '@/lib/utils'
import InstanceDetail from './InstanceDetail'

/** Clickable entity chip (mockup linklist): soft primary pill; the human
 *  label when present, the local curie name otherwise — the full curie
 *  rides along in the tooltip. Selecting navigates the workspace along. */
export function Chip({ eid, curie, label }: Ref) {
  const setSelected = useBrowseStore((s) => s.setSelected)
  const human = Object.values(label ?? {})[0]
  return (
    <button
      type="button"
      title={curie}
      onClick={() => setSelected(eid)}
      className={cn(
        'bg-primary-soft border-primary-border text-primary hover:bg-panel rounded-ctl border px-2 py-0.5 text-xs transition-colors',
        human ? '' : 'font-mono',
        'break-all',
      )}
    >
      {human ?? localName(curie)}
    </button>
  )
}

/** Chip list with the mockup's muted 无 placeholder. */
function ChipList({ refs }: { refs: Ref[] }) {
  const { t } = useTranslation()
  if (refs.length === 0) return <span className="text-ink-3 text-xs">{t('inspector.none')}</span>
  return (
    <div className="flex flex-wrap gap-1.5">
      {refs.map((r) => (
        <Chip key={r.eid} {...r} />
      ))}
    </div>
  )
}

/** Domain/range backrefs — the ones 被引用 groups; subClassOf backrefs
 *  duplicate 直接子类 above, so they drop out of the section entirely. */
function dirRefs(refs: ReferencedRef[]): ReferencedRef[] {
  return refs.filter((r) => r.relation !== 'subClassOf')
}

/** Display name for a plain (non-chip) ref: label or local curie name. */
function refName(r: Ref): string {
  return Object.values(r.label ?? {})[0] ?? localName(r.curie)
}

/** The axiom's far end: declared entities navigate on click (dotted
 *  underline marks it interactive); external IRIs stay plain text —
 *  they have no detail page to land on. */
function Counterpart({ counterpart, arrow }: { counterpart: CounterpartRef; arrow: string }) {
  const setSelected = useBrowseStore((s) => s.setSelected)
  return (
    <span className="text-ink-3 font-mono break-all">
      {arrow}{' '}
      {counterpart.declared ? (
        <button
          type="button"
          title={counterpart.curie}
          onClick={() => setSelected(counterpart.eid)}
          className="text-ink-2 hover:text-primary cursor-pointer underline decoration-dotted underline-offset-2"
        >
          {refName(counterpart)}
        </button>
      ) : (
        refName(counterpart)
      )}
    </span>
  )
}

/** Backref rows grouped by relation direction (competitor's relationship
 *  usage): each row pairs the referencing entity with the axiom's far end
 *  (`works in → Department` for a domain ref, `reviewed by ← Manager` for
 *  a range ref). */
function BackRefChips({ refs }: { refs: ReferencedRef[] }) {
  const { t } = useTranslation()
  const domains = refs.filter((r) => r.relation === 'rdfs:domain')
  const ranges = refs.filter((r) => r.relation === 'rdfs:range')
  if (domains.length + ranges.length === 0) return <span className="text-ink-3 text-xs">{t('inspector.none')}</span>
  const group = (title: string, list: ReferencedRef[], arrow: string) =>
    list.length > 0 && (
      <div className="flex flex-col gap-1">
        <span className="text-ink-3 text-[11px]">
          {title} ({list.length})
        </span>
        {list.map((r) => (
          <div key={r.eid} className="flex flex-wrap items-baseline gap-x-1.5 text-xs">
            <Chip {...r} />
            {r.counterpart && <Counterpart counterpart={r.counterpart} arrow={arrow} />}
          </div>
        ))}
      </div>
    )
  return (
    <div className="flex flex-col gap-2">
      {group(t('inspector.asDomain'), domains, '→')}
      {group(t('inspector.asRange'), ranges, '←')}
    </div>
  )
}

/** Instance chips: individuals have their own detail page since B2, so each
 *  row navigates there (label or local curie name in a chip; the full curie
 *  rides in the tooltip). Same direct-instances scope as the canvas badge. */
function InstanceRows({ nodes }: { nodes: GNode[] }) {
  const { t } = useTranslation()
  if (nodes.length === 0) return <span className="text-ink-3 text-xs">{t('inspector.none')}</span>
  return (
    <div className="flex flex-wrap gap-1.5">
      {nodes.map((n) => (
        <Chip key={n.id} eid={n.id} curie={n.curie} label={n.label} />
      ))}
    </div>
  )
}

export function Section({
  label,
  count,
  action,
  children,
}: {
  label: string
  count?: number
  /** Header-affordance control (e.g. the instances section's ＋). */
  action?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between">
        <span className="microlabel">
          {label}
          {count !== undefined && ` (${count})`}
        </span>
        {action}
      </div>
      {children}
    </section>
  )
}

/** Resident right-column summary of the selected entity: identity header,
 *  relation chips, property mini table — the workspace's detail surface
 *  (the content column is permanently the overview canvas). */
export default function InspectorPanel({ oid, eid }: { oid: string; eid: string | null }) {
  const { t } = useTranslation()
  const setInstanceDialog = useUiStore((s) => s.setInstanceDialog)
  const { data: ent, isError, error } = useQuery({
    enabled: eid !== null,
    queryKey: ['entity', oid, eid],
    queryFn: () =>
      api.get<EntityIR | InstanceIR>(`/api/ontologies/${oid}/entities/${encodeURIComponent(eid as string)}`),
    retry: false,
  })

  /** Instances join only for classes (same endpoint as the canvas badge).
   *  Boolean coercion matters: `ent && …` alone is undefined pre-resolve, and
   *  react-query reads `enabled: undefined` as the default true — firing an
   *  instances fetch before the entity (even /entities/null/instances when
   *  nothing is selected). */
  const isClass = !!ent && 'type' in ent && ent.type === 'Class'
  const { data: insts, isError: instsError } = useQuery({
    enabled: isClass,
    queryKey: ['instances', oid, eid],
    queryFn: () =>
      api.get<NodesEdges>(
        `/api/ontologies/${oid}/entities/${encodeURIComponent(eid as string)}/instances`,
      ),
    retry: false,
  })

  if (eid === null) {
    return (
      <div className="text-ink-3 rounded-card border-line flex h-full items-center justify-center border border-dashed p-6 text-center text-sm">
        {t('inspector.pickHint')}
      </div>
    )
  }
  if (isError) {
    // T8①: branch on the envelope code instead of one blanket sentence.
    return (
      <div className="text-ink-3 rounded-card border-line flex h-full items-center justify-center border border-dashed p-6 text-center text-sm">
        {errText(error, t)}
      </div>
    )
  }
  if (!ent) {
    return <div className="text-ink-3 py-10 text-center text-sm">{t('common.loading')}</div>
  }

  // Dispatch to InstanceDetail for instances (entities have kind: 'entity' or
  //  undefined). The key remounts per instance: a cached entity returns
  //  synchronously (no undefined gap → no unmount), which would otherwise
  //  carry instance A's edit draft onto instance B's page — and its PUT.
  if (ent && ent.kind === 'instance') {
    return <InstanceDetail key={eid as string} oid={oid} eid={eid as string} inst={ent} />
  }

  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto px-4 pt-3.5 pb-3">
      <div className="flex flex-col gap-3">
        {/* mockup head: panel microlabel + type pill */}
        <div className="flex items-center justify-between">
          <span className="microlabel">{t('inspector.detail')}</span>
          <span className="bg-primary-soft border-primary-border text-primary rounded-full border px-2 py-0.5 text-[10px] font-semibold tracking-wide">
            {ent.type.toUpperCase()}
          </span>
        </div>
        <h3 className="text-primary font-mono text-sm font-bold break-all" title={ent.curie}>
          {localName(ent.curie)}
        </h3>
        <Section label="URI">
          <pre className="text-ink bg-panel-2 border-line rounded-ctl inline-block max-w-full border p-1.5 px-2 font-mono text-xs break-all whitespace-pre-wrap">
            {ent.eid}
          </pre>
        </Section>
        {Object.keys(ent.label).length > 0 && (
          <Section label={t('inspector.labels')}>
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(ent.label).map(([lang, value]) => (
                <span
                  key={lang}
                  className="border-line text-ink-2 rounded-full border px-2 py-px text-[11px]"
                >
                  {/* Lang suffix only disambiguates multilingual labels; a
                      single label reads as the plain display name. */}
                  {Object.keys(ent.label).length > 1 ? `${value} (${lang})` : value}
                </span>
              ))}
            </div>
          </Section>
        )}
        {ent.comment && (
          <Section label={t('inspector.description')}>
            <p className="text-ink-2 line-clamp-2 text-xs" title={ent.comment}>
              {ent.comment}
            </p>
          </Section>
        )}
      </div>

      <Section label={t('inspector.parents')} count={ent.parents.length}>
        <ChipList refs={ent.parents} />
      </Section>
      <Section label={t('inspector.children')} count={ent.children.length}>
        <ChipList refs={ent.children} />
      </Section>
      <Section label={t('inspector.referencedBy')} count={dirRefs(ent.referencedBy).length}>
        <BackRefChips refs={ent.referencedBy} />
      </Section>
      {ent.type === 'Class' && (
        <Section
          label={t('inspector.instances')}
          count={insts?.nodes.length}
          action={
            <button
              type="button"
              aria-label={t('canvas.newInstance')}
              title={t('canvas.newInstance')}
              onClick={() => setInstanceDialog({ mode: 'create', parent: ent.eid })}
              className="border-line text-ink-2 hover:text-primary rounded-ctl border px-1.5 text-[11px] leading-4"
            >
              ＋
            </button>
          }
        >
          {instsError ? (
            <span className="text-ink-3 text-xs">{t('shell.loadFailed')}</span>
          ) : insts ? (
            <InstanceRows nodes={insts.nodes} />
          ) : (
            <span className="text-ink-3 text-xs">{t('common.loading')}</span>
          )}
        </Section>
      )}
    </div>
  )
}

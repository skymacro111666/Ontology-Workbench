import { useQuery } from '@tanstack/react-query'
import { useMemo, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../api/client'
import type { CounterpartRef, EntityIR, GNode, InstanceIR, ManchesterLine, NodesEdges, Ref, ReferencedRef, SchemaProp } from '../api/types'
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

/** A class's usable properties (own + inherited): where assertion editing
 *  draws its property list, and the class page's capability sheet. Inherited
 *  rows dim with a 「继承自 via」 suffix (competitor's pattern); object
 *  properties pair with a navigable range-class link, datatype properties
 *  with `= localName(xsd curie)`. Domainless rows (no rdfs:domain anywhere
 *  — usable on any class) sit in their own 全域属性 group so they never
 *  read as the class's own properties. Same query key shape as
 *  InstanceDetail's single-class schema lookups, so the entries share
 *  cache. */
function ClassPropSection({ oid, cls }: { oid: string; cls: string }) {
  const { t } = useTranslation()
  const setSelected = useBrowseStore((s) => s.setSelected)
  const { data: props } = useQuery({
    queryKey: ['assertion-schema', oid, cls],
    queryFn: () =>
      api.get<SchemaProp[]>(
        `/api/v1/ontologies/${oid}/assertion-schema?classes=${encodeURIComponent(cls)}`,
      ),
  })
  if (!props?.length) return null
  const universal = props.filter((p) => p.domainless)
  const declared = props.filter((p) => !p.domainless)
  const PropRow = ({ p }: { p: SchemaProp }) => (
    <div
      className={cn('flex flex-wrap items-baseline gap-1.5 text-xs', p.inherited && 'opacity-60')}
    >
      <span className="text-ink-2 font-mono">{localName(p.curie)}</span>
      {p.target?.kind === 'class' ? (
        <>
          <span className="text-ink-3">→</span>
          <button
            type="button"
            title={p.target.curie}
            onClick={() => p.target?.eid && setSelected(p.target.eid)}
            className="text-primary hover:underline underline decoration-dotted underline-offset-2"
          >
            {localName(p.target.curie)}
          </button>
        </>
      ) : (
        <span className="text-ink-3">= {localName(p.target?.curie ?? '')}</span>
      )}
      {p.inherited && p.via && (
        <span className="text-ink-3 text-[10px]">
          {t('inspector.inheritedFrom')} {p.via}
        </span>
      )}
    </div>
  )
  return (
    <>
      {declared.length > 0 && (
        <Section label={t('inspector.properties')} count={declared.length}>
          <div className="flex flex-col gap-1">
            {declared.map((p) => (
              <PropRow key={p.eid} p={p} />
            ))}
          </div>
        </Section>
      )}
      {universal.length > 0 && (
        <Section label={t('inspector.universalProps')} count={universal.length}>
          <p className="text-ink-3 text-[10px]">{t('inspector.universalPropsHint')}</p>
          <div className="flex flex-col gap-1">
            {universal.map((p) => (
              <PropRow key={p.eid} p={p} />
            ))}
          </div>
        </Section>
      )}
    </>
  )
}

/** Manchester 关键词(行内着色):渲染器模板词表 + 布尔/基数连接词. */
const MANCHESTER_KEYWORDS = new Set([
  'SubClassOf',
  'SubPropertyOf',
  'EquivalentTo',
  'DisjointClasses',
  'DisjointUnionOf',
  'HasKey',
  'Type',
  'Self',
  'some',
  'only',
  'min',
  'max',
  'exactly',
  'and',
  'or',
  'not',
  'value',
  'chain',
])

/** One axiom line: keywords carry the primary tint, literals dim, rest ink. */
function ManchesterText({ text }: { text: string }) {
  return (
    <code className="text-ink-2 font-mono text-xs break-all">
      {text.split(/(\s+)/).map((tok, i) => (
        <span
          key={i}
          className={cn(
            MANCHESTER_KEYWORDS.has(tok) && 'text-primary font-semibold',
            tok.startsWith('"') && 'text-ink-3',
          )}
        >
          {tok}
        </span>
      ))}
    </code>
  )
}

/** Axiom section (A+B iteration): one row per axiom with its kind as the
 *  leading anchor, kind chips filter when several families mix, and the box
 *  scrolls past ~12 rows instead of pushing the sections below away. Raw
 *  Turtle stays a closed <details> safety net (OWL 2 M1 degradation). */
function ManchesterSection({
  lines,
  axioms,
}: {
  lines: ManchesterLine[]
  axioms: { turtle: string }[]
}) {
  const { t } = useTranslation()
  const [kindFilter, setKindFilter] = useState<string | null>(null)
  const kinds = useMemo(() => [...new Set(lines.map((l) => l.kind))], [lines])
  const visible = kindFilter ? lines.filter((l) => l.kind === kindFilter) : lines
  return (
    <Section
      label={t('inspector.axioms.structured')}
      count={lines.length}
      action={
        kinds.length > 1 ? (
          <div className="flex flex-wrap gap-1">
            {kinds.map((k) => (
              <button
                key={k}
                type="button"
                aria-pressed={kindFilter === k}
                onClick={() => setKindFilter(kindFilter === k ? null : k)}
                className={cn(
                  'rounded-full border px-2 py-px font-mono text-[10px] leading-4',
                  kindFilter === k
                    ? 'bg-primary-soft border-primary-border text-primary'
                    : 'border-line text-ink-2 hover:text-primary',
                )}
              >
                {k}
              </button>
            ))}
          </div>
        ) : undefined
      }
    >
      <div className="border-line bg-panel-2 rounded-ctl flex max-h-72 flex-col gap-0.5 overflow-y-auto border p-1.5">
        {visible.map((l, i) => (
          <div
            key={`${l.kind}:${i}`}
            className={cn('flex items-start gap-2 py-1', i > 0 && 'border-line border-t')}
          >
            <span className="text-ink-3 shrink-0 pt-px font-mono text-[10px] leading-5">
              {l.kind}
            </span>
            <ManchesterText text={l.text} />
          </div>
        ))}
      </div>
      {axioms.length > 0 && (
        <details>
          <summary className="text-ink-3 cursor-pointer text-[11px] select-none">
            {t('inspector.axioms.raw')}
          </summary>
          <pre className="text-ink bg-panel-2 border-line rounded-ctl mt-1 max-w-full overflow-x-auto border p-1.5 font-mono text-xs break-all whitespace-pre-wrap">
            {axioms.map((a) => a.turtle).join('\n')}
          </pre>
        </details>
      )}
    </Section>
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
      api.get<EntityIR | InstanceIR>(`/api/v1/ontologies/${oid}/entities/${encodeURIComponent(eid as string)}`),
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
        `/api/v1/ontologies/${oid}/entities/${encodeURIComponent(eid as string)}/instances`,
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
      {ent.type === 'Class' && <ClassPropSection oid={oid} cls={ent.eid} />}
      <Section label={t('inspector.referencedBy')} count={dirRefs(ent.referencedBy).length}>
        <BackRefChips refs={ent.referencedBy} />
      </Section>
      {ent.manchester && ent.manchester.length > 0 && (
        <ManchesterSection lines={ent.manchester} axioms={ent.axioms} />
      )}
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

import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { EntityIR, PropRef, Ref, ReferencedRef } from '../api/types'
import { useBrowseStore } from '../stores/browseStore'
import { Badge } from '@/components/ui/badge'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

/** Clickable entity links for the parents/children lists. */
function RefLinks({ refs }: { refs: Ref[] }) {
  const setSelected = useBrowseStore((s) => s.setSelected)
  if (refs.length === 0) return <span className="text-ink-3">—</span>
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-1">
      {refs.map((r) => (
        <button
          key={r.eid}
          type="button"
          className="text-primary hover:text-primary-hover font-mono text-sm break-all underline-offset-4 hover:underline"
          onClick={() => setSelected(r.eid)}
        >
          {r.curie}
        </button>
      ))}
    </div>
  )
}

/** Property rows: curie + its type. */
function PropertyTable({ rows }: { rows: PropRef[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>属性</TableHead>
          <TableHead className="w-44">类型</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r) => (
          <TableRow key={r.eid}>
            <TableCell className="font-mono">{r.curie}</TableCell>
            <TableCell>{r.ptype}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

/** Reverse references (absorbed from RefPanel): who mentions this entity,
 *  row click navigates to the referencing entity. */
function BackRefTable({ refs }: { refs: ReferencedRef[] }) {
  const setSelected = useBrowseStore((s) => s.setSelected)
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>CURIE</TableHead>
          <TableHead className="w-44">关系</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {refs.map((r) => (
          <TableRow key={r.eid} className="cursor-pointer" onClick={() => setSelected(r.eid)}>
            <TableCell className="font-mono">{r.curie}</TableCell>
            <TableCell>{r.relation}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function Overview({ ent, compact }: { ent: EntityIR; compact: boolean }) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge variant="secondary" className="font-mono">
          {ent.type}
        </Badge>
        {Object.entries(ent.label).map(([lang, value]) => (
          <Badge key={lang} variant="outline">
            {lang}: {value}
          </Badge>
        ))}
        {ent.deprecated && <Badge variant="destructive">deprecated</Badge>}
      </div>

      {ent.comment && <p className="text-ink-2 text-sm">{ent.comment}</p>}

      <section className="flex flex-col gap-1.5">
        <span className="microlabel">父类</span>
        <RefLinks refs={ent.parents} />
      </section>
      <section className="flex flex-col gap-1.5">
        <span className="microlabel">子类</span>
        <RefLinks refs={ent.children} />
      </section>

      {ent.properties.length > 0 && (
        <section className="flex flex-col gap-1.5">
          <span className="microlabel">属性</span>
          <PropertyTable rows={ent.properties} />
        </section>
      )}

      <section className="flex flex-col gap-1.5">
        <span className="microlabel">反向引用</span>
        {ent.referencedBy.length > 0 ? (
          <BackRefTable refs={ent.referencedBy} />
        ) : (
          <span className="text-ink-3 text-sm">暂无反向引用</span>
        )}
      </section>

      {!compact && (
        <p className="text-ink-2 text-sm">
          直接子类 {ent.stats.directChildren} · 全部后代 {ent.stats.totalDescendants}
        </p>
      )}
    </div>
  )
}

/** Detail state of the selected entity: overview / raw TTL tabs.
 *  `eid` prop wins; when omitted the browse-store selection is used (legacy
 *  fallback kept for its tested contract — Browse passes eid explicitly).
 *  `compact` drops the TTL tab and stats line for the split-view right column.
 *  Tabs open on TTL when the store carries an inspector TTL request for this
 *  entity (`openTtl`); Browse re-keys the pane per request so repeats refire.
 *  Compact always opens on overview — it has no TTL tab to select. */
export default function EntityDetail({
  oid,
  eid,
  compact = false,
}: {
  oid: string
  eid?: string | null
  compact?: boolean
}) {
  const storeEid = useBrowseStore((s) => s.selectedEid)
  const ttlFocusEid = useBrowseStore((s) => s.ttlFocusEid)
  const selectedEid = eid !== undefined ? eid : storeEid

  const { data: ent, isError } = useQuery({
    enabled: selectedEid !== null,
    queryKey: ['entity', oid, selectedEid],
    queryFn: () =>
      api.get<EntityIR>(`/api/ontologies/${oid}/entities/${encodeURIComponent(selectedEid as string)}`),
    retry: false,
  })
  // Compact renders no TTL tab, so it never fetches the raw payload either.
  const { data: raw } = useQuery({
    enabled: selectedEid !== null && !compact,
    queryKey: ['raw', oid, selectedEid],
    queryFn: () =>
      api.get<{ turtle: string }>(
        `/api/ontologies/${oid}/raw/${encodeURIComponent(selectedEid as string)}`,
      ),
    retry: false,
  })

  if (selectedEid === null) {
    return (
      <div className="text-ink-3 rounded-card border-line flex items-center justify-center border border-dashed py-16 text-sm">
        选择左侧实体查看详情
      </div>
    )
  }
  if (isError) {
    return (
      <div className="text-ink-3 rounded-card border-line flex items-center justify-center border border-dashed py-16 text-sm">
        外部实体（未在本体中声明），无详情页
      </div>
    )
  }
  if (!ent) {
    return <div className="text-ink-3 py-16 text-center text-sm">加载中…</div>
  }

  return (
    <div className="flex flex-col gap-3">
      <h3 className="font-mono text-base font-semibold break-all">{ent.curie}</h3>
      <Tabs
        defaultValue={
          !compact && ttlFocusEid !== null && ttlFocusEid === selectedEid ? 'ttl' : 'overview'
        }
      >
        <TabsList>
          <TabsTrigger value="overview">概览</TabsTrigger>
          {!compact && <TabsTrigger value="ttl">原始 TTL</TabsTrigger>}
        </TabsList>
        <TabsContent value="overview">
          <Overview ent={ent} compact={compact} />
        </TabsContent>
        {!compact && (
          <TabsContent value="ttl">
            <pre className="text-ink-2 font-mono text-xs whitespace-pre-wrap break-all">
              {raw?.turtle ?? '…'}
            </pre>
          </TabsContent>
        )}
      </Tabs>
    </div>
  )
}

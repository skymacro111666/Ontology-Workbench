import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Tree, type NodeApi, type NodeRendererProps, type TreeApi } from 'react-arborist'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/client'
import type { EntityIR, OntologyMeta, TreeNode } from '../api/types'
import { useContainerHeight } from '../hooks/useContainerHeight'
import { localName } from '../lib/localName'
import { useBrowseStore } from '../stores/browseStore'
import { Table, TableBody, TableCell, TableRow } from '@/components/ui/table'
import { cn } from '@/lib/utils'

type ChildMap = Record<string, TreeNode[]>
type Tab = 'classes' | 'props' | 'prefixes'

/** react-arborist row: a TreeNode plus children (absent = leaf, [] = not loaded). */
type TreeRow = TreeNode & { children?: TreeRow[] }

/** Map API nodes to rows; leaves stay childless so they render without chevrons. */
function toRows(nodes: TreeNode[], childMap: ChildMap): TreeRow[] {
  return nodes.map((n) => {
    if (n.childrenCount === 0) return { ...n }
    const kids = childMap[n.eid]
    return { ...n, children: kids ? toRows(kids, childMap) : [] }
  })
}

/** Case-insensitive substring match over curie and label values. */
function matchesTerm(n: TreeRow, term: string): boolean {
  const t = term.trim().toLowerCase()
  if (n.curie.toLowerCase().includes(t)) return true
  return Object.values(n.label ?? {}).some((v) => v.toLowerCase().includes(t))
}

/** Property-kind pill after the name: OP primary-tinted (matches the
 *  canvas's object-property edge color), DP neutral slate (canvas draws
 *  datatype edges in ink-3). Classes and untyped properties show none. */
function KindPill({ type }: { type: string }) {
  if (type !== 'ObjectProperty' && type !== 'DatatypeProperty') return null
  const op = type === 'ObjectProperty'
  return (
    <span
      className={cn(
        'shrink-0 rounded-full border px-1.5 text-[10px] leading-4 font-semibold',
        op
          ? 'bg-primary-soft border-primary-border text-primary'
          : 'bg-panel-2 border-line text-ink-2',
      )}
    >
      {op ? 'OP' : 'DP'}
    </span>
  )
}

/** One row: chevron + curie + instance-count badge (solid primary pill,
 *  white with primary border when the row is selected). */
function ClassRow({ node, style }: NodeRendererProps<TreeRow>) {
  const { t } = useTranslation()
  return (
    <div
      style={style}
      className={cn(
        'flex h-7 shrink-0 items-center gap-1.5 rounded-ctl pr-2 text-[12.5px]',
        node.isSelected
          ? 'bg-primary-soft text-primary font-semibold'
          : 'text-ink-2 hover:bg-panel-2',
      )}
    >
      {node.isInternal ? (
        <button
          type="button"
          aria-label={node.isOpen ? t('tree.collapse') : t('tree.expand')}
          onClick={(e) => {
            e.stopPropagation()
            node.toggle()
          }}
          className="text-ink-3 flex h-3 w-3 shrink-0 cursor-pointer items-center justify-center"
        >
          <svg
            viewBox="0 0 16 16"
            width="12"
            height="12"
            aria-hidden="true"
            className={cn('transition-transform', node.isOpen && 'rotate-90')}
          >
            <path d="M6 4l4 4-4 4" fill="none" stroke="currentColor" strokeWidth="1.5" />
          </svg>
        </button>
      ) : (
        <span className="h-3 w-3 shrink-0" />
      )}
      <span
        title={node.data.curie}
        className={cn('truncate', node.isSelected && 'font-mono')}
      >
        {localName(node.data.curie)}
      </span>
      <KindPill type={node.data.type} />
      {(node.data.instanceCount ?? 0) > 0 && (
        <span
          title={t('tree.instanceCount')}
          className={cn(
            'ml-auto flex h-[17px] min-w-[17px] items-center justify-center rounded-full px-[5px] text-[10px]',
            node.isSelected
              ? 'bg-panel border-primary-border text-primary border'
              : 'bg-primary border-transparent text-primary-foreground border',
          )}
        >
          {node.data.instanceCount}
        </span>
      )}
    </div>
  )
}

/**
 * Tri-tab explorer (类/属性/前缀, spec §7.2): lazy react-arborist class tree,
 * property leaf list, and the prefix table, under one client-side filter box.
 */
export default function ClassTree({ oid }: { oid: string }) {
  const { t } = useTranslation()
  const selectedEid = useBrowseStore((s) => s.selectedEid)
  const revealEid = useBrowseStore((s) => s.revealEid)
  const setSelected = useBrowseStore((s) => s.setSelected)
  const clearReveal = useBrowseStore((s) => s.clearReveal)
  const queryClient = useQueryClient()
  const { ref, height } = useContainerHeight<HTMLDivElement>()
  const treeRef = useRef<TreeApi<TreeRow> | undefined>(undefined)
  const propTreeRef = useRef<TreeApi<TreeRow> | undefined>(undefined)
  const [childMap, setChildMap] = useState<ChildMap>({})
  const [filter, setFilter] = useState('')
  const [tab, setTab] = useState<Tab>('classes')

  const { data: roots } = useQuery({
    queryKey: ['tree', oid, 'roots'],
    queryFn: () => api.get<TreeNode[]>(`/api/ontologies/${oid}/tree`),
  })
  // Lazy like the old tab contents: fetch only once the tab is opened.
  const { data: propNodes } = useQuery({
    queryKey: ['tree', oid, '__props__'],
    queryFn: () => api.get<TreeNode[]>(`/api/ontologies/${oid}/tree?parent=__props__`),
    enabled: tab === 'props',
  })
  const { data: meta } = useQuery({
    queryKey: ['ontology', oid],
    queryFn: () => api.get<OntologyMeta>(`/api/ontologies/${oid}/meta`),
    enabled: tab === 'prefixes',
  })

  const loadChildren = useCallback(
    async (parentEid: string): Promise<TreeNode[]> => {
      const parent = encodeURIComponent(parentEid)
      const kids = await queryClient.fetchQuery({
        queryKey: ['tree-children', oid, parentEid],
        queryFn: () => api.get<TreeNode[]>(`/api/ontologies/${oid}/tree?parent=${parent}`),
      })
      setChildMap((m) => ({ ...m, [parentEid]: kids }))
      return kids
    },
    [oid, queryClient],
  )

  const handleToggle = useCallback(
    (id: string) => {
      // Expanding a materialized branch needs nothing; closing changes nothing.
      if (childMap[id]) return
      // Mirror the reveal walk's catch: a failed fetch leaves the branch
      // collapsed instead of an unhandled rejection (backlog T10①).
      loadChildren(id).catch(() => null)
    },
    [childMap, loadChildren],
  )

  // Search reveal: walk parents (cached /entities), load each level, expand.
  useEffect(() => {
    if (!revealEid) return
    let cancelled = false

    const entityOf = (eid: string) =>
      queryClient
        .fetchQuery({
          queryKey: ['entity', oid, eid],
          queryFn: () =>
            api.get<EntityIR>(`/api/ontologies/${oid}/entities/${encodeURIComponent(eid)}`),
        })
        .catch(() => null)

    void (async () => {
      try {
        // Chain bottom-up via the first parent (primary lineage, Phase 1).
        const chain: string[] = []
        let cursor: string | null = revealEid
        const seen = new Set<string>()
        while (cursor && !seen.has(cursor) && chain.length < 32) {
          seen.add(cursor)
          const ent = await entityOf(cursor)
          if (!ent) break
          chain.push(cursor)
          const parent = ent.parents.find((p) => p.eid !== cursor)
          cursor = parent ? parent.eid : null
        }
        // Top-down: materialize children so every ancestor becomes expandable.
        for (const eid of chain.reverse()) {
          if (cancelled) return
          await loadChildren(eid)
        }
        if (!cancelled) {
          // Expand ancestors only (the target is visible through its parent);
          // keep branches the user already expanded.
          for (const eid of chain.slice(0, -1)) treeRef.current?.open(eid)
          setSelected(revealEid)
        }
      } catch {
        // A failed walk leaves selection working (detail renders); the tree
        // just does not auto-expand this time.
      } finally {
        if (!cancelled) clearReveal()
      }
    })()

    return () => {
      cancelled = true
    }
  }, [revealEid, oid, queryClient, loadChildren, setSelected, clearReveal])

  const classRows = useMemo(() => toRows(roots ?? [], childMap), [roots, childMap])
  const propRows = useMemo(() => toRows(propNodes ?? [], {}), [propNodes])

  // The selection prop applies once per change; re-assert when rows arrive so
  // late loads (deep link, lazy expand) still show the highlight. Guarded by
  // visibility so the library's internal scroll wait always resolves.
  useEffect(() => {
    if (!selectedEid) return
    for (const tree of [treeRef.current, propTreeRef.current]) {
      if (tree?.visibleNodes.some((n) => n.id === selectedEid)) {
        tree.select(selectedEid, { focus: false })
      }
    }
  }, [selectedEid, classRows, propRows])

  // Shared by both trees; the class tree adds ref/onToggle for laziness.
  const shared = {
    height,
    rowHeight: 28,
    width: '100%',
    idAccessor: (n: TreeRow) => n.eid,
    openByDefault: false,
    disableDrag: true,
    disableDrop: true,
    disableMultiSelection: true,
    disableDeselectOnClick: true,
    selection: selectedEid ?? undefined,
    onActivate: (n: NodeApi<TreeRow>) => setSelected(n.id),
    searchTerm: filter,
    searchMatch: (n: NodeApi<TreeRow>, term: string) => matchesTerm(n.data, term),
  }

  const TABS: [Tab, string][] = [
    ['classes', t('tree.tabClasses')],
    ['props', t('tree.tabProps')],
    ['prefixes', t('tree.tabPrefixes')],
  ]

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* mockup: pill tabs on top, recessed search box under them */}

      <div className="px-3 pt-2.5 pb-1.5">
        <div className="relative">
          <svg
            viewBox="0 0 24 24"
            width="13"
            height="13"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            aria-hidden="true"
            className="text-ink-3 pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2"
          >
            <circle cx="11" cy="11" r="7" />
            <path d="m21 21-4-4" />
          </svg>
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder={t('tree.searchPlaceholder')}
            className="bg-panel-2 border-line text-ink focus:border-primary rounded-ctl w-full border py-1.5 pr-2.5 pl-8 text-xs outline-none"
          />
        </div>
      </div>
      <div className="border-line flex gap-0.5 border-b px-3 py-1.5">
        {TABS.map(([value, label]) => (
          <button
            key={value}
            type="button"
            onClick={() => setTab(value)}
            className={cn(
              'rounded-ctl px-2.5 py-1 text-xs',
              tab === value
                ? 'bg-primary-soft text-primary font-semibold'
                : 'text-ink-2 cursor-pointer',
            )}
          >
            {label}
          </button>
        ))}
      </div>
      <div ref={ref} className="min-h-0 flex-1 overflow-hidden px-2 pb-2">
        {/* The class tree stays mounted (reveal-expandable) even while the
            property or prefix tab is showing. */}
        <div className={tab === 'classes' ? 'h-full' : 'hidden'}>
          <Tree ref={treeRef} data={classRows} onToggle={handleToggle} aria-label={t('tree.classTree')} {...shared}>
            {ClassRow}
          </Tree>
        </div>
        {tab === 'props' && (
          <Tree ref={propTreeRef} data={propRows} aria-label={t('tree.propList')} {...shared}>
            {ClassRow}
          </Tree>
        )}
        {tab === 'prefixes' && (
          <Table>
            <TableBody>
              {Object.entries(meta?.prefixes ?? {}).map(([prefix, iri]) => (
                <TableRow key={prefix}>
                  <TableCell className="font-mono text-xs">{prefix}</TableCell>
                  <TableCell className="text-ink-2 font-mono text-xs break-all whitespace-normal">
                    {iri}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>
    </div>
  )
}

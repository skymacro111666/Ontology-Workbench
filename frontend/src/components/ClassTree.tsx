import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Tree, type NodeApi, type NodeRendererProps, type TreeApi } from 'react-arborist'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/client'
import type { EntityIR, OntologyMeta, TreeNode } from '../api/types'
import { useContainerHeight } from '../hooks/useContainerHeight'
import { useBrowseStore } from '../stores/browseStore'
import { Input } from '@/components/ui/input'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
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

/** One row: chevron + mono curie + direct-subclass badge (spec §7.2). */
function ClassRow({ node, style }: NodeRendererProps<TreeRow>) {
  return (
    <div
      style={style}
      className={cn(
        'flex h-7 shrink-0 items-center gap-1.5 rounded-md pr-2 font-mono text-xs',
        node.isSelected ? 'bg-primary-soft text-primary' : 'text-ink-2 hover:bg-muted/60',
      )}
    >
      {node.isInternal ? (
        <button
          type="button"
          aria-label={node.isOpen ? '折叠' : '展开'}
          onClick={(e) => {
            e.stopPropagation()
            node.toggle()
          }}
          className="text-ink-3 flex h-4 w-4 shrink-0 cursor-pointer items-center justify-center"
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
        <span className="h-4 w-4 shrink-0" />
      )}
      <span className="truncate">{node.data.curie}</span>
      {node.data.childrenCount > 0 && (
        <span
          title="直接子类数"
          className="bg-primary text-primary-foreground ml-auto flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[10px] font-semibold"
        >
          {node.data.childrenCount}
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
      void loadChildren(id)
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

  return (
    <div className="flex h-full min-h-0 flex-col gap-2">
      <Input
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        placeholder="过滤已加载节点"
        className="h-8"
      />
      <Tabs value={tab} onValueChange={(v) => setTab(v as Tab)} className="flex min-h-0 flex-1 flex-col">
        <TabsList className="grid w-full grid-cols-3">
          <TabsTrigger value="classes">类</TabsTrigger>
          <TabsTrigger value="props">属性</TabsTrigger>
          <TabsTrigger value="prefixes">前缀</TabsTrigger>
        </TabsList>
        <div ref={ref} className="min-h-0 flex-1 overflow-hidden">
          {/* forceMount keeps the class tree mounted (and reveal-expandable)
              while the property or prefix tab is showing. */}
          <TabsContent value="classes" forceMount className="h-full data-[state=inactive]:hidden">
            <Tree ref={treeRef} data={classRows} onToggle={handleToggle} aria-label="类树" {...shared}>
              {ClassRow}
            </Tree>
          </TabsContent>
          <TabsContent value="props" className="h-full data-[state=inactive]:hidden">
            <Tree ref={propTreeRef} data={propRows} aria-label="属性列表" {...shared}>
              {ClassRow}
            </Tree>
          </TabsContent>
          <TabsContent value="prefixes" className="data-[state=inactive]:hidden overflow-y-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-20">前缀</TableHead>
                  <TableHead>IRI</TableHead>
                </TableRow>
              </TableHeader>
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
          </TabsContent>
        </div>
      </Tabs>
    </div>
  )
}

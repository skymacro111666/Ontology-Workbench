import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Tree } from 'antd'
import type { DataNode } from 'antd/es/tree'
import { useCallback, useEffect, useState } from 'react'
import type { Key } from 'react'
import { api } from '../api/client'
import type { EntityIR, TreeNode } from '../api/types'
import { useContainerHeight } from '../hooks/useContainerHeight'
import { useBrowseStore } from '../stores/browseStore'

type ChildMap = Record<string, TreeNode[]>

function toDataNode(n: TreeNode, childMap: ChildMap): DataNode {
  return {
    key: n.eid,
    title: n.curie,
    isLeaf: n.childrenCount === 0,
    children: (childMap[n.eid] ?? []).map((c) => toDataNode(c, childMap)),
  }
}

/** Lazy-loading class tree over GET /tree?parent=, one level per expand. */
export default function ClassTree({ oid }: { oid: string }) {
  const selectedEid = useBrowseStore((s) => s.selectedEid)
  const revealEid = useBrowseStore((s) => s.revealEid)
  const setSelected = useBrowseStore((s) => s.setSelected)
  const clearReveal = useBrowseStore((s) => s.clearReveal)
  const queryClient = useQueryClient()
  const { ref, height } = useContainerHeight<HTMLDivElement>()
  const [childMap, setChildMap] = useState<ChildMap>({})
  const [expandedKeys, setExpandedKeys] = useState<Key[]>([])

  const { data: roots } = useQuery({
    queryKey: ['tree', oid, 'roots'],
    queryFn: () => api.get<TreeNode[]>(`/api/ontologies/${oid}/tree`),
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

  const loadData = useCallback(
    ({ key }: { key: Key }) => loadChildren(String(key)),
    [loadChildren],
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
        setExpandedKeys(chain)
        setSelected(revealEid)
        clearReveal()
      }
    })()

    return () => {
      cancelled = true
    }
  }, [revealEid, oid, queryClient, loadChildren, setSelected, clearReveal])

  const treeData = (roots ?? []).map((n) => toDataNode(n, childMap))

  return (
    <div ref={ref} style={{ height: '100%', minHeight: 120, overflow: 'hidden' }}>
      <Tree
        blockNode
        virtual
        height={height}
        treeData={treeData}
        loadData={loadData}
        expandedKeys={expandedKeys}
        onExpand={(keys) => setExpandedKeys(keys)}
        selectedKeys={selectedEid ? [selectedEid] : []}
        onSelect={(keys) => {
          const key = keys[0]
          setSelected(key ? String(key) : null)
        }}
      />
    </div>
  )
}

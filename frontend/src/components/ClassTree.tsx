import { useQuery } from '@tanstack/react-query'
import { Tree } from 'antd'
import type { DataNode } from 'antd/es/tree'
import { useCallback, useState } from 'react'
import type { Key } from 'react'
import { api } from '../api/client'
import type { TreeNode } from '../api/types'
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
  const setSelected = useBrowseStore((s) => s.setSelected)
  const { ref, height } = useContainerHeight<HTMLDivElement>()
  const [childMap, setChildMap] = useState<ChildMap>({})

  const { data: roots } = useQuery({
    queryKey: ['tree', oid, 'roots'],
    queryFn: () => api.get<TreeNode[]>(`/api/ontologies/${oid}/tree`),
  })

  const loadData = useCallback(
    async (node: { key: Key }) => {
      const parent = encodeURIComponent(String(node.key))
      const kids = await api.get<TreeNode[]>(`/api/ontologies/${oid}/tree?parent=${parent}`)
      setChildMap((m) => ({ ...m, [String(node.key)]: kids }))
    },
    [oid],
  )

  const treeData = (roots ?? []).map((n) => toDataNode(n, childMap))

  return (
    <div ref={ref} style={{ height: '100%', minHeight: 120, overflow: 'hidden' }}>
      <Tree
        blockNode
        virtual
        height={height}
        treeData={treeData}
        loadData={loadData}
        selectedKeys={selectedEid ? [selectedEid] : []}
        onSelect={(keys) => {
          const key = keys[0]
          setSelected(key ? String(key) : null)
        }}
      />
    </div>
  )
}

import { useQuery } from '@tanstack/react-query'
import { Empty, Spin } from 'antd'
import { Link } from 'react-router'
import { api } from '../api/client'
import type { EntityIR, NodesEdges } from '../api/types'
import GraphView, { type GraphViewNode } from './GraphView'
import { useBrowseStore } from '../stores/browseStore'

/**
 * Local neighbor canvas around one entity (/neighbors data). The selected
 * entity carries its direct-child count as the node badge (the neighbors
 * payload has no counts of its own).
 */
export default function LocalGraph({
  oid,
  eid,
  height = '100%',
}: {
  oid: string
  eid: string | null
  height?: number | string
}) {
  const setSelected = useBrowseStore((s) => s.setSelected)
  const { data: nb } = useQuery({
    enabled: eid !== null,
    queryKey: ['neighbors', oid, eid],
    queryFn: () =>
      api.get<NodesEdges>(
        `/api/ontologies/${oid}/entities/${encodeURIComponent(eid as string)}/neighbors`,
      ),
    retry: false,
  })
  // Shares the ['entity'] cache with the detail pane and breadcrumb.
  const { data: ent } = useQuery({
    enabled: eid !== null,
    queryKey: ['entity', oid, eid],
    queryFn: () =>
      api.get<EntityIR>(`/api/ontologies/${oid}/entities/${encodeURIComponent(eid as string)}`),
    retry: false,
  })

  if (eid === null) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="先选择一个实体" />
  }
  if (!nb) {
    return (
      <div style={{ padding: 24, textAlign: 'center' }}>
        <Spin />
      </div>
    )
  }

  const nodes: GraphViewNode[] = nb.nodes.map((n) =>
    n.id === eid && ent ? { ...n, childCount: ent.stats.directChildren } : n,
  )

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, height }}>
      <div style={{ textAlign: 'right' }}>
        <Link to={`/graph/${oid}?focus=${encodeURIComponent(eid)}`}>在总览中查看</Link>
      </div>
      <div style={{ flex: 1, minHeight: 0 }}>
        <GraphView nodes={nodes} edges={nb.edges} onSelect={setSelected} />
      </div>
    </div>
  )
}

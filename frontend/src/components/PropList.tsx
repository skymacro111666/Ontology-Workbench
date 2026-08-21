import { useQuery } from '@tanstack/react-query'
import { Table } from 'antd'
import { api } from '../api/client'
import type { TreeNode } from '../api/types'
import { useBrowseStore } from '../stores/browseStore'

/** Property entities from the tree's __props__ sentinel; click selects. */
export default function PropList({ oid }: { oid: string }) {
  const setSelected = useBrowseStore((s) => s.setSelected)
  const { data } = useQuery({
    queryKey: ['tree', oid, '__props__'],
    queryFn: () => api.get<TreeNode[]>(`/api/ontologies/${oid}/tree?parent=__props__`),
  })

  return (
    <Table<TreeNode>
      size="small"
      rowKey="eid"
      pagination={false}
      dataSource={data ?? []}
      onRow={(record) => ({ onClick: () => setSelected(record.eid), style: { cursor: 'pointer' } })}
      columns={[
        { title: 'CURIE', dataIndex: 'curie', ellipsis: true },
        { title: '类型', dataIndex: 'type', width: 130 },
        {
          title: '标签',
          width: 120,
          ellipsis: true,
          render: (_, r) => r.label?.en ?? r.label?.zh ?? '',
        },
      ]}
    />
  )
}

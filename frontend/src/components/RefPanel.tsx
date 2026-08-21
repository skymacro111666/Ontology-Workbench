import { Empty, Table } from 'antd'
import type { ReferencedRef } from '../api/types'
import { useBrowseStore } from '../stores/browseStore'

/** Reverse references: who mentions this entity, and via which axiom. */
export default function RefPanel({ refs }: { refs: ReferencedRef[] }) {
  const setSelected = useBrowseStore((s) => s.setSelected)

  if (refs.length === 0) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无反向引用" />
  }
  return (
    <Table<ReferencedRef>
      size="small"
      rowKey="eid"
      pagination={false}
      dataSource={refs}
      title={() => '反向引用'}
      onRow={(record) => ({ onClick: () => setSelected(record.eid), style: { cursor: 'pointer' } })}
      columns={[
        { title: 'CURIE', dataIndex: 'curie' },
        { title: '关系', dataIndex: 'relation', width: 160 },
      ]}
    />
  )
}

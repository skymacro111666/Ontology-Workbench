import { useQuery } from '@tanstack/react-query'
import { Empty, Space, Spin, Table, Tabs, Tag, Typography } from 'antd'
import { api } from '../api/client'
import type { EntityIR, PropRef, Ref } from '../api/types'
import { useBrowseStore } from '../stores/browseStore'
import RefPanel from './RefPanel'

const MONO = { fontFamily: "'Fira Code', monospace" }

/** Clickable entity links (parents/children lists, back-refs navigate too). */
function RefLinks({ refs }: { refs: Ref[] }) {
  const setSelected = useBrowseStore((s) => s.setSelected)
  if (refs.length === 0) return <Typography.Text type="secondary">—</Typography.Text>
  return (
    <Space wrap size={4}>
      {refs.map((r) => (
        <a key={r.eid} style={MONO} onClick={() => setSelected(r.eid)}>
          {r.curie}
        </a>
      ))}
    </Space>
  )
}

function Overview({ ent }: { ent: EntityIR }) {
  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Space wrap>
        <Tag>{ent.type}</Tag>
        {Object.entries(ent.label).map(([lang, value]) => (
          <Tag key={lang}>
            {lang}: {value}
          </Tag>
        ))}
        {ent.deprecated && <Tag color="warning">deprecated</Tag>}
      </Space>

      {ent.comment && <Typography.Paragraph>{ent.comment}</Typography.Paragraph>}

      <div>
        <Typography.Text type="secondary">父类</Typography.Text>
        <div>
          <RefLinks refs={ent.parents} />
        </div>
      </div>
      <div>
        <Typography.Text type="secondary">子类</Typography.Text>
        <div>
          <RefLinks refs={ent.children} />
        </div>
      </div>

      {ent.properties.length > 0 && (
        <Table<PropRef>
          size="small"
          rowKey="eid"
          pagination={false}
          dataSource={ent.properties}
          columns={[
            { title: '属性', dataIndex: 'curie' },
            { title: '类型', dataIndex: 'ptype', width: 150 },
            { title: '标签', render: (_, r) => r.label?.en ?? r.label?.zh ?? '' },
          ]}
        />
      )}

      <Typography.Text type="secondary">
        直接子类 {ent.stats.directChildren} · 全部后代 {ent.stats.totalDescendants}
      </Typography.Text>
    </Space>
  )
}

/** Detail state of the selected entity: overview/TTL tabs + back-ref panel. */
export default function EntityDetail({ oid }: { oid: string }) {
  const selectedEid = useBrowseStore((s) => s.selectedEid)
  const { data: ent, isError } = useQuery({
    enabled: selectedEid !== null,
    queryKey: ['entity', oid, selectedEid],
    queryFn: () =>
      api.get<EntityIR>(`/api/ontologies/${oid}/entities/${encodeURIComponent(selectedEid as string)}`),
    retry: false,
  })
  const { data: raw } = useQuery({
    enabled: selectedEid !== null,
    queryKey: ['raw', oid, selectedEid],
    queryFn: () =>
      api.get<{ turtle: string; eid: string }>(
        `/api/ontologies/${oid}/raw/${encodeURIComponent(selectedEid as string)}`,
      ),
    retry: false,
  })

  if (selectedEid === null) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="选择左侧实体查看详情" />
  }
  if (isError) {
    return (
      <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="外部实体（未在本体中声明），无详情页" />
    )
  }
  if (!ent) {
    return (
      <div style={{ padding: 24, textAlign: 'center' }}>
        <Spin />
      </div>
    )
  }

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Typography.Title level={5} style={MONO} copyable>
        {ent.curie}
      </Typography.Title>
      <Tabs
        tabPlacement="start"
        items={[
          { key: 'overview', label: '概览', children: <Overview ent={ent} /> },
          {
            key: 'ttl',
            label: '原始TTL',
            children: (
              <pre style={{ ...MONO, fontSize: 12, overflowX: 'auto' }}>
                {raw?.turtle ?? '…'}
              </pre>
            ),
          },
        ]}
      />
      <RefPanel refs={ent.referencedBy} />
    </Space>
  )
}

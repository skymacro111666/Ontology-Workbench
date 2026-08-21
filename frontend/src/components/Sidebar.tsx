import { Tabs, Typography } from 'antd'
import type { OntologyMeta } from '../api/types'
import ClassTree from './ClassTree'
import PrefixTable from './PrefixTable'
import PropList from './PropList'

/** Left sidebar: stats header + the 类/属性/前缀 tri-tab (spec §7.2). */
export default function Sidebar({ oid, meta }: { oid: string; meta: OntologyMeta }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', padding: '12px 8px' }}>
      <Typography.Text type="secondary" style={{ fontSize: 12, padding: '0 8px 8px' }}>
        {meta.classCount} 类 · {meta.propertyCount} 属性
      </Typography.Text>
      <Tabs
        size="small"
        style={{ flex: 1, minHeight: 0 }}
        items={[
          { key: 'classes', label: '类', children: <ClassTree oid={oid} /> },
          { key: 'props', label: '属性', children: <PropList oid={oid} /> },
          { key: 'prefixes', label: '前缀', children: <PrefixTable prefixes={meta.prefixes} /> },
        ]}
      />
    </div>
  )
}

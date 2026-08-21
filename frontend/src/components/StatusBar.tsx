import { Space } from 'antd'
import type { OntologyMeta } from '../api/types'

/** One-line footer: file, counts, parse status (spec §7.2 status bar). */
export default function StatusBar({ meta }: { meta: OntologyMeta }) {
  return (
    <Space size={12} style={{ fontSize: 12 }} split={<span>·</span>}>
      <span>{meta.filename}</span>
      <span>
        {meta.classCount} 类 · {meta.propertyCount} 属性
      </span>
      <span>{meta.axiomCount} axioms</span>
      <span>解析 ok</span>
    </Space>
  )
}

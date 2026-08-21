import { Table } from 'antd'

interface PrefixRow {
  key: string
  iri: string
}

/** Prefix ↔ IRI mapping from the ontology metadata (no API call). */
export default function PrefixTable({ prefixes }: { prefixes: Record<string, string> }) {
  const rows: PrefixRow[] = Object.entries(prefixes).map(([prefix, iri]) => ({ key: prefix, iri }))

  return (
    <Table<PrefixRow>
      size="small"
      pagination={false}
      dataSource={rows}
      columns={[
        { title: '前缀', dataIndex: 'key', width: 100 },
        { title: 'IRI', dataIndex: 'iri', ellipsis: true },
      ]}
    />
  )
}

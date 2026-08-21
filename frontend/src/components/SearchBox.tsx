import { useQuery } from '@tanstack/react-query'
import { AutoComplete, Tag } from 'antd'
import { useState } from 'react'
import { api } from '../api/client'
import type { SearchHit } from '../api/types'
import { useDebounced } from '../hooks/useDebounced'
import { useBrowseStore } from '../stores/browseStore'

interface HitOption {
  value: string
  eid: string
  label: React.ReactNode
}

/** Header search: debounced /search; picking a hit reveals it in the tree. */
export default function SearchBox({ oid }: { oid: string }) {
  const [q, setQ] = useState('')
  const debounced = useDebounced(q, 150)
  const reveal = useBrowseStore((s) => s.reveal)

  const { data: hits } = useQuery({
    enabled: debounced.trim().length > 0,
    queryKey: ['search', oid, debounced],
    queryFn: () =>
      api.get<SearchHit[]>(`/api/ontologies/${oid}/search?q=${encodeURIComponent(debounced)}`),
  })

  const options: HitOption[] = (hits ?? []).map((h) => ({
    value: h.curie,
    eid: h.eid,
    label: (
      <span style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
        <span style={{ fontFamily: "'Fira Code', monospace" }}>{h.curie}</span>
        <Tag style={{ marginRight: 0 }}>{h.matchedField}</Tag>
      </span>
    ),
  }))

  return (
    <AutoComplete
      value={q}
      allowClear
      style={{ width: 260 }}
      placeholder="搜索类 / 属性…"
      options={options}
      onSearch={setQ}
      onSelect={(_value, option) => reveal((option as HitOption).eid)}
    />
  )
}

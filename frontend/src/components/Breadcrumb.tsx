import { useQuery } from '@tanstack/react-query'
import { useBrowseStore } from '../stores/browseStore'
import { api } from '../api/client'
import type { EntityIR, Ref } from '../api/types'

const MAX_DEPTH = 32

const SEP = <span style={{ opacity: 0.5, margin: '0 6px' }}>›</span>

function entityUrl(oid: string, eid: string): string {
  return `/api/ontologies/${oid}/entities/${encodeURIComponent(eid)}`
}

/**
 * One lineage level: renders its own ancestor chain first, then itself.
 * An external (undeclared) ancestor renders as plain text and ends the chain.
 * Each level's /entities call is a cached query, so revisits are instant.
 */
function Lineage({ oid, ancestor, depth }: { oid: string; ancestor: Ref; depth: number }) {
  const setSelected = useBrowseStore((s) => s.setSelected)
  const { data: ent, isError } = useQuery({
    queryKey: ['entity', oid, ancestor.eid],
    queryFn: () => api.get<EntityIR>(entityUrl(oid, ancestor.eid)),
    retry: false,
  })

  if (isError) {
    return <span style={{ opacity: 0.65 }}>{ancestor.curie}</span>
  }
  const parent =
    depth < MAX_DEPTH ? ent?.parents.find((p) => p.eid !== ancestor.eid) : undefined
  return (
    <>
      {ent && parent && (
        <>
          <Lineage oid={oid} ancestor={parent} depth={depth + 1} />
          {SEP}
        </>
      )}
      <a onClick={() => setSelected(ancestor.eid)}>{ent?.curie ?? ancestor.curie}</a>
    </>
  )
}

/** Breadcrumb class lineage: root › … › selected (spec §7.4 informational decor). */
export default function Breadcrumb({ oid }: { oid: string }) {
  const selectedEid = useBrowseStore((s) => s.selectedEid)
  const setSelected = useBrowseStore((s) => s.setSelected)
  const { data: ent } = useQuery({
    enabled: selectedEid !== null,
    queryKey: ['entity', oid, selectedEid],
    queryFn: () => api.get<EntityIR>(entityUrl(oid, selectedEid as string)),
    retry: false,
  })

  if (!selectedEid || !ent) return null
  const parent = ent.parents.find((p) => p.eid !== selectedEid)
  return (
    <div style={{ fontFamily: "'Fira Code', monospace", fontSize: 13 }}>
      {parent && (
        <>
          <Lineage oid={oid} ancestor={parent} depth={0} />
          {SEP}
        </>
      )}
      <a onClick={() => setSelected(selectedEid)}>
        <strong>{ent.curie}</strong>
      </a>
    </div>
  )
}

/**
 * API payload types. The envelope is snake_case (request_id, spec §6);
 * every data payload is camelCase (golden contract + plan: the API layer
 * serializes snake_case models through a camel alias generator).
 */

/** Locale-tagged labels, e.g. { en: 'Pizza', zh: '披萨' }. */
export interface LocalizedLabels {
  [lang: string]: string
}

/** The five-field envelope every API response uses (success and error alike). */
export interface Envelope<T> {
  code: string
  message: string
  data: T | null
  hint: string | null
  request_id: string
}

/** Minimal reference to another entity. */
export interface Ref {
  eid: string
  curie: string
  label?: LocalizedLabels
}

/** Reference carrying the property type. */
export interface PropRef extends Ref {
  ptype: string
}

/** An axiom's far end, flagged for the UI: declared entities have a
 *  detail page to navigate to; external IRIs render as plain text. */
export interface CounterpartRef extends Ref {
  declared: boolean
}

/** Reverse reference carrying the axiom relating the two entities.
 *  counterpart is the axiom's far end (range class for a domain ref,
 *  domain class for a range ref); null when the axiom leaves it untyped. */
export interface ReferencedRef extends Ref {
  relation: string
  counterpart?: CounterpartRef | null
}

/** Aggregate counts shown on entity pages. */
export interface EntityStats {
  directChildren: number
  totalDescendants: number
}

/** Entity detail page payload (GET /entities/{eid}). */
export interface EntityIR {
  eid: string
  curie: string
  type: 'Class' | 'ObjectProperty' | 'DatatypeProperty' | 'Property' | string
  label: LocalizedLabels
  comment: string | null
  deprecated: boolean
  parents: Ref[]
  children: Ref[]
  properties: PropRef[]
  referencedBy: ReferencedRef[]
  axioms: { turtle: string }[]
  stats: EntityStats
  kind?: 'entity'
}

/** Instance detail page payload (GET /entities/{eid}). */
export interface InstanceIR {
  eid: string
  curie: string
  kind: 'instance'
  label: LocalizedLabels
  comment: string | null
  classes: Ref[]
  objectAssertions: { property: PropRef; object: Ref }[]
  dataAssertions: { property: PropRef; value: string; datatype: string }[]
}

/** Schema property reference used in property tables. */
export interface SchemaProp {
  eid: string
  curie: string
  label: LocalizedLabels
  ptype: string
  inherited: boolean
  via: string | null
  target: { kind: 'class' | 'datatype'; curie: string; eid: string | null; declared: boolean | null } | null
}

/** Assertion edge payload for graph queries. */
export interface AssertionEdgePayload {
  edges: { source: string; target: string; label: string }[]
  truncated: boolean
  total: number
}

/** One node of the lazily-loaded class tree (GET /tree). */
export interface TreeNode {
  eid: string
  curie: string
  label: LocalizedLabels
  type: string
  childrenCount: number
  /** Direct named individuals of a class (sidebar badge). */
  instanceCount?: number
}

/** One search result with the field that matched (GET /search). */
export interface SearchHit {
  eid: string
  curie: string
  label: LocalizedLabels
  type: string
  matchedField: string
}

/** Graph node as returned by /neighbors and /overview. */
export interface GNode {
  id: string
  curie: string
  label: LocalizedLabels
  kind: 'self' | 'class' | 'property' | 'instance' | string
  /** Direct named individuals of a class (overview badge data). */
  instanceCount?: number
  /** Property subtype (ObjectProperty / DatatypeProperty) — canvas filter key. */
  ptype?: string
}

/** Graph edge; kind encodes the relation (subClassOf / property / datatype / instance). */
export interface GEdge {
  source: string
  target: string
  kind: 'subClassOf' | 'property' | 'datatype' | 'instance' | 'assertion' | string
  /** Assertion edges carry the property's local name for their label. */
  label?: string
}

/** Nodes/edges payload; truncated marks the >5000-node degradation to 3 levels. */
export interface NodesEdges {
  nodes: GNode[]
  edges: GEdge[]
  truncated?: boolean
  totalCount?: number
}

/** List item from GET /api/ontologies. */
export interface OntologySummary {
  id: string
  title: string
  filename: string
  format: string
  classCount: number
  propertyCount: number
  axiomCount: number
  instanceCount: number
  fileSizeBytes: number
  createdAt: string
}

/** Upload response: full metadata including prefixes (POST /api/ontologies). */
export interface OntologyMeta extends OntologySummary {
  fileHash: string
  prefixes: Record<string, string>
  /** Parse wall-clock duration in ms (absent for records imported before this field). */
  parseMs?: number | null
}

/** Docs-site export result (POST /api/ontologies/{id}/export/site). */
export interface ExportSiteResult {
  outputDir: string
  pageCount: number
}

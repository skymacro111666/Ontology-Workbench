/** Display name without namespace noise: curie prefix stripped, full-IRI
 *  fallback (unbound namespace) reduced to its last #/ segment. Search and
 *  tooltips keep the full curie for matching and disambiguation. */
export function localName(curie: string): string {
  if (/^https?:\/\//.test(curie)) return curie.split(/[#/]/).filter(Boolean).pop() ?? curie
  const i = curie.indexOf(':')
  return i === -1 ? curie : curie.slice(i + 1)
}

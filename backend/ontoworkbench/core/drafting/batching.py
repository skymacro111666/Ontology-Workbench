"""FK-kinship batching (spec §5.3 step 3, user-ratified 2026-10-08).

Union-find over FK edges keeps kin in one batch; a component larger than the
limit is split by repeatedly carving off connected chunks starting from its
lowest-degree table (fewest cut FKs first). Cross-seam FK properties are
regenerated deterministically by the merger, so a split costs batch-local
context, never correctness.
"""

from __future__ import annotations

from ontoworkbench.core.drafting.models import TableSpec


def _components(tables: list[TableSpec]) -> list[list[str]]:
    """Union-find over FK edges → connected components (names)."""
    parent: dict[str, str] = {t.name: t.name for t in tables}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for t in tables:
        for fk in t.foreign_keys:
            if fk.ref_table in parent:
                ra, rb = find(t.name), find(fk.ref_table)
                if ra != rb:
                    parent[rb] = ra
    groups: dict[str, list[str]] = {}
    for t in tables:
        groups.setdefault(find(t.name), []).append(t.name)
    return list(groups.values())


def _split_component(names: list[str], adj: dict[str, set[str]], limit: int) -> list[list[str]]:
    """Split one oversized component into connected chunks of ≤ limit tables.

    Greedy BFS from the lowest-intra-degree table collects up to `limit`
    tables per chunk; the remainder recurses. Ties break by name for
    determinism.
    """
    remaining = set(names)
    chunks: list[list[str]] = []
    while remaining:
        start = min(remaining, key=lambda n: (-len(adj[n] & remaining), n))
        # lowest degree first = fewest cut edges; but a start with zero
        # remaining edges would orphan singletons — prefer the LOWEST
        # nonzero degree that exists, else any single node.
        chunk: list[str] = [start]
        remaining.discard(start)
        frontier = sorted(adj[start] & remaining)
        while frontier and len(chunk) < limit:
            nxt = frontier.pop(0)
            if nxt in remaining:
                chunk.append(nxt)
                remaining.discard(nxt)
                frontier.extend(sorted(adj[nxt] & remaining))
        chunks.append(chunk)
    return chunks


def plan_batches(tables: list[TableSpec], batch_tables: int = 35) -> list[list[TableSpec]]:
    """Group tables into LLM batches of ≤ batch_tables, kin together."""
    if batch_tables < 1:
        raise ValueError("batch_tables must be >= 1")
    by_name = {t.name: t for t in tables}
    adj: dict[str, set[str]] = {t.name: set() for t in tables}
    for t in tables:
        for fk in t.foreign_keys:
            if fk.ref_table in by_name and fk.ref_table != t.name:
                adj[t.name].add(fk.ref_table)
                adj[fk.ref_table].add(t.name)

    batches: list[list[TableSpec]] = []
    loose: list[TableSpec] = []
    for comp in _components(tables):
        if len(comp) > batch_tables:
            for chunk in _split_component(comp, adj, batch_tables):
                batches.append([by_name[n] for n in chunk])
        elif len(comp) == 1:
            loose.append(by_name[comp[0]])
        else:
            batches.append([by_name[n] for n in comp])
    # FK-free singletons pack greedily into ≤limit bins.
    for i in range(0, len(loose), batch_tables):
        batches.append(loose[i : i + batch_tables])
    return batches

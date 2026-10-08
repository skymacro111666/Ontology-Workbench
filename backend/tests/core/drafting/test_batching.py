"""batching: FK-kinship union-find with fewest-cut oversized split."""

from ontoworkbench.core.drafting.batching import plan_batches
from ontoworkbench.core.drafting.models import ColumnSpec, ForeignKeySpec, TableSpec


def _t(name: str, *fks: tuple[str, str]) -> TableSpec:
    """A table with synthetic FK edges (c{i} -> ref.id)."""
    return TableSpec(
        name=name,
        comment=None,
        columns=[
            ColumnSpec(name="id", type_="INTEGER", nullable=False, primary_key=True, unique=False)
        ],
        foreign_keys=[
            ForeignKeySpec(column=f"c{i}", ref_table=ref, ref_column="id")
            for i, (ref, _) in enumerate(fks)
        ],
    )


def test_small_family_stays_together() -> None:
    """FK-linked tables land in one batch when they fit."""
    tabs = [_t("customer"), _t("orders", ("customer", "id")), _t("items", ("orders", "id"))]
    batches = plan_batches(tabs, batch_tables=35)
    assert [len(b) for b in batches] == [3]


def test_independent_tables_pack_by_limit() -> None:
    """FK-free tables pack greedily up to the limit."""
    tabs = [_t(f"t{i:02d}") for i in range(70)]
    batches = plan_batches(tabs, batch_tables=35)
    assert all(len(b) <= 35 for b in batches)
    assert sum(len(b) for b in batches) == 70


def test_oversized_component_splits_under_limit() -> None:
    """A 26-table FK chain with limit 10: every batch ≤10, full coverage."""
    names = [chr(ord("a") + i) for i in range(26)]
    tabs = [_t(n, (names[i - 1], "id")) for i, n in enumerate(names)]
    batches = plan_batches(tabs, batch_tables=10)
    assert all(len(b) for b in batches if len(b) <= 10)
    assert all(len(b) <= 10 for b in batches)
    flat = sorted(t.name for b in batches for t in b)
    assert flat == sorted(names)


def test_batches_are_deterministic_and_keep_kin() -> None:
    """Same input → same output; the FK pair lands in one batch."""
    tabs = [_t("b"), _t("a"), _t("c", ("a", "id"))]
    first = plan_batches(list(tabs), batch_tables=35)
    second = plan_batches(list(tabs), batch_tables=35)
    assert [[t.name for t in b] for b in first] == [[t.name for t in b] for b in second]
    joined = ["".join(sorted(t.name for t in b)) for b in first]
    assert "ac" in joined  # kin together


def test_cross_referencing_pair_not_split() -> None:
    """Mutual FKs (a<->b) stay together even at a tight limit that fits both."""
    tabs = [_t("a", ("b", "id")), _t("b", ("a", "id")), _t("z")]
    batches = plan_batches(tabs, batch_tables=2)
    joined = ["".join(sorted(t.name for t in b)) for b in batches]
    assert "ab" in joined

"""Grouping rules for the workflow's release notes (tools/release_notes.py)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[2] / "tools"
_spec = importlib.util.spec_from_file_location("release_notes", _TOOLS / "release_notes.py")
release_notes = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(release_notes)


def _md(*entries: tuple[str, str]) -> str:
    return release_notes.group_markdown(list(entries))


def test_sections_in_order_with_b_rule_grouping() -> None:
    """feat→Added, fix→Fixed, perf/refactor/docs→Changed, test/chore/ci→Maintenance."""
    md = _md(
        ("aaa0001", "feat(back): one"),
        ("aaa0002", "fix(front): two"),
        ("aaa0003", "perf(front): three"),
        ("aaa0004", "refactor(back): four"),
        ("aaa0005", "docs: five"),
        ("aaa0006", "test(back): six"),
        ("aaa0007", "chore(front): seven"),
        ("aaa0008", "ci: eight"),
    )
    assert (
        md.index("## Added")
        < md.index("## Fixed")
        < md.index("## Changed")
        < md.index("## Maintenance")
    )
    assert "- **back**: one (aaa0001)" in md
    assert "- **front**: two (aaa0002)" in md
    assert "- **front**: three (aaa0003)" in md
    assert "- **back**: four (aaa0004)" in md
    assert "- five (aaa0005)" in md
    assert "- **back**: six (aaa0006)" in md


def test_empty_sections_are_omitted() -> None:
    """Only fixes → a lone Fixed section, no empty headers."""
    md = _md(("bbb0001", "fix(back): only"))
    assert md == "## Fixed\n\n- **back**: only (bbb0001)\n"


def test_unknown_and_unconventional_subjects_land_in_maintenance() -> None:
    """Unrecognized types and bare subjects cannot be classified → Maintenance."""
    md = _md(
        ("ccc0001", "whatever(front): odd type"),
        ("ccc0002", "no prefix at all"),
    )
    assert "## Added" not in md and "## Fixed" not in md and "## Changed" not in md
    assert "- **front**: odd type (ccc0001)" in md
    assert "- no prefix at all (ccc0002)" in md


def test_scopeless_conventional_commits_skip_the_prefix() -> None:
    """`feat: x` (no scope) renders without a bold prefix."""
    md = _md(("ddd0001", "feat: bare feature"))
    assert "- bare feature (ddd0001)" in md

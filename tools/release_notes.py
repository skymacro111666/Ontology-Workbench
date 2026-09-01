#!/usr/bin/env python3
"""Grouped release notes from conventional commits (for .github/workflows/release.yml).

Reads a git log range and prints English markdown grouped Added / Fixed /
Changed / Maintenance — feat→Added, fix→Fixed, perf/refactor/docs→Changed,
everything else (test/chore/ci/build/style/unrecognized)→Maintenance. Entries
keep the commit's scope as a bold prefix and end with the short hash; empty
sections are omitted.

Usage:
    python tools/release_notes.py [--from PREV_TAG] --to TAG
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

SECTION_ORDER = ("Added", "Fixed", "Changed", "Maintenance")
SECTION_FOR_TYPE = {
    "feat": "Added",
    "fix": "Fixed",
    "perf": "Changed",
    "refactor": "Changed",
    "docs": "Changed",
}
SUBJECT_RE = re.compile(r"^([a-z]+)(?:\(([^)]+)\))?:\s*(.+)$")


def group_markdown(entries: list[tuple[str, str]]) -> str:
    """(short_hash, subject) pairs → grouped markdown, ready for gh release."""
    groups: dict[str, list[str]] = {name: [] for name in SECTION_ORDER}
    for short_hash, subject in entries:
        match = SUBJECT_RE.match(subject)
        if match:
            typ, scope, text = match.groups()
            section = SECTION_FOR_TYPE.get(typ, "Maintenance")
        else:
            scope, text, section = None, subject, "Maintenance"
        entry = (
            f"- **{scope}**: {text} ({short_hash})"
            if scope
            else f"- {text} ({short_hash})"
        )
        groups[section].append(entry)
    blocks = [
        f"## {name}\n\n" + "\n".join(groups[name])
        for name in SECTION_ORDER
        if groups[name]
    ]
    return "\n\n".join(blocks) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--from",
        dest="from_ref",
        default="",
        help="previous tag (omit for full history)",
    )
    parser.add_argument("--to", dest="to_ref", required=True, help="release tag")
    args = parser.parse_args(argv)
    rev_range = f"{args.from_ref}..{args.to_ref}" if args.from_ref else args.to_ref
    log = subprocess.run(
        ["git", "log", "--pretty=format:%h|%s", rev_range],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    entries = [tuple(line.split("|", 1)) for line in log.splitlines() if "|" in line]
    sys.stdout.write(group_markdown(entries))  # type: ignore[arg-type]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

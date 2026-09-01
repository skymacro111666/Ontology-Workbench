"""0005: ontologies.source (sample vs upload provenance).

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-01 19:00:00.000000

No backfill: rows imported from bundled samples before this column cannot
be told apart from same-named user uploads, so every existing row stays
"upload" — re-import a sample to pick up the badge.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("ontologies", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("source", sa.String(16), server_default="upload", nullable=False)
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("ontologies", schema=None) as batch_op:
        batch_op.drop_column("source")

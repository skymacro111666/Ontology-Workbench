"""0013: ontology_r2rmls gains schema_json + previous_ttl (R2RML P2).

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-13 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("ontology_r2rmls", sa.Column("schema_json", sa.Text(), nullable=True))
    op.add_column("ontology_r2rmls", sa.Column("previous_ttl", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("ontology_r2rmls", "previous_ttl")
    op.drop_column("ontology_r2rmls", "schema_json")

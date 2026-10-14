"""0014: ontology_r2rmls gains db_connection_id (R2RML P3 drift check).

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-14 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("ontology_r2rmls", schema=None) as batch_op:
        batch_op.add_column(sa.Column("db_connection_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_ontology_r2rmls_db_connection_id",
            "db_connections",
            ["db_connection_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("ontology_r2rmls", schema=None) as batch_op:
        batch_op.drop_constraint("fk_ontology_r2rmls_db_connection_id", type_="foreignkey")
        batch_op.drop_column("db_connection_id")

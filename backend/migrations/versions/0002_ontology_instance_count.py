"""0002: ontologies.instance_count (footer 实例数).

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-25 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("ontologies", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("instance_count", sa.Integer(), server_default="0", nullable=False)
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("ontologies", schema=None) as batch_op:
        batch_op.drop_column("instance_count")

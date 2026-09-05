"""0006: ontologies.revision (Y 编辑轴的乐观锁代数).

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-05 20:00:00.000000

存量行 revision=0;第一次增量编辑后开始递增。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("ontologies", schema=None) as batch_op:
        batch_op.add_column(sa.Column("revision", sa.Integer(), server_default="0", nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("ontologies", schema=None) as batch_op:
        batch_op.drop_column("revision")

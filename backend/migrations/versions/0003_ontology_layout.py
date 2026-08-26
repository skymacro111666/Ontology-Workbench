"""0003: ontology_layouts — canvas node position persistence (A2).

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-26 23:20:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

StatsJSON = JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "ontology_layouts",
        sa.Column("ontology_id", sa.Uuid(), nullable=False),
        sa.Column("positions", StatsJSON, nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("ontology_id", name=op.f("pk_ontology_layouts")),
        sa.ForeignKeyConstraint(
            ["ontology_id"],
            ["ontologies.id"],
            name=op.f("fk_ontology_layouts_ontology_id_ontologies"),
            ondelete="CASCADE",
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("ontology_layouts")

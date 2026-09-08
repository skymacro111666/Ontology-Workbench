"""0007: validation_shapes — per-ontology SHACL shapes source (M1).

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-08 10:00:00.000000

spec 2026-09-08 §2.4: one editable shapes graph per ontology; the row is
dropped with its ontology (CASCADE).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "validation_shapes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ontology_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_validation_shapes")),
        sa.ForeignKeyConstraint(
            ["ontology_id"],
            ["ontologies.id"],
            name=op.f("fk_validation_shapes_ontology_id_ontologies"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("ontology_id", name=op.f("uq_validation_shapes_ontology_id")),
    )
    op.create_index(
        op.f("ix_validation_shapes_ontology_id"),
        "validation_shapes",
        ["ontology_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_validation_shapes_ontology_id"), table_name="validation_shapes")
    op.drop_table("validation_shapes")

"""0009: mutation_events — Registry Phase 1 operation journal (spec §8).

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-06 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "mutation_events",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("ontology_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("origin", sa.String(length=8), server_default="manual", nullable=False),
        sa.Column("source", sa.String(length=8), server_default="web", nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mutation_events")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_mutation_events_user_id_users"),
            ondelete="CASCADE",
        ),
    )
    # Covers list_before's (user_id, ontology_id, id DESC) scan; ontology_id
    # carries no FK by design — rows must survive their ontology (spec §8.1).
    op.create_index(
        "ix_mutation_events_user_id_ontology_id",
        "mutation_events",
        ["user_id", "ontology_id", "id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_mutation_events_user_id_ontology_id", table_name="mutation_events")
    op.drop_table("mutation_events")

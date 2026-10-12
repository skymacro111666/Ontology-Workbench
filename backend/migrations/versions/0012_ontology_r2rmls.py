"""0012: ontology_r2rmls — per-ontology R2RML mapping companion (R2RML P1).

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-12 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "ontology_r2rmls",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ontology_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(length=256), nullable=False),
        sa.Column("storage_path", sa.String(length=512), nullable=False),
        sa.Column("namespace", sa.String(length=512), nullable=False),
        sa.Column("base_revision", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("schema_hash", sa.String(length=64), nullable=False),
        sa.Column("skipped_tables", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ontology_r2rmls")),
        sa.ForeignKeyConstraint(
            ["ontology_id"],
            ["ontologies.id"],
            name=op.f("fk_ontology_r2rmls_ontology_id_ontologies"),
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        op.f("ix_ontology_r2rmls_ontology_id"), "ontology_r2rmls", ["ontology_id"], unique=True
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_ontology_r2rmls_ontology_id"), table_name="ontology_r2rmls")
    op.drop_table("ontology_r2rmls")

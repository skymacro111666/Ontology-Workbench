"""0004: lint_rules — per-ontology lint config storage (B3).

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-31 05:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "lint_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ontology_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=128), nullable=True),
        sa.Column("severity", sa.String(length=16), nullable=True),
        sa.Column("sparql", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lint_rules")),
        sa.ForeignKeyConstraint(
            ["ontology_id"],
            ["ontologies.id"],
            name=op.f("fk_lint_rules_ontology_id_ontologies"),
            ondelete="CASCADE",
        ),
    )
    op.create_index(op.f("ix_lint_rules_ontology_id"), "lint_rules", ["ontology_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_lint_rules_ontology_id"), table_name="lint_rules")
    op.drop_table("lint_rules")

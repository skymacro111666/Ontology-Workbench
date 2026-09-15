"""0008: agent_tokens — account machine credentials (MCP v1, spec D12).

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-15 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "agent_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("token_prefix", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_tokens")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_agent_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("user_id", "label", name="uq_agent_tokens_user_id_label"),
        sa.UniqueConstraint("token_hash", name="uq_agent_tokens_token_hash"),
    )
    op.create_index(op.f("ix_agent_tokens_user_id"), "agent_tokens", ["user_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_agent_tokens_user_id"), table_name="agent_tokens")
    op.drop_table("agent_tokens")

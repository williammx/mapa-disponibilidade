"""Hashed, organization/project-bounded integration API keys.

Revision ID: 20261005_0003
Revises: 20260813_0002
"""
from alembic import op
import sqlalchemy as sa

revision = "20261005_0003"
down_revision = "20260813_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("integration_api_keys"):
        return
    op.create_table(
        "integration_api_keys",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("scopes_json", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for field in ("organization_id", "project_id", "created_by_user_id", "expires_at"):
        op.create_index("ix_integration_api_keys_" + field, "integration_api_keys", [field])
    op.create_index("ix_integration_api_keys_token_hash", "integration_api_keys", ["token_hash"], unique=True)


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("integration_api_keys"):
        op.drop_table("integration_api_keys")

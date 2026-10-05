"""Durable integration webhook subscriptions and leased outbox deliveries."""

import sqlalchemy as sa

from alembic import op

revision = "20261005_0006"
down_revision = "20261005_0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "integration_webhooks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "api_key_id",
            sa.String(36),
            sa.ForeignKey("integration_api_keys.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "owner_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("event_types_json", sa.Text(), nullable=False),
        sa.Column("secret_nonce", sa.String(64), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("event_cursor", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for name in ("organization_id", "project_id"):
        op.create_index(
            "ix_integration_webhooks_" + name, "integration_webhooks", [name]
        )
    op.create_table(
        "integration_webhook_deliveries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "webhook_id",
            sa.String(36),
            sa.ForeignKey("integration_webhooks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "event_id",
            sa.Integer(),
            sa.ForeignKey("integration_events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
        sa.Column("lease_until", sa.DateTime(), nullable=True),
        sa.Column("lease_token", sa.String(64), nullable=True),
        sa.Column("last_http_status", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.String(160), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("webhook_id", "event_id", name="uq_webhook_event"),
    )
    for name in ("webhook_id", "event_id", "status", "next_attempt_at"):
        op.create_index(
            "ix_integration_webhook_deliveries_" + name,
            "integration_webhook_deliveries",
            [name],
        )


def downgrade():
    op.drop_table("integration_webhook_deliveries")
    op.drop_table("integration_webhooks")

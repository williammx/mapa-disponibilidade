"""Durable integration upload reservations and per-key request budgets."""
from alembic import op
import sqlalchemy as sa

revision = "20261005_0004"
down_revision = "20261005_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("integration_api_keys")}
    with op.batch_alter_table("integration_api_keys") as batch:
        if "rate_window_start" not in columns:
            batch.add_column(sa.Column("rate_window_start", sa.DateTime(), nullable=True))
        if "rate_request_count" not in columns:
            batch.add_column(sa.Column("rate_request_count", sa.Integer(), nullable=False, server_default="0"))
    if not sa.inspect(op.get_bind()).has_table("integration_upload_requests"):
        op.create_table(
            "integration_upload_requests",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("api_key_id", sa.String(36), sa.ForeignKey("integration_api_keys.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("idempotency_key_hash", sa.String(64), nullable=False),
            sa.Column("request_hash", sa.String(64), nullable=False),
            sa.Column("job_id", sa.String(36), sa.ForeignKey("processing_jobs.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("api_key_id", "project_id", "idempotency_key_hash", name="uq_integration_upload_request"),
        )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("integration_upload_requests"):
        op.drop_table("integration_upload_requests")
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("integration_api_keys")}
    with op.batch_alter_table("integration_api_keys") as batch:
        if "rate_request_count" in columns:
            batch.drop_column("rate_request_count")
        if "rate_window_start" in columns:
            batch.drop_column("rate_window_start")

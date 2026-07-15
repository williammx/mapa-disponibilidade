"""platform rebuild core tables

Revision ID: 20260715_0001
Revises:
Create Date: 2026-07-15
"""

from alembic import op
import sqlalchemy as sa

revision = "20260715_0001"
down_revision = None
branch_labels = None
depends_on = None


def has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return False
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if not has_column(table_name, column.name):
        op.add_column(table_name, column)


def upgrade() -> None:
    if not has_table("organizations"):
        op.create_table(
            "organizations",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("slug", sa.String(length=80), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_organizations_slug", "organizations", ["slug"], unique=True)

    if not has_table("users"):
        op.create_table(
            "users",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("email", sa.String(length=320), nullable=False),
            sa.Column("password_hash", sa.String(length=255), nullable=False),
            sa.Column("platform_role", sa.String(length=32), nullable=False, server_default="none"),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("last_login_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_users_email", "users", ["email"], unique=True)

    if not has_table("memberships"):
        op.create_table(
            "memberships",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("organization_id", sa.String(length=36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("role", sa.String(length=32), nullable=False, server_default="client_member"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("user_id", "organization_id", name="uq_membership_user_org"),
        )
        op.create_index("ix_memberships_user_id", "memberships", ["user_id"])
        op.create_index("ix_memberships_organization_id", "memberships", ["organization_id"])

    if not has_table("projects"):
        op.create_table(
            "projects",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("organization_id", sa.String(length=36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(length=180), nullable=False),
            sa.Column("slug", sa.String(length=100), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
            sa.Column("access_mode", sa.String(length=32), nullable=False, server_default="private"),
            sa.Column("client_can_edit", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_projects_slug", "projects", ["slug"], unique=True)
        op.create_index("ix_projects_organization_id", "projects", ["organization_id"])
    else:
        add_column_if_missing("projects", sa.Column("client_can_edit", sa.Boolean(), nullable=False, server_default=sa.text("false")))

    if not has_table("project_versions"):
        op.create_table(
            "project_versions",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("project_id", sa.String(length=36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("source_pdf_path", sa.String(length=500), nullable=True),
            sa.Column("map_html_path", sa.String(length=500), nullable=False),
            sa.Column("lot_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("quality", sa.String(length=32), nullable=False, server_default="balanced"),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
            sa.Column("validation_summary", sa.Text(), nullable=True),
            sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_project_versions_project_id", "project_versions", ["project_id"])
    else:
        add_column_if_missing("project_versions", sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"))
        add_column_if_missing("project_versions", sa.Column("validation_summary", sa.Text(), nullable=True))

    if not has_table("file_assets"):
        op.create_table(
            "file_assets",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("organization_id", sa.String(length=36), sa.ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True),
            sa.Column("project_id", sa.String(length=36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=True),
            sa.Column("project_version_id", sa.String(length=36), sa.ForeignKey("project_versions.id", ondelete="CASCADE"), nullable=True),
            sa.Column("kind", sa.String(length=40), nullable=False),
            sa.Column("original_name", sa.String(length=260), nullable=True),
            sa.Column("content_type", sa.String(length=120), nullable=True),
            sa.Column("storage_key", sa.String(length=700), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_file_assets_organization_id", "file_assets", ["organization_id"])
        op.create_index("ix_file_assets_project_id", "file_assets", ["project_id"])
        op.create_index("ix_file_assets_project_version_id", "file_assets", ["project_version_id"])
        op.create_index("ix_file_assets_kind", "file_assets", ["kind"])
        op.create_index("ix_file_assets_storage_key", "file_assets", ["storage_key"], unique=True)
        op.create_index("ix_file_assets_checksum_sha256", "file_assets", ["checksum_sha256"])

    if not has_table("processing_jobs"):
        op.create_table(
            "processing_jobs",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("organization_id", sa.String(length=36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", sa.String(length=36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("requested_by_user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("source_file_asset_id", sa.String(length=36), sa.ForeignKey("file_assets.id", ondelete="SET NULL"), nullable=True),
            sa.Column("project_version_id", sa.String(length=36), sa.ForeignKey("project_versions.id", ondelete="SET NULL"), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
            sa.Column("quality", sa.String(length=32), nullable=False, server_default="balanced"),
            sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("current_step", sa.String(length=160), nullable=True),
            sa.Column("logs", sa.Text(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("can_retry", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_processing_jobs_organization_id", "processing_jobs", ["organization_id"])
        op.create_index("ix_processing_jobs_project_id", "processing_jobs", ["project_id"])
        op.create_index("ix_processing_jobs_requested_by_user_id", "processing_jobs", ["requested_by_user_id"])
        op.create_index("ix_processing_jobs_status", "processing_jobs", ["status"])
        op.create_index("ix_processing_jobs_created_at", "processing_jobs", ["created_at"])

    if not has_table("lots"):
        op.create_table(
            "lots",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("project_id", sa.String(length=36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_version_id", sa.String(length=36), sa.ForeignKey("project_versions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("external_id", sa.String(length=120), nullable=False),
            sa.Column("name", sa.String(length=160), nullable=True),
            sa.Column("block", sa.String(length=120), nullable=True),
            sa.Column("area_m2", sa.Float(), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="available"),
            sa.Column("color", sa.String(length=24), nullable=True),
            sa.Column("geometry_json", sa.Text(), nullable=False),
            sa.Column("properties_json", sa.Text(), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("project_version_id", "external_id", name="uq_lot_version_external"),
        )
        op.create_index("ix_lots_project_id", "lots", ["project_id"])
        op.create_index("ix_lots_project_version_id", "lots", ["project_version_id"])
        op.create_index("ix_lots_name", "lots", ["name"])
        op.create_index("ix_lots_block", "lots", ["block"])
        op.create_index("ix_lots_status", "lots", ["status"])

    if not has_table("share_links"):
        op.create_table(
            "share_links",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("project_id", sa.String(length=36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("token", sa.String(length=96), nullable=True),
            sa.Column("token_hash", sa.String(length=64), nullable=True),
            sa.Column("password_hash", sa.String(length=255), nullable=True),
            sa.Column("access_mode", sa.String(length=32), nullable=False, server_default="token"),
            sa.Column("allow_edit", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("last_used_at", sa.DateTime(), nullable=True),
            sa.Column("access_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_share_links_project_id", "share_links", ["project_id"])
        op.create_index("ix_share_links_token", "share_links", ["token"], unique=True)
        op.create_index("ix_share_links_token_hash", "share_links", ["token_hash"], unique=True)
    else:
        add_column_if_missing("share_links", sa.Column("access_mode", sa.String(length=32), nullable=False, server_default="token"))
        add_column_if_missing("share_links", sa.Column("allow_edit", sa.Boolean(), nullable=False, server_default=sa.text("false")))
        add_column_if_missing("share_links", sa.Column("last_used_at", sa.DateTime(), nullable=True))
        add_column_if_missing("share_links", sa.Column("access_count", sa.Integer(), nullable=False, server_default="0"))

    if not has_table("edit_proposals"):
        op.create_table(
            "edit_proposals",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("project_id", sa.String(length=36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("base_project_version_id", sa.String(length=36), sa.ForeignKey("project_versions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("proposed_by_user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("share_link_id", sa.String(length=36), sa.ForeignKey("share_links.id", ondelete="SET NULL"), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("title", sa.String(length=180), nullable=False),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("changes_json", sa.Text(), nullable=False),
            sa.Column("review_notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("decided_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_edit_proposals_project_id", "edit_proposals", ["project_id"])
        op.create_index("ix_edit_proposals_base_project_version_id", "edit_proposals", ["base_project_version_id"])
        op.create_index("ix_edit_proposals_proposed_by_user_id", "edit_proposals", ["proposed_by_user_id"])
        op.create_index("ix_edit_proposals_share_link_id", "edit_proposals", ["share_link_id"])
        op.create_index("ix_edit_proposals_status", "edit_proposals", ["status"])
        op.create_index("ix_edit_proposals_created_at", "edit_proposals", ["created_at"])


def downgrade() -> None:
    for table in ["edit_proposals", "lots", "processing_jobs", "file_assets"]:
        if has_table(table):
            op.drop_table(table)

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.utcnow()


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    platform_role: Mapped[str] = mapped_column(String(32), default="none", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "organization_id", name="uq_membership_user_org"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), default="client_member", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    access_mode: Mapped[str] = mapped_column(String(32), default="private", nullable=False)
    client_can_edit: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class ProjectVersion(Base):
    __tablename__ = "project_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    source_pdf_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    map_html_path: Mapped[str] = mapped_column(String(500), nullable=False)
    lot_count: Mapped[int] = mapped_column(nullable=False, default=0)
    quality: Mapped[str] = mapped_column(String(32), nullable=False, default="balanced")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    validation_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class FileAsset(Base):
    __tablename__ = "file_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    project_version_id: Mapped[str | None] = mapped_column(ForeignKey("project_versions.id", ondelete="CASCADE"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    original_name: Mapped[str | None] = mapped_column(String(260), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    storage_key: Mapped[str] = mapped_column(String(700), nullable=False, unique=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    requested_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    source_file_asset_id: Mapped[str | None] = mapped_column(ForeignKey("file_assets.id", ondelete="SET NULL"), nullable=True)
    project_version_id: Mapped[str | None] = mapped_column(ForeignKey("project_versions.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", index=True)
    quality: Mapped[str] = mapped_column(String(32), nullable=False, default="balanced")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_step: Mapped[str | None] = mapped_column(String(160), nullable=True)
    logs: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    can_retry: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Lot(Base):
    __tablename__ = "lots"
    __table_args__ = (UniqueConstraint("project_version_id", "external_id", name="uq_lot_version_external"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    project_version_id: Mapped[str] = mapped_column(ForeignKey("project_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    block: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    area_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="available", index=True)
    color: Mapped[str | None] = mapped_column(String(24), nullable=True)
    geometry_json: Mapped[str] = mapped_column(Text, nullable=False)
    properties_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class ShareLink(Base):
    __tablename__ = "share_links"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    token: Mapped[str | None] = mapped_column(String(96), nullable=True, unique=True, index=True)
    token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    access_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="token")
    allow_edit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    access_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class EditProposal(Base):
    __tablename__ = "edit_proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    base_project_version_id: Mapped[str] = mapped_column(ForeignKey("project_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    proposed_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    share_link_id: Mapped[str | None] = mapped_column(ForeignKey("share_links.id", ondelete="SET NULL"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    changes_json: Mapped[str] = mapped_column(Text, nullable=False)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)

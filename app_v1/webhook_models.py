"""Webhook tables; import explicitly before metadata creation/migrations."""

import secrets
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from database import Base
from models import new_id, utcnow


class WebhookSubscription(Base):
    __tablename__ = "integration_webhooks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    api_key_id: Mapped[str | None] = mapped_column(
        ForeignKey("integration_api_keys.id", ondelete="SET NULL"), nullable=True
    )
    owner_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    url: Mapped[str] = mapped_column(String(2048))
    event_types_json: Mapped[str] = mapped_column(Text)
    secret_nonce: Mapped[str] = mapped_column(
        String(64), default=lambda: secrets.token_hex(32)
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    event_cursor: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WebhookDelivery(Base):
    __tablename__ = "integration_webhook_deliveries"
    __table_args__ = (
        UniqueConstraint("webhook_id", "event_id", name="uq_webhook_event"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    webhook_id: Mapped[str] = mapped_column(
        ForeignKey("integration_webhooks.id", ondelete="CASCADE"), index=True
    )
    event_id: Mapped[int] = mapped_column(
        ForeignKey("integration_events.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, index=True
    )
    lease_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

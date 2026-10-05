"""Organization-scoped outgoing webhook subscription services and routers."""
# ruff: noqa: B008 -- FastAPI dependency factories are intentionally defaults.

import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from auth import require_platform_admin
from database import get_db
from models import IntegrationApiKey, Project, User

from .integrations import authorized_project, require_api_key
from .serialization import dt
from .webhook_models import WebhookSubscription

router = APIRouter(prefix="/api/integrations/v1", tags=["webhooks"])
management_router = APIRouter(prefix="/api/v1", tags=["integration webhook management"])
EVENT_TYPES = frozenset({"unit.availability.changed"})


def master_key():
    """Persistent private key. Atomic publication prevents partial concurrent reads."""
    configured = os.getenv("WEBHOOK_MASTER_KEY")
    if configured:
        try:
            value = bytes.fromhex(configured)
        except ValueError:
            raise RuntimeError("Invalid webhook master key configuration.") from None
        if len(value) != 32:
            raise RuntimeError("Invalid webhook master key configuration.")
        return value
    path = Path(
        os.getenv("WEBHOOK_MASTER_KEY_FILE", "/data/private/webhook-master.key")
    )
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not path.exists():
        temp = path.with_name(path.name + "." + secrets.token_hex(16))
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as file:
                file.write(secrets.token_bytes(32))
                file.flush()
                os.fsync(file.fileno())
            try:
                os.link(temp, path)
            except FileExistsError:
                pass
        finally:
            temp.unlink(missing_ok=True)
    if path.is_symlink() or (os.name != "nt" and path.stat().st_mode & 0o077):
        raise RuntimeError("Webhook master key file must be private.")
    key = path.read_bytes()
    if len(key) != 32:
        raise RuntimeError("Invalid webhook master key file.")
    return key


def subscription_secret(subscription):
    return hmac.new(
        master_key(),
        ("webhook:v1:" + subscription.id + ":" + subscription.secret_nonce).encode(),
        hashlib.sha256,
    ).hexdigest()


def validate_url(url):
    try:
        parts = urlsplit(url)
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or "#" in url
            or parts.port not in (None, 443)
        ):
            raise ValueError()
        if any(ord(c) <= 32 or ord(c) == 127 for c in url) or "\\" in url:
            raise ValueError()
        parts.hostname.encode("idna")
        import ipaddress

        try:
            address = ipaddress.ip_address(parts.hostname)
        except ValueError:
            address = None
        if address and (
            not address.is_global
            or address.is_private
            or address.is_reserved
            or address.is_multicast
            or getattr(address, "ipv4_mapped", None)
            or getattr(address, "scope_id", None)
        ):
            raise ValueError()
    except (ValueError, UnicodeError):
        raise HTTPException(
            422,
            "Webhook URL must be HTTPS on port 443 without credentials or fragments.",
        ) from None
    return parts


class WebhookCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=2048)
    event_types: list[str] = Field(min_length=1, max_length=20)


def webhook_metadata(row):
    return {
        "id": row.id,
        "project_id": row.project_id,
        "url": row.url,
        "event_types": json.loads(row.event_types_json),
        "active": row.active,
        "created_at": dt(row.created_at),
    }


def create_subscription(db, project, payload, response, key=None, owner=None):
    validate_url(payload.url)
    if not set(payload.event_types).issubset(EVENT_TYPES):
        raise HTTPException(422, "Unsupported event type.")
    row = WebhookSubscription(
        organization_id=project.organization_id,
        project_id=project.id,
        api_key_id=key.id if key else None,
        owner_user_id=owner.id if owner else None,
        url=payload.url,
        event_types_json=json.dumps(sorted(set(payload.event_types))),
    )
    db.add(row)
    db.flush()
    secret = subscription_secret(row)
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return {"webhook": webhook_metadata(row), "secret": secret}


@router.post("/projects/{project_id}/webhooks", status_code=201)
def create_webhook(
    project_id: str,
    payload: WebhookCreate,
    response: Response,
    key: IntegrationApiKey = Depends(require_api_key("webhooks:write")),
    db: Session = Depends(get_db),
):
    return create_subscription(
        db, authorized_project(db, key, project_id), payload, response, key=key
    )


@router.get("/projects/{project_id}/webhooks")
def list_webhooks(
    project_id: str,
    key: IntegrationApiKey = Depends(require_api_key("webhooks:write")),
    db: Session = Depends(get_db),
):
    authorized_project(db, key, project_id)
    return {
        "webhooks": [
            webhook_metadata(row)
            for row in db.query(WebhookSubscription)
            .filter_by(project_id=project_id)
            .order_by(WebhookSubscription.created_at, WebhookSubscription.id)
        ]
    }


def admin_project(db, project_id):
    from models import Organization

    project = db.get(Project, project_id)
    org = db.get(Organization, project.organization_id) if project else None
    if not project or not org or not org.active:
        raise HTTPException(404, "Project not found.")
    return project


def authorized_webhook(db, webhook_id, key=None):
    row = db.get(WebhookSubscription, webhook_id)
    if not row:
        raise HTTPException(404, "Webhook not found.")
    if key:
        authorized_project(db, key, row.project_id)
    else:
        admin_project(db, row.project_id)
    return row


def delivery_metadata(row):
    return {
        "id": row.id,
        "event_id": row.event_id,
        "status": row.status,
        "attempts": row.attempts,
        "next_attempt_at": dt(row.next_attempt_at),
        "last_http_status": row.last_http_status,
        "last_error": row.last_error,
    }


def delivery_list(db, row, limit, offset):
    from .webhook_models import WebhookDelivery

    query = db.query(WebhookDelivery).filter_by(webhook_id=row.id)
    total = query.count()
    rows = (
        query.order_by(WebhookDelivery.created_at, WebhookDelivery.id)
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "deliveries": [delivery_metadata(item) for item in rows],
        "total": total,
        "next_offset": offset + len(rows) if offset + len(rows) < total else None,
    }


def disable_webhook(db, row):
    row.active = False
    db.commit()
    return Response(status_code=204)


@management_router.post("/projects/{project_id}/integration-webhooks", status_code=201)
def admin_create(
    project_id: str,
    payload: WebhookCreate,
    response: Response,
    user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    return create_subscription(
        db, admin_project(db, project_id), payload, response, owner=user
    )


@management_router.get("/projects/{project_id}/integration-webhooks")
def admin_list(
    project_id: str,
    user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    admin_project(db, project_id)
    return {
        "webhooks": [
            webhook_metadata(row)
            for row in db.query(WebhookSubscription)
            .filter_by(project_id=project_id)
            .order_by(WebhookSubscription.created_at, WebhookSubscription.id)
        ]
    }


@management_router.delete("/integration-webhooks/{webhook_id}", status_code=204)
def admin_delete(
    webhook_id: str,
    user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    return disable_webhook(db, authorized_webhook(db, webhook_id))


@router.delete("/webhooks/{webhook_id}", status_code=204)
def delete_webhook(
    webhook_id: str,
    key: IntegrationApiKey = Depends(require_api_key("webhooks:write")),
    db: Session = Depends(get_db),
):
    return disable_webhook(db, authorized_webhook(db, webhook_id, key))


@management_router.get("/integration-webhooks/{webhook_id}/deliveries")
def admin_deliveries(
    webhook_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    return delivery_list(db, authorized_webhook(db, webhook_id), limit, offset)


@router.get("/webhooks/{webhook_id}/deliveries")
def deliveries(
    webhook_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    key: IntegrationApiKey = Depends(require_api_key("events:read")),
    db: Session = Depends(get_db),
):
    return delivery_list(db, authorized_webhook(db, webhook_id, key), limit, offset)


def retry_delivery(db, row, delivery_id):
    from models import utcnow

    from .webhook_dispatch import owner_valid
    from .webhook_models import WebhookDelivery

    if not row.active or not owner_valid(db, row):
        raise HTTPException(409, "Subscription or owner is inactive.")
    delivery = (
        db.query(WebhookDelivery).filter_by(id=delivery_id, webhook_id=row.id).first()
    )
    if not delivery:
        raise HTTPException(404, "Delivery not found.")
    changed = (
        db.query(WebhookDelivery)
        .filter_by(id=delivery.id, webhook_id=row.id, status="failed")
        .update(
            {
                "status": "pending",
                "attempts": 0,
                "next_attempt_at": utcnow(),
                "last_error": None,
                "last_http_status": None,
                "lease_token": None,
                "lease_until": None,
            },
            synchronize_session=False,
        )
    )
    if not changed:
        raise HTTPException(409, "Only failed deliveries can be retried.")
    db.commit()
    db.refresh(delivery)
    return {"delivery": delivery_metadata(delivery)}


@router.post("/webhooks/{webhook_id}/deliveries/{delivery_id}/retry")
def machine_retry(
    webhook_id: str,
    delivery_id: str,
    key: IntegrationApiKey = Depends(require_api_key("webhooks:write")),
    db: Session = Depends(get_db),
):
    return retry_delivery(db, authorized_webhook(db, webhook_id, key), delivery_id)


@management_router.post(
    "/integration-webhooks/{webhook_id}/deliveries/{delivery_id}/retry"
)
def admin_retry(
    webhook_id: str,
    delivery_id: str,
    user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    return retry_delivery(db, authorized_webhook(db, webhook_id), delivery_id)

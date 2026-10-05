"""Durable at-least-once dispatcher. Run: python -m app_v1.webhook_dispatch."""

import hashlib
import hmac
import http.client
import ipaddress
import json
import queue
import secrets
import socket
import ssl
import threading
import time
from datetime import timedelta

from sqlalchemy import or_

from database import SessionLocal
from models import (
    IntegrationApiKey,
    IntegrationEvent,
    Organization,
    Project,
    User,
    utcnow,
)

from .webhook_models import WebhookDelivery, WebhookSubscription
from .webhooks import subscription_secret, validate_url

MAX_ATTEMPTS = 8
LEASE_SECONDS = 60


def owner_valid(db, subscription):
    org = db.get(Organization, subscription.organization_id)
    project = db.get(Project, subscription.project_id)
    if not org or not org.active or not project or project.organization_id != org.id:
        return False
    if subscription.api_key_id:
        key = db.get(IntegrationApiKey, subscription.api_key_id)
        if (
            not key
            or key.revoked_at
            or key.expires_at <= utcnow()
            or key.organization_id != org.id
            or (key.project_id and key.project_id != project.id)
            or "webhooks:write" not in json.loads(key.scopes_json)
        ):
            return False
        user = db.get(User, key.created_by_user_id)
    else:
        user = (
            db.get(User, subscription.owner_user_id)
            if subscription.owner_user_id
            else None
        )
    return bool(user and user.active and user.platform_role == "platform_admin")


def materialize(db, batch_size=200):
    """Serialize each subscription, anti-join ALL retained events, not id > cursor.

    PostgreSQL sequences allocate before commit: a high committed id is NOT a
    safe watermark. event_cursor is informational; the unique outbox pair is
    authoritative. Historical events are backfilled intentionally, including
    late commits, in bounded batches. Never prune events independently of outbox.
    """
    count = 0
    ids = [
        item[0]
        for item in db.query(WebhookSubscription.id).filter_by(active=True).all()
    ]
    db.commit()
    for ident in ids:
        # UPDATE acquires a write/row lock even on SQLite; don't read before lock.
        changed = (
            db.query(WebhookSubscription)
            .filter_by(id=ident, active=True)
            .update(
                {"event_cursor": WebhookSubscription.event_cursor},
                synchronize_session=False,
            )
        )
        if not changed:
            db.commit()
            continue
        sub = db.get(WebhookSubscription, ident, populate_existing=True)
        if not owner_valid(db, sub):
            sub.active = False
            db.commit()
            continue
        absent = (
            ~db.query(WebhookDelivery.id)
            .filter(
                WebhookDelivery.webhook_id == ident,
                WebhookDelivery.event_id == IntegrationEvent.id,
            )
            .exists()
        )
        rows = (
            db.query(IntegrationEvent)
            .filter(
                IntegrationEvent.project_id == sub.project_id,
                IntegrationEvent.organization_id == sub.organization_id,
                IntegrationEvent.event_type.in_(json.loads(sub.event_types_json)),
                absent,
            )
            .order_by(IntegrationEvent.id)
            .limit(batch_size)
            .all()
        )
        for event in rows:
            db.add(WebhookDelivery(webhook_id=ident, event_id=event.id))
            sub.event_cursor = max(sub.event_cursor, event.id)
        db.commit()
        count += len(rows)
    return count


def claim(db, now=None):
    now = now or utcnow()
    eligible = or_(
        WebhookDelivery.status == "pending",
        (WebhookDelivery.status == "sending") & (WebhookDelivery.lease_until <= now),
    )
    # A crashed last attempt must become terminal, not stay sending forever.
    db.query(WebhookDelivery).filter(
        eligible, WebhookDelivery.attempts >= MAX_ATTEMPTS
    ).update(
        {
            "status": "failed",
            "lease_token": None,
            "lease_until": None,
            "last_error": "Attempt budget exhausted.",
        },
        synchronize_session=False,
    )
    candidates = (
        db.query(WebhookDelivery.id)
        .filter(
            eligible,
            WebhookDelivery.next_attempt_at <= now,
            WebhookDelivery.attempts < MAX_ATTEMPTS,
        )
        .order_by(WebhookDelivery.next_attempt_at, WebhookDelivery.id)
        .limit(100)
        .all()
    )
    for (ident,) in candidates:
        token = secrets.token_hex(32)
        changed = (
            db.query(WebhookDelivery)
            .filter(
                WebhookDelivery.id == ident,
                eligible,
                WebhookDelivery.next_attempt_at <= now,
                WebhookDelivery.attempts < MAX_ATTEMPTS,
            )
            .update(
                {
                    "status": "sending",
                    "attempts": WebhookDelivery.attempts + 1,
                    "lease_token": token,
                    "lease_until": now + timedelta(seconds=LEASE_SECONDS),
                },
                synchronize_session=False,
            )
        )
        if changed:
            db.commit()
            return db.get(WebhookDelivery, ident, populate_existing=True)
    db.commit()
    return None


def dispatch_one(db, transport=None, now=None):
    now = now or utcnow()
    delivery = claim(db, now)
    if not delivery:
        return False
    ident, token, attempts = delivery.id, delivery.lease_token, delivery.attempts
    sub = db.get(WebhookSubscription, delivery.webhook_id, populate_existing=True)
    event = db.get(IntegrationEvent, delivery.event_id)
    code = None
    error = None
    if (
        not sub
        or not sub.active
        or not owner_valid(db, sub)
        or not event
        or event.project_id != sub.project_id
        or event.organization_id != sub.organization_id
    ):
        status = "cancelled"
        error = "Subscription or owner is inactive."
        if sub:
            sub.active = False
        db.commit()
    else:
        try:
            body = json.dumps(
                {
                    "id": event.id,
                    "type": event.event_type,
                    "organization_id": event.organization_id,
                    "project_id": event.project_id,
                    "created_at": event.created_at.isoformat() + "Z",
                    "data": json.loads(event.payload_json),
                },
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
            timestamp = str(int(time.time()))
            signature = hmac.new(
                subscription_secret(sub).encode(),
                timestamp.encode() + b"." + body,
                hashlib.sha256,
            ).hexdigest()
            headers = {
                "Content-Type": "application/json",
                "X-NexoLote-Timestamp": timestamp,
                "X-NexoLote-Signature": "v1=" + signature,
                "X-NexoLote-Delivery-Id": ident,
                "X-NexoLote-Event-Id": str(event.id),
            }
            url = sub.url
            db.commit()  # Never hold a database transaction across network I/O.
            code = (transport or safe_send)(url, body, headers)
            status = (
                "succeeded"
                if 200 <= code < 300
                else ("failed" if attempts >= MAX_ATTEMPTS else "pending")
            )
            if status != "succeeded":
                error = "Receiver returned a non-success status."
        except Exception:  # noqa: BLE001 -- Persist failure without leaking exception details.
            # Exception text may include URL credentials, paths, or sensitive data.
            status = "failed" if attempts >= MAX_ATTEMPTS else "pending"
            error = "Webhook delivery failed."
    db.query(WebhookDelivery).filter_by(
        id=ident, lease_token=token, status="sending"
    ).update(
        {
            "status": status,
            "last_http_status": code,
            "last_error": error,
            "next_attempt_at": now
            + timedelta(seconds=min(3600, 5 * 2 ** (attempts - 1))),
            "lease_token": None,
            "lease_until": None,
        },
        synchronize_session=False,
    )
    db.commit()
    return True


_DNS_SLOTS = threading.BoundedSemaphore(8)


def resolve_public(host):
    if not _DNS_SLOTS.acquire(blocking=False):
        raise ValueError("Resolver capacity exhausted.")
    result = queue.Queue(maxsize=1)

    def resolve():
        try:
            result.put(
                socket.getaddrinfo(
                    host, 443, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM
                )
            )
        except OSError:
            result.put(None)
        finally:
            _DNS_SLOTS.release()

    threading.Thread(target=resolve, daemon=True).start()
    try:
        records = result.get(timeout=3)
    except queue.Empty:
        raise ValueError("DNS timed out.") from None
    if not records:
        raise ValueError("DNS resolution failed.")
    for family, kind, protocol, canonname, address in records:
        ip = ipaddress.ip_address(address[0])
        if (
            not ip.is_global
            or ip.is_private
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_unspecified
            or getattr(ip, "ipv4_mapped", None)
            or getattr(ip, "scope_id", None)
        ):
            raise ValueError("Webhook destination is not public.")
    return records


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, record):
        super().__init__(host, 443, timeout=5, context=ssl.create_default_context())
        self.record = record

    def connect(self):
        family, kind, protocol, _, address = self.record
        raw = socket.socket(family, kind, protocol)
        raw.settimeout(self.timeout)
        self.sock = raw
        try:
            raw.connect(address)  # Numeric approved address, no second DNS lookup.
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def safe_send(url, body, headers):
    parts = validate_url(url)
    host = parts.hostname.encode("idna").decode("ascii")
    records = resolve_public(host)  # Validate every A/AAAA answer on every attempt.
    connection = PinnedHTTPSConnection(host, records[0])

    def abort():
        if connection.sock:
            try:
                connection.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        connection.close()

    timer = threading.Timer(12, abort)
    timer.daemon = True
    timer.start()
    try:
        target = parts.path or "/"
        if parts.query:
            target += "?" + parts.query
        connection.request("POST", target, body=body, headers=headers)
        response = connection.getresponse()
        # No redirects, and zero response body bytes are read or stored.
        return response.status
    finally:
        timer.cancel()
        connection.close()


def main():
    import os
    import signal

    stop = threading.Event()

    def shutdown(signum, frame):
        stop.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    maximum = int(os.getenv("WEBHOOK_DISPATCH_MAX_ITERATIONS", "0"))
    interval = float(os.getenv("WEBHOOK_DISPATCH_POLL_SECONDS", "2"))
    if maximum < 0 or not 0.05 <= interval <= 60:
        raise ValueError("Invalid dispatcher configuration.")
    iterations = 0
    failures = 0
    while not stop.is_set() and (not maximum or iterations < maximum):
        try:
            with SessionLocal() as db:
                materialize(db)
                for _ in range(100):
                    if stop.is_set() or not dispatch_one(db):
                        break
        except Exception:  # noqa: BLE001 -- Keep service alive, without logging secrets.
            failures += 1
            print("webhook dispatcher iteration failed", flush=True)
        iterations += 1
        if not maximum or iterations < maximum:
            stop.wait(interval)
    print("webhook dispatcher iterations=" + str(iterations), flush=True)
    return 1 if maximum and failures else 0


if __name__ == "__main__":
    import sys

    sys.exit(main())

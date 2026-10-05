"""Isolated webhook contract tests; network fixtures never contact receivers."""

import importlib.util
import json
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from auth import hash_token
from database import Base, get_db
from models import IntegrationApiKey, Organization, Project, User, utcnow

PREFIX = "/api/integrations/v1"


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    from app_v1.webhooks import router

    monkeypatch.delenv("WEBHOOK_MASTER_KEY", raising=False)
    monkeypatch.setenv(
        "WEBHOOK_MASTER_KEY_FILE", str(tmp_path / "private" / "master.key")
    )
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    admin = User(
        name="Admin",
        email="hooks@example.com",
        password_hash="unused",
        platform_role="platform_admin",
    )
    org = Organization(name="One", slug="hooks-one")
    other = Organization(name="Two", slug="hooks-two")
    db.add_all([admin, org, other])
    db.flush()
    project = Project(organization_id=org.id, name="Map", slug="hooks-map")
    foreign = Project(organization_id=other.id, name="Other", slug="hooks-other")
    db.add_all([project, foreign])
    db.flush()
    key = IntegrationApiKey(
        name="Hooks",
        organization_id=org.id,
        project_id=project.id,
        created_by_user_id=admin.id,
        token_hash=hash_token("nlk_test"),
        scopes_json=json.dumps(["webhooks:write", "events:read"]),
        expires_at=utcnow() + timedelta(days=1),
    )
    db.add(key)
    db.commit()
    from app_v1.webhooks import management_router

    app = FastAPI()
    app.include_router(router)
    app.include_router(management_router)
    from auth import require_platform_admin

    app.dependency_overrides[require_platform_admin] = lambda: admin
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        yield client, db, key, project, foreign
    db.close()
    engine.dispose()


def test_subscription_secret_only_at_creation(ctx):
    client, db, _key, project, _foreign = ctx
    headers = {"Authorization": "Bearer nlk_test"}
    path = PREFIX + "/projects/" + project.id + "/webhooks"
    result = client.post(
        path,
        headers=headers,
        json={
            "url": "https://receiver.example/hook",
            "event_types": ["unit.availability.changed"],
        },
    )
    assert result.status_code == 201, result.text
    created = result.json()
    assert len(created["secret"]) >= 32
    assert result.headers["cache-control"] == "no-store"
    assert "secret" not in created["webhook"]
    listed = client.get(path, headers=headers)
    assert listed.status_code == 200
    assert listed.json()["webhooks"] == [created["webhook"]]
    assert created["secret"] not in listed.text
    from app_v1.webhook_models import WebhookSubscription

    stored = db.get(WebhookSubscription, created["webhook"]["id"])
    assert created["secret"] not in str(stored.__dict__)


def test_admin_subscription_delivery_management(ctx):
    client, _db, _key, project, _foreign = ctx
    path = "/api/v1/projects/" + project.id + "/integration-webhooks"
    result = client.post(
        path,
        json={
            "url": "https://receiver.example/hook",
            "event_types": ["unit.availability.changed"],
        },
    )
    assert result.status_code == 201, result.text
    row = result.json()["webhook"]
    assert client.get(path).json()["webhooks"] == [row]
    deliveries = "/api/v1/integration-webhooks/" + row["id"] + "/deliveries"
    assert client.get(deliveries).json() == {
        "deliveries": [],
        "total": 0,
        "next_offset": None,
    }
    assert client.delete("/api/v1/integration-webhooks/" + row["id"]).status_code == 204
    assert client.get(path).json()["webhooks"][0]["active"] is False


def test_bearer_tenant_scope_enforced(ctx):
    client, db, key, project, foreign = ctx
    headers = {"Authorization": "Bearer nlk_test"}
    path = PREFIX + "/projects/" + project.id + "/webhooks"
    assert client.get(path).status_code == 401
    assert (
        client.get(
            PREFIX + "/projects/" + foreign.id + "/webhooks", headers=headers
        ).status_code
        == 404
    )
    key.scopes_json = json.dumps(["events:read"])
    db.commit()
    assert client.get(path, headers=headers).status_code == 403


def subscribe(ctx):
    client, _db, _key, project, _foreign = ctx
    result = client.post(
        PREFIX + "/projects/" + project.id + "/webhooks",
        headers={"Authorization": "Bearer nlk_test"},
        json={
            "url": "https://receiver.example/hook",
            "event_types": ["unit.availability.changed"],
        },
    )
    assert result.status_code == 201, result.text
    return result.json()


def event(ctx, **kw):
    from models import IntegrationEvent

    _, db, _, project, _ = ctx
    row = IntegrationEvent(
        organization_id=project.organization_id,
        project_id=project.id,
        event_type="unit.availability.changed",
        payload_json=json.dumps(
            {"source": {"system": "external", "origin": "crm"}, "unit_id": "u1"}
        ),
        **kw,
    )
    db.add(row)
    db.commit()
    return row


def test_durable_delivery_exact_signature_origin_and_dedupe(ctx):
    import hashlib
    import hmac

    from app_v1 import webhook_dispatch as dispatch
    from app_v1.webhook_models import WebhookDelivery

    created = subscribe(ctx)
    row = event(ctx)
    _, db, *_ = ctx
    assert dispatch.materialize(db) == 1
    assert dispatch.materialize(db) == 0
    sent = []

    def transport(url, body, headers):
        sent.append((url, body, headers))
        return 204

    assert dispatch.dispatch_one(db, transport=transport)
    delivery = db.query(WebhookDelivery).one()
    assert delivery.status == "succeeded" and delivery.attempts == 1
    _url, body, headers = sent[0]
    timestamp = headers["X-NexoLote-Timestamp"]
    expected = hmac.new(
        created["secret"].encode(), timestamp.encode() + b"." + body, hashlib.sha256
    ).hexdigest()
    assert headers["X-NexoLote-Signature"] == "v1=" + expected
    assert headers["X-NexoLote-Delivery-Id"] == delivery.id
    assert headers["X-NexoLote-Event-Id"] == str(row.id)
    assert json.loads(body)["data"]["source"] == {"system": "external", "origin": "crm"}
    assert "Authorization" not in headers


def test_retry_backoff_terminal_and_manual_retry(ctx):
    from app_v1 import webhook_dispatch as dispatch
    from app_v1.webhook_models import WebhookDelivery

    created = subscribe(ctx)
    event(ctx)
    client, db, *_ = ctx
    dispatch.materialize(db)
    now = utcnow()
    for attempt in range(1, dispatch.MAX_ATTEMPTS + 1):
        assert dispatch.dispatch_one(db, transport=lambda *a: 503, now=now)
        row = db.query(WebhookDelivery).populate_existing().one()
        assert row.attempts == attempt
        assert row.next_attempt_at == now + timedelta(
            seconds=min(3600, 5 * 2 ** (attempt - 1))
        )
        now = row.next_attempt_at
    assert row.status == "failed"
    assert not dispatch.dispatch_one(db, transport=lambda *a: 200, now=now)
    path = (
        PREFIX
        + "/webhooks/"
        + created["webhook"]["id"]
        + "/deliveries/"
        + row.id
        + "/retry"
    )
    result = client.post(path, headers={"Authorization": "Bearer nlk_test"})
    assert result.status_code == 200, result.text
    assert result.json()["delivery"]["status"] == "pending"
    assert result.json()["delivery"]["attempts"] == 0


def test_lease_expiry_prevents_duplicate_and_stale_ack(ctx):
    from app_v1 import webhook_dispatch as dispatch
    from app_v1.webhook_models import WebhookDelivery

    subscribe(ctx)
    event(ctx)
    _, db, *_ = ctx
    dispatch.materialize(db)
    now = utcnow()
    first = dispatch.claim(db, now)
    token = first.lease_token
    assert dispatch.claim(db, now) is None
    second = dispatch.claim(db, now + timedelta(seconds=dispatch.LEASE_SECONDS + 1))
    assert (
        second.id == first.id and second.lease_token != token and second.attempts == 2
    )
    assert (
        db.query(WebhookDelivery)
        .filter_by(id=first.id, lease_token=token)
        .update({"status": "succeeded"})
        == 0
    )


@pytest.mark.parametrize("reason", ["revoked", "deleted", "owner_inactive", "scope"])
def test_invalid_machine_owner_never_sends(ctx, reason):
    from app_v1 import webhook_dispatch as dispatch
    from app_v1.webhook_models import WebhookDelivery, WebhookSubscription

    subscribe(ctx)
    event(ctx)
    _, db, key, *_ = ctx
    dispatch.materialize(db)
    if reason == "revoked":
        key.revoked_at = utcnow()
    elif reason == "deleted":
        db.delete(key)
    elif reason == "owner_inactive":
        db.get(User, key.created_by_user_id).active = False
    else:
        key.scopes_json = "[]"
    db.commit()
    sent = []
    assert dispatch.dispatch_one(db, transport=lambda *a: sent.append(a))
    assert sent == []
    assert db.query(WebhookDelivery).populate_existing().one().status == "cancelled"
    assert not db.query(WebhookSubscription).populate_existing().one().active


def test_late_lower_event_id_not_skipped(ctx):
    from app_v1 import webhook_dispatch as dispatch
    from app_v1.webhook_models import WebhookDelivery

    subscribe(ctx)
    event(ctx, id=50)
    _, db, *_ = ctx
    assert dispatch.materialize(db) == 1
    event(ctx, id=20)
    assert dispatch.materialize(db) == 1
    assert sorted(r.event_id for r in db.query(WebhookDelivery)) == [20, 50]


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://user:pass@example.com",
        "https://example.com:22",
        "https://example.com/#secret",
        "https://example.com/#",
    ],
)
def test_unsafe_url_rejected_at_creation(ctx, url):
    client, _db, _key, project, _ = ctx
    response = client.post(
        PREFIX + "/projects/" + project.id + "/webhooks",
        headers={"Authorization": "Bearer nlk_test"},
        json={"url": url, "event_types": ["unit.availability.changed"]},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "records",
    [
        ["127.0.0.1"],
        ["10.0.0.1"],
        ["169.254.169.254"],
        ["::1"],
        ["224.0.0.1"],
        ["93.184.216.34", "192.168.1.1"],
    ],
)
def test_ssrf_all_dns_records_must_be_public(monkeypatch, records):
    import socket

    from app_v1 import webhook_dispatch as dispatch

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [
            (
                socket.AF_INET6 if ":" in ip else socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                (ip, 443),
            )
            for ip in records
        ],
    )
    with pytest.raises(ValueError):
        dispatch.safe_send("https://receiver.example/hook", b"{}", {})


def test_safe_transport_pins_dns_keeps_sni_no_redirect_reads(monkeypatch):
    import socket

    from app_v1 import webhook_dispatch as dispatch

    connections = []
    calls = []

    def resolve(*args, **kwargs):
        calls.append(args)
        return (
            [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
            if len(calls) == 1
            else [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
        )

    monkeypatch.setattr(socket, "getaddrinfo", resolve)

    class Connection:
        sock = None

        def __init__(self, host, record):
            connections.append((host, record))
            self.requests = []

        def request(self, *args, **kwargs):
            self.requests.append((args, kwargs))

        def getresponse(self):
            class Response:
                status = 302

                def read(self, *args):
                    raise AssertionError("Must not read response body")

            return Response()

        def close(self):
            pass

    monkeypatch.setattr(dispatch, "PinnedHTTPSConnection", Connection)
    assert dispatch.safe_send("https://receiver.example/hook?x=1", b"{}", {}) == 302
    assert len(calls) == 1 and len(connections) == 1
    assert connections[0][0] == "receiver.example"
    assert connections[0][1][4] == ("93.184.216.34", 443)
    with pytest.raises(ValueError):
        dispatch.safe_send("https://receiver.example/hook", b"{}", {})
    assert len(connections) == 1


def test_pinned_connection_numeric_socket_and_verified_sni(monkeypatch):
    import socket
    import ssl

    from app_v1 import webhook_dispatch as dispatch

    record = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
    connection = dispatch.PinnedHTTPSConnection("receiver.example", record)
    assert connection._context.check_hostname
    assert connection._context.verify_mode == ssl.CERT_REQUIRED
    calls = []

    class Socket:
        def settimeout(self, value):
            calls.append(("timeout", value))

        def connect(self, value):
            calls.append(("connect", value))

        def close(self):
            pass

    class Context:
        def wrap_socket(self, raw, server_hostname):
            calls.append(("sni", server_hostname))
            return raw

    monkeypatch.setattr(socket, "socket", lambda *a: Socket())
    connection._context = Context()
    connection.connect()
    assert ("connect", ("93.184.216.34", 443)) in calls
    assert ("sni", "receiver.example") in calls
    connection.close()


@pytest.mark.parametrize("ip", ["64:ff9b::7f00:1", "2002:7f00:1::"])
def test_transition_ipv6_cannot_hide_private_ipv4(monkeypatch, ip):
    import socket

    from app_v1 import webhook_dispatch as dispatch

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", (ip, 443, 0, 0))
        ],
    )
    with pytest.raises(ValueError):
        dispatch.resolve_public("receiver.example")


def test_dispatcher_cli_bounded_iteration(ctx, tmp_path):
    import os
    import sqlite3
    import subprocess
    import sys
    from pathlib import Path

    _, db, *_ = ctx
    db.commit()
    path = tmp_path / "worker.db"
    source = db.get_bind().raw_connection()
    with sqlite3.connect(path) as target:
        source.driver_connection.backup(target)
    source.close()
    result = subprocess.run(
        [sys.executable, "-m", "app_v1.webhook_dispatch"],
        env={
            **os.environ,
            "DATABASE_URL": "sqlite:///" + str(path),
            "WEBHOOK_DISPATCH_MAX_ITERATIONS": "1",
        },
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        check=False,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert "webhook dispatcher iterations=1" in result.stdout


def test_migration_creates_owned_tables(ctx):
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect

    _, db, *_ = ctx
    db.commit()
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/20261005_0006_integration_webhooks.py"
    )
    assert path.exists()
    spec = importlib.util.spec_from_file_location("webhook_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == "20261005_0005"
    with db.get_bind().begin() as connection:
        connection.exec_driver_sql("DROP TABLE integration_webhook_deliveries")
        connection.exec_driver_sql("DROP TABLE integration_webhooks")
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
            assert inspect(connection).has_table("integration_webhooks")
            assert inspect(connection).has_table("integration_webhook_deliveries")
            module.downgrade()
            assert not inspect(connection).has_table("integration_webhooks")


@pytest.fixture
def disk_factory(ctx, tmp_path):
    import sqlite3

    _, db, *_ = ctx
    db.commit()
    path = tmp_path / "concurrent.db"
    source = db.get_bind().raw_connection()
    with sqlite3.connect(path) as target:
        source.driver_connection.backup(target)
    source.close()
    engine = create_engine(
        "sqlite:///" + str(path),
        connect_args={"check_same_thread": False, "timeout": 15},
    )
    factory = sessionmaker(bind=engine)
    yield factory
    engine.dispose()


def test_parallel_materialization_and_claim_are_unique(ctx, disk_factory):
    import sqlite3
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from app_v1 import webhook_dispatch as dispatch

    # Copy fixture was created before events: insert them into the file database.
    from app_v1.webhook_models import WebhookDelivery

    subscribe(ctx)
    event(ctx)
    _, db, *_ = ctx
    source = db.get_bind().raw_connection()
    with sqlite3.connect(disk_factory.kw["bind"].url.database) as target:
        source.driver_connection.backup(target)
    source.close()
    barrier = threading.Barrier(4)

    def materializer(_):
        with disk_factory() as session:
            barrier.wait()
            return dispatch.materialize(session)

    with ThreadPoolExecutor(max_workers=4) as executor:
        assert sum(executor.map(materializer, range(4))) == 1

    def claimer(_):
        with disk_factory() as session:
            barrier.wait()
            row = dispatch.claim(session)
            return row.id if row else None

    with ThreadPoolExecutor(max_workers=4) as executor:
        claimed = list(executor.map(claimer, range(4)))
    assert len([item for item in claimed if item]) == 1
    with disk_factory() as session:
        assert session.query(WebhookDelivery).count() == 1
        assert session.query(WebhookDelivery).one().attempts == 1


def test_admin_real_cookie_auth_not_bearer(ctx):
    from auth import COOKIE_NAME, require_platform_admin
    from models import Session as LoginSession

    client, db, key, project, _ = ctx
    client.app.dependency_overrides.pop(require_platform_admin)
    path = "/api/v1/projects/" + project.id + "/integration-webhooks"
    assert (
        client.get(path, headers={"Authorization": "Bearer nlk_test"}).status_code
        == 401
    )
    admin = db.get(User, key.created_by_user_id)
    db.add(
        LoginSession(
            user_id=admin.id,
            token_hash=hash_token("hook-cookie"),
            expires_at=utcnow() + timedelta(days=1),
        )
    )
    db.commit()
    client.cookies.set(COOKIE_NAME, "hook-cookie")
    assert client.get(path).status_code == 200
    admin.platform_role = "none"
    db.commit()
    assert client.get(path).status_code == 403


def test_admin_owner_disable_prevents_dispatch(ctx):
    from app_v1 import webhook_dispatch as dispatch
    from app_v1.webhook_models import WebhookDelivery

    client, db, key, project, _ = ctx
    response = client.post(
        "/api/v1/projects/" + project.id + "/integration-webhooks",
        json={
            "url": "https://receiver.example/hook",
            "event_types": ["unit.availability.changed"],
        },
    )
    assert response.status_code == 201
    event(ctx)
    dispatch.materialize(db)
    db.get(User, key.created_by_user_id).active = False
    db.commit()
    sent = []
    assert dispatch.dispatch_one(db, transport=lambda *a: sent.append(a))
    assert not sent
    assert db.query(WebhookDelivery).populate_existing().one().status == "cancelled"


def test_master_key_persistent_private_atomic_under_concurrency(tmp_path, monkeypatch):
    import os
    from concurrent.futures import ThreadPoolExecutor

    from app_v1.webhooks import master_key

    path = tmp_path / "private" / "master.key"
    monkeypatch.delenv("WEBHOOK_MASTER_KEY", raising=False)
    monkeypatch.setenv("WEBHOOK_MASTER_KEY_FILE", str(path))
    with ThreadPoolExecutor(max_workers=8) as executor:
        keys = list(executor.map(lambda _: master_key(), range(16)))
    assert len(set(keys)) == 1
    assert len(keys[0]) == 32 and path.read_bytes() == keys[0]
    if os.name != "nt":
        assert path.stat().st_mode & 0o077 == 0


def test_last_crashed_attempt_transitions_terminal(ctx):
    from app_v1 import webhook_dispatch as dispatch
    from app_v1.webhook_models import WebhookDelivery

    subscribe(ctx)
    event(ctx)
    _, db, *_ = ctx
    dispatch.materialize(db)
    row = db.query(WebhookDelivery).one()
    row.attempts = dispatch.MAX_ATTEMPTS - 1
    db.commit()
    now = utcnow()
    claimed = dispatch.claim(db, now)
    assert claimed.attempts == dispatch.MAX_ATTEMPTS
    assert (
        dispatch.claim(db, now + timedelta(seconds=dispatch.LEASE_SECONDS + 1)) is None
    )
    db.refresh(row)
    assert row.status == "failed"


def test_ssrf_literal_private_url_rejected(ctx):
    client, _db, _key, project, _ = ctx
    result = client.post(
        PREFIX + "/projects/" + project.id + "/webhooks",
        headers={"Authorization": "Bearer nlk_test"},
        json={
            "url": "https://127.0.0.1/hook",
            "event_types": ["unit.availability.changed"],
        },
    )
    assert result.status_code == 422


def test_multiprocess_materialization_and_claim(ctx, disk_factory, tmp_path):
    import os
    import sqlite3
    import subprocess
    import sys
    import time
    from pathlib import Path

    from app_v1.webhook_models import WebhookDelivery

    subscribe(ctx)
    event(ctx)
    _, db, *_ = ctx
    database = disk_factory.kw["bind"].url.database
    source = db.get_bind().raw_connection()
    with sqlite3.connect(database) as target:
        source.driver_connection.backup(target)
    source.close()
    gate = tmp_path / "gate"
    code = """import sys,time,json
from pathlib import Path
from database import SessionLocal
from app_v1.webhook_dispatch import materialize,claim
Path(sys.argv[1]).touch()
while not Path(sys.argv[2]).exists(): time.sleep(0.01)
with SessionLocal() as db:
    count=materialize(db)
    row=claim(db)
    print(json.dumps({'materialized':count,'claimed':row.id if row else None}))
"""
    children = []
    try:
        for index in range(4):
            ready = tmp_path / ("ready-" + str(index))
            process = subprocess.Popen(
                [sys.executable, "-c", code, str(ready), str(gate)],
                env={**os.environ, "DATABASE_URL": "sqlite:///" + str(database)},
                cwd=Path(__file__).resolve().parents[1],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            children.append((process, ready))
        deadline = time.monotonic() + 20
        while not all(path.exists() for _, path in children):
            assert time.monotonic() < deadline, "Workers did not initialize"
            time.sleep(0.02)
        gate.touch()
        results = []
        for process, _ in children:
            stdout, stderr = process.communicate(timeout=30)
            assert process.returncode == 0, stderr
            results.append(json.loads(stdout))
        assert sum(item["materialized"] for item in results) == 1
        assert len([item for item in results if item["claimed"]]) == 1
        with disk_factory() as session:
            assert session.query(WebhookDelivery).one().attempts == 1
    finally:
        for process, _ in children:
            if process.poll() is None:
                process.kill()
                process.wait()


def test_cli_reports_unavailable_database_nonzero(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    result = subprocess.run(
        [sys.executable, "-m", "app_v1.webhook_dispatch"],
        env={
            **os.environ,
            "DATABASE_URL": "sqlite:///" + str(tmp_path / "empty.db"),
            "WEBHOOK_DISPATCH_MAX_ITERATIONS": "1",
        },
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        check=False,
        text=True,
        timeout=20,
    )
    assert result.returncode != 0
    assert "iteration failed" in result.stdout
    assert "sqlite" not in result.stdout


def test_admin_delivery_pagination_retry_and_missing_resource(ctx):
    from app_v1 import webhook_dispatch as dispatch
    from app_v1.webhook_models import WebhookDelivery

    client, db, _key, project, _ = ctx
    created = client.post(
        "/api/v1/projects/" + project.id + "/integration-webhooks",
        json={
            "url": "https://receiver.example/hook",
            "event_types": ["unit.availability.changed"],
        },
    ).json()
    event(ctx)
    event(ctx)
    dispatch.materialize(db)
    row = (
        db.query(WebhookDelivery)
        .order_by(WebhookDelivery.created_at, WebhookDelivery.id)
        .first()
    )
    row.status = "failed"
    row.attempts = 8
    db.commit()
    root = "/api/v1/integration-webhooks/" + created["webhook"]["id"]
    response = client.get(root + "/deliveries?limit=1&offset=0")
    assert response.status_code == 200
    data = response.json()
    assert (
        data["total"] == 2 and data["next_offset"] == 1 and len(data["deliveries"]) == 1
    )
    assert data["deliveries"][0]["id"] == row.id
    assert created["secret"] not in response.text
    assert client.post(root + "/deliveries/" + row.id + "/retry").status_code == 200
    assert client.post(root + "/deliveries/" + row.id + "/retry").status_code == 409
    assert client.post(root + "/deliveries/missing/retry").status_code == 404
    assert client.get(root + "/deliveries?limit=1000").status_code == 422
    assert (
        client.get("/api/v1/projects/missing/integration-webhooks").status_code == 404
    )


def test_machine_metadata_tenant_scope_and_soft_delete(ctx):
    from app_v1 import webhook_dispatch as dispatch

    client, db, key, project, foreign = ctx
    created = subscribe(ctx)
    event(ctx)
    dispatch.materialize(db)
    root = PREFIX + "/webhooks/" + created["webhook"]["id"]
    headers = {"Authorization": "Bearer nlk_test"}
    assert client.get(root + "/deliveries", headers=headers).json()["total"] == 1
    key.scopes_json = json.dumps(["webhooks:write"])
    db.commit()
    assert client.get(root + "/deliveries", headers=headers).status_code == 403
    key.scopes_json = json.dumps(["events:read"])
    db.commit()
    assert client.delete(root, headers=headers).status_code == 403
    key.scopes_json = json.dumps(["webhooks:write", "events:read"])
    key.project_id = foreign.id
    db.commit()
    assert client.get(root + "/deliveries", headers=headers).status_code == 404
    assert client.delete(root, headers=headers).status_code == 404
    key.project_id = project.id
    db.commit()
    assert client.delete(root, headers=headers).status_code == 204
    assert (
        client.get(
            PREFIX + "/projects/" + project.id + "/webhooks", headers=headers
        ).json()["webhooks"][0]["active"]
        == False
    )


def test_dispatch_stale_sender_cannot_ack_new_lease(ctx):
    from app_v1 import webhook_dispatch as dispatch
    from app_v1.webhook_models import WebhookDelivery

    subscribe(ctx)
    event(ctx)
    _, db, *_ = ctx
    dispatch.materialize(db)
    now = utcnow()

    def transport(*args):
        replacement = dispatch.claim(
            db, now + timedelta(seconds=dispatch.LEASE_SECONDS + 1)
        )
        assert replacement.attempts == 2
        return 200

    assert dispatch.dispatch_one(db, transport=transport, now=now)
    row = db.query(WebhookDelivery).populate_existing().one()
    assert row.status == "sending" and row.attempts == 2 and row.lease_token


def test_main_graceful_sigterm(ctx, disk_factory, monkeypatch, capsys):
    import signal

    from app_v1 import webhook_dispatch as dispatch

    handlers = {}
    monkeypatch.setattr(
        signal, "signal", lambda signum, callback: handlers.setdefault(signum, callback)
    )
    monkeypatch.setattr(dispatch, "SessionLocal", disk_factory)
    original = dispatch.materialize

    def stop_after_scan(db):
        result = original(db)
        handlers[signal.SIGTERM](signal.SIGTERM, None)
        return result

    monkeypatch.setattr(dispatch, "materialize", stop_after_scan)
    monkeypatch.setenv("WEBHOOK_DISPATCH_MAX_ITERATIONS", "0")
    assert dispatch.main() == 0
    assert "webhook dispatcher iterations=1" in capsys.readouterr().out


def test_dns_resolution_timeout_bounded(monkeypatch):
    import socket
    import threading
    import time

    from app_v1 import webhook_dispatch as dispatch

    release = threading.Event()
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: release.wait(timeout=5))
    started = time.monotonic()
    try:
        with pytest.raises(ValueError, match="DNS timed out"):
            dispatch.resolve_public("receiver.example")
        assert time.monotonic() - started < 4
    finally:
        release.set()

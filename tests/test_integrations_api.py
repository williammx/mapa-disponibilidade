"""HTTP contract and security tests for the external generation API."""
import importlib.util
import json
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from auth import COOKIE_NAME, hash_token
from database import Base, get_db
from models import Organization, Project, Session, User, utcnow

PREFIX = "/api/integrations/v1"
MANAGEMENT = "/api/v1/integration-api-keys"


def test_public_integration_docs_expose_only_external_contract(ctx):
    client, *_ = ctx
    response = client.get(PREFIX + "/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert PREFIX + "/projects" in schema["paths"]
    assert all(path.startswith(PREFIX) for path in schema["paths"])
    assert "IntegrationBearer" in schema["components"]["securitySchemes"]
    assert schema["paths"][PREFIX + "/projects"]["get"]["security"] == [{"IntegrationBearer": []}]
    page = client.get(PREFIX + "/docs")
    assert page.status_code == 200 and PREFIX + "/openapi.json" in page.text


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    admin = User(name="Admin", email="integration-admin@example.com", password_hash="unused", platform_role="platform_admin")
    org = Organization(name="One", slug="integration-one")
    other = Organization(name="Two", slug="integration-two")
    db.add_all([admin, org, other])
    db.flush()
    project = Project(organization_id=org.id, name="Map", slug="integration-map")
    foreign = Project(organization_id=other.id, name="Other", slug="integration-other")
    db.add_all([project, foreign, Session(user_id=admin.id, token_hash=hash_token("test-cookie"), expires_at=utcnow() + timedelta(days=1))])
    db.commit()
    from app_v1.api import router
    import app_v1.storage as storage
    monkeypatch.setattr(storage, "STORAGE_ROOT", tmp_path / "storage")
    app = FastAPI()
    app.include_router(router)
    if importlib.util.find_spec("app_v1.integrations"):
        from app_v1.integrations import router as external, management_router
        app.include_router(external)
        app.include_router(management_router)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        yield client, db, admin, org, project, foreign
    db.close()
    engine.dispose()


def mint(ctx, scopes=None, **extra):
    client, _, _, org, _, _ = ctx
    client.cookies.set(COOKIE_NAME, "test-cookie")
    response = client.post(MANAGEMENT, json={"name": "Integrator", "organization_id": org.id,
        "scopes": scopes or ["capabilities:read", "jobs:write", "jobs:read", "jobs:cancel", "results:read"], **extra})
    assert response.status_code == 201, response.text
    client.cookies.clear()
    return response.json()


def bearer(created):
    return {"Authorization": "Bearer " + created["key"]}


def test_external_projects_are_org_scoped_and_strict(ctx):
    client, db, _, org, project, foreign = ctx
    created = mint(ctx, ["projects:read", "projects:write"])
    headers = bearer(created)
    listed = client.get(PREFIX + "/projects", headers=headers)
    assert listed.status_code == 200
    assert [p["id"] for p in listed.json()["projects"]] == [project.id]
    response = client.post(PREFIX + "/projects", headers=headers,
        json={"name": "New map", "slug": "new-external-map"})
    assert response.status_code == 201, response.text
    new = response.json()["project"]
    assert new["organization_id"] == org.id
    assert new["access_mode"] == "private" and new["client_can_edit"] is False
    assert client.get(PREFIX + "/projects/" + new["id"], headers=headers).status_code == 200
    changed = client.patch(PREFIX + "/projects/" + new["id"], headers=headers, json={"name": "Renamed"})
    assert changed.status_code == 200 and changed.json()["project"]["name"] == "Renamed"
    assert client.patch(PREFIX + "/projects/" + foreign.id, headers=headers, json={"name": "No"}).status_code == 404
    for payload in ({"organization_id": foreign.organization_id}, {"name": None}, {"name": "  "}, {"client_can_edit": True}):
        assert client.patch(PREFIX + "/projects/" + project.id, headers=headers, json=payload).status_code == 422
    bound = bearer(mint(ctx, ["projects:read", "projects:write"], project_id=project.id))
    assert client.get(PREFIX + "/projects/" + new["id"], headers=bound).status_code == 404
    assert client.post(PREFIX + "/projects", headers=bound, json={"name": "No", "slug": "no-new-map"}).status_code == 403
    read_only = bearer(mint(ctx, ["projects:read"]))
    assert client.patch(PREFIX + "/projects/" + project.id, headers=read_only, json={"name": "No"}).status_code == 403


def test_rate_limit_is_persisted_per_key_and_resets(ctx, monkeypatch):
    from models import IntegrationApiKey
    client, db, _, _, _, _ = ctx
    from app_v1 import integrations
    fixed_now = utcnow()
    monkeypatch.setattr(integrations, "utcnow", lambda: fixed_now)
    monkeypatch.setenv("INTEGRATION_RATE_LIMIT_PER_MINUTE", "2")
    created = mint(ctx, ["capabilities:read"])
    headers = bearer(created)
    assert client.get(PREFIX + "/capabilities", headers=headers).status_code == 200
    factory = sessionmaker(bind=db.bind)
    def fresh_db():
        with factory() as fresh:
            yield fresh
    client.app.dependency_overrides[get_db] = fresh_db
    assert client.get(PREFIX + "/capabilities", headers=headers).status_code == 200
    denied = client.get(PREFIX + "/capabilities", headers=headers)
    assert denied.status_code == 429 and 1 <= int(denied.headers["retry-after"]) <= 60
    client.app.dependency_overrides[get_db] = lambda: db
    other = bearer(mint(ctx, ["capabilities:read"]))
    assert client.get(PREFIX + "/capabilities", headers=other).status_code == 200
    db.expire_all()
    row = db.get(IntegrationApiKey, created["api_key"]["id"])
    assert row.rate_request_count == 2
    row.rate_window_start = utcnow() - timedelta(minutes=2)
    db.commit()
    assert client.get(PREFIX + "/capabilities", headers=headers).status_code == 200
    db.refresh(row)
    assert row.rate_request_count == 1


def test_rate_limit_is_atomic_across_concurrent_database_sessions(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from fastapi import HTTPException
    from models import IntegrationApiKey
    from app_v1 import integrations
    fixed_now = utcnow()
    monkeypatch.setattr(integrations, "utcnow", lambda: fixed_now)
    monkeypatch.setenv("INTEGRATION_RATE_LIMIT_PER_MINUTE", "3")
    engine = create_engine("sqlite:///" + str(tmp_path / "rate.db"), connect_args={"timeout": 20})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        key = IntegrationApiKey(organization_id="org", created_by_user_id="user", name="Concurrent",
            token_hash=hash_token("concurrent-test-only"), scopes_json="[]", expires_at=utcnow() + timedelta(days=1))
        db.add(key)
        db.commit()
        key_id = key.id
    def consume(_):
        with factory() as db:
            try:
                integrations.enforce_rate_limit(db, db.get(IntegrationApiKey, key_id))
                return 200
            except HTTPException as exc:
                return exc.status_code
    with ThreadPoolExecutor(max_workers=6) as pool:
        statuses = list(pool.map(consume, range(12)))
    assert statuses.count(200) == 3 and statuses.count(429) == 9, statuses
    with factory() as db:
        assert db.get(IntegrationApiKey, key_id).rate_request_count == 3
    engine.dispose()


def test_keys_are_shown_once_and_hashed_only(ctx):
    client, db, _, org, _, _ = ctx
    created = mint(ctx)
    from models import IntegrationApiKey
    row = db.get(IntegrationApiKey, created["api_key"]["id"])
    assert row.token_hash == hash_token(created["key"])
    assert created["key"] not in json.dumps(created["api_key"])
    client.cookies.set(COOKIE_NAME, "test-cookie")
    listing = client.get(MANAGEMENT, params={"organization_id": org.id})
    assert listing.status_code == 200
    assert created["key"] not in listing.text
    assert row.token_hash not in listing.text
    assert "key" not in listing.json()["api_keys"][0]


def test_bearer_is_scoped_revocable_and_never_a_session(ctx):
    client, db, admin, org, _, _ = ctx
    created = mint(ctx, ["capabilities:read"])
    headers = bearer(created)
    assert client.get(PREFIX + "/capabilities", headers=headers).status_code == 200
    assert client.get("/api/v1/me", headers=headers).status_code == 401
    assert client.post(MANAGEMENT, headers=headers, json={}).status_code == 401
    client.cookies.set(COOKIE_NAME, "test-cookie")
    assert client.get(PREFIX + "/capabilities").status_code == 401
    assert client.delete(MANAGEMENT + "/" + created["api_key"]["id"]).status_code == 204
    client.cookies.clear()
    assert client.get(PREFIX + "/capabilities", headers=headers).status_code == 401
    from models import IntegrationApiKey
    key = db.get(IntegrationApiKey, created["api_key"]["id"])
    assert key.revoked_at is not None
    key.revoked_at = None
    key.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert client.get(PREFIX + "/capabilities", headers=headers).status_code == 401
    key.expires_at = utcnow() + timedelta(days=1)
    org.active = False
    db.commit()
    assert client.get(PREFIX + "/capabilities", headers=headers).status_code == 401
    org.active = True
    admin.active = False
    db.commit()
    assert client.get(PREFIX + "/capabilities", headers=headers).status_code == 401


@pytest.mark.parametrize("changes", [{"scopes": ["*"]}, {"scopes": []}, {"expires_at": "2000-01-01T00:00:00Z"}, {"name": "   "}])
def test_key_management_rejects_unbounded_inputs(ctx, changes):
    client, _, _, org, _, _ = ctx
    client.cookies.set(COOKIE_NAME, "test-cookie")
    payload = {"name": "Key", "organization_id": org.id, "scopes": ["jobs:read"], **changes}
    assert client.post(MANAGEMENT, json=payload).status_code == 422


def test_key_management_requires_platform_admin_and_project_belongs_to_org(ctx):
    client, db, admin, org, _, foreign = ctx
    client.cookies.set(COOKIE_NAME, "test-cookie")
    payload = {"name": "Key", "organization_id": org.id, "project_id": foreign.id, "scopes": ["jobs:read"]}
    assert client.post(MANAGEMENT, json=payload).status_code == 404
    admin.platform_role = "operator"
    db.commit()
    assert client.post(MANAGEMENT, json=payload).status_code == 403
    assert client.get(MANAGEMENT, params={"organization_id": org.id}).status_code == 403


def pdf_bytes():
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=300)
    page.draw_rect(pymupdf.Rect(50, 50, 100, 150))
    page.insert_text((60, 90), "01", fontsize=8)
    page.insert_text((60, 110), "150 m2", fontsize=8)
    data = doc.tobytes()
    doc.close()
    return data


def test_upload_idempotency_is_persisted_key_project_bound(ctx, monkeypatch):
    client, db, _, org, project, _ = ctx
    import app_v1.api as existing
    from models import ProcessingJob, FileAsset
    queued = []
    monkeypatch.setattr(existing, "enqueue_processing_job", queued.append)
    headers = {**bearer(mint(ctx)), "Idempotency-Key": "upload-1"}
    data = pdf_bytes()
    url = PREFIX + "/projects/" + project.id + "/jobs"
    first = client.post(url, headers=headers, files={"upload": ("map.pdf", data, "application/pdf")})
    assert first.status_code == 202, first.text
    db.expire_all()
    again = client.post(url, headers=headers, files={"upload": ("map.pdf", data, "application/pdf")})
    assert again.status_code == 202 and again.json()["job"]["id"] == first.json()["job"]["id"]
    assert len(queued) == 1 and db.query(ProcessingJob).count() == db.query(FileAsset).count() == 1
    conflict = client.post(url + "?quality=sharp", headers=headers, files={"upload": ("map.pdf", data, "application/pdf")})
    assert conflict.status_code == 409
    conflict = client.post(url, headers=headers, files={"upload": ("map.pdf", pdf_bytes(), "application/pdf")})
    assert conflict.status_code == 409
    sibling = Project(organization_id=org.id, name="Sibling", slug="idempotent-sibling")
    db.add(sibling)
    db.commit()
    assert client.post(PREFIX + "/projects/" + sibling.id + "/jobs", headers=headers,
        files={"upload": ("map.pdf", data, "application/pdf")}).status_code == 202
    second_key = {**bearer(mint(ctx)), "Idempotency-Key": "upload-1"}
    assert client.post(url, headers=second_key, files={"upload": ("map.pdf", data, "application/pdf")}).status_code == 202
    assert db.query(ProcessingJob).count() == 3
    assert client.post(url, headers={**headers, "Idempotency-Key": " "},
        files={"upload": ("map.pdf", data, "application/pdf")}).status_code == 422


def test_upload_pending_reservation_never_creates_duplicate_conversion(ctx, monkeypatch):
    import hashlib
    from models import IntegrationUploadRequest, FileAsset, ProcessingJob
    client, db, _, _, project, _ = ctx
    created = mint(ctx)
    data = pdf_bytes()
    db.add(IntegrationUploadRequest(api_key_id=created["api_key"]["id"], project_id=project.id,
        idempotency_key_hash=hash_token("reserved"), request_hash=hashlib.sha256(data + b"\0balanced").hexdigest()))
    db.commit()
    response = client.post(PREFIX + "/projects/" + project.id + "/jobs",
        headers={**bearer(created), "Idempotency-Key": "reserved"},
        files={"upload": ("map.pdf", data, "application/pdf")})
    assert response.status_code == 409 and response.headers["retry-after"] == "5"
    assert db.query(FileAsset).count() == db.query(ProcessingJob).count() == 0


@pytest.mark.parametrize("method, suffix, body", [
    ("get", "/projects", None), ("post", "/projects", {"name": "Denied", "slug": "denied-map"}),
    ("get", "/projects/{project}", None), ("patch", "/projects/{project}", {"name": "Denied"}),
    ("post", "/projects/{project}/publish", {}), ("get", "/projects/{project}/share-links", None),
    ("post", "/projects/{project}/share-links", {}), ("delete", "/share-links/missing", None),
    ("post", "/jobs/missing/retry", None),
])
def test_new_operations_require_scope_and_do_not_accept_cookie(ctx, method, suffix, body):
    client, _, _, _, project, _ = ctx
    created = mint(ctx, ["capabilities:read"])
    kwargs = {"json": body} if body is not None else {}
    url = PREFIX + suffix.format(project=project.id)
    assert client.request(method, url, headers=bearer(created), **kwargs).status_code == 403
    client.cookies.set(COOKIE_NAME, "test-cookie")
    assert client.request(method, url, **kwargs).status_code == 401


def test_upload_creates_existing_processing_job_and_enforces_tenant_and_scope(ctx, monkeypatch):
    client, db, _, org, project, foreign = ctx
    created = mint(ctx, project_id=project.id)
    import app_v1.api as existing
    queued = []
    monkeypatch.setattr(existing, "enqueue_processing_job", queued.append)
    headers = bearer(created)
    response = client.post(PREFIX + "/projects/" + project.id + "/jobs", headers=headers,
        files={"upload": ("source.pdf", pdf_bytes(), "application/pdf")})
    assert response.status_code == 202, response.text
    from models import FileAsset, ProcessingJob
    job = db.get(ProcessingJob, response.json()["job"]["id"])
    assert queued == [job.id]
    assert job.project_id == project.id and job.organization_id == org.id
    assert db.get(FileAsset, job.source_file_asset_id).kind == "source_pdf"
    assert client.post(PREFIX + "/projects/" + foreign.id + "/jobs", headers=headers,
        files={"upload": ("source.pdf", pdf_bytes(), "application/pdf")}).status_code == 404
    restricted = mint(ctx, ["jobs:read"])
    assert client.post(PREFIX + "/projects/" + project.id + "/jobs", headers=bearer(restricted),
        files={"upload": ("source.pdf", pdf_bytes(), "application/pdf")}).status_code == 403
    assert db.query(ProcessingJob).count() == 1


@pytest.mark.parametrize("content, filename, expected", [(b"%PDF-not-really-a-pdf", "test.pdf", 422), (b"no pdf", "test.pdf", 422), (b"data", "test.txt", 422)])
def test_upload_rejects_invalid_pdf_without_creating_records(ctx, content, filename, expected):
    client, db, _, _, project, _ = ctx
    created = mint(ctx)
    response = client.post(PREFIX + "/projects/" + project.id + "/jobs", headers=bearer(created),
        files={"upload": (filename, content, "application/pdf")})
    assert response.status_code == expected, response.text
    from models import FileAsset, ProcessingJob
    assert db.query(FileAsset).count() == db.query(ProcessingJob).count() == 0


def test_upload_limit_is_enforced_before_persisting(ctx, monkeypatch):
    client, db, _, _, project, _ = ctx
    created = mint(ctx)
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "10")
    response = client.post(PREFIX + "/projects/" + project.id + "/jobs", headers=bearer(created),
        files={"upload": ("test.pdf", pdf_bytes(), "application/pdf")})
    assert response.status_code == 413, response.text
    from models import FileAsset
    assert db.query(FileAsset).count() == 0


def seed_job(ctx, project=None, status="queued"):
    from models import ProcessingJob
    _, db, _, _, default_project, _ = ctx
    project = project or default_project
    job = ProcessingJob(project_id=project.id, organization_id=project.organization_id, status=status)
    db.add(job)
    db.commit()
    return job


def test_external_retry_is_scoped_atomic_and_handles_queue_failure(ctx, monkeypatch):
    from models import ProcessingJob
    import app_v1.api as existing
    client, db, _, _, project, foreign = ctx
    headers = bearer(mint(ctx, ["jobs:write"]))
    monkeypatch.setattr(existing, "enqueue_processing_job", lambda _: None)
    upload = client.post(PREFIX + "/projects/" + project.id + "/jobs", headers=headers,
        files={"upload": ("map.pdf", pdf_bytes(), "application/pdf")})
    job = db.get(ProcessingJob, upload.json()["job"]["id"])
    job.status = "failed"
    job.started_at = utcnow()
    job.finished_at = utcnow()
    db.commit()
    queued = []
    monkeypatch.setattr(existing, "enqueue_processing_job", queued.append)
    retry = client.post(PREFIX + "/jobs/" + job.id + "/retry", headers=headers)
    assert retry.status_code == 202, retry.text
    db.refresh(job)
    assert job.status == "queued" and job.finished_at is None and job.started_at is None
    assert queued == [job.id]
    assert client.post(PREFIX + "/jobs/" + job.id + "/retry", headers=headers).status_code == 409
    assert client.post(PREFIX + "/jobs/" + seed_job(ctx, foreign, "failed").id + "/retry", headers=headers).status_code == 404
    assert client.post(PREFIX + "/jobs/" + seed_job(ctx, status="failed").id + "/retry", headers=headers).status_code == 409
    job.status = "failed"
    db.commit()
    def unavailable(_):
        raise RuntimeError("private queue address")
    monkeypatch.setattr(existing, "enqueue_processing_job", unavailable)
    response = client.post(PREFIX + "/jobs/" + job.id + "/retry", headers=headers)
    assert response.status_code == 202 and response.json()["job"]["status"] == "failed"
    assert "private queue" not in response.text


def test_job_status_and_cancel_are_tenant_and_project_scoped(ctx):
    client, db, _, org, project, foreign = ctx
    created = mint(ctx, project_id=project.id)
    headers = bearer(created)
    own = seed_job(ctx)
    other = seed_job(ctx, foreign)
    same_org_project = Project(organization_id=org.id, name="Sibling", slug="integration-sibling")
    db.add(same_org_project)
    db.commit()
    sibling = seed_job(ctx, same_org_project)
    assert client.get(PREFIX + "/jobs/" + own.id, headers=headers).status_code == 200
    for denied in (other, sibling):
        assert client.get(PREFIX + "/jobs/" + denied.id, headers=headers).status_code == 404
        assert client.post(PREFIX + "/jobs/" + denied.id + "/cancel", headers=headers).status_code == 404
    response = client.post(PREFIX + "/jobs/" + own.id + "/cancel", headers=headers)
    assert response.status_code == 200, response.text
    db.refresh(own)
    assert own.status == "cancelled"
    assert client.get(PREFIX + "/jobs/" + own.id, headers=headers).json()["job"]["status"] == "cancelled"
    assert client.post(PREFIX + "/jobs/" + own.id + "/cancel", headers=headers).status_code == 409
    running = seed_job(ctx, status="running")
    assert client.post(PREFIX + "/jobs/" + running.id + "/cancel", headers=headers).status_code == 409
    read_only = mint(ctx, ["jobs:read"])
    assert client.post(PREFIX + "/jobs/" + running.id + "/cancel", headers=bearer(read_only)).status_code == 403


def test_publication_sharing_is_stable_read_only_and_rolls_back(ctx):
    from models import ProjectVersion, ShareLink, Lot
    from app_v1.storage import storage_path
    client, db, _, _, project, foreign = ctx
    headers = bearer(mint(ctx, ["publications:write", "shares:read", "shares:write"]))
    url = PREFIX + "/projects/" + project.id
    assert client.post(url + "/publish", headers=headers, json={}).status_code == 409
    path = storage_path("projects/" + project.id + "/map.html")
    path.parent.mkdir(parents=True)
    path.write_text("<html>map</html>", encoding="utf-8")
    version = ProjectVersion(project_id=project.id, map_html_path=str(path), lot_count=1)
    db.add(version)
    db.flush()
    db.add(Lot(project_id=project.id, project_version_id=version.id, external_id="1",
        geometry_json=json.dumps({"points": [[0, 0], [10, 0], [10, 10], [0, 10]]})))
    db.commit()
    assert client.post(url + "/publish", headers=headers, json={"access_mode": "password"}).status_code == 422
    db.refresh(version)
    assert version.is_published is False and db.query(ShareLink).count() == 0
    first = client.post(url + "/publish", headers=headers, json={"access_mode": "unlisted"})
    assert first.status_code == 200, first.text
    assert first.json()["share_link"]["allow_edit"] is False
    again = client.post(url + "/publish", headers=headers, json={"access_mode": "unlisted"})
    assert again.json()["share_link"]["url"] == first.json()["share_link"]["url"]
    assert db.query(ShareLink).count() == 1
    assert client.post(PREFIX + "/projects/" + foreign.id + "/publish", headers=headers, json={}).status_code == 404
    assert client.post(url + "/publish", headers=headers, json={"allow_edit": True}).status_code == 422
    shares = client.get(url + "/share-links", headers=headers)
    assert shares.status_code == 200 and len(shares.json()["share_links"]) == 1
    made = client.post(url + "/share-links", headers=headers, json={})
    assert made.status_code == 201, made.text
    assert made.json()["share_link"]["allow_edit"] is False
    link_id = made.json()["share_link"]["id"]
    assert client.delete(PREFIX + "/share-links/" + link_id, headers=headers).status_code == 204
    db.refresh(db.get(ShareLink, link_id))
    assert db.get(ShareLink, link_id).active is False


def test_results_are_paginated_and_geojson_requires_local_opt_in(ctx):
    from models import ProjectVersion, Lot
    client, db, _, _, project, _ = ctx
    headers = bearer(mint(ctx, ["results:read"]))
    job = seed_job(ctx, status="succeeded")
    version = ProjectVersion(project_id=project.id, map_html_path="unused", lot_count=3)
    db.add(version)
    db.flush()
    for i in range(3):
        db.add(Lot(project_id=project.id, project_version_id=version.id, external_id=str(i), sort_order=i,
            geometry_json=json.dumps({"points": [[200, 300], [400, 300], [400, 500]]})))
    job.project_version_id = version.id
    db.commit()
    url = PREFIX + "/jobs/" + job.id + "/results/"
    response = client.get(url + "lots?limit=2&offset=0", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert len(body["lots"]) == 2 and body["total"] == 3 and body["next_offset"] == 2
    last = client.get(url + "lots?limit=2&offset=2", headers=headers).json()
    assert len(last["lots"]) == 1 and last["next_offset"] is None
    assert client.get(url + "lots?limit=501", headers=headers).status_code == 422
    assert client.get(url + "geojson", headers=headers).status_code == 422
    geo = client.get(url + "geojson?page_local=true&limit=2", headers=headers)
    assert geo.status_code == 200, geo.text
    body = geo.json()
    assert body["type"] == "FeatureCollection" and len(body["features"]) == 2
    assert body["coordinate_system"] == "pdf_page_local" and body["non_geographic"] is True
    assert body["rfc7946_compliant"] is False and body["page_index"] == 0
    ring = body["features"][0]["geometry"]["coordinates"][0]
    assert ring[0] == [200, 300] and ring[-1] == ring[0]
    assert body["features"][0]["properties"]["external_id"] == "0"


def test_results_serve_only_completed_authorized_version_with_local_coordinates(ctx):
    client, db, _, _, project, foreign = ctx
    created = mint(ctx)
    headers = bearer(created)
    job = seed_job(ctx)
    assert client.get(PREFIX + "/jobs/" + job.id + "/results/lots", headers=headers).status_code == 409
    from app_v1.storage import storage_path
    from models import Lot, ProjectVersion
    path = storage_path("projects/" + project.id + "/v/map.html")
    path.parent.mkdir(parents=True)
    path.write_text("<html>map artifact</html>", encoding="utf-8")
    version = ProjectVersion(project_id=project.id, map_html_path=str(path), lot_count=1)
    db.add(version)
    db.flush()
    db.add(Lot(project_id=project.id, project_version_id=version.id, external_id="1", geometry_json=json.dumps({"points": [[0,0],[1,0],[1,1],[0,0]]})))
    job.status = "succeeded"
    job.project_version_id = version.id
    db.commit()
    lots = client.get(PREFIX + "/jobs/" + job.id + "/results/lots", headers=headers)
    assert lots.status_code == 200, lots.text
    assert len(lots.json()["lots"]) == 1
    assert lots.json()["coordinate_system"] == "pdf_page_local"
    html = client.get(PREFIX + "/jobs/" + job.id + "/results/html", headers=headers)
    assert html.status_code == 200 and html.text == "<html>map artifact</html>"
    assert "attachment" in html.headers["content-disposition"]
    assert client.get(PREFIX + "/jobs/" + job.id + "/results/geojson", headers=headers).status_code == 422
    other = seed_job(ctx, foreign, "succeeded")
    other.project_version_id = version.id
    db.commit()
    assert client.get(PREFIX + "/jobs/" + other.id + "/results/html", headers=headers).status_code == 404
    foreign_version = ProjectVersion(project_id=foreign.id, map_html_path=str(path))
    db.add(foreign_version)
    db.flush()
    job.project_version_id = foreign_version.id
    db.commit()
    assert client.get(PREFIX + "/jobs/" + job.id + "/results/lots", headers=headers).status_code == 404


@pytest.mark.parametrize("status", ["cancelled", "succeeded", "running", "failed"])
def test_worker_never_restarts_nonqueued_jobs(ctx, monkeypatch, status):
    from app_v1 import worker
    _, db, _, _, _, _ = ctx
    job = seed_job(ctx, status=status)
    # Real SQL transaction, a separate session as an actual worker uses.
    factory = sessionmaker(bind=db.bind)
    monkeypatch.setattr(worker, "SessionLocal", factory)
    worker.run_processing_job(job.id)
    db.refresh(job)
    assert job.status == status


def test_api_key_migration_upgrade_and_downgrade(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + str(tmp_path / "integration-migration.db"))
    config = Config()
    config.set_main_option("script_location", "alembic")
    command.upgrade(config, "head")
    engine = create_engine("sqlite:///" + str(tmp_path / "integration-migration.db"))
    inspector = inspect(engine)
    assert "integration_api_keys" in inspector.get_table_names()
    columns = {c["name"] for c in inspector.get_columns("integration_api_keys")}
    assert {"token_hash", "organization_id", "project_id", "scopes_json", "expires_at", "revoked_at"} <= columns
    assert {"rate_window_start", "rate_request_count"} <= columns
    assert "integration_upload_requests" in inspector.get_table_names()
    upload_columns = {c["name"] for c in inspector.get_columns("integration_upload_requests")}
    assert {"api_key_id", "project_id", "idempotency_key_hash", "request_hash", "job_id"} <= upload_columns
    assert any(set(c["column_names"]) == {"api_key_id", "project_id", "idempotency_key_hash"}
        for c in inspector.get_unique_constraints("integration_upload_requests"))
    assert "key" not in columns and "token" not in columns
    command.downgrade(config, "20261005_0003")
    assert "integration_upload_requests" not in inspect(engine).get_table_names()
    assert "rate_window_start" not in {c["name"] for c in inspect(engine).get_columns("integration_api_keys")}
    command.upgrade(config, "head")
    command.downgrade(config, "20260813_0002")
    assert "integration_api_keys" not in inspect(engine).get_table_names()
    engine.dispose()


def test_main_application_mounts_external_and_management_routers():
    import api
    paths = api.app.openapi()["paths"]
    assert MANAGEMENT in paths
    assert PREFIX + "/capabilities" in paths
    assert PREFIX + "/projects/{project_id}/jobs" in paths


def test_real_pdf_conversion_is_reused_end_to_end(ctx, monkeypatch):
    from app_v1 import worker
    from models import Lot, ProcessingJob, ProjectVersion
    client, db, _, _, project, _ = ctx
    created = mint(ctx)
    monkeypatch.setattr(worker, "SessionLocal", sessionmaker(bind=db.bind))
    monkeypatch.setenv("SYNC_PROCESSING", "true")
    response = client.post(PREFIX + "/projects/" + project.id + "/jobs", headers=bearer(created),
        files={"upload": ("real.pdf", pdf_bytes(), "application/pdf")})
    assert response.status_code == 202, response.text
    job = db.get(ProcessingJob, response.json()["job"]["id"])
    db.refresh(job)
    assert job.status == "succeeded"
    assert db.get(ProjectVersion, job.project_version_id).project_id == project.id
    result = client.get(PREFIX + "/jobs/" + job.id + "/results/html", headers=bearer(created))
    assert result.status_code == 200 and "<html" in result.text.lower()
    lots = client.get(PREFIX + "/jobs/" + job.id + "/results/lots", headers=bearer(created))
    assert lots.status_code == 200
    assert len(lots.json()["lots"]) > 0
    assert len(lots.json()["lots"]) == db.query(Lot).filter(Lot.project_version_id == job.project_version_id).count()


def test_result_html_cannot_escape_project_storage(ctx, tmp_path):
    from models import ProjectVersion
    from app_v1.storage import storage_path
    client, db, _, _, project, foreign = ctx
    created = mint(ctx)
    job = seed_job(ctx, status="succeeded")
    foreign_artifact = storage_path("projects/" + foreign.id + "/map.html")
    foreign_artifact.parent.mkdir(parents=True)
    foreign_artifact.write_text("Other tenant confidential map", encoding="utf-8")
    version = ProjectVersion(project_id=project.id, map_html_path=str(foreign_artifact))
    db.add(version)
    db.flush()
    job.project_version_id = version.id
    db.commit()
    response = client.get(PREFIX + "/jobs/" + job.id + "/results/html", headers=bearer(created))
    assert response.status_code == 404
    version.map_html_path = str(tmp_path / "outside.html")
    db.commit()
    assert client.get(PREFIX + "/jobs/" + job.id + "/results/html", headers=bearer(created)).status_code == 404


def test_enqueue_exception_does_not_fail_already_claimed_job(ctx, monkeypatch):
    import app_v1.api as existing
    from models import ProcessingJob
    client, db, _, _, project, _ = ctx
    def delivered_then_error(job_id):
        job = db.get(ProcessingJob, job_id)
        job.status = "running"
        db.commit()
        raise RuntimeError("transport failed after delivery")
    monkeypatch.setattr(existing, "enqueue_processing_job", delivered_then_error)
    response = client.post(PREFIX + "/projects/" + project.id + "/jobs", headers=bearer(mint(ctx)),
        files={"upload": ("map.pdf", pdf_bytes(), "application/pdf")})
    assert response.status_code == 202 and response.json()["job"]["status"] == "running"
    assert client.post(PREFIX + "/jobs/" + response.json()["job"]["id"] + "/retry",
        headers=bearer(mint(ctx, ["jobs:write"]))).status_code == 409


def test_enqueue_failure_returns_pollable_failed_job_without_internal_exception(ctx, monkeypatch):
    import app_v1.api as existing
    from models import ProcessingJob
    client, db, _, _, project, _ = ctx
    created = mint(ctx)
    def unavailable(_):
        raise RuntimeError("private redis host and internal path")
    monkeypatch.setattr(existing, "enqueue_processing_job", unavailable)
    response = client.post(PREFIX + "/projects/" + project.id + "/jobs", headers=bearer(created),
        files={"upload": ("source.pdf", pdf_bytes(), "application/pdf")})
    assert response.status_code == 202, response.text
    assert response.json()["job"]["status"] == "failed"
    assert "private redis" not in response.text
    job = db.get(ProcessingJob, response.json()["job"]["id"])
    assert job.can_retry is True
    assert client.get(PREFIX + "/jobs/" + job.id, headers=bearer(created)).status_code == 200

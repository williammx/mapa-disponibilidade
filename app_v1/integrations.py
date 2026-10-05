"""Separate authentication boundaries for machine integrations and key management."""
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session as DbSession

from auth import audit, hash_token, require_platform_admin
from database import get_db
from models import IntegrationUploadRequest, IntegrationApiKey, Lot, Organization, ProcessingJob, Project, ProjectVersion, User, utcnow
from .serialization import dt

router = APIRouter(prefix="/api/integrations/v1", tags=["integrations"])
management_router = APIRouter(prefix="/api/v1/integration-api-keys", tags=["integration key management"])
SCOPES = frozenset({"capabilities:read", "jobs:write", "jobs:read", "jobs:cancel", "results:read", "projects:read", "projects:write", "publications:write", "shares:read", "shares:write"})


@router.get("/openapi.json", include_in_schema=False)
def integration_openapi():
    from fastapi.openapi.utils import get_openapi
    schema = get_openapi(title="NexoLote Integration API", version="1.0.0", routes=router.routes,
        description="Generate, publish and share maps using organization-scoped Bearer API keys. Geometry uses PDF-local coordinates.")
    schema.setdefault("components", {}).setdefault("securitySchemes", {})["IntegrationBearer"] = {
        "type": "http", "scheme": "bearer", "description": "API key created in /app/integracoes. Never use a session token."}
    for path in schema["paths"].values():
        for method, operation in path.items():
            if method in {"get", "post", "patch", "delete", "put"}:
                operation["security"] = [{"IntegrationBearer": []}]
    return schema


@router.get("/docs", include_in_schema=False)
def integration_docs():
    from fastapi.openapi.docs import get_swagger_ui_html
    return get_swagger_ui_html(openapi_url="/api/integrations/v1/openapi.json", title="NexoLote — API externa",
        swagger_ui_parameters={"persistAuthorization": False})


class ExternalProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=2, max_length=180)
    slug: str = Field(min_length=3, max_length=100)
    description: str | None = Field(default=None, max_length=4000)


class ExternalProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(default=None, min_length=2, max_length=180)
    description: str | None = Field(default=None, max_length=4000)


class ApiKeyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=160)
    organization_id: str = Field(min_length=1, max_length=36)
    project_id: str | None = Field(default=None, min_length=1, max_length=36)
    scopes: list[str] = Field(min_length=1, max_length=len(SCOPES))
    expires_at: datetime | None = None


def key_metadata(key: IntegrationApiKey) -> dict:
    return {"id": key.id, "name": key.name, "organization_id": key.organization_id,
            "project_id": key.project_id, "scopes": json.loads(key.scopes_json),
            "expires_at": dt(key.expires_at), "revoked_at": dt(key.revoked_at), "created_at": dt(key.created_at)}


@management_router.post("", status_code=201)
def create_api_key(payload: ApiKeyCreate, response: Response,
                   user: User = Depends(require_platform_admin), db: DbSession = Depends(get_db)):
    org = db.get(Organization, payload.organization_id)
    if not org or not org.active:
        raise HTTPException(404, "Organization not found.")
    if payload.project_id:
        project = db.get(Project, payload.project_id)
        if not project or project.organization_id != org.id:
            raise HTTPException(404, "Project not found.")
    if not payload.name.strip() or not set(payload.scopes).issubset(SCOPES):
        raise HTTPException(422, "Invalid name or scopes.")
    expires = payload.expires_at or utcnow() + timedelta(days=90)
    if expires.tzinfo:
        expires = expires.astimezone(timezone.utc).replace(tzinfo=None)
    if not utcnow() < expires <= utcnow() + timedelta(days=365):
        raise HTTPException(422, "Expiry must be in the future and within 365 days.")
    raw = "nlk_" + secrets.token_urlsafe(48)
    key = IntegrationApiKey(name=payload.name.strip(), organization_id=org.id, project_id=payload.project_id,
        created_by_user_id=user.id, token_hash=hash_token(raw), scopes_json=json.dumps(sorted(set(payload.scopes))), expires_at=expires)
    db.add(key)
    db.flush()
    audit(db, "integration_api_key_created", "integration_api_key", actor=user, target_id=key.id, organization_id=org.id)
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return {"api_key": key_metadata(key), "key": raw}


@management_router.get("")
def list_api_keys(organization_id: str = Query(...), user: User = Depends(require_platform_admin),
                  db: DbSession = Depends(get_db)):
    rows = db.query(IntegrationApiKey).filter(IntegrationApiKey.organization_id == organization_id).order_by(IntegrationApiKey.created_at.desc()).all()
    return {"api_keys": [key_metadata(row) for row in rows]}


@management_router.delete("/{key_id}", status_code=204)
def revoke_api_key(key_id: str, user: User = Depends(require_platform_admin), db: DbSession = Depends(get_db)):
    key = db.get(IntegrationApiKey, key_id)
    if not key:
        raise HTTPException(404, "API key not found.")
    if not key.revoked_at:
        key.revoked_at = utcnow()
        audit(db, "integration_api_key_revoked", "integration_api_key", actor=user,
              target_id=key.id, organization_id=key.organization_id)
        db.commit()
    return Response(status_code=204)


def enforce_rate_limit(db: DbSession, key: IntegrationApiKey) -> None:
    """Durable fixed-minute budget using atomic conditional SQL, no process cache."""
    import os
    try:
        limit = int(os.getenv("INTEGRATION_RATE_LIMIT_PER_MINUTE", "120"))
        if not 1 <= limit <= 10000:
            raise ValueError()
    except ValueError:
        raise HTTPException(503, "Integration rate limit configuration is invalid.") from None
    now = utcnow()
    window = now.replace(second=0, microsecond=0)
    try:
        changed = db.query(IntegrationApiKey).filter(IntegrationApiKey.id == key.id,
            or_(IntegrationApiKey.rate_window_start.is_(None), IntegrationApiKey.rate_window_start < window)).update(
            {"rate_window_start": window, "rate_request_count": 1}, synchronize_session=False)
        if not changed:
            changed = db.query(IntegrationApiKey).filter(IntegrationApiKey.id == key.id,
                IntegrationApiKey.rate_window_start == window, IntegrationApiKey.rate_request_count < limit).update(
                {"rate_request_count": IntegrationApiKey.rate_request_count + 1}, synchronize_session=False)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(503, "Integration rate limiter unavailable.", headers={"Retry-After": "5"}) from None
    if not changed:
        retry_after = max(1, 60 - now.second)
        raise HTTPException(429, "API key rate limit exceeded.", headers={"Retry-After": str(retry_after)})


def require_api_key(scope: str):
    """Bearer-only: never consult or override the existing session dependency."""
    def authenticate(request: Request, db: DbSession = Depends(get_db)) -> IntegrationApiKey:
        parts = request.headers.get("Authorization", "").split()
        if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].startswith("nlk_") or len(parts[1]) > 256:
            raise HTTPException(401, "API key required.", headers={"WWW-Authenticate": "Bearer"})
        key = db.query(IntegrationApiKey).filter(IntegrationApiKey.token_hash == hash_token(parts[1])).first()
        if not key or key.revoked_at or key.expires_at <= utcnow():
            raise HTTPException(401, "Invalid API key.", headers={"WWW-Authenticate": "Bearer"})
        org = db.get(Organization, key.organization_id)
        owner = db.get(User, key.created_by_user_id)
        if not org or not org.active or not owner or not owner.active or owner.platform_role != "platform_admin":
            raise HTTPException(401, "Invalid API key.")
        if scope not in json.loads(key.scopes_json):
            raise HTTPException(403, "Insufficient API key scope.")
        enforce_rate_limit(db, key)
        return key
    return authenticate


@router.get("/projects")
def list_projects(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                  key: IntegrationApiKey = Depends(require_api_key("projects:read")), db: DbSession = Depends(get_db)):
    from .serialization import project_dict
    query = db.query(Project).filter(Project.organization_id == key.organization_id)
    if key.project_id:
        query = query.filter(Project.id == key.project_id)
    total = query.count()
    rows = query.order_by(Project.created_at, Project.id).offset(offset).limit(limit).all()
    return {"projects": [project_dict(row) for row in rows], "total": total, "limit": limit, "offset": offset}


@router.post("/projects", status_code=201)
def create_project(payload: ExternalProjectCreate, key: IntegrationApiKey = Depends(require_api_key("projects:write")),
                   db: DbSession = Depends(get_db)):
    from . import api as existing
    from .schemas import ProjectCreate
    if key.project_id:
        raise HTTPException(403, "Project-bound keys cannot create projects.")
    return existing.create_project(ProjectCreate(organization_id=key.organization_id, **payload.model_dump()),
                                   db.get(User, key.created_by_user_id), db)


@router.get("/projects/{project_id}")
def get_project(project_id: str, key: IntegrationApiKey = Depends(require_api_key("projects:read")),
                db: DbSession = Depends(get_db)):
    from .serialization import project_dict
    return {"project": project_dict(authorized_project(db, key, project_id))}


@router.patch("/projects/{project_id}")
def update_project(project_id: str, payload: ExternalProjectUpdate,
                   key: IntegrationApiKey = Depends(require_api_key("projects:write")), db: DbSession = Depends(get_db)):
    from . import api as existing
    from .schemas import ProjectUpdate
    authorized_project(db, key, project_id)
    return existing.update_project(project_id, ProjectUpdate(**payload.model_dump(exclude_unset=True)),
                                   db.get(User, key.created_by_user_id), db)


class ExternalPublish(BaseModel):
    model_config = ConfigDict(extra="forbid")
    access_mode: Literal["private", "password", "unlisted", "public"] = "private"
    password: str | None = Field(default=None, min_length=1, max_length=128)
    allow_edit: Literal[False] = False
    require_clean_validation: bool = True


class ExternalShareCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    access_mode: Literal["token", "password", "private"] = "token"
    password: str | None = Field(default=None, min_length=1, max_length=128)
    allow_edit: Literal[False] = False
    expires_at: datetime | None = None


@router.post("/projects/{project_id}/publish")
def publish_project(project_id: str, payload: ExternalPublish, request: Request,
                    key: IntegrationApiKey = Depends(require_api_key("publications:write")), db: DbSession = Depends(get_db)):
    from . import api as existing
    from .schemas import ProjectPublishPayload
    authorized_project(db, key, project_id)
    try:
        # A write lock serializes publication on SQLite and PostgreSQL, including
        # choosing/creating the first stable link. Existing API commits once.
        db.query(Project).filter(Project.id == project_id).update({"updated_at": Project.updated_at}, synchronize_session=False)
        return existing.publish_project_delivery(project_id, ProjectPublishPayload(**payload.model_dump()),
            request, db.get(User, key.created_by_user_id), db)
    except Exception:
        db.rollback()
        raise


@router.get("/projects/{project_id}/share-links")
def list_shares(project_id: str, request: Request,
                key: IntegrationApiKey = Depends(require_api_key("shares:read")), db: DbSession = Depends(get_db)):
    from . import api as existing
    authorized_project(db, key, project_id)
    return existing.list_share_links(project_id, request, db.get(User, key.created_by_user_id), db)


@router.post("/projects/{project_id}/share-links", status_code=201)
def create_share(project_id: str, payload: ExternalShareCreate, request: Request,
                 key: IntegrationApiKey = Depends(require_api_key("shares:write")), db: DbSession = Depends(get_db)):
    from . import api as existing
    from .schemas import ShareLinkCreate
    authorized_project(db, key, project_id)
    if payload.access_mode == "password" and not payload.password:
        raise HTTPException(422, "A password is required.")
    expires = payload.expires_at
    if expires and expires.tzinfo:
        expires = expires.astimezone(timezone.utc).replace(tzinfo=None)
    if expires and expires <= utcnow():
        raise HTTPException(422, "Share expiry must be in the future.")
    return existing.create_share_link(project_id, ShareLinkCreate(**{**payload.model_dump(), "expires_at": expires}),
        request, db.get(User, key.created_by_user_id), db)


@router.delete("/share-links/{share_link_id}", status_code=204)
def revoke_share(share_link_id: str, key: IntegrationApiKey = Depends(require_api_key("shares:write")),
                 db: DbSession = Depends(get_db)):
    from . import api as existing
    from models import ShareLink
    link = db.get(ShareLink, share_link_id)
    if not link:
        raise HTTPException(404, "Share link not found.")
    authorized_project(db, key, link.project_id)
    existing.revoke_share_link(share_link_id, Response(), db.get(User, key.created_by_user_id), db)
    return Response(status_code=204)


@router.get("/capabilities")
def capabilities(key: IntegrationApiKey = Depends(require_api_key("capabilities:read"))):
    import os
    return {"api_version": "v1", "scopes": sorted(SCOPES), "organization_id": key.organization_id,
            "project_id": key.project_id, "input_formats": ["application/pdf"],
            "max_upload_bytes": int(os.getenv("MAX_UPLOAD_BYTES", str(80 * 1024 * 1024))),
            "qualities": ["light", "balanced", "sharp", "high", "optimized"],
            "result_formats": ["html", "lots", "geojson"], "coordinate_system": "pdf_page_local",
            "geojson": "page_local_opt_in_non_rfc7946", "page_index": 0, "cancellation": "queued_only"}


def authorized_project(db: DbSession, key: IntegrationApiKey, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if not project or project.organization_id != key.organization_id or (key.project_id and key.project_id != project.id):
        raise HTTPException(404, "Project not found.")
    return project


@router.post("/projects/{project_id}/jobs", status_code=202)
def upload_and_process(project_id: str, request: Request, upload: UploadFile = File(...), quality: str = Query("balanced"),
                       key: IntegrationApiKey = Depends(require_api_key("jobs:write")), db: DbSession = Depends(get_db)):
    import os
    import pymupdf
    from . import api as existing
    from .storage import safe_filename
    authorized_project(db, key, project_id)
    if quality not in {"light", "balanced", "sharp", "high", "optimized"}:
        raise HTTPException(422, "Invalid quality.")
    if not (upload.filename or "").lower().endswith(".pdf") or upload.content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(422, "A PDF upload is required.")
    limit = int(os.getenv("MAX_UPLOAD_BYTES", str(80 * 1024 * 1024)))
    upload.file.seek(0, 2)
    size = upload.file.tell()
    upload.file.seek(0)
    if size > limit:
        raise HTTPException(413, "Upload exceeds size limit.")
    content = upload.file.read(limit + 1)
    try:
        if not content.startswith(b"%PDF-"):
            raise ValueError("Not a PDF")
        with pymupdf.open(stream=content, filetype="pdf") as document:
            if not document.is_pdf or document.needs_pass or document.page_count < 1 or document.is_repaired:
                raise ValueError("Invalid or encrypted PDF")
    except Exception:
        raise HTTPException(422, "Invalid, damaged or encrypted PDF.") from None
    finally:
        upload.file.seek(0)
    reservation = None
    idempotency_key = request.headers.get("Idempotency-Key")
    if idempotency_key is not None:
        if not 1 <= len(idempotency_key) <= 200 or any(ord(c) < 33 or ord(c) > 126 for c in idempotency_key):
            raise HTTPException(422, "Idempotency-Key must be 1-200 visible ASCII characters.")
        digest = hashlib.sha256(content + b"\0" + quality.encode()).hexdigest()
        key_hash = hash_token(idempotency_key)
        reservation = IntegrationUploadRequest(api_key_id=key.id, project_id=project_id,
            idempotency_key_hash=key_hash, request_hash=digest)
        db.add(reservation)
        try:
            # Unique reservation is durable before any shared API can commit.
            db.commit()
        except IntegrityError:
            db.rollback()
            previous = db.query(IntegrationUploadRequest).filter_by(api_key_id=key.id,
                project_id=project_id, idempotency_key_hash=key_hash).one()
            if previous.request_hash != digest:
                raise HTTPException(409, "Idempotency key was used with a different request.")
            if not previous.job_id:
                raise HTTPException(409, "Request is pending; do not start a duplicate conversion.", headers={"Retry-After": "5"})
            return {"job": external_job_dict(authorized_job(db, key, previous.job_id))}
    owner = db.get(User, key.created_by_user_id)
    # Shared upload storage uses second-resolution filenames. Add entropy so
    # concurrent integrations cannot overwrite another source in the project.
    upload.filename = secrets.token_hex(12) + "-" + safe_filename(upload.filename)
    asset = existing.upload_project_file(project_id, upload, "source_pdf", owner, db)
    asset_id = asset["file"]["id"]
    try:
        result = existing.start_processing_job(project_id, asset_id, quality, owner, db, reservation)
        job = db.get(ProcessingJob, result["job"]["id"])
    except HTTPException:
        raise
    except Exception:
        # Shared creation commits before enqueueing. Preserve a pollable job on
        # queue outages or synchronous conversion failures, never exception text.
        db.rollback()
        job = db.query(ProcessingJob).filter(ProcessingJob.source_file_asset_id == asset_id).first()
        if not job:
            raise HTTPException(503, "Processing unavailable.") from None
        # Delivery may have succeeded before the transport raised. Never mark a
        # claimed/running job failed, which would allow a concurrent retry.
        db.query(ProcessingJob).filter(ProcessingJob.id == job.id, ProcessingJob.status == "queued").update(
            {"status": "failed", "error_message": "Processing could not be started.",
             "can_retry": True, "finished_at": utcnow()}, synchronize_session=False)
        db.commit()
        db.refresh(job)
    return {"job": external_job_dict(job)}


def external_job_dict(job: ProcessingJob) -> dict:
    # Do not expose worker logs or exception text containing filesystem paths.
    return {"id": job.id, "organization_id": job.organization_id, "project_id": job.project_id,
            "project_version_id": job.project_version_id, "status": job.status, "quality": job.quality,
            "progress": job.progress, "created_at": dt(job.created_at), "finished_at": dt(job.finished_at),
            "error": "Processing failed." if job.status == "failed" else None}


def authorized_job(db: DbSession, key: IntegrationApiKey, job_id: str) -> ProcessingJob:
    job = db.get(ProcessingJob, job_id)
    if not job or job.organization_id != key.organization_id:
        raise HTTPException(404, "Job not found.")
    authorized_project(db, key, job.project_id)
    return job


@router.get("/jobs/{job_id}")
def job_status(job_id: str, key: IntegrationApiKey = Depends(require_api_key("jobs:read")),
               db: DbSession = Depends(get_db)):
    job = authorized_job(db, key, job_id)
    from .worker import recover_stalled_jobs_quietly
    recover_stalled_jobs_quietly(db)
    db.refresh(job)
    return {"job": external_job_dict(job)}


@router.post("/jobs/{job_id}/retry", status_code=202)
def retry_job(job_id: str, key: IntegrationApiKey = Depends(require_api_key("jobs:write")),
              db: DbSession = Depends(get_db)):
    from . import api as existing
    from . import storage
    from models import FileAsset
    job = authorized_job(db, key, job_id)
    asset = db.get(FileAsset, job.source_file_asset_id) if job.source_file_asset_id else None
    if not asset or asset.project_id != job.project_id or asset.kind != "source_pdf" or not storage.storage_path(asset.storage_key).is_file():
        raise HTTPException(409, "Retry source is unavailable.")
    changed = db.query(ProcessingJob).filter(ProcessingJob.id == job.id,
        ProcessingJob.status.in_(["failed", "cancelled"])).update({"status": "queued", "progress": 0,
        "error_message": None, "can_retry": False, "started_at": None, "finished_at": None,
        "current_step": "Requeued by integration."}, synchronize_session=False)
    if not changed:
        raise HTTPException(409, "Only failed or cancelled jobs can be retried.")
    audit(db, "integration_processing_job_retried", "processing_job", actor=db.get(User, key.created_by_user_id),
          target_id=job.id, organization_id=job.organization_id)
    db.commit()
    try:
        existing.enqueue_processing_job(job.id)
    except Exception:
        db.rollback()
        db.query(ProcessingJob).filter(ProcessingJob.id == job.id, ProcessingJob.status == "queued").update(
            {"status": "failed", "error_message": "Processing could not be started.", "can_retry": True,
             "finished_at": utcnow()}, synchronize_session=False)
        db.commit()
    db.refresh(job)
    return {"job": external_job_dict(job)}


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, key: IntegrationApiKey = Depends(require_api_key("jobs:cancel")),
               db: DbSession = Depends(get_db)):
    job = authorized_job(db, key, job_id)
    # Atomic compare-and-set pairs with the worker's queued -> running claim.
    changed = db.query(ProcessingJob).filter(ProcessingJob.id == job.id, ProcessingJob.status == "queued").update(
        {"status": "cancelled", "finished_at": utcnow(), "current_step": "Cancelled by integration."}, synchronize_session=False)
    if not changed:
        raise HTTPException(409, "Only queued jobs can be cancelled; running conversion cannot be interrupted safely.")
    audit(db, "integration_processing_job_cancelled", "processing_job", actor=db.get(User, key.created_by_user_id),
          target_id=job.id, organization_id=job.organization_id)
    db.commit()
    db.refresh(job)
    return {"job": external_job_dict(job)}


@router.get("/jobs/{job_id}/results/{result_format}")
def job_result(job_id: str, result_format: str, limit: int = Query(100, ge=1, le=500),
               offset: int = Query(0, ge=0), page_local: bool = Query(False),
               key: IntegrationApiKey = Depends(require_api_key("results:read")),
               db: DbSession = Depends(get_db)):
    from pathlib import Path
    from fastapi.responses import FileResponse
    from .serialization import lot_dict
    from . import storage
    job = authorized_job(db, key, job_id)
    if job.status != "succeeded" or not job.project_version_id:
        raise HTTPException(409, "Results are not ready.")
    version = db.get(ProjectVersion, job.project_version_id)
    if not version or version.project_id != job.project_id:
        raise HTTPException(404, "Result not found.")
    if result_format in {"lots", "geojson"}:
        if result_format == "geojson" and not page_local:
            raise HTTPException(422, "GeoJSON-shaped local geometry requires page_local=true; coordinates are not WGS84 or RFC 7946.")
        query = db.query(Lot).filter(Lot.project_version_id == version.id, Lot.project_id == job.project_id)
        total = query.count()
        lots = query.order_by(Lot.sort_order, Lot.id).offset(offset).limit(limit).all()
        metadata = {"project_version_id": version.id, "coordinate_system": "pdf_page_local", "page_index": 0,
                    "non_geographic": True, "total": total, "limit": limit, "offset": offset,
                    "next_offset": offset + len(lots) if offset + len(lots) < total else None}
        if result_format == "lots":
            return {**metadata, "lots": [lot_dict(lot) for lot in lots]}
        features = []
        for lot in lots:
            data = lot_dict(lot)
            points = data.pop("geometry").get("points", [])
            # Invalid polygons stay visible as null geometries, not invented shapes.
            import math
            valid = isinstance(points, list) and len(points) >= 3 and all(
                isinstance(point, (list, tuple)) and len(point) == 2 and all(
                    isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
                    for value in point) for point in points)
            ring = [list(point) for point in points] if valid else []
            if ring and ring[-1] != ring[0]:
                ring.append(ring[0])
            features.append({"type": "Feature", "id": lot.id, "properties": {**data, "page_index": 0},
                             "geometry": {"type": "Polygon", "coordinates": [ring]} if ring else None})
        return {**metadata, "type": "FeatureCollection", "rfc7946_compliant": False,
                "coordinate_warning": "Page-local map canvas coordinates, not longitude/latitude. No geographic CRS or distance inference.",
                "features": features}
    if result_format == "html":
        path = Path(version.map_html_path).resolve()
        root = storage.storage_path("projects/" + job.project_id).resolve()
        if root not in path.parents or not path.is_file():
            raise HTTPException(404, "Result artifact not found.")
        return FileResponse(path, media_type="text/html", filename="map.html",
                            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                                     "Content-Security-Policy": "sandbox"})
    raise HTTPException(422, "Use html, lots, or geojson with page_local=true.")

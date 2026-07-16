import json
import os
import secrets

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.orm import Session as DbSession

from auth import audit, current_user, hash_token, password_hash
from database import get_db
from models import (
    AuditEvent,
    EditProposal,
    FileAsset,
    Lot,
    Membership,
    Organization,
    ProcessingJob,
    Project,
    ProjectVersion,
    ShareLink,
    User,
    utcnow,
)

from .permissions import user_can_access_org, user_can_manage_org
from .schemas import (
    EditProposalCreate,
    LotBatchPatch,
    LotPatch,
    OrganizationCreate,
    ProjectCreate,
    ProjectUpdate,
    ProposalDecision,
    PublishVersionPayload,
    ShareLinkCreate,
    ShareLinkUpdate,
)
from .serialization import (
    audit_event_dict,
    dt,
    file_asset_dict,
    job_dict,
    lot_dict,
    organization_dict,
    project_dict,
    proposal_dict,
    share_link_dict,
    user_dict,
    version_dict,
)
from .storage import ensure_project_key, safe_filename, storage_path, write_stream
from .validation import validate_lots
from .worker import enqueue_processing_job

router = APIRouter(prefix="/api/v1")


def normalize_slug(value: str, max_length: int) -> str:
    import re
    import unicodedata

    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    if len(slug) < 3:
        raise HTTPException(status_code=422, detail="Use pelo menos 3 letras ou numeros no identificador.")
    return slug[:max_length]


def latest_version(db: DbSession, project_id: str, published_only: bool = False) -> ProjectVersion | None:
    query = db.query(ProjectVersion).filter(ProjectVersion.project_id == project_id)
    if published_only:
        query = query.filter(ProjectVersion.is_published.is_(True))
    return query.order_by(ProjectVersion.created_at.desc()).first()


def project_workspace_dict(db: DbSession, project: Project) -> dict:
    """Return the persisted project in the shape consumed by the React workspace."""
    org = db.get(Organization, project.organization_id)
    version = latest_version(db, project.id)
    links = db.query(ShareLink).filter(
        ShareLink.project_id == project.id,
        ShareLink.active.is_(True),
    ).all()
    source = db.query(FileAsset).filter(
        FileAsset.project_id == project.id,
        FileAsset.kind == "source_pdf",
    ).order_by(FileAsset.created_at.desc()).first()
    job = db.query(ProcessingJob).filter(
        ProcessingJob.project_id == project.id,
    ).order_by(ProcessingJob.created_at.desc()).first()
    job_is_current = bool(job and (not version or job.created_at >= version.created_at))
    has_password = any(bool(link.password_hash) for link in links)
    access_mode = project.access_mode
    if access_mode in {"link", "token"}:
        visibility = "password" if has_password else "unlisted"
    elif access_mode in {"private", "password", "unlisted", "public"}:
        visibility = access_mode
    else:
        visibility = "private"
    data = project_dict(project)
    data.update({
        "client": org.name if org else "Cliente nao encontrado",
        "lots": version.lot_count if version else 0,
        "pdfName": source.original_name if source else None,
        "quality": version.quality if version else "balanced",
        "processingStatus": (
            "processing" if job_is_current and job.status in {"queued", "running"}
            else "failed" if job_is_current and job.status == "failed"
            else "processed" if version
            else "ready" if source
            else "empty"
        ),
        "processingProgress": job.progress if job_is_current else (100 if version else 0),
        "processingJobId": job.id if job_is_current and job.status in {"queued", "running"} else None,
        "processingLog": [
            entry.get("message", "") if isinstance(entry, dict) else str(entry)
            for entry in (json.loads(job.logs) if job_is_current and job and job.logs else [])
        ],
        "processingError": job.error_message if job_is_current and job else None,
        "mapUrl": f"/projects/{project.id}/editor" if version else None,
        "visibility": visibility,
        "allowEdit": project.client_can_edit,
        "passwordEnabled": has_password,
        "updatedAt": dt(project.updated_at),
        "version": db.query(ProjectVersion).filter(ProjectVersion.project_id == project.id).count(),
    })
    return data


def require_project_access(db: DbSession, user: User, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if not project or not user_can_access_org(db, user, project.organization_id):
        raise HTTPException(status_code=404, detail="Projeto nao encontrado.")
    return project


def require_project_manager(db: DbSession, user: User, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if not project or not user_can_manage_org(db, user, project.organization_id):
        raise HTTPException(status_code=404, detail="Projeto nao encontrado.")
    return project


def link_url(request: Request, link: ShareLink, project: Project) -> str:
    base = str(request.base_url).rstrip("/")
    if link.access_mode == "public" or not link.token:
        return f"{base}/mapas/{project.slug}"
    return f"{base}/s/{link.token}"


@router.get("/me")
def read_me(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    memberships = db.query(Membership, Organization).join(Organization).filter(Membership.user_id == user.id).all()
    return {
        "user": user_dict(user),
        "organizations": [
            {**organization_dict(org), "membership_role": membership.role}
            for membership, org in memberships
        ],
    }


@router.get("/organizations")
def list_organizations(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    if user.platform_role in {"platform_admin", "operator"}:
        rows = db.query(Organization).order_by(Organization.name).all()
    else:
        rows = db.query(Organization).join(Membership).filter(Membership.user_id == user.id).order_by(Organization.name).all()
    organizations = []
    for row in rows:
        data = organization_dict(row)
        data["project_count"] = db.query(Project).filter(Project.organization_id == row.id).count()
        data["contact_count"] = db.query(Membership).filter(Membership.organization_id == row.id).count()
        organizations.append(data)
    return {"organizations": organizations}


@router.post("/organizations", status_code=201)
def create_organization(payload: OrganizationCreate, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    if user.platform_role != "platform_admin":
        raise HTTPException(status_code=403, detail="Permissao de administrador necessaria.")
    slug = normalize_slug(payload.slug, 80)
    if db.query(Organization).filter(Organization.slug == slug).first():
        raise HTTPException(status_code=409, detail="Identificador ja esta em uso.")
    org = Organization(name=payload.name.strip(), slug=slug)
    db.add(org)
    db.flush()
    audit(db, "organization_created", "organization", actor=user, target_id=org.id, organization_id=org.id)
    db.commit()
    db.refresh(org)
    return {"organization": organization_dict(org)}


@router.get("/dashboard")
def dashboard(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    projects = db.query(Project)
    if user.platform_role not in {"platform_admin", "operator"}:
        projects = projects.join(Membership, Membership.organization_id == Project.organization_id).filter(Membership.user_id == user.id)
    project_rows = projects.order_by(Project.updated_at.desc()).limit(8).all()
    proposal_count = db.query(EditProposal).filter(EditProposal.status == "pending").count() if user.platform_role in {"platform_admin", "operator"} else 0
    failed_jobs = db.query(ProcessingJob).filter(ProcessingJob.status == "failed").count()
    return {
        "metrics": {
            "projects": projects.count(),
            "in_review": projects.filter(Project.status == "review").count(),
            "published": projects.filter(Project.status == "published").count(),
            "failed_jobs": failed_jobs,
            "pending_proposals": proposal_count,
        },
        "recent_projects": [project_workspace_dict(db, project) for project in project_rows],
    }


@router.get("/projects")
def list_projects(organization_id: str | None = None, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    query = db.query(Project)
    if user.platform_role not in {"platform_admin", "operator"}:
        query = query.join(Membership, Membership.organization_id == Project.organization_id).filter(Membership.user_id == user.id)
    if organization_id:
        if not user_can_access_org(db, user, organization_id):
            raise HTTPException(status_code=403, detail="Sem permissao para este cliente.")
        query = query.filter(Project.organization_id == organization_id)
    return {"projects": [project_workspace_dict(db, row) for row in query.order_by(Project.updated_at.desc()).all()]}


@router.post("/projects", status_code=201)
def create_project(payload: ProjectCreate, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    if not user_can_manage_org(db, user, payload.organization_id):
        raise HTTPException(status_code=403, detail="Sem permissao para criar projeto para este cliente.")
    slug = normalize_slug(payload.slug, 100)
    if db.query(Project).filter(Project.slug == slug).first():
        raise HTTPException(status_code=409, detail="Identificador de projeto ja esta em uso.")
    project = Project(
        organization_id=payload.organization_id,
        name=payload.name.strip(),
        slug=slug,
        description=payload.description,
    )
    db.add(project)
    db.flush()
    audit(db, "project_created", "project", actor=user, target_id=project.id, organization_id=project.organization_id)
    db.commit()
    db.refresh(project)
    return {"project": project_workspace_dict(db, project)}


@router.get("/projects/{project_id}")
def get_project(project_id: str, request: Request, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    project = require_project_access(db, user, project_id)
    org = db.get(Organization, project.organization_id)
    version = latest_version(db, project.id)
    links = db.query(ShareLink).filter(ShareLink.project_id == project.id).order_by(ShareLink.created_at.desc()).all()
    return {
        "project": project_workspace_dict(db, project),
        "organization": organization_dict(org),
        "latest_version": version_dict(version),
        "share_links": [share_link_dict(link, link_url(request, link, project)) for link in links],
    }


@router.patch("/projects/{project_id}")
def update_project(project_id: str, payload: ProjectUpdate, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    project = require_project_manager(db, user, project_id)
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(project, key, value.strip() if isinstance(value, str) else value)
    audit(db, "project_updated", "project", actor=user, target_id=project.id, organization_id=project.organization_id, details=json.dumps(changes, ensure_ascii=False))
    db.commit()
    db.refresh(project)
    return {"project": project_workspace_dict(db, project)}


@router.post("/projects/{project_id}/files", status_code=201)
def upload_project_file(project_id: str, upload: UploadFile = File(...), kind: str = Query("source_pdf"),
                        user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    project = require_project_manager(db, user, project_id)
    if kind == "source_pdf" and (upload.content_type not in {"application/pdf", "application/octet-stream"} or not (upload.filename or "").lower().endswith(".pdf")):
        raise HTTPException(status_code=422, detail="Envie um arquivo PDF valido.")
    max_bytes = int(os.getenv("MAX_UPLOAD_BYTES", str(80 * 1024 * 1024)))
    storage_key = ensure_project_key(project.id, "uploads", f"{utcnow().strftime('%Y%m%d%H%M%S')}-{safe_filename(upload.filename)}")
    size, digest = write_stream(storage_key, upload.file)
    if size > max_bytes:
        try:
            storage_path(storage_key).unlink(missing_ok=True)
        finally:
            raise HTTPException(status_code=413, detail="Arquivo excede o limite de upload.")
    asset = FileAsset(
        organization_id=project.organization_id,
        project_id=project.id,
        kind=kind,
        original_name=safe_filename(upload.filename),
        content_type=upload.content_type,
        storage_key=storage_key,
        size_bytes=size,
        checksum_sha256=digest,
    )
    db.add(asset)
    db.flush()
    audit(db, "file_uploaded", "file_asset", actor=user, target_id=asset.id, organization_id=project.organization_id, details=asset.original_name)
    db.commit()
    db.refresh(asset)
    return {"file": file_asset_dict(asset)}


@router.get("/files/{file_id}")
def download_file(file_id: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    asset = db.get(FileAsset, file_id)
    if not asset or (asset.organization_id and not user_can_access_org(db, user, asset.organization_id)):
        raise HTTPException(status_code=404, detail="Arquivo nao encontrado.")
    return FileResponse(storage_path(asset.storage_key), media_type=asset.content_type or "application/octet-stream", filename=asset.original_name)


@router.post("/projects/{project_id}/processing-jobs", status_code=202)
def create_processing_job(project_id: str, source_file_id: str | None = None, quality: str = Query("balanced"),
                          user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    project = require_project_manager(db, user, project_id)
    if quality not in {"light", "balanced", "sharp", "high", "optimized"}:
        raise HTTPException(status_code=422, detail="Qualidade invalida.")
    asset = db.get(FileAsset, source_file_id) if source_file_id else db.query(FileAsset).filter(
        FileAsset.project_id == project.id,
        FileAsset.kind == "source_pdf",
    ).order_by(FileAsset.created_at.desc()).first()
    if not asset:
        raise HTTPException(status_code=409, detail="Envie um PDF antes de iniciar o processamento.")
    job = ProcessingJob(
        organization_id=project.organization_id,
        project_id=project.id,
        requested_by_user_id=user.id,
        source_file_asset_id=asset.id,
        quality=quality,
        status="queued",
        progress=0,
        current_step="Na fila de processamento.",
        logs=json.dumps([{"at": utcnow().isoformat(), "message": "Job criado."}], ensure_ascii=False),
    )
    db.add(job)
    db.flush()
    audit(db, "processing_job_created", "processing_job", actor=user, target_id=job.id, organization_id=project.organization_id)
    db.commit()
    enqueue_processing_job(job.id)
    db.refresh(job)
    return {"job": job_dict(job)}


@router.get("/processing-jobs/{job_id}")
def get_processing_job(job_id: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    job = db.get(ProcessingJob, job_id)
    if not job or not user_can_access_org(db, user, job.organization_id):
        raise HTTPException(status_code=404, detail="Processamento nao encontrado.")
    return {"job": job_dict(job)}


@router.post("/processing-jobs/{job_id}/retry", status_code=202)
def retry_processing_job(job_id: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    job = db.get(ProcessingJob, job_id)
    if not job or not user_can_manage_org(db, user, job.organization_id):
        raise HTTPException(status_code=404, detail="Processamento nao encontrado.")
    if job.status not in {"failed", "cancelled"}:
        raise HTTPException(status_code=409, detail="Somente jobs com falha ou cancelados podem ser repetidos.")
    job.status = "queued"
    job.progress = 0
    job.error_message = None
    job.can_retry = False
    job.current_step = "Reenviado para a fila."
    db.commit()
    enqueue_processing_job(job.id)
    db.refresh(job)
    return {"job": job_dict(job)}


@router.post("/processing-jobs/{job_id}/cancel")
def cancel_processing_job(job_id: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    job = db.get(ProcessingJob, job_id)
    if not job or not user_can_manage_org(db, user, job.organization_id):
        raise HTTPException(status_code=404, detail="Processamento nao encontrado.")
    if job.status not in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="Esse job nao pode ser cancelado.")
    job.status = "cancelled"
    job.current_step = "Cancelado pelo operador."
    job.finished_at = utcnow()
    audit(db, "processing_job_cancelled", "processing_job", actor=user, target_id=job.id, organization_id=job.organization_id)
    db.commit()
    return {"job": job_dict(job)}


@router.get("/projects/{project_id}/versions")
def list_versions(project_id: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    project = require_project_access(db, user, project_id)
    rows = db.query(ProjectVersion).filter(ProjectVersion.project_id == project.id).order_by(ProjectVersion.created_at.desc()).all()
    return {"versions": [version_dict(row) for row in rows]}


@router.post("/project-versions/{version_id}/validate")
def validate_version(version_id: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    version = db.get(ProjectVersion, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Versao nao encontrada.")
    project = require_project_access(db, user, version.project_id)
    lots = db.query(Lot).filter(Lot.project_version_id == version.id).all()
    summary = validate_lots(lots)
    version.validation_summary = json.dumps(summary, ensure_ascii=False)
    audit(db, "project_version_validated", "project_version", actor=user, target_id=version.id, organization_id=project.organization_id, details=json.dumps(summary, ensure_ascii=False))
    db.commit()
    return {"validation": summary}


@router.post("/project-versions/{version_id}/publish")
def publish_version(version_id: str, payload: PublishVersionPayload, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    version = db.get(ProjectVersion, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Versao nao encontrada.")
    project = require_project_manager(db, user, version.project_id)
    lots = db.query(Lot).filter(Lot.project_version_id == version.id).all()
    summary = validate_lots(lots)
    version.validation_summary = json.dumps(summary, ensure_ascii=False)
    if payload.require_clean_validation and summary["error_count"]:
        raise HTTPException(status_code=409, detail={"message": "Existem erros de validacao antes da publicacao.", "validation": summary})
    db.query(ProjectVersion).filter(ProjectVersion.project_id == project.id).update({"is_published": False})
    version.is_published = True
    version.status = "published"
    project.status = "published"
    audit(db, "project_version_published", "project_version", actor=user, target_id=version.id, organization_id=project.organization_id)
    db.commit()
    return {"version": version_dict(version), "url": f"/mapas/{project.slug}"}


@router.get("/project-versions/{version_id}/lots")
def list_lots(version_id: str, q: str | None = None, status_filter: str | None = Query(default=None, alias="status"),
              user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    version = db.get(ProjectVersion, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Versao nao encontrada.")
    require_project_access(db, user, version.project_id)
    query = db.query(Lot).filter(Lot.project_version_id == version.id)
    if q:
        like = f"%{q}%"
        query = query.filter((Lot.name.ilike(like)) | (Lot.block.ilike(like)))
    if status_filter:
        query = query.filter(Lot.status == status_filter)
    return {"lots": [lot_dict(row) for row in query.order_by(Lot.sort_order).all()]}


@router.patch("/lots/{lot_id}")
def patch_lot(lot_id: str, payload: LotPatch, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    lot = db.get(Lot, lot_id)
    if not lot:
        raise HTTPException(status_code=404, detail="Lote nao encontrado.")
    project = require_project_manager(db, user, lot.project_id)
    changes = payload.model_dump(exclude_unset=True)
    if "geometry" in changes:
        lot.geometry_json = json.dumps(changes.pop("geometry"), ensure_ascii=False)
    if "properties" in changes:
        lot.properties_json = json.dumps(changes.pop("properties"), ensure_ascii=False)
    for key, value in changes.items():
        setattr(lot, key, value)
    audit(db, "lot_updated", "lot", actor=user, target_id=lot.id, organization_id=project.organization_id, details=json.dumps(payload.model_dump(exclude_unset=True), ensure_ascii=False))
    db.commit()
    db.refresh(lot)
    return {"lot": lot_dict(lot)}


@router.patch("/lots/batch")
def patch_lots_batch(payload: LotBatchPatch, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    lots = db.query(Lot).filter(Lot.id.in_(payload.lot_ids)).all()
    if len(lots) != len(set(payload.lot_ids)):
        raise HTTPException(status_code=404, detail="Um ou mais lotes nao foram encontrados.")
    project = require_project_manager(db, user, lots[0].project_id)
    if any(lot.project_id != project.id for lot in lots):
        raise HTTPException(status_code=422, detail="Todos os lotes devem pertencer ao mesmo projeto.")
    changes = payload.changes.model_dump(exclude_unset=True)
    geometry = changes.pop("geometry", None)
    properties = changes.pop("properties", None)
    for lot in lots:
        for key, value in changes.items():
            setattr(lot, key, value)
        if geometry is not None:
            lot.geometry_json = json.dumps(geometry, ensure_ascii=False)
        if properties is not None:
            lot.properties_json = json.dumps(properties, ensure_ascii=False)
    audit(db, "lots_batch_updated", "lot", actor=user, organization_id=project.organization_id, details=json.dumps({"count": len(lots), "changes": payload.changes.model_dump(exclude_unset=True)}, ensure_ascii=False))
    db.commit()
    return {"updated": len(lots)}


@router.get("/projects/{project_id}/share-links")
def list_share_links(project_id: str, request: Request, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    project = require_project_access(db, user, project_id)
    links = db.query(ShareLink).filter(ShareLink.project_id == project.id).order_by(ShareLink.created_at.desc()).all()
    return {"share_links": [share_link_dict(link, link_url(request, link, project)) for link in links]}


@router.post("/projects/{project_id}/share-links", status_code=201)
def create_share_link(project_id: str, payload: ShareLinkCreate, request: Request, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    project = require_project_manager(db, user, project_id)
    if not latest_version(db, project.id, published_only=True):
        raise HTTPException(status_code=409, detail="Publique uma versao antes de compartilhar.")
    token = None if payload.access_mode == "public" else secrets.token_urlsafe(18)
    link = ShareLink(
        project_id=project.id,
        token=token,
        token_hash=hash_token(token) if token else None,
        password_hash=password_hash.hash(payload.password) if payload.password else None,
        access_mode=payload.access_mode,
        allow_edit=payload.allow_edit,
        expires_at=payload.expires_at,
    )
    db.add(link)
    db.flush()
    audit(db, "share_link_created", "share_link", actor=user, target_id=link.id, organization_id=project.organization_id)
    db.commit()
    db.refresh(link)
    return {"share_link": share_link_dict(link, link_url(request, link, project))}


@router.patch("/share-links/{share_link_id}")
def update_share_link(share_link_id: str, payload: ShareLinkUpdate, request: Request, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    link = db.get(ShareLink, share_link_id)
    if not link:
        raise HTTPException(status_code=404, detail="Link nao encontrado.")
    project = require_project_manager(db, user, link.project_id)
    changes = payload.model_dump(exclude_unset=True)
    if "password" in changes:
        link.password_hash = password_hash.hash(changes.pop("password")) if payload.password else None
    for key, value in changes.items():
        setattr(link, key, value)
    audit(db, "share_link_updated", "share_link", actor=user, target_id=link.id, organization_id=project.organization_id)
    db.commit()
    db.refresh(link)
    return {"share_link": share_link_dict(link, link_url(request, link, project))}


@router.delete("/share-links/{share_link_id}", status_code=204)
def revoke_share_link(share_link_id: str, response: Response, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    link = db.get(ShareLink, share_link_id)
    if not link:
        raise HTTPException(status_code=404, detail="Link nao encontrado.")
    project = require_project_manager(db, user, link.project_id)
    link.active = False
    audit(db, "share_link_revoked", "share_link", actor=user, target_id=link.id, organization_id=project.organization_id)
    db.commit()
    response.status_code = status.HTTP_204_NO_CONTENT


@router.get("/projects/{project_id}/edit-proposals")
def list_edit_proposals(project_id: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    project = require_project_access(db, user, project_id)
    rows = db.query(EditProposal).filter(EditProposal.project_id == project.id).order_by(EditProposal.created_at.desc()).all()
    return {"edit_proposals": [proposal_dict(row) for row in rows]}


@router.post("/projects/{project_id}/edit-proposals", status_code=201)
def create_edit_proposal(project_id: str, payload: EditProposalCreate, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    project = require_project_access(db, user, project_id)
    base_version = latest_version(db, project.id, published_only=True)
    if not base_version:
        raise HTTPException(status_code=409, detail="Nao ha versao publicada para propor alteracao.")
    proposal = EditProposal(
        project_id=project.id,
        base_project_version_id=base_version.id,
        proposed_by_user_id=user.id,
        share_link_id=payload.share_link_id,
        title=payload.title.strip(),
        summary=payload.summary,
        changes_json=json.dumps(payload.changes, ensure_ascii=False),
    )
    db.add(proposal)
    db.flush()
    audit(db, "edit_proposal_created", "edit_proposal", actor=user, target_id=proposal.id, organization_id=project.organization_id)
    db.commit()
    db.refresh(proposal)
    return {"edit_proposal": proposal_dict(proposal)}


@router.post("/edit-proposals/{proposal_id}/accept")
def accept_edit_proposal(proposal_id: str, payload: ProposalDecision, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    proposal = db.get(EditProposal, proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposta nao encontrada.")
    project = require_project_manager(db, user, proposal.project_id)
    proposal.status = "accepted"
    proposal.review_notes = payload.notes
    proposal.decided_at = utcnow()
    audit(db, "edit_proposal_accepted", "edit_proposal", actor=user, target_id=proposal.id, organization_id=project.organization_id)
    db.commit()
    return {"edit_proposal": proposal_dict(proposal)}


@router.post("/edit-proposals/{proposal_id}/reject")
def reject_edit_proposal(proposal_id: str, payload: ProposalDecision, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    proposal = db.get(EditProposal, proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposta nao encontrada.")
    project = require_project_manager(db, user, proposal.project_id)
    proposal.status = "rejected"
    proposal.review_notes = payload.notes
    proposal.decided_at = utcnow()
    audit(db, "edit_proposal_rejected", "edit_proposal", actor=user, target_id=proposal.id, organization_id=project.organization_id)
    db.commit()
    return {"edit_proposal": proposal_dict(proposal)}


@router.get("/audit-events")
def list_audit_events(organization_id: str | None = None, limit: int = Query(50, ge=1, le=200),
                      user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    query = db.query(AuditEvent, User).outerjoin(User, AuditEvent.actor_user_id == User.id)
    if organization_id:
        if not user_can_access_org(db, user, organization_id):
            raise HTTPException(status_code=403, detail="Sem permissao para este cliente.")
        query = query.filter(AuditEvent.organization_id == organization_id)
    elif user.platform_role not in {"platform_admin", "operator"}:
        org_ids = [row[0] for row in db.query(Membership.organization_id).filter(Membership.user_id == user.id).all()]
        query = query.filter(AuditEvent.organization_id.in_(org_ids))
    rows = query.order_by(AuditEvent.created_at.desc()).limit(limit).all()
    return {"audit_events": [audit_event_dict(event, actor.name if actor else None) for event, actor in rows]}


@router.get("/admin/health")
def admin_health(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    if user.platform_role not in {"platform_admin", "operator"}:
        raise HTTPException(status_code=403, detail="Sem permissao administrativa.")
    db.execute(text("SELECT 1"))
    return {
        "status": "ok",
        "database": "ok",
        "redis_configured": bool(os.getenv("REDIS_URL")),
        "storage_root": os.getenv("PRIVATE_STORAGE_DIR", os.getenv("DATA_DIR", "/data")),
    }

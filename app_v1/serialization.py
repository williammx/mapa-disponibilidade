import json

from models import AuditEvent, EditProposal, FileAsset, Lot, Organization, ProcessingJob, Project, ProjectVersion, ShareLink, User


def dt(value):
    return value.isoformat() if value else None


def user_dict(user: User) -> dict:
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "platform_role": user.platform_role,
        "active": user.active,
        "must_change_password": user.must_change_password,
        "created_at": dt(user.created_at),
        "last_login_at": dt(user.last_login_at),
    }


def organization_dict(org: Organization) -> dict:
    return {"id": org.id, "name": org.name, "slug": org.slug, "active": org.active, "created_at": dt(org.created_at)}


def project_dict(project: Project) -> dict:
    return {
        "id": project.id,
        "organization_id": project.organization_id,
        "name": project.name,
        "slug": project.slug,
        "status": project.status,
        "access_mode": project.access_mode,
        "client_can_edit": project.client_can_edit,
        "description": project.description,
        "created_at": dt(project.created_at),
        "updated_at": dt(project.updated_at),
    }


def version_dict(version: ProjectVersion | None) -> dict | None:
    if not version:
        return None
    return {
        "id": version.id,
        "project_id": version.project_id,
        "lot_count": version.lot_count,
        "quality": version.quality,
        "status": version.status,
        "is_published": version.is_published,
        "validation_summary": json.loads(version.validation_summary) if version.validation_summary else None,
        "created_at": dt(version.created_at),
    }


def file_asset_dict(asset: FileAsset) -> dict:
    return {
        "id": asset.id,
        "project_id": asset.project_id,
        "project_version_id": asset.project_version_id,
        "kind": asset.kind,
        "original_name": asset.original_name,
        "content_type": asset.content_type,
        "size_bytes": asset.size_bytes,
        "checksum_sha256": asset.checksum_sha256,
        "created_at": dt(asset.created_at),
    }


def job_dict(job: ProcessingJob) -> dict:
    return {
        "id": job.id,
        "organization_id": job.organization_id,
        "project_id": job.project_id,
        "project_version_id": job.project_version_id,
        "status": job.status,
        "quality": job.quality,
        "progress": job.progress,
        "current_step": job.current_step,
        "logs": json.loads(job.logs) if job.logs else [],
        "error_message": job.error_message,
        "can_retry": job.can_retry,
        "created_at": dt(job.created_at),
        "started_at": dt(job.started_at),
        "finished_at": dt(job.finished_at),
    }


def lot_dict(lot: Lot) -> dict:
    return {
        "id": lot.id,
        "project_id": lot.project_id,
        "project_version_id": lot.project_version_id,
        "external_id": lot.external_id,
        "name": lot.name,
        "block": lot.block,
        "area_m2": lot.area_m2,
        "status": lot.status,
        "color": lot.color,
        "geometry": json.loads(lot.geometry_json),
        "properties": json.loads(lot.properties_json) if lot.properties_json else {},
        "sort_order": lot.sort_order,
        "updated_at": dt(lot.updated_at),
    }


def share_link_dict(link: ShareLink, public_url: str | None = None) -> dict:
    return {
        "id": link.id,
        "project_id": link.project_id,
        "url": public_url,
        "has_password": bool(link.password_hash),
        "access_mode": link.access_mode,
        "allow_edit": link.allow_edit,
        "active": link.active,
        "expires_at": dt(link.expires_at),
        "last_used_at": dt(link.last_used_at),
        "access_count": link.access_count,
        "created_at": dt(link.created_at),
    }


def proposal_dict(proposal: EditProposal) -> dict:
    return {
        "id": proposal.id,
        "project_id": proposal.project_id,
        "base_project_version_id": proposal.base_project_version_id,
        "status": proposal.status,
        "title": proposal.title,
        "summary": proposal.summary,
        "changes": json.loads(proposal.changes_json),
        "review_notes": proposal.review_notes,
        "created_at": dt(proposal.created_at),
        "decided_at": dt(proposal.decided_at),
    }


def audit_event_dict(event: AuditEvent, actor_name: str | None = None) -> dict:
    return {
        "id": event.id,
        "actor_user_id": event.actor_user_id,
        "actor_name": actor_name,
        "organization_id": event.organization_id,
        "action": event.action,
        "target_type": event.target_type,
        "target_id": event.target_id,
        "details": event.details,
        "created_at": dt(event.created_at),
    }

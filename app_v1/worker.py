import json
import os
import tempfile

import pdf_to_map
from database import SessionLocal
from models import AuditEvent, FileAsset, Lot, ProcessingJob, Project, ProjectVersion, utcnow

from .storage import copy_file, copy_to_path, ensure_project_key, storage_path
from .validation import validate_lots


def append_log(job: ProcessingJob, message: str) -> None:
    rows = json.loads(job.logs) if job.logs else []
    rows.append({"at": utcnow().isoformat(), "message": message})
    job.logs = json.dumps(rows, ensure_ascii=False)


def update_job(db, job: ProcessingJob, progress: int, step: str) -> None:
    job.progress = progress
    job.current_step = step
    append_log(job, step)
    db.commit()


def extract_lots_from_info(info: dict, project_id: str, version_id: str) -> list[Lot]:
    raw_lots = info.get("data") or info.get("lots") or []
    lots: list[Lot] = []
    for index, item in enumerate(raw_lots):
        name = item.get("nome") or item.get("name") or item.get("label")
        block = item.get("quadra") or item.get("block") or item.get("area")
        geometry = item.get("points") or item.get("polygon") or item.get("geometry") or []
        if isinstance(geometry, dict):
            geometry_json = geometry
        else:
            geometry_json = {"points": geometry}
        lots.append(Lot(
            project_id=project_id,
            project_version_id=version_id,
            external_id=str(item.get("id") or item.get("external_id") or index + 1),
            name=name,
            block=block,
            area_m2=item.get("area_m2") or item.get("area"),
            status=item.get("status") or "available",
            color=item.get("color") or item.get("cor"),
            geometry_json=json.dumps(geometry_json, ensure_ascii=False),
            properties_json=json.dumps(item, ensure_ascii=False),
            sort_order=index,
        ))
    return lots


def run_processing_job(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(ProcessingJob, job_id)
        if not job:
            return
        project = db.get(Project, job.project_id)
        source_asset = db.get(FileAsset, job.source_file_asset_id) if job.source_file_asset_id else None
        if not project or not source_asset:
            job.status = "failed"
            job.error_message = "Projeto ou arquivo de origem nao encontrado."
            job.can_retry = True
            job.finished_at = utcnow()
            db.commit()
            return
        job.status = "running"
        job.started_at = utcnow()
        update_job(db, job, 8, "Preparando PDF em armazenamento privado.")
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = os.path.join(tmp, "source.pdf")
            out_html = os.path.join(tmp, "map.html")
            copy_to_path(source_asset.storage_key, pdf_path)
            update_job(db, job, 22, "Convertendo PDF em mapa interativo.")
            info = pdf_to_map.convert(pdf_path, out_html, title=project.name, quality=job.quality)
            version = ProjectVersion(
                project_id=project.id,
                source_pdf_path="",
                map_html_path="",
                lot_count=int(info.get("lotes", 0)),
                quality=job.quality,
                status="draft",
            )
            db.add(version)
            db.flush()
            update_job(db, job, 72, "Salvando artefatos e lotes.")
            pdf_key = ensure_project_key(project.id, version.id, "source.pdf")
            html_key = ensure_project_key(project.id, version.id, "map.html")
            copy_file(pdf_path, pdf_key)
            copy_file(out_html, html_key)
            version.source_pdf_path = str(storage_path(pdf_key))
            version.map_html_path = str(storage_path(html_key))
            lots = extract_lots_from_info(info, project.id, version.id)
            db.add_all(lots)
            db.flush()
            summary = validate_lots(lots)
            version.validation_summary = json.dumps(summary, ensure_ascii=False)
            job.project_version_id = version.id
            job.status = "succeeded"
            job.progress = 100
            job.current_step = "Processamento concluido."
            job.finished_at = utcnow()
            db.add(AuditEvent(
                actor_user_id=job.requested_by_user_id,
                organization_id=job.organization_id,
                action="processing_job_succeeded",
                target_type="processing_job",
                target_id=job.id,
                details=json.dumps({"version_id": version.id, "lot_count": version.lot_count}, ensure_ascii=False),
            ))
            db.commit()
    except Exception as exc:
        job = db.get(ProcessingJob, job_id)
        if job:
            job.status = "failed"
            job.error_message = f"{type(exc).__name__}: {exc}"
            job.can_retry = True
            job.finished_at = utcnow()
            append_log(job, "Falha no processamento.")
            db.commit()
        raise
    finally:
        db.close()


def enqueue_processing_job(job_id: str) -> None:
    redis_url = os.getenv("REDIS_URL")
    if not redis_url or os.getenv("SYNC_PROCESSING", "false").lower() == "true":
        run_processing_job(job_id)
        return
    from redis import Redis
    from rq import Queue

    queue = Queue("pdf-processing", connection=Redis.from_url(redis_url))
    queue.enqueue("app_v1.worker.run_processing_job", job_id, job_timeout=int(os.getenv("JOB_TIMEOUT_SECONDS", "900")))

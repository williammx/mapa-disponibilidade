import json
import os
import re
import tempfile
from datetime import datetime, timedelta

import pdf_to_map
from database import SessionLocal
from models import AuditEvent, FileAsset, Lot, ProcessingJob, Project, ProjectVersion, utcnow

from .storage import copy_file, copy_to_path, ensure_project_key, storage_path
from .validation import validate_lots


def read_logs(job: ProcessingJob) -> list:
    """Le job.logs sem deixar um texto corrompido derrubar o processamento.

    A coluna e Text livre: uma gravacao truncada transformava qualquer append
    seguinte — inclusive o que registra a falha — em JSONDecodeError.
    """
    try:
        rows = json.loads(job.logs) if job.logs else []
    except (TypeError, ValueError):
        return []
    return rows if isinstance(rows, list) else []


def append_log(job: ProcessingJob, message: str) -> None:
    rows = read_logs(job)
    rows.append({"at": utcnow().isoformat(), "message": message})
    job.logs = json.dumps(rows, ensure_ascii=False)


def update_job(db, job: ProcessingJob, progress: int, step: str) -> None:
    job.progress = progress
    job.current_step = step
    append_log(job, step)
    db.commit()


# ---------------------------------------------------------------------------
# Recuperacao de jobs orfaos
#
# O bloco `except` de run_processing_job so roda quando a excecao acontece
# dentro do processo. Se o worker for morto de fora — OOM killer (PDF grande
# rasteriza pixmaps enormes), `docker compose up -d` no meio de uma conversao,
# reboot da VPS — nada marca a linha como falha: ela fica "running" para sempre
# e a interface gira sem fim, sem nem oferecer o botao de repetir.
#
# ProcessingJob nao tem coluna de heartbeat e nao vamos inventar uma. O ultimo
# sinal de vida disponivel e o mais recente entre created_at, started_at e o
# timestamp da ultima linha de `logs` — que update_job() grava a cada etapa da
# conversao. Um job vivo e lento sempre tem um desses recente.
# ---------------------------------------------------------------------------
JOB_TIMEOUT_DEFAULT_SECONDS = 900
# Margem sobre o timeout da fila: cobre a limpeza do proprio RQ, relogios
# levemente fora de sincronia entre containers e a etapa final de gravacao, que
# nao emite log. So depois de timeout + margem sem sinal de vida a linha e dada
# como perdida.
JOB_STALE_MARGIN_DEFAULT_SECONDS = 300

RECOVERABLE_JOB_STATUSES = ("running", "queued")

STALLED_JOB_MESSAGE = (
    "O processamento foi interrompido antes de terminar e nao deu sinal de vida "
    "por mais de {minutos} minutos. Normalmente isso acontece quando o servidor "
    "fica sem memoria durante a conversao de um PDF muito pesado, ou quando o "
    "servico e reiniciado no meio do trabalho. Nenhum dado foi gravado pela "
    "metade. Tente novamente ou envie um PDF mais leve."
)


def _env_seconds(name: str, default: int) -> int:
    """Le um inteiro positivo do ambiente sem deixar valor invalido derrubar o worker."""
    try:
        value = int(os.getenv(name, "") or default)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def stalled_job_cutoff_seconds() -> int:
    return (_env_seconds("JOB_TIMEOUT_SECONDS", JOB_TIMEOUT_DEFAULT_SECONDS)
            + _env_seconds("JOB_STALE_MARGIN_SECONDS", JOB_STALE_MARGIN_DEFAULT_SECONDS))


def _last_log_timestamp(job: ProcessingJob) -> datetime | None:
    latest = None
    for row in read_logs(job):
        if not isinstance(row, dict):
            continue
        try:
            moment = datetime.fromisoformat(str(row.get("at")))
        except (TypeError, ValueError):
            continue
        # utcnow() e ingenuo; um timestamp com fuso quebraria a comparacao.
        if moment.tzinfo is not None:
            moment = moment.replace(tzinfo=None)
        if latest is None or moment > latest:
            latest = moment
    return latest


def last_sign_of_life(job: ProcessingJob) -> datetime | None:
    moments = [job.created_at, job.started_at, _last_log_timestamp(job)]
    known = [moment for moment in moments if isinstance(moment, datetime)]
    return max(known) if known else None


def recover_stalled_jobs(db, skip_job_id: str | None = None, now: datetime | None = None) -> list[str]:
    """Marca como falha os jobs que ficaram orfaos e devolve os ids afetados.

    Idempotente e barata: o filtro por created_at usa indice e, em operacao
    normal, nao volta linha nenhuma.
    """
    now = now or utcnow()
    limit_seconds = stalled_job_cutoff_seconds()
    cutoff = now - timedelta(seconds=limit_seconds)
    # created_at e sempre <= qualquer outro sinal de vida, entao filtrar por ele
    # no banco nunca descarta um job realmente travado.
    candidates = db.query(ProcessingJob).filter(
        ProcessingJob.status.in_(RECOVERABLE_JOB_STATUSES),
        ProcessingJob.created_at < cutoff,
    ).all()
    message = STALLED_JOB_MESSAGE.format(minutos=max(1, limit_seconds // 60))
    recovered: list[str] = []
    for job in candidates:
        if skip_job_id and job.id == skip_job_id:
            continue
        seen_at = last_sign_of_life(job)
        if seen_at is not None and seen_at >= cutoff:
            continue
        job.status = "failed"
        job.error_message = message
        job.can_retry = True
        job.current_step = "Processamento interrompido pelo servidor."
        job.finished_at = now
        append_log(job, "Job dado como perdido: sem sinal de vida desde %s." % (
            seen_at.isoformat() if seen_at else "o inicio"))
        db.add(AuditEvent(
            actor_user_id=job.requested_by_user_id,
            organization_id=job.organization_id,
            action="processing_job_stalled",
            target_type="processing_job",
            target_id=job.id,
            details=json.dumps({
                "last_sign_of_life": seen_at.isoformat() if seen_at else None,
                "cutoff_seconds": limit_seconds,
            }, ensure_ascii=False),
        ))
        recovered.append(job.id)
    if recovered:
        db.commit()
    return recovered


def recover_stalled_jobs_quietly(db, skip_job_id: str | None = None) -> list[str]:
    """Varredura best-effort: um erro aqui nunca pode impedir o trabalho real."""
    try:
        return recover_stalled_jobs(db, skip_job_id=skip_job_id)
    except Exception:
        db.rollback()
        return []


# O conversor devolve o status como indice (0/1/2) na mesma ordem de
# pdf_to_map.STATUS_NAMES; o banco guarda o vocabulario em ingles de
# app_v1/schemas.py:42.
STATUS_BY_INDEX = ("available", "sold", "reserved")


def _parse_points(raw) -> list[list[float]]:
    """Converte "x,y x,y ..." (formato do conversor) em lista de pares."""
    if isinstance(raw, (list, tuple)):
        return [[float(point[0]), float(point[1])] for point in raw
                if isinstance(point, (list, tuple)) and len(point) >= 2]
    points = []
    for pair in str(raw or "").split():
        x, _, y = pair.partition(",")
        try:
            points.append([float(x), float(y)])
        except ValueError:
            continue
    return points


def _parse_area(raw) -> float | None:
    """Extrai o numero de textos como "178.86m2" / "1.234,56 m²"."""
    if isinstance(raw, (int, float)):
        return float(raw) or None
    match = re.search(r"\d+(?:[.,]\d+)?", str(raw or ""))
    if not match:
        return None
    try:
        value = float(match.group(0).replace(",", "."))
    except ValueError:
        return None
    return value if value > 0 else None


def extract_lots_from_info(info: dict, project_id: str, version_id: str) -> list[Lot]:
    """Traduz o retorno de pdf_to_map.convert() em linhas da tabela Lot.

    O contrato e o de ``pdf_to_map._normalize_lot``: cada item traz ``nome``,
    ``quadra``, ``area`` (texto), ``color``, ``pts`` (string "x,y x,y") e ``s``
    (indice de status). Ler chaves que o conversor nunca produziu — como
    ``points`` ou ``status`` — devolve lista vazia silenciosamente.
    """
    raw_lots = info.get("data") or info.get("lots") or []
    lots: list[Lot] = []
    for index, item in enumerate(raw_lots):
        if not isinstance(item, dict):
            continue
        points = _parse_points(item.get("pts") or item.get("points"))
        try:
            status_index = int(item.get("s", 0) or 0)
        except (TypeError, ValueError):
            status_index = 0
        status = (STATUS_BY_INDEX[status_index]
                  if 0 <= status_index < len(STATUS_BY_INDEX) else "available")
        # external_id tem unicidade por versao: o indice do conversor e a unica
        # chave garantidamente unica (nomes de lote se repetem entre quadras).
        external_id = str(item.get("index", index))
        lots.append(Lot(
            project_id=project_id,
            project_version_id=version_id,
            external_id=external_id,
            name=item.get("nome") or item.get("name") or None,
            block=item.get("quadra") or item.get("block") or None,
            area_m2=_parse_area(item.get("area_m2") or item.get("area")),
            status=status,
            color=item.get("color") or item.get("cor") or None,
            geometry_json=json.dumps({"points": points}, ensure_ascii=False),
            properties_json=json.dumps(item, ensure_ascii=False),
            sort_order=index,
        ))
    return lots


def run_processing_job(job_id: str) -> None:
    db = SessionLocal()
    try:
        # Se o worker anterior morreu de OOM, o proximo job e quem descobre:
        # varre antes de comecar e liberta as linhas presas em "running".
        recover_stalled_jobs_quietly(db, skip_job_id=job_id)
        # Claim once, atomically against integration queued-only cancellation.
        # Duplicate RQ deliveries must not restart completed/cancelled jobs.
        claimed = db.query(ProcessingJob).filter(
            ProcessingJob.id == job_id, ProcessingJob.status == "queued",
        ).update({"status": "running", "started_at": utcnow()}, synchronize_session=False)
        db.commit()
        if not claimed:
            return
        job = db.get(ProcessingJob, job_id)
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
            # Se o conversor achou lotes e nada chegou na tabela, o contrato
            # entre os dois quebrou. Falhar alto e melhor que publicar um mapa
            # vazio com laudo de validacao verde.
            if version.lot_count and not lots:
                raise RuntimeError(
                    "O conversor devolveu %d lotes mas nenhum foi convertido para "
                    "a tabela Lot. Contrato de dados quebrado entre "
                    "pdf_to_map.convert() e extract_lots_from_info()."
                    % version.lot_count)
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

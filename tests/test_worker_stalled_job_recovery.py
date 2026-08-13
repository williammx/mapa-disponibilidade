"""Job preso em "running" para sempre quando o worker morre de fora.

`run_processing_job` so marca `failed` no `except` — que nunca roda se o
processo for morto pelo OOM killer no meio da rasterizacao de um PDF grande,
ou se o container for reiniciado. A linha ficava `running` eternamente e a
interface girava sem fim, sem nem oferecer o botao de repetir.
"""
import json
from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app_v1.worker import (
    JOB_STALE_MARGIN_DEFAULT_SECONDS,
    JOB_TIMEOUT_DEFAULT_SECONDS,
    last_sign_of_life,
    recover_stalled_jobs,
    recover_stalled_jobs_quietly,
    stalled_job_cutoff_seconds,
)
from database import Base
from models import AuditEvent, Organization, ProcessingJob, Project, User, utcnow


CUTOFF = JOB_TIMEOUT_DEFAULT_SECONDS + JOB_STALE_MARGIN_DEFAULT_SECONDS


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def project(db):
    organization = Organization(name="Cliente", slug="cliente")
    user = User(name="Admin", email="admin@example.com", password_hash="x", platform_role="platform_admin")
    db.add_all([organization, user])
    db.flush()
    project = Project(organization_id=organization.id, name="Mapa", slug="mapa-teste")
    db.add(project)
    db.flush()
    db.commit()
    return project


def make_job(db, project, status="running", age_seconds=0, logs=None):
    """Cria um job com idade controlada. age_seconds e quanto tempo faz que ele nasceu."""
    born = utcnow() - timedelta(seconds=age_seconds)
    job = ProcessingJob(
        organization_id=project.organization_id,
        project_id=project.id,
        status=status,
        progress=22 if status == "running" else 0,
        current_step="Convertendo PDF em mapa interativo.",
        created_at=born,
        started_at=None if status == "queued" else born,
        logs=json.dumps(logs, ensure_ascii=False) if logs is not None else None,
    )
    db.add(job)
    db.commit()
    return job


def test_job_preso_em_running_vira_failed_com_can_retry(db, project):
    job = make_job(db, project, status="running", age_seconds=CUTOFF + 60)

    recovered = recover_stalled_jobs(db)

    assert recovered == [job.id]
    db.refresh(job)
    assert job.status == "failed"
    assert job.can_retry is True, "sem can_retry a interface nao oferece o botao de repetir"
    assert job.finished_at is not None, "job sem finished_at continua parecendo em andamento"
    assert job.error_message and "memoria" in job.error_message.lower()


def test_job_recente_nao_e_tocado(db, project):
    job = make_job(db, project, status="running", age_seconds=60)

    assert recover_stalled_jobs(db) == []

    db.refresh(job)
    assert job.status == "running"
    assert job.can_retry is False
    assert job.finished_at is None


def test_job_longo_mas_vivo_nao_e_tocado(db, project):
    """Conversao lenta que ainda emite log e trabalho legitimo, nao job perdido."""
    recente = (utcnow() - timedelta(seconds=30)).isoformat()
    job = make_job(
        db, project,
        status="running",
        age_seconds=CUTOFF * 3,
        logs=[
            {"at": (utcnow() - timedelta(seconds=CUTOFF * 3)).isoformat(), "message": "Job criado."},
            {"at": recente, "message": "Salvando artefatos e lotes."},
        ],
    )

    assert recover_stalled_jobs(db) == []

    db.refresh(job)
    assert job.status == "running"


def test_job_queued_esquecido_tambem_e_recuperado(db, project):
    """Fila perdida no Redis deixa o job em queued sem started_at para sempre."""
    job = make_job(db, project, status="queued", age_seconds=CUTOFF + 60)

    assert recover_stalled_jobs(db) == [job.id]

    db.refresh(job)
    assert job.status == "failed"
    assert job.can_retry is True


def test_jobs_ja_encerrados_ficam_como_estao(db, project):
    for status in ("succeeded", "failed", "cancelled"):
        make_job(db, project, status=status, age_seconds=CUTOFF * 5)

    assert recover_stalled_jobs(db) == []

    encerrados = {job.status for job in db.query(ProcessingJob).all()}
    assert encerrados == {"succeeded", "failed", "cancelled"}


def test_job_em_execucao_agora_e_poupado_pelo_skip(db, project):
    """O worker varre antes de comecar; ele nao pode marcar como perdido o proprio job."""
    antigo = make_job(db, project, status="queued", age_seconds=CUTOFF + 60)
    atual = make_job(db, project, status="queued", age_seconds=CUTOFF + 60)

    recovered = recover_stalled_jobs(db, skip_job_id=atual.id)

    assert recovered == [antigo.id]
    db.refresh(atual)
    assert atual.status == "queued"


def test_varredura_e_idempotente(db, project):
    make_job(db, project, status="running", age_seconds=CUTOFF + 60)

    primeira = recover_stalled_jobs(db)
    segunda = recover_stalled_jobs(db)

    assert len(primeira) == 1
    assert segunda == [], "a segunda passada nao pode reescrever nem duplicar auditoria"
    assert db.query(AuditEvent).filter(AuditEvent.action == "processing_job_stalled").count() == 1


def test_recuperacao_registra_auditoria(db, project):
    job = make_job(db, project, status="running", age_seconds=CUTOFF + 60)

    recover_stalled_jobs(db)

    evento = db.query(AuditEvent).filter(AuditEvent.action == "processing_job_stalled").one()
    assert evento.target_id == job.id
    assert evento.organization_id == project.organization_id


def test_log_de_falha_fica_visivel_no_historico(db, project):
    job = make_job(db, project, status="running", age_seconds=CUTOFF + 60,
                   logs=[{"at": (utcnow() - timedelta(seconds=CUTOFF + 60)).isoformat(), "message": "Job criado."}])

    recover_stalled_jobs(db)

    db.refresh(job)
    mensagens = [linha["message"] for linha in json.loads(job.logs)]
    assert any("perdido" in mensagem for mensagem in mensagens)


def test_cutoff_soma_timeout_da_fila_com_margem(monkeypatch):
    monkeypatch.setenv("JOB_TIMEOUT_SECONDS", "600")
    monkeypatch.setenv("JOB_STALE_MARGIN_SECONDS", "120")
    assert stalled_job_cutoff_seconds() == 720


def test_cutoff_ignora_valor_invalido_no_ambiente(monkeypatch):
    monkeypatch.setenv("JOB_TIMEOUT_SECONDS", "nao-e-numero")
    monkeypatch.setenv("JOB_STALE_MARGIN_SECONDS", "-5")
    assert stalled_job_cutoff_seconds() == CUTOFF


def test_logs_corrompidos_nao_derrubam_a_varredura(db, project):
    job = make_job(db, project, status="running", age_seconds=CUTOFF + 60)
    job.logs = "{isso nao e json"
    db.commit()

    assert recover_stalled_jobs(db) == [job.id]
    assert last_sign_of_life(job) is not None


def test_varredura_silenciosa_engole_erro_de_banco(db, project):
    """A varredura e um faxineiro: se ela quebrar, o job real ainda tem que rodar."""
    make_job(db, project, status="running", age_seconds=CUTOFF + 60)
    Base.metadata.tables["processing_jobs"].drop(db.get_bind())

    assert recover_stalled_jobs_quietly(db) == []
    with pytest.raises(Exception):
        recover_stalled_jobs(db)

#!/usr/bin/env python3
"""API da plataforma NexoLote e portal autenticado."""
import json
import os
import re
import secrets
import shutil
import tempfile
import unicodedata
import uuid
from datetime import datetime

from fastapi import BackgroundTasks, Body, Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session as DbSession

import pdf_to_map
import rate_limit
from auth import COOKIE_NAME, audit, clear_session, current_user, hash_token, normalize_email, password_hash, require_platform_admin, set_session
from database import Base, engine, get_db
from models import AuditEvent, EditProposal, Membership, Organization, Project, ProjectVersion, Session, ShareLink, User, utcnow
from app_v1.api import router as api_v1_router
from app_v1.integrations import router as integrations_router, management_router as integration_keys_router
from app_v1.schemas import SharedEditProposalCreate

# Em producao a documentacao interativa expunha o mapa completo de rotas, schemas
# e nomes de campo para qualquer visitante anonimo em /docs.
_DOCS_ENABLED = os.getenv("APP_ENV", "development").lower() != "production"
app = FastAPI(
    title="NexoLote",
    docs_url="/docs" if _DOCS_ENABLED else None,
    redoc_url="/redoc" if _DOCS_ENABLED else None,
    openapi_url="/openapi.json" if _DOCS_ENABLED else None,
)
app.include_router(api_v1_router)
app.include_router(integrations_router)
app.include_router(integration_keys_router)
HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.getenv("DATA_DIR", "/data")
CONVERTER_JOB_DIR = os.getenv("CONVERTER_JOB_DIR", os.path.join(HERE, "data", "converter_jobs"))
FRONTEND_DIST = os.path.join(HERE, "frontend", "dist")
FRONTEND_INDEX = os.path.join(FRONTEND_DIST, "index.html")
DEMO_MAP_PATH = os.path.join(HERE, "demo", "setor-e-demo.html")
if os.path.isdir(os.path.join(FRONTEND_DIST, "assets")):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")), name="frontend-assets")


class SetupPayload(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=12, max_length=128)
    token: str = Field(min_length=16, max_length=256)


class LoginPayload(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=1, max_length=128)


class PasswordPayload(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class OrganizationPayload(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    slug: str = Field(min_length=1, max_length=80)


class ProjectPayload(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    slug: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=4000)


class ProjectUpdatePayload(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=180)
    description: str | None = Field(default=None, max_length=4000)
    status: str | None = Field(default=None, pattern=r"^(draft|review|published|paused|archived)$")
    access_mode: str | None = Field(default=None, pattern=r"^(private|link|public)$")
    client_can_edit: bool | None = None


class ProfilePayload(BaseModel):
    name: str = Field(min_length=2, max_length=160)


class ShareLinkPayload(BaseModel):
    password: str | None = Field(default=None, max_length=128)


class HtmlVersionPayload(BaseModel):
    html: str = Field(min_length=100, max_length=80_000_000)
    lot_count: int = Field(default=0, ge=0)


class ConverterPublishPayload(BaseModel):
    published: bool = True
    allow_edit: bool = False
    require_password: bool = False
    password: str | None = Field(default=None, max_length=128)


class MemberPayload(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    role: str = Field(default="client_member", pattern=r"^(client_admin|client_member)$")


@app.on_event("startup")
def initialize_database():
    if os.getenv("AUTO_CREATE_TABLES", "false").lower() == "true":
        Base.metadata.create_all(bind=engine)


def user_data(user: User) -> dict:
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "platform_role": user.platform_role,
        "must_change_password": user.must_change_password,
    }


def organization_data(org: Organization) -> dict:
    return {"id": org.id, "name": org.name, "slug": org.slug, "active": org.active}


def project_data(project: Project) -> dict:
    return {
        "id": project.id,
        "organization_id": project.organization_id,
        "name": project.name,
        "slug": project.slug,
        "status": project.status,
        "access_mode": project.access_mode,
        "client_can_edit": project.client_can_edit,
        "description": project.description,
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
    }


def latest_version(db: DbSession, project_id: str, published_only: bool = False) -> ProjectVersion | None:
    query = db.query(ProjectVersion).filter(ProjectVersion.project_id == project_id)
    if published_only:
        query = query.filter(ProjectVersion.is_published.is_(True))
    return query.order_by(ProjectVersion.created_at.desc()).first()


def validate_email(email: str) -> str:
    email = normalize_email(email)
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise HTTPException(status_code=422, detail="Email invalido.")
    return email


def normalize_slug(value: str, max_length: int) -> str:
    """Create a predictable URL-safe identifier from operator input."""
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    if len(slug) < 3:
        raise HTTPException(status_code=422, detail="Use pelo menos 3 letras ou numeros no identificador.")
    if len(slug) > max_length:
        raise HTTPException(status_code=422, detail=f"O identificador pode ter no maximo {max_length} caracteres.")
    return slug


def organization_membership(db: DbSession, user_id: str, organization_id: str) -> Membership | None:
    return db.query(Membership).filter(
        Membership.user_id == user_id,
        Membership.organization_id == organization_id,
    ).first()


def can_manage_organization(db: DbSession, user: User, organization_id: str) -> bool:
    if user.platform_role in {"platform_admin", "operator"}:
        return True
    membership = organization_membership(db, user.id, organization_id)
    return bool(membership and membership.role == "client_admin")


def can_access_organization(db: DbSession, user: User, organization_id: str) -> bool:
    if user.platform_role in {"platform_admin", "operator"}:
        return True
    return organization_membership(db, user.id, organization_id) is not None


def authenticated_request_user(request: Request, db: DbSession) -> User | None:
    raw_token = request.cookies.get(COOKIE_NAME)
    if not raw_token:
        return None
    session = db.query(Session).filter(Session.token_hash == hash_token(raw_token)).first()
    if not session or session.expires_at <= utcnow():
        return None
    user = db.get(User, session.user_id)
    return user if user and user.active else None


@app.get("/health")
def health(db: DbSession = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


def spa_response() -> FileResponse:
    if os.path.isfile(FRONTEND_INDEX):
        return FileResponse(FRONTEND_INDEX)
    return FileResponse(os.path.join(HERE, "index.html"))


@app.get("/")
def home():
    return spa_response()


@app.get("/gerador")
def legacy_generator():
    return FileResponse(os.path.join(HERE, "index.html"))


_STATIC_ROOT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
_STATIC_TYPES = {
    ".webp": "image/webp", ".png": "image/png", ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg", ".svg": "image/svg+xml", ".ico": "image/x-icon",
    ".webmanifest": "application/manifest+json", ".txt": "text/plain",
    ".xml": "application/xml",
}


def _frontend_public_file(filename: str):
    """Arquivo da pasta public/ do Vite, servido da raiz do site.

    Antes existia uma rota codificada por arquivo — a imagem nova do hero deu 404
    em producao justamente por isso. Aqui o nome e validado contra um padrao sem
    barra nem ponto-ponto e o caminho resolvido tem que continuar dentro do dist,
    entao nao da para escapar do diretorio.
    """
    if not _STATIC_ROOT_RE.match(filename):
        return None
    media_type = _STATIC_TYPES.get(os.path.splitext(filename)[1].lower())
    if not media_type:
        return None
    caminho = os.path.realpath(os.path.join(FRONTEND_DIST, filename))
    if not caminho.startswith(os.path.realpath(FRONTEND_DIST) + os.sep):
        return None
    if not os.path.isfile(caminho):
        return None
    return FileResponse(caminho, media_type=media_type,
                        headers={"Cache-Control": "public, max-age=604800"})


@app.get("/entrar")
def login_spa():
    return spa_response()


@app.get("/cliente")
def client_portal_spa():
    return spa_response()


@app.get("/login")
def login_page():
    return RedirectResponse(url="/entrar", status_code=307)


PORTAL_DELIVERY_CONTROLS = """
<script>
(() => {
  const previousRenderProject = window.renderProject;
  if (typeof previousRenderProject !== 'function') return;
  window.renderProject = async function(projectId) {
    await previousRenderProject(projectId);
    const data = await window.api('/api/projects/' + projectId);
    const detail = document.querySelector('.detail');
    if (!detail || document.getElementById('deliveryPolicy')) return;
    const project = data.project;
    const policy = document.createElement('form');
    policy.id = 'deliveryPolicy';
    policy.className = 'notice';
    policy.style.marginTop = '18px';
    policy.innerHTML = '<strong>Entrega ao cliente</strong>' +
      '<label class="field" style="margin-top:12px">Visibilidade<select id="deliveryAccess"><option value="private">Privado - link controlado</option><option value="link">Por link - sem senha</option><option value="public">Publico - URL publica</option></select></label>' +
      '<label class="field" style="display:flex;grid-template-columns:auto 1fr;align-items:center;gap:10px;margin-top:12px"><input id="clientCanEdit" type="checkbox" style="width:auto;min-height:0"><span>Permitir edicao pelo cliente</span></label>' +
      '<p style="margin:10px 0 0;font-size:12px">Desligado por padrao: o cliente abre somente o mapa, sem lista, ferramentas ou edicao.</p>' +
      '<div class="actions" style="margin-top:13px"><button class="primary">Salvar acesso</button><a href="/projects/' + project.id + '/editor" target="_blank"><button type="button">Abrir editor</button></a></div><div class="error" id="deliveryError"></div>';
    detail.prepend(policy);
    document.getElementById('deliveryAccess').value = project.access_mode;
    document.getElementById('clientCanEdit').checked = !!project.client_can_edit;
    policy.onsubmit = async event => {
      event.preventDefault();
      try {
        await window.api('/api/projects/' + project.id, {method: 'PATCH', body: JSON.stringify({
          access_mode: document.getElementById('deliveryAccess').value,
          client_can_edit: document.getElementById('clientCanEdit').checked
        })});
        document.getElementById('deliveryError').textContent = 'Configuracao salva.';
      } catch (error) {
        document.getElementById('deliveryError').textContent = error.message;
      }
    };
  };
})();
</script>
"""


@app.get("/portal-legado")
def portal_page():
    with open(os.path.join(HERE, "portal.html"), "r", encoding="utf-8") as portal_file:
        return HTMLResponse(portal_file.read() + PORTAL_DELIVERY_CONTROLS)


@app.get("/app")
def app_spa():
    return spa_response()


@app.get("/app/{path:path}")
def app_spa_path(path: str):
    return spa_response()


def project_editor_response(project: Project, version: ProjectVersion) -> HTMLResponse:
    if not os.path.isfile(version.map_html_path):
        raise HTTPException(status_code=404, detail="Arquivo do mapa nao encontrado.")
    with open(version.map_html_path, "r", encoding="utf-8") as map_file:
        html = map_file.read()
    controls = f"""<style>#project-save-bar{{position:fixed;z-index:30;top:12px;right:64px;display:flex;gap:8px;padding:7px;border:1px solid #3a4651;border-radius:8px;background:#161c22;box-shadow:0 12px 28px rgba(0,0,0,.28)}}#project-save-bar button,#project-save-bar a{{border:1px solid #43515d;border-radius:6px;background:#212b33;color:#eef5f1;padding:8px 10px;font:600 12px system-ui;text-decoration:none;cursor:pointer}}#project-save-bar button{{border-color:#36d889;background:#36d889;color:#06281a}}</style><div id=\"project-save-bar\"><a href=\"/app/projetos/{project.id}\">Voltar ao projeto</a><button id=\"save-project-map\">Salvar alteracoes</button></div><script>document.getElementById('save-project-map').onclick=async function(){{var button=this;button.disabled=true;button.textContent='Salvando...';try{{var payload=window.getMapaPayload();var rendered=await fetch('/render',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(payload)}});if(!rendered.ok)throw new Error('Nao foi possivel preparar o mapa.');var saved=await fetch('/api/projects/{project.id}/versions/html',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{html:await rendered.text(),lot_count:Array.isArray(payload.lots)?payload.lots.length:0}})}});if(!saved.ok)throw new Error('Nao foi possivel salvar.');button.textContent='Alteracoes salvas';}}catch(error){{button.disabled=false;button.textContent='Salvar alteracoes';alert(error.message);}}}};</script>"""
    return HTMLResponse(html.replace("</body>", controls + "</body>", 1))


@app.get("/projects/{project_id}/editor")
def project_editor(project_id: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project or not can_manage_organization(db, user, project.organization_id):
        raise HTTPException(status_code=404, detail="Projeto nao encontrado.")
    version = latest_version(db, project.id)
    if not version:
        raise HTTPException(status_code=409, detail="Salve ou gere um mapa antes de abrir o editor.")
    return project_editor_response(project, version)


@app.post("/api/auth/setup")
def setup_first_admin(payload: SetupPayload, response: Response, db: DbSession = Depends(get_db)):
    setup_token = os.getenv("SETUP_TOKEN", "")
    if not setup_token:
        raise HTTPException(status_code=503, detail="Setup inicial nao esta habilitado.")
    if db.query(User).count():
        raise HTTPException(status_code=409, detail="O administrador inicial ja foi criado.")
    if not secrets.compare_digest(payload.token, setup_token):
        raise HTTPException(status_code=403, detail="Token de configuracao invalido.")
    email = validate_email(payload.email)
    user = User(
        name=payload.name.strip(),
        email=email,
        password_hash=password_hash.hash(payload.password),
        platform_role="platform_admin",
    )
    db.add(user)
    audit(db, "bootstrap_admin_created", "user", actor=user, target_id=user.id)
    db.commit()
    set_session(response, db, user)
    db.commit()
    return {"user": user_data(user)}


@app.post("/api/auth/login")
def login(payload: LoginPayload, request: Request, response: Response, db: DbSession = Depends(get_db)):
    email = validate_email(payload.email)
    attempts = rate_limit.password_attempts("login", email, request)
    # Antes de verificar o hash: assim a conta bloqueada tambem para de gastar
    # CPU de argon2 a cada chute.
    attempts.enforce()
    user = db.query(User).filter(User.email == email).first()
    if not user or not user.active or not password_hash.verify(payload.password, user.password_hash):
        attempts.register_failure()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Email ou senha invalidos.")
    attempts.clear()
    user.last_login_at = utcnow()
    audit(db, "login", "user", actor=user, target_id=user.id)
    set_session(response, db, user)
    db.commit()
    return {"user": user_data(user)}


@app.post("/api/auth/logout", status_code=204)
def logout(request_response: Response, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    # Revoking every session is deliberate: an explicit logout signs the account out on all devices.
    db.query(Session).filter(Session.user_id == user.id).delete()
    audit(db, "logout", "user", actor=user, target_id=user.id)
    db.commit()
    clear_session(request_response)


@app.get("/api/auth/me")
def me(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    memberships = db.query(Membership, Organization).join(Organization).filter(Membership.user_id == user.id).all()
    return {
        "user": user_data(user),
        "organizations": [
            {**organization_data(org), "membership_role": membership.role}
            for membership, org in memberships
        ],
    }


@app.post("/api/auth/password")
def change_password(payload: PasswordPayload, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    if not password_hash.verify(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Senha atual incorreta.")
    user.password_hash = password_hash.hash(payload.new_password)
    user.must_change_password = False
    audit(db, "password_changed", "user", actor=user, target_id=user.id)
    db.commit()
    return {"ok": True}


@app.get("/api/organizations")
def list_organizations(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    if user.platform_role in {"platform_admin", "operator"}:
        organizations = db.query(Organization).order_by(Organization.name).all()
    else:
        organizations = db.query(Organization).join(Membership).filter(Membership.user_id == user.id).order_by(Organization.name).all()
    return {"organizations": [organization_data(org) for org in organizations]}


@app.post("/api/organizations", status_code=201)
def create_organization(payload: OrganizationPayload, user: User = Depends(require_platform_admin), db: DbSession = Depends(get_db)):
    slug = normalize_slug(payload.slug, 80)
    if db.query(Organization).filter(Organization.slug == slug).first():
        raise HTTPException(status_code=409, detail="Esse identificador de cliente ja esta em uso.")
    org = Organization(name=payload.name.strip(), slug=slug)
    db.add(org)
    db.flush()
    audit(db, "organization_created", "organization", actor=user, target_id=org.id, organization_id=org.id)
    db.commit()
    return {"organization": organization_data(org)}


@app.post("/api/organizations/{organization_id}/members", status_code=201)
def add_member(organization_id: str, payload: MemberPayload, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    org = db.get(Organization, organization_id)
    if not org:
        raise HTTPException(status_code=404, detail="Cliente nao encontrado.")
    if not can_manage_organization(db, user, organization_id):
        raise HTTPException(status_code=403, detail="Sem permissao para administrar este cliente.")
    member = db.query(User).filter(User.email == validate_email(payload.email)).first()
    if not member:
        raise HTTPException(status_code=404, detail="O usuario precisa criar a conta antes de ser associado ao cliente.")
    if organization_membership(db, member.id, organization_id):
        raise HTTPException(status_code=409, detail="Usuario ja associado a este cliente.")
    membership = Membership(user_id=member.id, organization_id=organization_id, role=payload.role)
    db.add(membership)
    audit(db, "member_added", "membership", actor=user, target_id=membership.id, organization_id=organization_id, details=member.email)
    db.commit()
    return {"membership": {"id": membership.id, "user_id": member.id, "role": membership.role}}


@app.get("/api/projects")
def list_projects(organization_id: str | None = None, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    query = db.query(Project)
    if user.platform_role not in {"platform_admin", "operator"}:
        query = query.join(Membership, Membership.organization_id == Project.organization_id).filter(Membership.user_id == user.id)
    if organization_id:
        if not can_manage_organization(db, user, organization_id) and user.platform_role not in {"platform_admin", "operator"}:
            raise HTTPException(status_code=403, detail="Sem permissao para este cliente.")
        query = query.filter(Project.organization_id == organization_id)
    return {"projects": [project_data(project) for project in query.order_by(Project.updated_at.desc()).all()]}


@app.get("/api/projects/{project_id}")
def get_project(project_id: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projeto nao encontrado.")
    if not can_manage_organization(db, user, project.organization_id) and user.platform_role not in {"platform_admin", "operator"}:
        raise HTTPException(status_code=403, detail="Sem permissao para este projeto.")
    org = db.get(Organization, project.organization_id)
    version = latest_version(db, project.id)
    links = db.query(ShareLink).filter(ShareLink.project_id == project.id, ShareLink.active.is_(True)).order_by(ShareLink.created_at.desc()).all()
    return {"project": project_data(project), "organization": organization_data(org),
            "version": {"id": version.id, "lot_count": version.lot_count, "quality": version.quality, "is_published": version.is_published} if version else None,
            "share_links": [{"id": link.id, "has_password": bool(link.password_hash), "url": f"/s/{link.token}" if link.token else f"/mapas/{project.slug}"} for link in links]}


@app.patch("/api/projects/{project_id}")
def update_project(project_id: str, payload: ProjectUpdatePayload, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projeto nao encontrado.")
    if not can_manage_organization(db, user, project.organization_id):
        raise HTTPException(status_code=403, detail="Sem permissao para alterar este projeto.")
    changes = payload.model_dump(exclude_unset=True)
    if "name" in changes:
        project.name = changes["name"].strip()
    if "description" in changes:
        project.description = changes["description"]
    if "status" in changes:
        project.status = changes["status"]
    if "access_mode" in changes:
        project.access_mode = changes["access_mode"]
    if "client_can_edit" in changes:
        project.client_can_edit = changes["client_can_edit"]
    audit(db, "project_updated", "project", actor=user, target_id=project.id, organization_id=project.organization_id, details=json.dumps(changes))
    db.commit()
    db.refresh(project)
    return {"project": project_data(project)}


@app.post("/api/projects/{project_id}/generate", status_code=201)
async def generate_project_map(project_id: str, arquivo: UploadFile = File(...), quality: str = Query("balanced"),
                               user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projeto nao encontrado.")
    if not can_manage_organization(db, user, project.organization_id):
        raise HTTPException(status_code=403, detail="Sem permissao para gerar este projeto.")
    if not (arquivo.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=422, detail="Envie um arquivo PDF.")
    project_dir = os.path.join(DATA_DIR, "projects", project.id)
    os.makedirs(project_dir, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = os.path.join(tmp, "source.pdf")
        out_path = os.path.join(tmp, "map.html")
        with open(pdf_path, "wb") as fh:
            shutil.copyfileobj(arquivo.file, fh)
        try:
            info = pdf_to_map.convert(pdf_path, out_path, title=project.name, quality=quality)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Nao consegui processar o PDF ({type(exc).__name__}).") from exc
        version = ProjectVersion(project_id=project.id, source_pdf_path="", map_html_path="", lot_count=int(info.get("lotes", 0)), quality=quality)
        db.add(version)
        db.flush()
        version_dir = os.path.join(project_dir, version.id)
        os.makedirs(version_dir, exist_ok=True)
        version.source_pdf_path = os.path.join(version_dir, "source.pdf")
        version.map_html_path = os.path.join(version_dir, "map.html")
        shutil.copy2(pdf_path, version.source_pdf_path)
        shutil.copy2(out_path, version.map_html_path)
    audit(db, "project_map_generated", "project_version", actor=user, target_id=version.id, organization_id=project.organization_id)
    db.commit()
    return {"version": {"id": version.id, "lot_count": version.lot_count, "quality": version.quality}}


@app.post("/api/projects/{project_id}/versions/html", status_code=201)
def save_editor_version(project_id: str, payload: HtmlVersionPayload, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project or not can_manage_organization(db, user, project.organization_id):
        raise HTTPException(status_code=404, detail="Projeto nao encontrado.")
    version = ProjectVersion(
        project_id=project.id,
        source_pdf_path=None,
        map_html_path="",
        lot_count=payload.lot_count,
        quality="editor",
    )
    db.add(version)
    db.flush()
    version_dir = os.path.join(DATA_DIR, "projects", project.id, version.id)
    os.makedirs(version_dir, exist_ok=True)
    version.map_html_path = os.path.join(version_dir, "map.html")
    with open(version.map_html_path, "w", encoding="utf-8") as fh:
        fh.write(payload.html)
    audit(db, "project_editor_saved", "project_version", actor=user, target_id=version.id, organization_id=project.organization_id)
    db.commit()
    return {"version": {"id": version.id}}


@app.post("/api/projects/{project_id}/publish")
def publish_project(project_id: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project or not can_manage_organization(db, user, project.organization_id):
        raise HTTPException(status_code=404, detail="Projeto nao encontrado.")
    version = latest_version(db, project.id)
    if not version:
        raise HTTPException(status_code=409, detail="Gere uma versao do mapa antes de publicar.")
    db.query(ProjectVersion).filter(ProjectVersion.project_id == project.id).update({"is_published": False})
    version.is_published = True
    project.status = "published"
    audit(db, "project_published", "project_version", actor=user, target_id=version.id, organization_id=project.organization_id)
    db.commit()
    return {"url": f"/mapas/{project.slug}", "version_id": version.id}


@app.post("/api/projects/{project_id}/share", status_code=201)
def create_share_link(project_id: str, payload: ShareLinkPayload, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project or not can_manage_organization(db, user, project.organization_id):
        raise HTTPException(status_code=404, detail="Projeto nao encontrado.")
    if not latest_version(db, project.id, published_only=True):
        raise HTTPException(status_code=409, detail="Publique uma versao antes de compartilhar.")
    token = secrets.token_urlsafe(18)
    link = ShareLink(project_id=project.id, token=token, token_hash=hash_token(token), password_hash=password_hash.hash(payload.password) if payload.password else None)
    db.add(link)
    audit(db, "share_link_created", "share_link", actor=user, target_id=link.id, organization_id=project.organization_id)
    db.commit()
    return {"url": f"/s/{token}", "has_password": bool(payload.password)}


def share_unlock_cookie_name(link: ShareLink) -> str:
    return f"nexolote_share_{link.id.replace('-', '')[:20]}"


def share_unlock_value(link: ShareLink) -> str:
    return hash_token(f"{link.id}:{link.token or ''}:{link.password_hash or ''}")


def share_is_unlocked(request: Request, link: ShareLink) -> bool:
    value = request.cookies.get(share_unlock_cookie_name(link), "")
    return bool(value and secrets.compare_digest(value, share_unlock_value(link)))


def client_edit_injection(link: ShareLink) -> str:
    endpoint = json.dumps(f"/api/shared-edit-proposals/{link.id}")
    return f"""
<style id="client-edit-ui">
#client-edit-bar{{position:fixed;z-index:90;right:18px;bottom:18px;width:min(360px,calc(100vw - 36px));padding:15px;border:1px solid #34444d;border-radius:8px;background:#0b151b;color:#edf5f1;box-shadow:0 18px 60px rgba(0,0,0,.4);font:13px/1.45 system-ui}}
#client-edit-bar strong{{display:block;font-size:14px;font-weight:600}}#client-edit-bar p{{margin:5px 0 11px;color:#9caeb6}}
#client-edit-bar textarea{{box-sizing:border-box;width:100%;min-height:62px;padding:9px;border:1px solid #3b4c55;border-radius:6px;background:#071014;color:#eef5f1;resize:vertical}}
#client-edit-bar button{{width:100%;height:40px;margin-top:9px;border:0;border-radius:6px;background:#35d894;color:#06291b;font-weight:600;cursor:pointer}}
#client-edit-bar button:disabled{{cursor:wait;opacity:.65}}#client-edit-feedback{{min-height:18px;margin-top:8px;color:#9de9c7}}
</style>
<script id="client-edit-script">
window.addEventListener('DOMContentLoaded',function(){{
  var editButton=document.getElementById('edt');
  if(editButton&&!editButton.classList.contains('on'))editButton.click();
  var bar=document.createElement('aside');bar.id='client-edit-bar';
  bar.innerHTML='<strong>Edicao do cliente</strong><p>As alteracoes viram uma proposta. O mapa publicado nao e alterado automaticamente.</p><textarea id="client-edit-summary" placeholder="Descreva o que foi alterado (opcional)"></textarea><button id="client-edit-submit" type="button">Enviar alteracoes para aprovacao</button><div id="client-edit-feedback" role="status"></div>';
  document.body.appendChild(bar);
  document.getElementById('client-edit-submit').onclick=async function(){{
    var button=this,feedback=document.getElementById('client-edit-feedback');
    if(typeof window.getMapaPayload!=='function'){{feedback.textContent='Nao foi possivel ler as alteracoes do mapa.';return;}}
    var map=window.getMapaPayload();button.disabled=true;button.textContent='Enviando...';feedback.textContent='';
    try{{
      var response=await fetch({endpoint},{{method:'POST',credentials:'same-origin',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{title:'Alteracoes enviadas pelo cliente',summary:document.getElementById('client-edit-summary').value||null,changes:{{lots:map.lots,settings:{{opacity:map.opacity,stroke_width:map.stroke_width,label_mode:map.label_mode}}}}}})}});
      var data=await response.json();if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'Nao foi possivel enviar a proposta.');
      feedback.textContent='Proposta enviada. A equipe ja pode revisar as alteracoes.';button.textContent='Proposta enviada';
    }}catch(error){{feedback.textContent=error.message;button.disabled=false;button.textContent='Tentar enviar novamente';}}
  }};
}});
</script>
"""


def shared_map_response(project: Project, version: ProjectVersion, allow_edit: bool = False, link: ShareLink | None = None):
    if not os.path.isfile(version.map_html_path):
        raise HTTPException(status_code=404, detail="Arquivo do mapa nao encontrado.")
    with open(version.map_html_path, "r", encoding="utf-8") as map_file:
        html = map_file.read()
    if allow_edit and link:
        html = html.replace("</head>", client_edit_injection(link) + "</head>", 1)
    else:
        # Fonte unica em pdf_to_map.viewer_guard_html: as tres copias que
        # existiam aqui divergiam entre si e esqueciam ids diferentes.
        viewer_guard = pdf_to_map.viewer_guard_html()
        html = html.replace("</head>", viewer_guard + "</head>", 1)
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


def read_only_html_response(path: str) -> HTMLResponse:
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Mapa de demonstracao nao encontrado.")
    with open(path, "r", encoding="utf-8") as map_file:
        html = map_file.read()
    viewer_guard = pdf_to_map.viewer_guard_html(count_label="demonstracao")
    html = html.replace("</head>", viewer_guard + "</head>", 1)
    return HTMLResponse(html, headers={"Cache-Control": "public, max-age=3600"})


@app.get("/mapas/setor-e-demo")
def demo_project_map():
    return read_only_html_response(DEMO_MAP_PATH)


@app.get("/p/{slug}")
def public_project_map(slug: str, db: DbSession = Depends(get_db)):
    project = db.query(Project).filter(Project.slug == slug, Project.status == "published", Project.access_mode == "public").first()
    if not project:
        raise HTTPException(status_code=404, detail="Mapa nao esta publico.")
    version = latest_version(db, project.id, published_only=True)
    if not version:
        raise HTTPException(status_code=404, detail="Mapa nao encontrado.")
    link = db.query(ShareLink).filter(
        ShareLink.project_id == project.id,
        ShareLink.active.is_(True),
        ShareLink.access_mode == "public",
    ).order_by(ShareLink.created_at.desc()).first()
    return shared_map_response(project, version, allow_edit=bool(link and link.allow_edit), link=link)


@app.get("/mapas/{slug}")
def public_project_map_v2(slug: str, db: DbSession = Depends(get_db)):
    return public_project_map(slug, db)


@app.get("/s/{token}")
def shared_project_map(token: str, request: Request, db: DbSession = Depends(get_db)):
    link = db.query(ShareLink).filter(ShareLink.token == token).first()
    if not link:
        raise HTTPException(status_code=404, detail="Link nao encontrado.")
    if not link.active:
        explicitly_revoked = db.query(AuditEvent).filter(
            AuditEvent.action == "share_link_revoked",
            AuditEvent.target_id == link.id,
        ).first()
        replacement = db.query(ShareLink).filter(
            ShareLink.project_id == link.project_id,
            ShareLink.active.is_(True),
        ).order_by(ShareLink.created_at.desc()).first()
        if replacement and not explicitly_revoked:
            project = db.get(Project, link.project_id)
            destination = (
                f"/mapas/{project.slug}"
                if replacement.access_mode == "public" or not replacement.token
                else f"/s/{replacement.token}"
            )
            return RedirectResponse(destination, status_code=307)
        raise HTTPException(status_code=410, detail="Este link foi revogado.")
    if link.expires_at and link.expires_at <= utcnow():
        raise HTTPException(status_code=410, detail="Este link expirou.")
    project = db.get(Project, link.project_id)
    if not project or project.status != "published":
        raise HTTPException(status_code=404, detail="Mapa nao publicado.")
    if link.access_mode == "private":
        user = authenticated_request_user(request, db)
        if not user:
            return RedirectResponse(url=f"/entrar?next=/s/{token}", status_code=303)
        if not can_access_organization(db, user, project.organization_id):
            raise HTTPException(status_code=403, detail="Este usuario nao possui acesso ao projeto.")
    version = latest_version(db, project.id, published_only=True)
    if not version:
        raise HTTPException(status_code=404, detail="Mapa nao publicado.")
    if link.password_hash and not share_is_unlocked(request, link):
        return HTMLResponse('<form method="post" style="font:16px system-ui;max-width:360px;margin:15vh auto"><h1>Acesso protegido</h1><input name="password" type="password" autocomplete="current-password" placeholder="Senha" required style="width:100%;padding:12px"><button style="margin-top:12px;padding:12px">Abrir mapa</button></form>')
    link.last_used_at = utcnow()
    link.access_count += 1
    db.commit()
    return shared_map_response(project, version, allow_edit=link.allow_edit, link=link)


@app.post("/s/{token}")
def unlock_shared_project(token: str, request: Request, password: str = Form(...), db: DbSession = Depends(get_db)):
    link = db.query(ShareLink).filter(ShareLink.token == token, ShareLink.active.is_(True)).first()
    if not link:
        raise HTTPException(status_code=404, detail="Link nao encontrado.")
    if link.expires_at and link.expires_at <= utcnow():
        raise HTTPException(status_code=410, detail="Este link expirou.")
    project = db.get(Project, link.project_id)
    if not project or project.status != "published":
        raise HTTPException(status_code=404, detail="Mapa nao publicado.")
    if link.access_mode == "private":
        user = authenticated_request_user(request, db)
        if not user or not can_access_organization(db, user, project.organization_id):
            raise HTTPException(status_code=403, detail="Este usuario nao possui acesso ao projeto.")
    attempts = rate_limit.password_attempts("share_link", token, request)
    attempts.enforce()
    if not link.password_hash or not password_hash.verify(password, link.password_hash):
        attempts.register_failure()
        raise HTTPException(status_code=403, detail="Senha invalida.")
    attempts.clear()
    version = latest_version(db, project.id, published_only=True)
    if not version:
        raise HTTPException(status_code=404, detail="Mapa nao publicado.")
    link.last_used_at = utcnow()
    link.access_count += 1
    db.commit()
    response = shared_map_response(project, version, allow_edit=link.allow_edit, link=link)
    response.set_cookie(
        share_unlock_cookie_name(link),
        share_unlock_value(link),
        max_age=8 * 3600,
        httponly=True,
        secure=os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true",
        samesite="lax",
        path="/",
    )
    return response


@app.post("/api/shared-edit-proposals/{share_link_id}", status_code=201)
def create_shared_edit_proposal(share_link_id: str, payload: SharedEditProposalCreate, request: Request, db: DbSession = Depends(get_db)):
    link = db.get(ShareLink, share_link_id)
    if not link or not link.active or not link.allow_edit:
        raise HTTPException(status_code=404, detail="Edicao nao esta disponivel para este link.")
    if link.expires_at and link.expires_at <= utcnow():
        raise HTTPException(status_code=410, detail="Este link expirou.")
    project = db.get(Project, link.project_id)
    version = latest_version(db, link.project_id, published_only=True)
    if not project or project.status != "published" or not version:
        raise HTTPException(status_code=404, detail="Mapa nao publicado.")
    actor = authenticated_request_user(request, db)
    if link.access_mode == "private" and (not actor or not can_access_organization(db, actor, project.organization_id)):
        raise HTTPException(status_code=403, detail="Entre com um usuario autorizado para enviar alteracoes.")
    if link.password_hash and not share_is_unlocked(request, link):
        raise HTTPException(status_code=403, detail="Desbloqueie o mapa com a senha antes de enviar alteracoes.")
    proposal = EditProposal(
        project_id=project.id,
        base_project_version_id=version.id,
        proposed_by_user_id=actor.id if actor else None,
        share_link_id=link.id,
        title=payload.title.strip(),
        summary=payload.summary,
        changes_json=json.dumps(payload.changes, ensure_ascii=False),
    )
    db.add(proposal)
    db.flush()
    audit(db, "edit_proposal_created", "edit_proposal", actor=actor, target_id=proposal.id, organization_id=project.organization_id)
    db.commit()
    return {"proposal": {"id": proposal.id, "status": proposal.status, "created_at": proposal.created_at.isoformat()}}


@app.get("/api/activity")
def list_activity(limit: int = Query(50, ge=1, le=100), user: User = Depends(require_platform_admin), db: DbSession = Depends(get_db)):
    rows = db.query(AuditEvent, User).outerjoin(User, AuditEvent.actor_user_id == User.id).order_by(AuditEvent.created_at.desc()).limit(limit).all()
    return {"events": [
        {"id": event.id, "action": event.action, "target_type": event.target_type, "target_id": event.target_id,
         "organization_id": event.organization_id, "details": event.details, "created_at": event.created_at.isoformat(),
         "actor_name": actor.name if actor else "Sistema"}
        for event, actor in rows
    ]}


@app.patch("/api/profile")
def update_profile(payload: ProfilePayload, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    user.name = payload.name.strip()
    audit(db, "profile_updated", "user", actor=user, target_id=user.id)
    db.commit()
    return {"user": user_data(user)}


@app.post("/api/organizations/{organization_id}/projects", status_code=201)
def create_project(organization_id: str, payload: ProjectPayload, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    if not db.get(Organization, organization_id):
        raise HTTPException(status_code=404, detail="Cliente nao encontrado.")
    if not can_manage_organization(db, user, organization_id):
        raise HTTPException(status_code=403, detail="Sem permissao para criar projeto para este cliente.")
    slug = normalize_slug(payload.slug, 100)
    if db.query(Project).filter(Project.slug == slug).first():
        raise HTTPException(status_code=409, detail="Esse identificador de projeto ja esta em uso.")
    project = Project(organization_id=organization_id, name=payload.name.strip(), slug=slug, description=payload.description)
    db.add(project)
    db.flush()
    audit(db, "project_created", "project", actor=user, target_id=project.id, organization_id=organization_id)
    db.commit()
    return {"project": project_data(project)}


@app.post("/converter")
async def converter(arquivo: UploadFile = File(...), rotate: str = Query("auto"),
                    area_min: float = Query(800), area_max: float = Query(9000),
                    title: str = Query("Mapa NexoLote"),
                    quality: str = Query("balanced")):
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = os.path.join(tmp, "in.pdf")
        out_html = os.path.join(tmp, "out.html")
        with open(pdf_path, "wb") as fh:
            fh.write(await arquivo.read())
        try:
            info = pdf_to_map.convert(pdf_path, out_html, rotate=rotate, area_min=area_min, area_max=area_max, title=title, quality=quality)
        except SystemExit as exc:
            return JSONResponse({"erro": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"erro": "Nao consegui processar este arquivo (%s)." % type(exc).__name__}, status_code=400)
        html = open(out_html, encoding="utf-8").read()
    return HTMLResponse(content=html, headers={"X-Mapa-Info": json.dumps(info, ensure_ascii=False)})


def converter_job_path(job_id: str, filename: str) -> str:
    return os.path.join(CONVERTER_JOB_DIR, job_id, filename)


def write_converter_job(job_id: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(converter_job_path(job_id, "job.json")), exist_ok=True)
    temp_path = converter_job_path(job_id, "job.json.tmp")
    with open(temp_path, "w", encoding="utf-8") as job_file:
        json.dump(payload, job_file, ensure_ascii=False)
    os.replace(temp_path, converter_job_path(job_id, "job.json"))


def read_converter_job(job_id: str) -> dict:
    if not re.fullmatch(r"[a-f0-9]{32}", job_id):
        raise HTTPException(status_code=404, detail="Processamento nao encontrado.")
    path = converter_job_path(job_id, "job.json")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Processamento nao encontrado.")
    with open(path, "r", encoding="utf-8") as job_file:
        return json.load(job_file)


_PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _safe_project_id(value: str | None) -> str | None:
    """So aceita identificador opaco. O valor e interpolado dentro de <script>."""
    if value and _PROJECT_ID_RE.match(value):
        return value
    return None


def _is_job_owner(job: dict, token: str | None) -> bool:
    """Confere o token de quem enviou o PDF contra o hash gravado no job."""
    stored = job.get("owner_token_hash")
    if not stored or not token:
        return False
    return secrets.compare_digest(stored, hash_token(token))


_JOB_PRIVATE_KEYS = ("password_hash", "owner_token_hash")


def converter_job_data(job: dict, request: Request | None = None) -> dict:
    payload = {key: value for key, value in job.items() if key not in _JOB_PRIVATE_KEYS}
    payload["has_password"] = bool(job.get("password_hash"))
    if job.get("share_token"):
        path = f"/map/{job['share_token']}"
        payload["share_url"] = path
    return payload


def update_converter_job(job_id: str, *, status_value: str, progress: int, step: str,
                         info: dict | None = None, error: str | None = None) -> None:
    job = read_converter_job(job_id)
    job.update({"status": status_value, "progress": progress, "current_step": step})
    logs = job.setdefault("logs", [])
    if not logs or logs[-1] != step:
        logs.append(step)
    if info is not None:
        job["info"] = info
    if error is not None:
        job["error"] = error
    write_converter_job(job_id, job)


def run_converter_job(job_id: str, title: str, quality: str) -> None:
    try:
        update_converter_job(
            job_id,
            status_value="processing",
            progress=18,
            step="PDF recebido. Preparando o arquivo.",
        )
        update_converter_job(
            job_id,
            status_value="processing",
            progress=32,
            step="Analisando linhas, textos e limites dos lotes.",
        )
        info = pdf_to_map.convert(
            converter_job_path(job_id, "source.pdf"),
            converter_job_path(job_id, "map.html"),
            title=title,
            quality=quality,
        )
        update_converter_job(
            job_id,
            status_value="processing",
            progress=92,
            step="Finalizando o mapa e preparando o editor.",
        )
        lot_count = int(info.get("lotes", 0))
        update_converter_job(
            job_id,
            status_value="completed",
            progress=100,
            step=f"Mapa concluido com {lot_count} lotes.",
            info=info,
        )
    except Exception as exc:
        update_converter_job(
            job_id,
            status_value="failed",
            progress=100,
            step="O processamento nao foi concluido.",
            error=f"{type(exc).__name__}: {exc}",
        )


@app.post("/converter/jobs", status_code=202)
async def create_converter_job(background_tasks: BackgroundTasks, arquivo: UploadFile = File(...),
                               title: str = Query("Mapa NexoLote"),
                               quality: str = Query("balanced"),
                               project_id: str | None = Query(default=None),
                               project_slug: str | None = Query(default=None)):
    filename = arquivo.filename or ""
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=422, detail="Envie um arquivo PDF.")
    if quality not in {"light", "balanced", "sharp", "high", "optimized"}:
        raise HTTPException(status_code=422, detail="Qualidade invalida.")

    job_id = uuid.uuid4().hex
    job_dir = os.path.dirname(converter_job_path(job_id, "source.pdf"))
    os.makedirs(job_dir, exist_ok=True)
    max_bytes = int(os.getenv("MAX_UPLOAD_BYTES", str(80 * 1024 * 1024)))
    size = 0
    with open(converter_job_path(job_id, "source.pdf"), "wb") as pdf_file:
        while chunk := await arquivo.read(1024 * 1024):
            size += len(chunk)
            if size > max_bytes:
                pdf_file.close()
                shutil.rmtree(job_dir, ignore_errors=True)
                raise HTTPException(status_code=413, detail="Arquivo excede o limite de upload.")
            pdf_file.write(chunk)
    with open(converter_job_path(job_id, "source.pdf"), "rb") as pdf_file:
        if pdf_file.read(5) != b"%PDF-":
            shutil.rmtree(job_dir, ignore_errors=True)
            raise HTTPException(status_code=422, detail="O arquivo enviado nao e um PDF valido.")

    # Sem dono, qualquer pessoa com o job_id podia publicar, despublicar e trocar
    # a senha do mapa alheio. O token fica so com quem enviou o PDF; no disco
    # guardamos apenas o hash.
    owner_token = secrets.token_urlsafe(32)
    job = {
        "id": job_id,
        "status": "queued",
        "progress": 8,
        "current_step": "PDF enviado. Processamento iniciado.",
        "logs": ["PDF enviado. Processamento iniciado."],
        "filename": filename,
        "quality": quality,
        "project_id": _safe_project_id(project_id),
        "project_slug": project_slug,
        "published": False,
        "allow_edit": False,
        "owner_token_hash": hash_token(owner_token),
        "map_url": f"/converter/jobs/{job_id}/map?token={owner_token}",
    }
    write_converter_job(job_id, job)
    background_tasks.add_task(run_converter_job, job_id, title.strip() or "Mapa NexoLote", quality)
    return {"job": {**converter_job_data(job, None), "owner_token": owner_token,
                    "map_url": job["map_url"]}}


@app.get("/converter/jobs/{job_id}")
def get_converter_job(job_id: str, request: Request):
    return {"job": converter_job_data(read_converter_job(job_id), request)}


def _js_literal(value) -> str:
    """Serializa para dentro de <script>.

    json.dumps sozinho nao escapa ``</``: um valor contendo ``</script>`` fecha o
    bloco e injeta HTML arbitrario na pagina.
    """
    return (json.dumps(value)
            .replace("</", "<\\/")
            .replace(" ", "\\u2028")
            .replace(" ", "\\u2029"))


def converter_editor_controls(job: dict, owner_token: str | None = None) -> str:
    job_id = _js_literal(job["id"])
    project_id = _js_literal(job.get("project_id"))
    owner_query = _js_literal("?token=%s" % owner_token if owner_token else "")
    return f"""
<style id="maplot-project-controls-style">
  #maplot-project-bar{{position:fixed;z-index:70;top:12px;left:calc(var(--side-w,356px) + 58px);display:flex;align-items:center;gap:8px;padding:6px;border:1px solid #34424b;border-radius:8px;background:rgba(14,22,27,.96);box-shadow:0 14px 36px rgba(0,0,0,.28);font:500 12px system-ui;color:#e9f2ee}}
  #maplot-project-bar button{{height:34px;border:1px solid #3b4a54;border-radius:6px;background:#1b252c;color:#eef5f1;padding:0 11px;font:500 12px system-ui;cursor:pointer}}
  #maplot-project-bar button:hover{{background:#26333b}}
  #maplot-project-bar .primary{{border-color:#35d894;background:#35d894;color:#06291b}}
  #maplot-project-status{{display:flex;align-items:center;gap:7px;padding:0 7px;color:#aebcc3;white-space:nowrap}}
  #maplot-project-status i{{width:7px;height:7px;border-radius:50%;background:#70808a}}
  #maplot-project-status.published i{{background:#35d894}}
  #maplot-share-panel{{position:fixed;z-index:71;top:64px;right:18px;width:min(350px,calc(100vw - 36px));border:1px solid #34424b;border-radius:8px;background:#10191f;box-shadow:0 24px 70px rgba(0,0,0,.42);padding:18px;font:500 13px/1.45 system-ui;color:#eef5f1}}
  #maplot-share-panel[hidden]{{display:none}}
  #maplot-share-panel header{{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:18px}}
  #maplot-share-panel h2{{margin:0;font:500 17px/1.2 system-ui}}
  #maplot-share-panel p{{margin:5px 0 0;color:#91a2ab;font:400 12px/1.5 system-ui}}
  #maplot-share-panel .close{{border:0;background:transparent;color:#aebcc3;font-size:20px;cursor:pointer}}
  #maplot-share-panel label.field{{display:block;margin-top:15px;color:#c8d4d9}}
  #maplot-share-panel input[type=password],#maplot-share-link{{width:100%;height:40px;margin-top:7px;border:1px solid #3a4952;border-radius:6px;background:#081115;color:#f2f7f4;padding:0 11px;outline:none}}
  #maplot-share-panel input:focus{{border-color:#35d894}}
  #maplot-share-panel .toggle-row{{display:flex;align-items:center;justify-content:space-between;gap:18px;margin-top:14px;padding:12px;border:1px solid #2c3941;border-radius:7px;background:#0c151a}}
  #maplot-share-panel input[type=checkbox]{{width:18px;height:18px;accent-color:#35d894}}
  #maplot-share-actions{{display:grid;grid-template-columns:1fr auto;gap:8px;margin-top:18px}}
  #maplot-share-actions button,#maplot-copy-link{{height:40px;border:1px solid #3a4952;border-radius:6px;background:#1c2830;color:#eef5f1;padding:0 13px;font:500 12px system-ui;cursor:pointer}}
  #maplot-share-actions .primary{{border-color:#35d894;background:#35d894;color:#06291b}}
  #maplot-link-wrap{{display:none;margin-top:16px;padding-top:16px;border-top:1px solid #2d3a42}}
  #maplot-link-wrap.visible{{display:block}}
  #maplot-link-row{{display:grid;grid-template-columns:1fr auto;gap:8px}}
  #maplot-share-feedback{{min-height:18px;margin-top:10px;color:#91e9c3;font:400 12px system-ui}}
  @media(max-width:850px){{#maplot-project-bar{{left:12px;right:12px;top:auto;bottom:12px;justify-content:space-between}}#maplot-project-status{{display:none}}#maplot-share-panel{{top:12px;right:12px}}}}
</style>
<nav id="maplot-project-bar" aria-label="Acoes do projeto">
  <button id="maplot-back-project" type="button">&#8592; Voltar ao projeto</button>
  <span id="maplot-project-status"><i></i><span>Rascunho</span></span>
  <button id="maplot-open-share" class="primary" type="button">Compartilhar</button>
</nav>
<aside id="maplot-share-panel" hidden aria-label="Publicacao e compartilhamento">
  <header><div><h2>Publicar mapa</h2><p>Configure o acesso do cliente sem sair do editor.</p></div><button class="close" id="maplot-close-share" type="button" aria-label="Fechar">&times;</button></header>
  <label class="toggle-row"><span><strong>Permitir edicao</strong><small style="display:block;color:#91a2ab;margin-top:3px">O cliente recebe o editor completo.</small></span><input id="maplot-allow-edit" type="checkbox"></label>
  <label class="toggle-row"><span><strong>Proteger com senha</strong><small style="display:block;color:#91a2ab;margin-top:3px">Exige senha antes de abrir o mapa.</small></span><input id="maplot-require-password" type="checkbox"></label>
  <label class="field" id="maplot-password-field" hidden>Senha do link<input id="maplot-share-password" type="password" minlength="4" placeholder="Defina uma senha"></label>
  <div id="maplot-share-actions"><button id="maplot-cancel-share" type="button">Cancelar</button><button id="maplot-publish" class="primary" type="button">Publicar e gerar link</button></div>
  <div id="maplot-link-wrap"><label class="field">Link do cliente</label><div id="maplot-link-row"><input id="maplot-share-link" readonly><button id="maplot-copy-link" type="button">Copiar</button></div></div>
  <div id="maplot-share-feedback" role="status"></div>
</aside>
<script id="maplot-project-controls-script">
(function(){{
  var jobId={job_id}, projectId={project_id}, ownerQuery={owner_query};
  var panel=document.getElementById('maplot-share-panel');
  var status=document.getElementById('maplot-project-status');
  var allowEdit=document.getElementById('maplot-allow-edit');
  var requirePassword=document.getElementById('maplot-require-password');
  var passwordField=document.getElementById('maplot-password-field');
  var password=document.getElementById('maplot-share-password');
  var linkWrap=document.getElementById('maplot-link-wrap');
  var linkInput=document.getElementById('maplot-share-link');
  var feedback=document.getElementById('maplot-share-feedback');
  var hasExistingPassword=false;
  function closePanel(){{panel.hidden=true}}
  function updateStatus(job){{
    hasExistingPassword=!!job.has_password;
    allowEdit.checked=!!job.allow_edit;
    requirePassword.checked=hasExistingPassword;
    passwordField.hidden=!requirePassword.checked;
    if(job.published){{status.classList.add('published');status.querySelector('span').textContent='Publicado'}}
    if(job.share_url){{job.share_url=job.share_url.charAt(0)==='/'?location.origin+job.share_url:job.share_url;linkInput.value=job.share_url;linkWrap.classList.add('visible')}}
  }}
  function updateLocalProject(job){{
    if(!projectId)return;
    try{{
      var key='maplot.workspace.v2', workspace=JSON.parse(localStorage.getItem(key)||'null');
      if(!workspace||!Array.isArray(workspace.projects))return;
      workspace.projects=workspace.projects.map(function(project){{
        if(project.id!==projectId)return project;
        return Object.assign({{}},project,{{status:'published',version:Math.max(Number(project.version)||0,1),allowEdit:!!job.allow_edit,visibility:job.has_password?'password':'unlisted',passwordEnabled:!!job.has_password,shareUrl:job.share_url,updatedAt:'Agora'}});
      }});
      localStorage.setItem(key,JSON.stringify(workspace));
    }}catch(error){{}}
  }}
  document.getElementById('maplot-back-project').onclick=function(){{
    if(projectId)location.href='/app/projetos/'+encodeURIComponent(projectId);
    else if(history.length>1)history.back();
    else location.href='/app';
  }};
  document.getElementById('maplot-open-share').onclick=function(){{panel.hidden=false;passwordField.hidden=!requirePassword.checked}};
  document.getElementById('maplot-close-share').onclick=closePanel;
  document.getElementById('maplot-cancel-share').onclick=closePanel;
  requirePassword.onchange=function(){{passwordField.hidden=!this.checked;if(!this.checked)password.value=''}};
  document.getElementById('maplot-publish').onclick=async function(){{
    var button=this;
    if(requirePassword.checked&&!password.value&&!hasExistingPassword){{feedback.textContent='Defina uma senha para proteger o link.';password.focus();return}}
    button.disabled=true;button.textContent='Publicando...';feedback.textContent='';
    try{{
      var response=await fetch('/converter/jobs/'+jobId+'/publish'+ownerQuery,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{allow_edit:allowEdit.checked,require_password:requirePassword.checked,password:password.value||null}})}});
      var data=await response.json();
      if(!response.ok)throw new Error(data.detail||'Nao foi possivel publicar.');
      updateStatus(data.job);updateLocalProject(data.job);password.value='';feedback.textContent='Mapa publicado. Link pronto para envio.';
      button.textContent='Atualizar publicacao';
    }}catch(error){{feedback.textContent=error.message;button.textContent='Publicar e gerar link'}}finally{{button.disabled=false}}
  }};
  document.getElementById('maplot-copy-link').onclick=async function(){{
    try{{await navigator.clipboard.writeText(linkInput.value);feedback.textContent='Link copiado.'}}
    catch(error){{linkInput.select();feedback.textContent='Selecione e copie o link acima.'}}
  }};
  fetch('/converter/jobs/'+jobId,{{cache:'no-store'}}).then(function(response){{return response.json()}}).then(function(data){{updateStatus(data.job)}}).catch(function(){{}});
}})();
</script>
"""


def converter_map_html(job: dict, include_controls: bool, allow_edit: bool = True,
                       owner_token: str | None = None) -> str:
    map_path = converter_job_path(job["id"], "map.html")
    with open(map_path, "r", encoding="utf-8") as map_file:
        html = map_file.read()
    additions = converter_editor_controls(job, owner_token) if include_controls else ""
    if not allow_edit:
        additions += pdf_to_map.viewer_guard_html()
    return html.replace("</body>", additions + "</body>", 1)


@app.get("/converter/jobs/{job_id}/map")
def open_converter_job_map(job_id: str, project_id: str | None = Query(default=None),
                           token: str | None = Query(default=None)):
    job = read_converter_job(job_id)
    map_path = converter_job_path(job_id, "map.html")
    if job.get("status") != "completed" or not os.path.isfile(map_path):
        raise HTTPException(status_code=409, detail="O mapa ainda nao esta pronto.")
    is_owner = _is_job_owner(job, token)
    # Sem o token de dono o mapa continua visivel, mas sem a barra que publica,
    # despublica e troca a senha — e sem poder gravar nada no job.
    safe_project_id = _safe_project_id(project_id)
    if is_owner and safe_project_id and job.get("project_id") != safe_project_id:
        job["project_id"] = safe_project_id
        write_converter_job(job_id, job)
    return HTMLResponse(
        converter_map_html(job, include_controls=is_owner, owner_token=token if is_owner else None),
        headers={"Cache-Control": "no-store"})


@app.post("/converter/jobs/{job_id}/publish")
def publish_converter_job(job_id: str, payload: ConverterPublishPayload, request: Request,
                          token: str | None = Query(default=None)):
    job = read_converter_job(job_id)
    if not _is_job_owner(job, token):
        raise HTTPException(status_code=403, detail="Somente quem enviou o PDF pode publicar este mapa.")
    if job.get("status") != "completed":
        raise HTTPException(status_code=409, detail="Conclua o processamento antes de publicar.")
    if not payload.published:
        job["published"] = False
        job["allow_edit"] = False
        job.pop("password_hash", None)
        job.pop("share_token", None)
        job.pop("project_id", None)
        write_converter_job(job_id, job)
        return {"job": converter_job_data(job, request)}
    if payload.require_password and not payload.password and not job.get("password_hash"):
        raise HTTPException(status_code=422, detail="Defina uma senha para proteger o link.")
    if payload.require_password and payload.password:
        job["password_hash"] = password_hash.hash(payload.password)
    elif not payload.require_password:
        job.pop("password_hash", None)
    job["allow_edit"] = payload.allow_edit
    job["published"] = True
    job["share_token"] = job.get("share_token") or secrets.token_urlsafe(20)
    write_converter_job(job_id, job)
    return {"job": converter_job_data(job, request)}


def find_converter_job_by_token(token: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,80}", token) or not os.path.isdir(CONVERTER_JOB_DIR):
        raise HTTPException(status_code=404, detail="Mapa nao encontrado.")
    for entry in os.scandir(CONVERTER_JOB_DIR):
        if not entry.is_dir():
            continue
        try:
            job = read_converter_job(entry.name)
        except (HTTPException, OSError, ValueError, json.JSONDecodeError):
            continue
        if job.get("published") and secrets.compare_digest(str(job.get("share_token", "")), token):
            return job
    raise HTTPException(status_code=404, detail="Mapa nao encontrado.")


def converter_password_page(token: str, error: str = "", status_code: int = 200,
                            headers: dict | None = None) -> HTMLResponse:
    error_html = f'<p style="color:#b42318">{error}</p>' if error else ""
    return HTMLResponse(status_code=status_code, headers=headers, content=f"""<!doctype html><html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Mapa protegido</title><body style="margin:0;background:#081014;color:#f4f7f5;font:15px system-ui"><form method="post" style="width:min(420px,calc(100% - 32px));margin:15vh auto;padding:28px;border:1px solid #31404a;border-radius:8px;background:#10191f"><p style="color:#35d894;text-transform:uppercase;font-size:11px;letter-spacing:.16em">acesso protegido</p><h1 style="font-size:25px;font-weight:500">Digite a senha do mapa</h1><p style="color:#9babb3">Use a senha enviada junto com o link.</p>{error_html}<input name="password" type="password" required autofocus style="width:100%;box-sizing:border-box;padding:12px;border:1px solid #41515b;border-radius:6px;background:#081014;color:white"><button style="width:100%;margin-top:12px;padding:12px;border:0;border-radius:6px;background:#35d894;color:#06291b;font-weight:600">Abrir mapa</button></form></body></html>""")


@app.get("/map/{token}")
def shared_converter_map(token: str):
    job = find_converter_job_by_token(token)
    if job.get("password_hash"):
        return converter_password_page(token)
    return HTMLResponse(converter_map_html(job, include_controls=False, allow_edit=bool(job.get("allow_edit"))), headers={"Cache-Control": "no-store"})


@app.post("/map/{token}")
def unlock_shared_converter_map(token: str, request: Request, password: str = Form(...)):
    attempts = rate_limit.password_attempts("converter_map", token, request)
    # Aqui o formulario e HTML, entao o bloqueio volta como pagina de senha com
    # 429 em vez do JSON de erro que os outros endpoints usam.
    blocked_for = attempts.retry_after()
    if blocked_for:
        return converter_password_page(
            token, rate_limit.blocked_message(blocked_for),
            status_code=429, headers={"Retry-After": str(blocked_for)},
        )
    job = find_converter_job_by_token(token)
    if not job.get("password_hash") or not password_hash.verify(password, job["password_hash"]):
        attempts.register_failure()
        return converter_password_page(token, "Senha incorreta.")
    attempts.clear()
    return HTMLResponse(converter_map_html(job, include_controls=False, allow_edit=bool(job.get("allow_edit"))), headers={"Cache-Control": "no-store"})


@app.post("/render")
async def render(payload: dict = Body(...)):
    try:
        html = pdf_to_map.build_html(
            payload["img"], int(payload["w"]), int(payload["h"]), payload.get("lots", []),
            payload.get("title", "Mapa NexoLote"), payload.get("img_mime", "image/jpeg"),
            payload.get("opacity", pdf_to_map.DEFAULT_OPACITY),
            payload.get("stroke_width", pdf_to_map.DEFAULT_STROKE_WIDTH),
            payload.get("label_mode", pdf_to_map.DEFAULT_LABEL_MODE),
        )
    except Exception as exc:
        return JSONResponse({"erro": str(exc)}, status_code=400)
    return HTMLResponse(content=html)


# Registrada por ultimo de proposito: o Starlette casa as rotas na ordem de
# definicao, entao toda rota explicita acima continua ganhando desta.
@app.get("/{filename}")
def frontend_public_asset(filename: str):
    resposta = _frontend_public_file(filename)
    if resposta is None:
        raise HTTPException(status_code=404, detail="Arquivo nao encontrado.")
    return resposta

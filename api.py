#!/usr/bin/env python3
"""API do Mapa de Disponibilidade e portal autenticado."""
import json
import os
import re
import secrets
import shutil
import tempfile
import unicodedata
from datetime import datetime

from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session as DbSession

import pdf_to_map
from auth import audit, clear_session, current_user, hash_token, normalize_email, password_hash, require_platform_admin, set_session
from database import Base, engine, get_db
from models import Membership, Organization, Project, ProjectVersion, Session, ShareLink, User, utcnow

app = FastAPI(title="Mapa de Disponibilidade")
HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.getenv("DATA_DIR", "/data")


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


class MemberPayload(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    role: str = Field(default="client_member", pattern=r"^(client_admin|client_member)$")


@app.on_event("startup")
def initialize_database():
    Base.metadata.create_all(bind=engine)
    columns = {column["name"] for column in inspect(engine).get_columns("projects")}
    if "client_can_edit" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE projects ADD COLUMN client_can_edit BOOLEAN NOT NULL DEFAULT FALSE"))


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


@app.get("/health")
def health(db: DbSession = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/")
def home():
    return FileResponse(os.path.join(HERE, "index.html"))


@app.get("/login")
def login_page():
    return FileResponse(os.path.join(HERE, "login.html"))


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
      '<label class="field" style="display:flex;grid-template-columns:auto 1fr;align-items:center;gap:10px;margin-top:12px"><input id="clientCanEdit" type="checkbox"><span>Permitir edicao pelo cliente</span></label>' +
      '<p style="margin:10px 0 0;font-size:12px">Desligado por padrao: o cliente abre somente o mapa, sem lista, ferramentas ou edicao.</p>' +
      '<div class="actions" style="margin-top:13px"><button class="primary">Salvar acesso</button></div><div class="error" id="deliveryError"></div>';
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


@app.get("/app")
def portal_page():
    with open(os.path.join(HERE, "portal.html"), "r", encoding="utf-8") as portal_file:
        return HTMLResponse(portal_file.read() + PORTAL_DELIVERY_CONTROLS)


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
def login(payload: LoginPayload, response: Response, db: DbSession = Depends(get_db)):
    email = validate_email(payload.email)
    user = db.query(User).filter(User.email == email).first()
    if not user or not user.active or not password_hash.verify(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Email ou senha invalidos.")
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
            "share_links": [{"id": link.id, "has_password": bool(link.password_hash), "url": f"/s/{link.token}" if link.token else f"/p/{project.slug}"} for link in links]}


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
    return {"url": f"/p/{project.slug}", "version_id": version.id}


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


def shared_map_response(project: Project, version: ProjectVersion):
    if not os.path.isfile(version.map_html_path):
        raise HTTPException(status_code=404, detail="Arquivo do mapa nao encontrado.")
    if project.client_can_edit:
        return FileResponse(version.map_html_path, media_type="text/html")
    with open(version.map_html_path, "r", encoding="utf-8") as map_file:
        html = map_file.read()
    viewer_guard = """<style id=\"shared-viewer\">#side,#sideToggle,#edit,#editor,#draft,#vertices{display:none!important}#lots{pointer-events:none!important}.lot{cursor:default!important}</style><script>window.addEventListener('DOMContentLoaded',function(){var app=document.getElementById('app');if(app)app.classList.add('shared-viewer');});</script>"""
    html = html.replace("</head>", viewer_guard + "</head>", 1)
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@app.get("/p/{slug}")
def public_project_map(slug: str, db: DbSession = Depends(get_db)):
    project = db.query(Project).filter(Project.slug == slug, Project.status == "published", Project.access_mode == "public").first()
    if not project:
        raise HTTPException(status_code=404, detail="Mapa nao esta publico.")
    version = latest_version(db, project.id, published_only=True)
    if not version:
        raise HTTPException(status_code=404, detail="Mapa nao encontrado.")
    return shared_map_response(project, version)


@app.get("/s/{token}")
def shared_project_map(token: str, db: DbSession = Depends(get_db)):
    link = db.query(ShareLink).filter(ShareLink.token == token, ShareLink.active.is_(True)).first()
    if not link:
        raise HTTPException(status_code=404, detail="Link nao encontrado.")
    project = db.get(Project, link.project_id)
    version = latest_version(db, project.id, published_only=True)
    if not version:
        raise HTTPException(status_code=404, detail="Mapa nao publicado.")
    if link.password_hash:
        return HTMLResponse('<form method="post" style="font:16px system-ui;max-width:360px;margin:15vh auto"><h1>Acesso protegido</h1><input name="password" type="password" placeholder="Senha" required style="width:100%;padding:12px"><button style="margin-top:12px;padding:12px">Abrir mapa</button></form>')
    return shared_map_response(project, version)


@app.post("/s/{token}")
def unlock_shared_project(token: str, password: str = Form(...), db: DbSession = Depends(get_db)):
    link = db.query(ShareLink).filter(ShareLink.token == token, ShareLink.active.is_(True)).first()
    if not link or not link.password_hash or not password_hash.verify(password, link.password_hash):
        raise HTTPException(status_code=403, detail="Senha invalida.")
    project = db.get(Project, link.project_id)
    version = latest_version(db, project.id, published_only=True)
    if not version:
        raise HTTPException(status_code=404, detail="Mapa nao publicado.")
    return shared_map_response(project, version)


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
                    title: str = Query("Mapa de Disponibilidade"),
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


@app.post("/render")
async def render(payload: dict = Body(...)):
    try:
        html = pdf_to_map.build_html(
            payload["img"], int(payload["w"]), int(payload["h"]), payload.get("lots", []),
            payload.get("title", "Mapa de Disponibilidade"), payload.get("img_mime", "image/jpeg"),
            payload.get("opacity", pdf_to_map.DEFAULT_OPACITY),
            payload.get("stroke_width", pdf_to_map.DEFAULT_STROKE_WIDTH),
            payload.get("label_mode", pdf_to_map.DEFAULT_LABEL_MODE),
        )
    except Exception as exc:
        return JSONResponse({"erro": str(exc)}, status_code=400)
    return HTMLResponse(content=html)

#!/usr/bin/env python3
"""API do Mapa de Disponibilidade e portal autenticado."""
import json
import os
import re
import secrets
import tempfile
import unicodedata
from datetime import datetime

from fastapi import Body, Depends, FastAPI, File, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session as DbSession

import pdf_to_map
from auth import audit, clear_session, current_user, normalize_email, password_hash, require_platform_admin, set_session
from database import Base, engine, get_db
from models import Membership, Organization, Project, Session, User, utcnow

app = FastAPI(title="Mapa de Disponibilidade")
HERE = os.path.dirname(os.path.abspath(__file__))


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


class MemberPayload(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    role: str = Field(default="client_member", pattern=r"^(client_admin|client_member)$")


@app.on_event("startup")
def initialize_database():
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
        "description": project.description,
        "updated_at": project.updated_at.isoformat(),
    }


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


@app.get("/app")
def portal_page():
    return FileResponse(os.path.join(HERE, "portal.html"))


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

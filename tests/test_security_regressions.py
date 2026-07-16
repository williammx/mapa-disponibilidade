from datetime import timedelta

import pytest
from fastapi import HTTPException, Request
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api import client_portal_spa, shared_project_map, unlock_shared_project
from app_v1.api import create_processing_job
from auth import password_hash
from database import Base
from models import FileAsset, Organization, Project, ProjectVersion, ShareLink, User, utcnow


def request(path: str) -> Request:
    return Request({
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "https",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [(b"host", b"map.example.com")],
        "client": ("127.0.0.1", 1234),
        "server": ("map.example.com", 443),
    })


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def make_project(db, slug: str = "mapa-teste"):
    organization = Organization(name="Cliente", slug=f"cliente-{slug}")
    user = User(name="Admin", email=f"{slug}@example.com", password_hash="x", platform_role="platform_admin")
    db.add_all([organization, user])
    db.flush()
    project = Project(organization_id=organization.id, name="Mapa", slug=slug, status="published")
    db.add(project)
    db.flush()
    db.add(ProjectVersion(project_id=project.id, map_html_path="/tmp/map.html", lot_count=1, is_published=True))
    db.commit()
    return organization, user, project


def test_client_portal_has_a_direct_spa_entrypoint():
    response = client_portal_spa()
    assert response.path.endswith("index.html")


def test_processing_job_rejects_a_source_file_from_another_project(db):
    organization, user, project = make_project(db, "principal")
    other = Project(organization_id=organization.id, name="Outro", slug="outro")
    db.add(other)
    db.flush()
    foreign_asset = FileAsset(
        organization_id=organization.id,
        project_id=other.id,
        kind="source_pdf",
        original_name="mapa.pdf",
        storage_key="foreign/mapa.pdf",
        size_bytes=10,
        checksum_sha256="0" * 64,
    )
    db.add(foreign_asset)
    db.commit()

    with pytest.raises(HTTPException) as error:
        create_processing_job(project.id, foreign_asset.id, "balanced", user, db)

    assert error.value.status_code == 409


def test_expired_share_link_is_rejected_before_map_delivery(db):
    _, _, project = make_project(db, "expirado")
    link = ShareLink(
        project_id=project.id,
        token="expired-token",
        token_hash="1" * 64,
        expires_at=utcnow() - timedelta(minutes=1),
    )
    db.add(link)
    db.commit()

    with pytest.raises(HTTPException) as error:
        shared_project_map(link.token, request(f"/s/{link.token}"), db)

    assert error.value.status_code == 410


def test_private_password_link_still_requires_an_authenticated_member(db):
    _, _, project = make_project(db, "privado")
    link = ShareLink(
        project_id=project.id,
        token="private-token",
        token_hash="2" * 64,
        password_hash=password_hash.hash("senha-segura"),
        access_mode="private",
    )
    db.add(link)
    db.commit()

    with pytest.raises(HTTPException) as error:
        unlock_shared_project(link.token, request(f"/s/{link.token}"), "senha-segura", db)

    assert error.value.status_code == 403

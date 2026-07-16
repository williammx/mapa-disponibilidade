from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app_v1.api import publish_project_delivery
from app_v1.schemas import ProjectPublishPayload
from database import Base
from models import Organization, Project, ProjectVersion, ShareLink, User


def make_request() -> Request:
    return Request({
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/api/v1/projects/project/publish",
        "raw_path": b"/api/v1/projects/project/publish",
        "query_string": b"",
        "headers": [(b"host", b"map.example.com")],
        "client": ("127.0.0.1", 1234),
        "server": ("map.example.com", 443),
    })


def make_proxy_request() -> Request:
    return Request({
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/projects/project/publish",
        "raw_path": b"/api/v1/projects/project/publish",
        "query_string": b"",
        "headers": [
            (b"host", b"127.0.0.1:8000"),
            (b"x-forwarded-proto", b"https"),
            (b"x-forwarded-host", b"map.example.com"),
        ],
        "client": ("127.0.0.1", 1234),
        "server": ("127.0.0.1", 8000),
    })


def test_publish_project_keeps_the_existing_delivery_url_stable():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        organization = Organization(name="Cliente", slug="cliente")
        user = User(name="Admin", email="admin@example.com", password_hash="x", platform_role="platform_admin")
        db.add_all([organization, user])
        db.flush()
        project = Project(organization_id=organization.id, name="Mapa", slug="mapa-teste")
        db.add(project)
        db.flush()
        version = ProjectVersion(project_id=project.id, map_html_path="/data/map.html", lot_count=1509)
        old_link = ShareLink(project_id=project.id, token="old-token", token_hash="old-hash", active=True)
        db.add_all([version, old_link])
        db.commit()

        result = publish_project_delivery(
            project.id,
            ProjectPublishPayload(access_mode="unlisted", allow_edit=False),
            make_request(),
            user,
            db,
        )

        db.refresh(project)
        db.refresh(version)
        db.refresh(old_link)
        active_links = db.query(ShareLink).filter(ShareLink.project_id == project.id, ShareLink.active.is_(True)).all()

        assert project.status == "published"
        assert project.access_mode == "unlisted"
        assert version.is_published is True
        assert old_link.active is True
        assert len(active_links) == 1
        assert result["share_link"]["url"] == "https://map.example.com/s/old-token"
    finally:
        db.close()
        engine.dispose()


def test_public_publication_uses_project_slug_url():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        organization = Organization(name="Cliente", slug="cliente")
        user = User(name="Admin", email="admin@example.com", password_hash="x", platform_role="platform_admin")
        db.add_all([organization, user])
        db.flush()
        project = Project(organization_id=organization.id, name="Mapa", slug="mapa-publico")
        db.add(project)
        db.flush()
        db.add(ProjectVersion(project_id=project.id, map_html_path="/data/map.html", lot_count=10))
        db.commit()

        result = publish_project_delivery(
            project.id,
            ProjectPublishPayload(access_mode="public"),
            make_request(),
            user,
            db,
        )

        assert result["share_link"]["url"] == "https://map.example.com/mapas/mapa-publico"
    finally:
        db.close()
        engine.dispose()


def test_publication_uses_forwarded_https_address():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        organization = Organization(name="Cliente", slug="cliente")
        user = User(name="Admin", email="admin@example.com", password_hash="x", platform_role="platform_admin")
        db.add_all([organization, user])
        db.flush()
        project = Project(organization_id=organization.id, name="Mapa", slug="mapa-proxy")
        db.add(project)
        db.flush()
        db.add(ProjectVersion(project_id=project.id, map_html_path="/data/map.html", lot_count=10))
        db.commit()

        result = publish_project_delivery(
            project.id,
            ProjectPublishPayload(access_mode="public"),
            make_proxy_request(),
            user,
            db,
        )

        assert result["share_link"]["url"] == "https://map.example.com/mapas/mapa-proxy"
    finally:
        db.close()
        engine.dispose()

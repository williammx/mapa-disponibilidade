from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app_v1.api import project_workspace_dict
from database import Base
from models import Organization, Project, ProjectVersion, ShareLink


def test_persisted_project_is_serialized_for_the_react_workspace():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        organization = Organization(name="Teste 001", slug="teste-001")
        db.add(organization)
        db.flush()
        project = Project(
            organization_id=organization.id,
            name="Mapa Setor E",
            slug="mapa-setor-e",
            status="published",
            access_mode="link",
        )
        db.add(project)
        db.flush()
        db.add(ProjectVersion(
            project_id=project.id,
            map_html_path="/data/projects/map.html",
            lot_count=1509,
            quality="high",
            is_published=True,
        ))
        db.add(ShareLink(
            project_id=project.id,
            token="test-token",
            password_hash="hashed-password",
            active=True,
        ))
        db.commit()

        data = project_workspace_dict(db, project)

        assert data["client"] == "Teste 001"
        assert data["lots"] == 1509
        assert data["mapUrl"] == f"/projects/{project.id}/editor"
        assert data["processingStatus"] == "processed"
        assert data["visibility"] == "password"
        assert data["passwordEnabled"] is True
    finally:
        db.close()
        engine.dispose()

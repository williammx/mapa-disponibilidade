from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app_v1.api import get_organization, invite_organization_user
from app_v1.schemas import OrganizationInvite
from auth import password_hash
from database import Base
from models import Membership, Organization, User


def test_invite_creates_login_and_membership():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        admin = User(name="Admin", email="admin@example.com", password_hash="x", platform_role="platform_admin")
        organization = Organization(name="Cliente", slug="cliente")
        db.add_all([admin, organization])
        db.commit()

        result = invite_organization_user(
            organization.id,
            OrganizationInvite(name="Pessoa Cliente", email="Pessoa@Example.com", role="client_admin"),
            admin,
            db,
        )

        invited = db.query(User).filter(User.email == "pessoa@example.com").one()
        membership = db.query(Membership).filter(Membership.user_id == invited.id).one()
        assert result["temporary_password"]
        assert password_hash.verify(result["temporary_password"], invited.password_hash)
        assert invited.must_change_password is True
        assert membership.organization_id == organization.id
        assert membership.role == "client_admin"

        detail = get_organization(organization.id, admin, db)
        assert detail["members"][0]["user"]["email"] == "pessoa@example.com"
    finally:
        db.close()
        engine.dispose()

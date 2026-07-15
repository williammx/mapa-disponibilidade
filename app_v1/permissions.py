from sqlalchemy.orm import Session as DbSession

from models import Membership, User


def user_can_access_org(db: DbSession, user: User, organization_id: str) -> bool:
    if user.platform_role in {"platform_admin", "operator"}:
        return True
    return db.query(Membership).filter(
        Membership.user_id == user.id,
        Membership.organization_id == organization_id,
    ).first() is not None


def user_can_manage_org(db: DbSession, user: User, organization_id: str) -> bool:
    if user.platform_role in {"platform_admin", "operator"}:
        return True
    membership = db.query(Membership).filter(
        Membership.user_id == user.id,
        Membership.organization_id == organization_id,
    ).first()
    return bool(membership and membership.role == "client_admin")

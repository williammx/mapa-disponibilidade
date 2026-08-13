import hashlib
import os
import secrets
from datetime import timedelta

from fastapi import Depends, HTTPException, Request, Response, status
from pwdlib import PasswordHash
from sqlalchemy.orm import Session as DbSession

from database import get_db
from models import AuditEvent, Session, User, utcnow

COOKIE_NAME = "mapa_session"
SESSION_DAYS = int(os.getenv("SESSION_DAYS", "30"))
# Default seguro: so cai para cookie sem Secure quando alguem pedir
# explicitamente (desenvolvimento local em http).
COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "true").lower() != "false"
password_hash = PasswordHash.recommended()


def normalize_email(value: str) -> str:
    return value.strip().lower()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def set_session(response: Response, db: DbSession, user: User) -> None:
    raw_token = secrets.token_urlsafe(48)
    expires_at = utcnow() + timedelta(days=SESSION_DAYS)
    db.add(Session(user_id=user.id, token_hash=hash_token(raw_token), expires_at=expires_at))
    response.set_cookie(
        COOKIE_NAME,
        raw_token,
        max_age=SESSION_DAYS * 86400,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, secure=COOKIE_SECURE, samesite="lax")


def audit(db: DbSession, action: str, target_type: str, actor: User | None = None,
          target_id: str | None = None, organization_id: str | None = None, details: str | None = None) -> None:
    db.add(AuditEvent(
        actor_user_id=actor.id if actor else None,
        organization_id=organization_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=details,
    ))


def current_user(request: Request, db: DbSession = Depends(get_db)) -> User:
    raw_token = request.cookies.get(COOKIE_NAME)
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Autenticacao necessaria.")
    session = db.query(Session).filter(Session.token_hash == hash_token(raw_token)).first()
    if not session or session.expires_at <= utcnow():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessao expirada.")
    user = db.get(User, session.user_id)
    if not user or not user.active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Conta sem acesso.")
    now = utcnow()
    if session.last_seen_at <= now - timedelta(minutes=5):
        session.last_seen_at = now
        db.commit()
    return user


def require_platform_admin(user: User = Depends(current_user)) -> User:
    if user.platform_role != "platform_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permissao de administrador necessaria.")
    return user

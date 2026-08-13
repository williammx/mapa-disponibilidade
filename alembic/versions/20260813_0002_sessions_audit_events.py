"""sessions e audit_events

A revision inicial criou 10 das 12 tabelas de models.py. As duas que ficaram de
fora sao justamente as que a autenticacao usa: `auth.set_session` grava em
`sessions` em todo login e `auth.audit` grava em `audit_events`. Num banco novo
(VPS nova, restore de backup, ambiente de teste) o `alembic upgrade head`
terminava com exito e o primeiro `POST /api/auth/login` respondia 500 com
"no such table: audit_events". Producao so funciona porque o schema de la nasceu
por `Base.metadata.create_all` antes de a migration existir.

Revision ID: 20260813_0002
Revises: 20260715_0001
Create Date: 2026-08-13
"""

from alembic import op
import sqlalchemy as sa

revision = "20260813_0002"
down_revision = "20260715_0001"
branch_labels = None
depends_on = None


def has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def upgrade() -> None:
    # Idempotente de proposito: em producao as duas tabelas ja existem, criadas
    # por create_all. Recriar levantaria erro e derrubaria o boot do container.
    if not has_table("sessions"):
        op.create_table(
            "sessions",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("user_id", sa.String(length=36),
                      sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
        op.create_index("ix_sessions_token_hash", "sessions", ["token_hash"], unique=True)
        op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])

    if not has_table("audit_events"):
        op.create_table(
            "audit_events",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("actor_user_id", sa.String(length=36),
                      sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("organization_id", sa.String(length=36),
                      sa.ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True),
            sa.Column("action", sa.String(length=120), nullable=False),
            sa.Column("target_type", sa.String(length=80), nullable=False),
            sa.Column("target_id", sa.String(length=36), nullable=True),
            sa.Column("details", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_audit_events_actor_user_id", "audit_events", ["actor_user_id"])
        op.create_index("ix_audit_events_organization_id", "audit_events", ["organization_id"])
        op.create_index("ix_audit_events_action", "audit_events", ["action"])
        op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"])


def downgrade() -> None:
    if has_table("audit_events"):
        op.drop_table("audit_events")
    if has_table("sessions"):
        op.drop_table("sessions")

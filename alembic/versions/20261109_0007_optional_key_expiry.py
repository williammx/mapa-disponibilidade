"""Allow integration keys without an automatic expiration date.

Existing deadlines and revocations are preserved. Removing a deadline from a
specific existing key is a separate, explicitly authorized administrative act.
"""
from alembic import op
import sqlalchemy as sa

revision = "20261109_0007"
down_revision = "20261005_0006"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("integration_api_keys") as batch:
        batch.alter_column("expires_at", existing_type=sa.DateTime(), nullable=True)


def downgrade():
    # A legacy release cannot interpret NULL deadlines. Fail closed for those
    # keys rather than silently inventing a new future lifetime on rollback.
    op.execute(sa.text("UPDATE integration_api_keys SET expires_at = created_at WHERE expires_at IS NULL"))
    with op.batch_alter_table("integration_api_keys") as batch:
        batch.alter_column("expires_at", existing_type=sa.DateTime(), nullable=False)
